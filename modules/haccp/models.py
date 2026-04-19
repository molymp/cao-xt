"""HACCP – DB-Layer (Geraete, Messwerte, Grenzwerte, Alarme, Sichtkontrolle).

Alle Funktionen arbeiten gegen den pool ``wawi_pool`` (gemeinsam mit den
anderen WaWi-Modulen, selber CAO-Datenbank).
"""
from __future__ import annotations

import statistics
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

# Nutzt den gemeinsamen Connection-Pool (wird von der App via init_pool gesetzt).
from common.db import get_db as _get_db, get_db_transaction as _get_db_tx


@contextmanager
def get_db_ro():
    with _get_db() as cur:
        yield cur


@contextmanager
def get_db_rw():
    with _get_db_tx() as cur:
        yield cur


# ── Geraete ───────────────────────────────────────────────────────────

def geraete_liste(nur_aktive: bool = True) -> list[dict]:
    q = ("SELECT * FROM XT_HACCP_GERAET"
         + (" WHERE AKTIV = 1" if nur_aktive else "")
         + " ORDER BY NAME")
    with get_db_ro() as cur:
        cur.execute(q)
        return cur.fetchall()


def geraet_by_id(geraet_id: int) -> dict | None:
    with get_db_ro() as cur:
        cur.execute("SELECT * FROM XT_HACCP_GERAET WHERE GERAET_ID = %s",
                    (int(geraet_id),))
        return cur.fetchone()


def geraet_by_tfa(tfa_device_id: str, sensor_index: int = 0) -> dict | None:
    with get_db_ro() as cur:
        cur.execute(
            "SELECT * FROM XT_HACCP_GERAET "
            "  WHERE TFA_DEVICE_ID = %s AND TFA_SENSOR_INDEX = %s",
            (tfa_device_id, int(sensor_index)),
        )
        return cur.fetchone()


def geraet_anlegen(tfa_device_id: str, name: str, *,
                   sensor_index: int = 0,
                   standort: str | None = None,
                   warengruppe: str | None = None,
                   tfa_internal_id: str | None = None,
                   tfa_name: str | None = None,
                   tfa_messintervall_s: int | None = None) -> int:
    """Legt ein Geraet an (oder liefert PKID, falls TFA_DEVICE_ID+INDEX schon exist)."""
    vorhanden = geraet_by_tfa(tfa_device_id, sensor_index)
    if vorhanden:
        return int(vorhanden['GERAET_ID'])
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_HACCP_GERAET
                 (TFA_DEVICE_ID, TFA_SENSOR_INDEX, TFA_INTERNAL_ID,
                  TFA_NAME, TFA_MESSINTERVALL_S,
                  NAME, STANDORT, WARENGRUPPE)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (tfa_device_id, int(sensor_index), tfa_internal_id,
             tfa_name, tfa_messintervall_s,
             name, standort, warengruppe),
        )
        return int(cur.lastrowid)


def geraet_tfa_metadata_aktualisieren(geraet_id: int, *,
                                       tfa_internal_id: str | None = None,
                                       tfa_name: str | None = None,
                                       tfa_messintervall_s: int | None = None
                                       ) -> None:
    """Aktualisiert die API-spiegel-Felder (TFA_INTERNAL_ID, TFA_NAME,
    TFA_MESSINTERVALL_S), wenn die API neue/geaenderte Werte liefert.
    Setzt nur die nicht-None Parameter (COALESCE-Pattern)."""
    if tfa_internal_id is None and tfa_name is None and tfa_messintervall_s is None:
        return
    felder, args = [], []
    if tfa_internal_id is not None:
        felder.append('TFA_INTERNAL_ID = %s'); args.append(tfa_internal_id)
    if tfa_name is not None:
        felder.append('TFA_NAME = %s'); args.append(tfa_name)
    if tfa_messintervall_s is not None:
        felder.append('TFA_MESSINTERVALL_S = %s'); args.append(int(tfa_messintervall_s))
    args.append(int(geraet_id))
    with get_db_rw() as cur:
        cur.execute(
            f"UPDATE XT_HACCP_GERAET SET {', '.join(felder)} WHERE GERAET_ID = %s",
            tuple(args),
        )


