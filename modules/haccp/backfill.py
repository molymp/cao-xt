"""Backfill-Logik fuer fehlende Messwerte.

Reusable Baustein fuer (a) den UI-Button auf dem Dashboard und (b) den
Auto-Backfill beim Poller-Start nach einem Ausfall. Bewusst ohne Flask-
Abhaengigkeit, damit der Standalone-Poller ihn benutzen kann.

Die TFA-API beschraenkt ``measurementHistory`` auf max. 7 Tage pro Request
und 10 Requests/h. ``nachholen`` chunked deshalb laengere Zeitraeume in
7-Tages-Bloecke (bzw. klemmt auf 7 Tage, wenn ``max_tage=None``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import models as m
from .tfa_client import TFAClient, TFAError


log = logging.getLogger(__name__)

# API-Hardlimit: pro Request max 7 Tage (siehe TFA-Doku).
MAX_TAGE_PRO_CALL = 7


def nachholen(client: TFAClient, device_ids: list[str],
              von_utc: datetime, bis_utc: datetime
              ) -> tuple[int, int, list[str]]:
    """Holt Messwerte fuer ``device_ids`` im Intervall [von..bis] und
    persistiert sie idempotent (INSERT IGNORE auf UNIQUE geraet+zeit).

    Chunked automatisch in 7-Tages-Bloecke, damit auch laengere Ausfaelle
    rekonstruierbar sind (sofern die Cloud die Daten so lange vorhaelt).

    Rueckgabe: ``(gefunden, neu, fehler_strings)``.
    - ``gefunden`` = Messwerte insgesamt aus der Cloud gelesen
    - ``neu``      = davon neu in unsere DB geschrieben
    - ``fehler``   = Fehlerstrings pro Chunk; leer = alles gut
    """
    if not device_ids:
        return 0, 0, []
    if bis_utc <= von_utc:
        return 0, 0, []

    gefunden = neu = 0
    fehler: list[str] = []

    chunk_von = von_utc
    chunk_max = timedelta(days=MAX_TAGE_PRO_CALL)
    while chunk_von < bis_utc:
        chunk_bis = min(chunk_von + chunk_max, bis_utc)
        try:
            mw_list = client.historie(device_ids, chunk_von, chunk_bis)
        except TFAError as e:
            fehler.append(f'{chunk_von.isoformat()}..{chunk_bis.isoformat()}: {e}')
            chunk_von = chunk_bis
            continue
        for mw in mw_list:
            g = m.geraet_by_tfa(mw.device_id, mw.sensor_index)
            if not g:
                # Neuer Sensor aus History? Anlegen (wie Poller-Auto-Discovery).
                gid = m.geraet_anlegen(
                    mw.device_id,
                    name=mw.device_name or f'Neu: {mw.device_id}/{mw.sensor_index}',
                    sensor_index=mw.sensor_index,
                    tfa_internal_id=mw.internal_id,
                    tfa_name=mw.device_name,
                    tfa_messintervall_s=mw.mess_intervall_s,
                )
            else:
                gid = int(g['GERAET_ID'])
            gefunden += 1
            if m.messwert_insert(
                gid, mw.zeitpunkt_utc,
                temp_c=mw.temp_c, feuchte_pct=mw.feuchte_pct,
                battery_low=mw.battery_low, no_connection=mw.no_connection,
                transmission_counter=mw.transmission_counter,
            ):
                neu += 1
        chunk_von = chunk_bis
    return gefunden, neu, fehler


def nachholen_ab(client: TFAClient, device_ids: list[str],
                 von_utc: datetime, *, max_tage: int | None = None
                 ) -> tuple[int, int, list[str]]:
    """Backfill ab ``von_utc`` bis jetzt. Klemmt optional auf ``max_tage``
    (Default: API-Limit ``MAX_TAGE_PRO_CALL`` pro Request, intern chunked).

    Beim Auto-Backfill nach Poller-Ausfall aufgerufen, damit die Zeit seit
    dem letzten erfolgreichen Heartbeat rekonstruiert wird.
    """
    bis = datetime.now(timezone.utc).replace(tzinfo=None)
    # Mini-Luecken (< 1 min) lohnen keinen API-Call; der naechste Zyklus
    # holt sie sowieso ab.
    if (bis - von_utc).total_seconds() < 60:
        return 0, 0, []
    if max_tage is not None:
        grenze = bis - timedelta(days=max(1, int(max_tage)))
        if von_utc < grenze:
            von_utc = grenze
    return nachholen(client, device_ids, von_utc, bis)
