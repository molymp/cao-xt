"""TFA.me Cloud-API-Client (Pull-basiert).

Doku-Basis: https://go.tfa.me/api/p/v1/index.html (OpenAPI 3).
Auth: Header ``x-api-key``. Keine Webhooks.

Wir nutzen zwei Endpoints:
- ``POST /api/p/v1/currentMeasurements`` mit Body ``[]`` -> alle Geraete +
  jeweils letzter Messwert. Kein Rate-Limit dokumentiert (fuer Polling ok).
- ``POST /api/p/v1/measurementHistory`` -> max 7 Tage, max 10/h. Fuer
  Nachholen von Luecken.

Sensor-valueType-Mapping: 0=Temp C, 1=Feuchte %, 8=Hochpraezisions-Temp C.
Defensiv gegen ``noConnection``, ``overflow``, ``lowBattery``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests


log = logging.getLogger(__name__)

_BASE = 'https://go.tfa.me'
_TIMEOUT_S = 15

# valueType-Konstanten aus der Doku
VT_TEMP_C          = 0
VT_HUMIDITY_PCT    = 1
VT_TEMP_PRECISE_C  = 8


@dataclass(frozen=True)
class Messwert:
    """Ein auf die fuer HACCP relevanten Felder reduziertes Messwert-Objekt.

    Spiegel der API-Felder, die wir persistieren / protokollieren:
      - ``device_id``             ← API ``deviceID``
      - ``internal_id``           ← API ``id`` (GUID, pro Account)
      - ``device_name``           ← API ``name``
      - ``mess_intervall_s``      ← API ``measurementInterval``
      - ``transmission_counter``  ← API ``transmissionCounter`` (monoton)
    """
    device_id:            str
    sensor_index:         int
    zeitpunkt_utc:        datetime
    temp_c:               float | None
    feuchte_pct:          float | None
    battery_low:          bool
    no_connection:        bool
    transmission_counter: int | None  = None
    internal_id:          str | None  = None
    device_name:          str | None  = None
    mess_intervall_s:     int | None  = None


class TFAError(Exception):
    """Fehler beim API-Zugriff (Netzwerk, HTTP, Parsing)."""


class TFAClient:
    """Dünner Wrapper um die TFA-Cloud-API.

    Beispiel:
        c = TFAClient(api_key='...')
        for mw in c.aktuelle_messwerte():
            print(mw.device_id, mw.temp_c)
    """

    def __init__(self, api_key: str, base_url: str = _BASE,
                 timeout_s: float = _TIMEOUT_S):
        if not api_key:
            raise ValueError('api_key fehlt')
        self._headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
        }
        self._base = base_url.rstrip('/')
        self._timeout = timeout_s

    # ── Public API ───────────────────────────────────────────────────

    def aktuelle_messwerte(self, device_ids: Iterable[str] | None = None
                           ) -> list[Messwert]:
        """Liefert letzte Messwerte aller (oder der angegebenen) Geraete.
        ``None`` bedeutet "alle Geraete des Accounts" (Body wird dann
        weggelassen — die Doku behauptet ``[]``, aber das liefert leer)."""
        body = list(device_ids) if device_ids else None
        payload = self._post('/api/p/v1/currentMeasurements', body)
        return list(self._parse_messwerte(payload))

    def historie(self, device_ids: Iterable[str],
                 von_utc: datetime, bis_utc: datetime) -> list[Messwert]:
        """Holt historische Messwerte (max 7 Tage pro Request!).
        Rate-Limit: 10/h. Nur fuer Luecken-Nachholen."""
        body = {
            'deviceIDs': list(device_ids),
            'from': _iso_utc(von_utc),
            'to':   _iso_utc(bis_utc),
        }
        payload = self._post('/api/p/v1/measurementHistory', body)
        # Response: {from, to, generated, devices: [{deviceID, measurements: [...]}]}
        # Anders als /currentMeasurements liefert die History auf Device-Ebene
        # nur ``deviceID`` + ``measurements`` — keine id/name/measurementInterval.
        # Die halten wir aus /currentMeasurements aktuell, hier also None.
        out: list[Messwert] = []
        for dev in (payload or {}).get('devices') or []:
            dev_id = dev.get('deviceID') or ''
            for mess in dev.get('measurements') or []:
                out.extend(self._messwert_aus_measurement(dev_id, mess))
        return out

    def ping(self) -> bool:
        """Health-Check (nur zum Diagnostizieren der Auth)."""
        try:
            r = requests.get(f'{self._base}/api/p/v1/ping',
                             headers=self._headers, timeout=self._timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ── intern ───────────────────────────────────────────────────────

    def _post(self, path: str, body) -> dict | list:
        url = f'{self._base}{path}'
        # body=None -> ohne Body senden (TFA-API interpretiert fehlenden Body
        # als "alle Geraete"; ein explizites [] hingegen als "keine").
        kwargs = {'headers': self._headers, 'timeout': self._timeout}
        if body is not None:
            kwargs['json'] = body
        try:
            r = requests.post(url, **kwargs)
        except requests.RequestException as e:
            raise TFAError(f'Netzwerkfehler {path}: {e}') from e
        if r.status_code >= 400:
            raise TFAError(f'{path} -> HTTP {r.status_code}: {r.text[:300]}')
        try:
            return r.json()
        except ValueError as e:
            raise TFAError(f'{path}: kein gueltiges JSON: {e}') from e

    def _parse_messwerte(self, payload: dict) -> Iterable[Messwert]:
        """``/currentMeasurements``-Response -> Messwert-Objekte."""
        for dev in (payload or {}).get('devices') or []:
            dev_id      = dev.get('deviceID') or ''
            internal_id = dev.get('id')
            dev_name    = dev.get('name')
            intervall   = dev.get('measurementInterval')
            mess = dev.get('measurement') or {}
            yield from self._messwert_aus_measurement(
                dev_id, mess,
                internal_id=internal_id,
                device_name=dev_name,
                mess_intervall_s=intervall,
            )

    @staticmethod
    def _messwert_aus_measurement(device_id: str, m: dict,
                                   *,
                                   internal_id: str | None = None,
                                   device_name: str | None = None,
                                   mess_intervall_s: int | None = None
                                   ) -> Iterable[Messwert]:
        """Ein ``MeasurementDto`` kann mehrere Sensoren liefern (z.B. Kombi-Geraet
        Temp + Feuchte). Wir erzeugen pro Temp-Sensor eine Messwert-Zeile und
        packen die Feuchte desselben Zeitstempels dazu."""
        ts = _parse_iso_utc(m.get('timestamp'))
        if ts is None:
            return
        battery_low = bool(m.get('lowBattery'))
        tx_counter  = m.get('transmissionCounter')
        try:
            tx_counter = int(tx_counter) if tx_counter is not None else None
        except (TypeError, ValueError):
            tx_counter = None
        sensor_values = m.get('sensorValues') or []

        # Feuchte (falls vorhanden) dem Temp-Sensor desselben Measurements anhaengen.
        feuchte = None
        for v in sensor_values:
            if v.get('valueType') == VT_HUMIDITY_PCT and not v.get('noConnection'):
                feuchte = _as_float(v.get('value'))
                break

        gemeinsam = dict(
            device_id=device_id, zeitpunkt_utc=ts,
            battery_low=battery_low,
            transmission_counter=tx_counter,
            internal_id=internal_id,
            device_name=device_name,
            mess_intervall_s=int(mess_intervall_s) if mess_intervall_s else None,
        )

        erzeugt = 0
        for idx, v in enumerate(sensor_values):
            vt = v.get('valueType')
            if vt not in (VT_TEMP_C, VT_TEMP_PRECISE_C):
                continue
            no_conn = bool(v.get('noConnection')) or bool(v.get('overflow'))
            temp = None if no_conn else _as_float(v.get('value'))
            yield Messwert(
                sensor_index=idx,
                temp_c=temp, feuchte_pct=feuchte,
                no_connection=no_conn,
                **gemeinsam,
            )
            erzeugt += 1

        # Geraet ohne Temp-Sensor? Dann nur Feuchte als eigenen Eintrag
        # (sensor_index=0) liefern, damit Staleness-Check funktioniert.
        if erzeugt == 0 and feuchte is not None:
            yield Messwert(
                sensor_index=0,
                temp_c=None, feuchte_pct=feuchte,
                no_connection=False,
                **gemeinsam,
            )


# ── Helfer ───────────────────────────────────────────────────────────

def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    # TFA liefert "...Z" - fromisoformat akzeptiert das ab Python 3.11.
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)  # naive UTC


def _iso_utc(dt: datetime) -> str:
    """datetime -> ISO-8601 mit Z-Suffix."""
    if dt.tzinfo is None:
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _as_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