def geraet_update(geraet_id: int, felder: dict) -> int:
    erlaubt = ('NAME', 'STANDORT', 'WARENGRUPPE', 'AKTIV',
               'LETZTE_KALIBRIERUNG', 'BEMERKUNG')
    paare = [(k, v) for k, v in felder.items() if k in erlaubt]
    if not paare:
        return 0
    sql = ("UPDATE XT_HACCP_GERAET SET "
           + ", ".join(f"{k} = %s" for k, _ in paare)
           + " WHERE GERAET_ID = %s")
    with get_db_rw() as cur:
        cur.execute(sql, tuple(v for _, v in paare) + (int(geraet_id),))
        return cur.rowcount


# ── Grenzwerte ────────────────────────────────────────────────────────

def grenzwerte_aktuell(geraet_id: int) -> dict | None:
    """Die Zeile mit dem neuesten GUELTIG_AB <= now()."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT * FROM XT_HACCP_GRENZWERTE
                WHERE GERAET_ID = %s AND GUELTIG_AB <= %s
                ORDER BY GUELTIG_AB DESC LIMIT 1""",
            (int(geraet_id), datetime.now(timezone.utc).replace(tzinfo=None)),
        )
        return cur.fetchone()


def grenzwerte_setzen(geraet_id: int, *, temp_min: float, temp_max: float,
                     karenz_min: int, erstellt_von: int,
                     drift_aktiv: bool = False, drift_k: float | None = None,
                     drift_fenster_h: int = 24, stale_min: int = 30,
                     gueltig_ab: datetime | None = None,
                     bemerkung: str | None = None) -> int:
    if temp_min >= temp_max:
        raise ValueError('temp_min muss kleiner als temp_max sein')
    if drift_aktiv and (drift_k is None or drift_k <= 0):
        raise ValueError('drift_k > 0 bei DRIFT_AKTIV=1 erforderlich')
    if karenz_min < 0 or stale_min <= 0:
        raise ValueError('ungueltige Minutenwerte')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_HACCP_GRENZWERTE
                (GERAET_ID, TEMP_MIN_C, TEMP_MAX_C, KARENZ_MIN,
                 DRIFT_AKTIV, DRIFT_K, DRIFT_FENSTER_H, STALE_MIN,
                 GUELTIG_AB, ERSTELLT_VON, BEMERKUNG)
              VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s)""",
            (int(geraet_id), float(temp_min), float(temp_max), int(karenz_min),
             1 if drift_aktiv else 0, drift_k, int(drift_fenster_h), int(stale_min),
             gueltig_ab or datetime.now(timezone.utc).replace(tzinfo=None), int(erstellt_von), bemerkung),
        )
        return int(cur.lastrowid)


# ── Messwerte ─────────────────────────────────────────────────────────

def messwert_insert(geraet_id: int, zeitpunkt_utc: datetime, *,
                    temp_c: float | None, feuchte_pct: float | None,
                    battery_low: bool, no_connection: bool,
                    transmission_counter: int | None = None) -> bool:
    """INSERT IGNORE auf (GERAET_ID, ZEITPUNKT_UTC). True wenn neu, False wenn Duplikat."""
    with get_db_rw() as cur:
        cur.execute(
            """INSERT IGNORE INTO XT_HACCP_MESSWERT
                 (GERAET_ID, ZEITPUNKT_UTC, TEMP_C, FEUCHTE_PCT,
                  BATTERY_LOW, NO_CONNECTION, TRANSMISSION_COUNTER)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (int(geraet_id), zeitpunkt_utc, temp_c, feuchte_pct,
             1 if battery_low else 0, 1 if no_connection else 0,
             int(transmission_counter) if transmission_counter is not None else None),
        )
        return cur.rowcount > 0


def messwerte_zeitraum(geraet_id: int, von_utc: datetime,
                       bis_utc: datetime) -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT ZEITPUNKT_UTC, TEMP_C, FEUCHTE_PCT,
                      BATTERY_LOW, NO_CONNECTION
                 FROM XT_HACCP_MESSWERT
                WHERE GERAET_ID = %s AND ZEITPUNKT_UTC BETWEEN %s AND %s
                ORDER BY ZEITPUNKT_UTC""",
            (int(geraet_id), von_utc, bis_utc),
        )
        return cur.fetchall()


def messwerte_letzte(geraet_id: int, n: int = 1) -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT ZEITPUNKT_UTC, TEMP_C, FEUCHTE_PCT,
                      BATTERY_LOW, NO_CONNECTION
                 FROM XT_HACCP_MESSWERT
                WHERE GERAET_ID = %s
                ORDER BY ZEITPUNKT_UTC DESC LIMIT %s""",
            (int(geraet_id), int(n)),
        )
        return list(reversed(cur.fetchall()))


def rolling_median_temp(geraet_id: int, ende_utc: datetime,
                        fenster_h: int) -> float | None:
    """Median aller gueltigen (TEMP_C NOT NULL, NO_CONNECTION=0) Messwerte
    im Fenster ``[ende - fenster_h, ende]``. None wenn zu wenige Daten."""
    von = ende_utc - timedelta(hours=int(fenster_h))
    with get_db_ro() as cur:
        cur.execute(
            """SELECT TEMP_C FROM XT_HACCP_MESSWERT
                WHERE GERAET_ID = %s AND ZEITPUNKT_UTC BETWEEN %s AND %s
                  AND TEMP_C IS NOT NULL AND NO_CONNECTION = 0""",
            (int(geraet_id), von, ende_utc),
        )
        werte = [float(r['TEMP_C']) for r in cur.fetchall()]
    if len(werte) < 5:        # Minimum fuer sinnvollen Median
        return None
    return statistics.median(werte)


# ── Alarme ────────────────────────────────────────────────────────────

def alarm_offen(geraet_id: int, typ: str) -> dict | None:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT * FROM XT_HACCP_ALARM
                WHERE GERAET_ID = %s AND TYP = %s AND ENDE_AT IS NULL
                ORDER BY START_AT DESC LIMIT 1""",
            (int(geraet_id), typ),
        )
        return cur.fetchone()


def alarme_offen_alle() -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT a.*, g.NAME AS GERAET_NAME, g.STANDORT, g.WARENGRUPPE
                 FROM XT_HACCP_ALARM a
                 JOIN XT_HACCP_GERAET g ON g.GERAET_ID = a.GERAET_ID
                WHERE a.ENDE_AT IS NULL
                ORDER BY a.START_AT""",
        )
        return cur.fetchall()


def alarm_oeffnen(geraet_id: int, typ: str, start_at: datetime,
                  max_wert: float | None = None) -> int:
    if typ not in ('temp_hoch', 'temp_tief', 'drift', 'offline', 'battery'):
        raise ValueError(f'ungueltiger typ: {typ}')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_HACCP_ALARM
                 (GERAET_ID, TYP, START_AT, MAX_WERT)
               VALUES (%s, %s, %s, %s)""",
            (int(geraet_id), typ, start_at, max_wert),
        )
        return int(cur.lastrowid)


def alarm_max_wert_aktualisieren(alarm_id: int, neuer_max: float) -> None:
    with get_db_rw() as cur:
        cur.execute(
            """UPDATE XT_HACCP_ALARM
                  SET MAX_WERT = CASE
                        WHEN MAX_WERT IS NULL THEN %s
                        WHEN ABS(%s) > ABS(MAX_WERT) THEN %s
                        ELSE MAX_WERT END
                WHERE ALARM_ID = %s""",
            (float(neuer_max), float(neuer_max), float(neuer_max), int(alarm_id)),
        )


def alarm_stufe_setzen(alarm_id: int, stufe: int) -> None:
    with get_db_rw() as cur:
        cur.execute("UPDATE XT_HACCP_ALARM SET LETZTE_STUFE = %s "
                    "WHERE ALARM_ID = %s",
                    (int(stufe), int(alarm_id)))


def alarm_schliessen(alarm_id: int, ende_at: datetime) -> None:
    with get_db_rw() as cur:
        cur.execute(
            """UPDATE XT_HACCP_ALARM SET ENDE_AT = %s
                WHERE ALARM_ID = %s AND ENDE_AT IS NULL""",
            (ende_at, int(alarm_id)),
        )


def alarm_korrektur_eintragen(alarm_id: int, text: str, ma_id: int) -> None:
    text = (text or '').strip()
    if not text:
        raise ValueError('Korrekturmassnahme (Text) ist Pflicht')
    with get_db_rw() as cur:
        cur.execute(
            """UPDATE XT_HACCP_ALARM
                  SET KORREKTUR_TEXT = %s, KORREKTUR_VON = %s,
                      KORREKTUR_AT = %s
                WHERE ALARM_ID = %s""",
            (text[:500], int(ma_id), datetime.now(timezone.utc).replace(tzinfo=None), int(alarm_id)),
        )


def eskalation_loggen(alarm_id: int, stufe: int, empfaenger: str,
                      erfolg: bool, fehlertext: str | None = None) -> None:
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_HACCP_ALARM_ESKALATION
                 (ALARM_ID, STUFE, EMPFAENGER, ERFOLG, FEHLERTEXT)
               VALUES (%s, %s, %s, %s, %s)""",
            (int(alarm_id), int(stufe), empfaenger[:255],
             1 if erfolg else 0, (fehlertext or '')[:500] or None),
        )


def alarm_history(geraet_id: int | None = None, limit: int = 200) -> list[dict]:
    q = (
        """SELECT a.*, g.NAME AS GERAET_NAME,
                  (SELECT LOGIN_NAME FROM MITARBEITER
                    WHERE MA_ID = a.KORREKTUR_VON) AS KORREKTUR_VON_NAME
             FROM XT_HACCP_ALARM a
             JOIN XT_HACCP_GERAET g ON g.GERAET_ID = a.GERAET_ID"""
    )
    args: tuple = ()
    if geraet_id:
        q += " WHERE a.GERAET_ID = %s"
        args = (int(geraet_id),)
    q += " ORDER BY a.START_AT DESC LIMIT %s"
    args += (int(limit),)
    with get_db_ro() as cur:
        cur.execute(q, args)
        return cur.fetchall()


# ── Alarmkette (Empfaenger) ───────────────────────────────────────────

def alarmkette_aktiv() -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT * FROM XT_HACCP_ALARMKETTE
                WHERE AKTIV = 1 ORDER BY STUFE, DELAY_MIN""",
        )
        return cur.fetchall()


def alarmkette_empfaenger_fuer_stufe(stufe: int) -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT * FROM XT_HACCP_ALARMKETTE
                WHERE AKTIV = 1 AND STUFE = %s""",
            (int(stufe),),
        )
        return cur.fetchall()


def alarmkette_anlegen(stufe: int, name: str, email: str,
                       delay_min: int = 0) -> int:
    if stufe not in (1, 2, 3):
        raise ValueError('stufe muss 1, 2 oder 3 sein')
    if '@' not in (email or ''):
        raise ValueError('ungueltige email')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_HACCP_ALARMKETTE
                 (STUFE, NAME, EMAIL, DELAY_MIN)
               VALUES (%s, %s, %s, %s)""",
            (int(stufe), name.strip()[:100], email.strip()[:255],
             int(delay_min)),
        )
        return int(cur.lastrowid)


def alarmkette_loeschen(rec_id: int) -> None:
    with get_db_rw() as cur:
        cur.execute("DELETE FROM XT_HACCP_ALARMKETTE WHERE REC_ID = %s",
                    (int(rec_id),))


# ── Sichtkontrolle ────────────────────────────────────────────────────

def sichtkontrolle_quittieren(geraet_id: int, ma_id: int,
                              datum: date | None = None,
                              bemerkung: str | None = None) -> bool:
    """Tagesquittung. True wenn neu, False wenn heute schon quittiert."""
    d = datum or date.today()
    with get_db_rw() as cur:
        cur.execute(
            """INSERT IGNORE INTO XT_HACCP_SICHTKONTROLLE
                 (GERAET_ID, DATUM, QUITTIERT_VON, BEMERKUNG)
               VALUES (%s, %s, %s, %s)""",
            (int(geraet_id), d, int(ma_id), bemerkung),
        )
        return cur.rowcount > 0


def sichtkontrolle_heute(geraet_id: int) -> dict | None:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT s.*, m.LOGIN_NAME
                 FROM XT_HACCP_SICHTKONTROLLE s
            LEFT JOIN MITARBEITER m ON m.MA_ID = s.QUITTIERT_VON
                WHERE s.GERAET_ID = %s AND s.DATUM = %s""",
            (int(geraet_id), date.today()),
        )
        return cur.fetchone()


def sichtkontrolle_heute_alle() -> dict[int, dict]:
    """Map GERAET_ID -> Zeile fuer heute, nur fuer Geraete mit Quittung."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT s.*, m.LOGIN_NAME
                 FROM XT_HACCP_SICHTKONTROLLE s
            LEFT JOIN MITARBEITER m ON m.MA_ID = s.QUITTIERT_VON
                WHERE s.DATUM = %s""",
            (date.today(),),
        )
        return {int(r['GERAET_ID']): r for r in cur.fetchall()}


# ── Dashboard-Aggregat ────────────────────────────────────────────────

def status_fuer_dashboard(jetzt: datetime) -> dict:
    """Aggregat-Status fuer das WaWi-Hauptdashboard (Temperatur- und
    Sichtkontroll-Ampel).

    Ampel-Logik Temperatur:
        rot  – offener Alarm
        gelb – Sensor offline oder Batterie schwach
        gruen – alles OK
        grau – keine Geraete konfiguriert
    Ampel-Logik Sichtkontrolle:
        rot  – mind. 1 Geraet heute noch nicht quittiert
        gruen – alle quittiert
        grau – keine Geraete
    """
    geraete = geraete_liste(nur_aktive=True)
    total = len(geraete)
    alarme_count = len(alarme_offen_alle())
    quittiert_ids = sichtkontrolle_heute_alle()
    quittiert = sum(1 for g in geraete
                    if int(g['GERAET_ID']) in quittiert_ids)
    unquittiert = total - quittiert

    offline = batt_low = 0
    for g in geraete:
        gid = int(g['GERAET_ID'])
        letzte = messwerte_letzte(gid, 1)
        if not letzte:
            offline += 1
            continue
        letzter = letzte[0]
        grenz = grenzwerte_aktuell(gid)
        stale_min = int(grenz['STALE_MIN']) if grenz else 60
        alter_min = int((jetzt - letzter['ZEITPUNKT_UTC']).total_seconds() / 60)
        if alter_min >= stale_min:
            offline += 1
        if letzter.get('BATTERY_LOW'):
            batt_low += 1

    if total == 0:
        temp_ampel = 'grau'
    elif alarme_count > 0:
        temp_ampel = 'rot'
    elif offline > 0 or batt_low > 0:
        temp_ampel = 'gelb'
    else:
        temp_ampel = 'gruen'

    if total == 0:
        sicht_ampel = 'grau'
    elif unquittiert > 0:
        sicht_ampel = 'rot'
    else:
        sicht_ampel = 'gruen'

    return {
        'temp_ampel': temp_ampel,
        'sicht_ampel': sicht_ampel,
        'geraete_total': total,
        'alarme_offen': alarme_count,
        'offline_count': offline,
        'batt_low_count': batt_low,
        'unquittiert_count': unquittiert,
        'quittiert_count': quittiert,
    }


# ── Poller-Heartbeat ──────────────────────────────────────────────────

def poller_status_lesen() -> dict | None:
    with get_db_ro() as cur:
        cur.execute("SELECT * FROM XT_HACCP_POLLER_STATUS WHERE REC_ID = 1")
        return cur.fetchone()


def poller_status_schreiben(*, tfa_ok: bool, last_error: str | None,
                            neu_entdeckt: int, hostname: str | None) -> None:
    """UPSERT der Single-Row Heartbeat. Bei Erfolg wird LAST_SUCCESS_AT
    aktualisiert, Fehler bleiben in LAST_ERROR stehen bis zum naechsten Erfolg."""
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_HACCP_POLLER_STATUS
                 (REC_ID, LAST_RUN_AT, LAST_SUCCESS_AT, TFA_OK,
                  LAST_ERROR, ZYKLUS_COUNT, NEU_ENTDECKT, HOSTNAME)
               VALUES (1, %s, %s, %s, %s, 1, %s, %s)
               ON DUPLICATE KEY UPDATE
                 LAST_RUN_AT     = VALUES(LAST_RUN_AT),
                 LAST_SUCCESS_AT = CASE WHEN VALUES(TFA_OK) = 1
                                         THEN VALUES(LAST_RUN_AT)
                                         ELSE LAST_SUCCESS_AT END,
                 TFA_OK          = VALUES(TFA_OK),
                 LAST_ERROR      = VALUES(LAST_ERROR),
                 ZYKLUS_COUNT    = ZYKLUS_COUNT + 1,
                 NEU_ENTDECKT    = NEU_ENTDECKT + VALUES(NEU_ENTDECKT),
                 HOSTNAME        = VALUES(HOSTNAME)""",
            (jetzt, jetzt if tfa_ok else None, 1 if tfa_ok else 0,
             (last_error or '')[:500] or None, int(neu_entdeckt), hostname),
        )


def poller_watchdog_alarm_markieren() -> None:
    """Merkt, wann das letzte Watchdog-Alarm-Mail rausging (Anti-Spam)."""
    with get_db_rw() as cur:
        cur.execute(
            "UPDATE XT_HACCP_POLLER_STATUS SET WATCHDOG_ALARM_AT = %s "
            "WHERE REC_ID = 1",
            (datetime.now(timezone.utc).replace(tzinfo=None),),
        )
