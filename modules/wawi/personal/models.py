"""
CAO-XT WaWi-Personal – Datenzugriff (DictCursor, kein ORM).

Konventionen:
  - Beträge als Integer-Cent (STUNDENSATZ_CT).
  - DATE fuer GEBDATUM/EINTRITT/AUSTRITT/GUELTIG_AB (kein DATETIME).
  - Jede Schreiboperation auf XT_PERSONAL_MA erzeugt einen Audit-Eintrag
    in XT_PERSONAL_MA_LOG (append-only).
  - Keine Schreibzugriffe auf CAO-Tabellen.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

# Nutzt den gemeinsamen Connection-Pool (wird von der App via init_pool gesetzt).
from common.db import get_db as _get_db, get_db_transaction as _get_db_tx


# Fachlich relevante Felder in XT_PERSONAL_MA (ohne Audit / PK).
MA_FELDER: tuple[str, ...] = (
    'PERSONALNUMMER', 'VNAME', 'NAME', 'KUERZEL', 'GEBDATUM',
    'EMAIL', 'EMAIL_ALT', 'STRASSE', 'PLZ', 'ORT',
    'TELEFON', 'MOBIL', 'EINTRITT', 'AUSTRITT', 'BEMERKUNG',
    'CAO_MA_ID',
)


@contextmanager
def get_db_ro():
    """Read-only Cursor (alias fuer WaWi-get_db, autocommit=True)."""
    with _get_db() as cur:
        yield cur


@contextmanager
def get_db_rw():
    """Cursor mit expliziter Transaktion (commit/rollback)."""
    with _get_db_tx() as cur:
        yield cur


# ── Liste / Detail ────────────────────────────────────────────────────────────

def ma_liste(nur_aktive: bool = True) -> list[dict]:
    sql = (
        "SELECT PERS_ID, PERSONALNUMMER, KUERZEL, VNAME, NAME, "
        "       EMAIL, EMAIL_ALT, MOBIL, EINTRITT, AUSTRITT "
        "  FROM XT_PERSONAL_MA "
    )
    if nur_aktive:
        sql += "WHERE AUSTRITT IS NULL OR AUSTRITT >= CURDATE() "
    sql += "ORDER BY NAME, VNAME"
    with get_db_ro() as cur:
        cur.execute(sql)
        return cur.fetchall()


def ma_by_id(pers_id: int) -> dict | None:
    with get_db_ro() as cur:
        cur.execute("SELECT * FROM XT_PERSONAL_MA WHERE PERS_ID = %s", (int(pers_id),))
        return cur.fetchone()


def aktueller_stundensatz_ct(pers_id: int, stichtag: date | None = None) -> int | None:
    """Hoechster GUELTIG_AB bis zum Stichtag. Keine Zeile → None."""
    stichtag = stichtag or date.today()
    with get_db_ro() as cur:
        cur.execute(
            """SELECT STUNDENSATZ_CT FROM XT_PERSONAL_STUNDENSATZ_HIST
                WHERE PERS_ID = %s AND GUELTIG_AB <= %s
                ORDER BY GUELTIG_AB DESC, REC_ID DESC LIMIT 1""",
            (int(pers_id), stichtag),
        )
        row = cur.fetchone()
        return int(row['STUNDENSATZ_CT']) if row else None


# ── Create / Update mit Audit ────────────────────────────────────────────────

def _normalisiere(werte: dict) -> dict:
    """Nur bekannte Felder, leere Strings → None."""
    out: dict[str, Any] = {}
    for k in MA_FELDER:
        if k in werte:
            v = werte[k]
            if isinstance(v, str) and v.strip() == '':
                v = None
            out[k] = v
    return out


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f'Nicht JSON-serialisierbar: {type(o).__name__}')


def ma_insert(werte: dict, benutzer_ma_id: int) -> int:
    """Legt einen neuen MA an und schreibt einen INSERT-Audit-Eintrag.
    Gibt die neue PERS_ID zurueck. Rollback bei Fehlern."""
    werte = _normalisiere(werte)
    if not werte.get('VNAME') or not werte.get('NAME') or not werte.get('PERSONALNUMMER'):
        raise ValueError('Pflichtfelder: PERSONALNUMMER, VNAME, NAME')

    cols = list(werte.keys()) + ['ERSTELLT_VON']
    placeholders = ', '.join(['%s'] * len(cols))
    col_list = ', '.join(cols)
    params = tuple(list(werte.values()) + [int(benutzer_ma_id)])

    with get_db_rw() as cur:
        cur.execute(
            f"INSERT INTO XT_PERSONAL_MA ({col_list}) VALUES ({placeholders})",
            params,
        )
        pers_id = cur.lastrowid
        cur.execute(
            """INSERT INTO XT_PERSONAL_MA_LOG
                 (PERS_ID, OPERATION, FELDER_ALT_JSON, FELDER_NEU_JSON, GEAEND_VON)
               VALUES (%s, 'INSERT', NULL, %s, %s)""",
            (pers_id,
             json.dumps(werte, default=_json_default, ensure_ascii=False),
             int(benutzer_ma_id)),
        )
    return pers_id


def ma_update(pers_id: int, werte: dict, benutzer_ma_id: int) -> int:
    """Aktualisiert nur die uebergebenen Felder. Protokolliert Alt/Neu-Wert
    pro Feld. Rueckgabe: Anzahl geaenderter Felder."""
    werte = _normalisiere(werte)
    if not werte:
        return 0

    with get_db_rw() as cur:
        cur.execute("SELECT * FROM XT_PERSONAL_MA WHERE PERS_ID = %s FOR UPDATE",
                    (int(pers_id),))
        alt = cur.fetchone()
        if not alt:
            raise LookupError(f'PERS_ID {pers_id} nicht gefunden')

        diff_alt: dict[str, Any] = {}
        diff_neu: dict[str, Any] = {}
        for k, v_neu in werte.items():
            v_alt = alt.get(k)
            # Datums-/Zahl-Normalisierung fuer fairen Vergleich
            if isinstance(v_alt, (date, datetime)) and isinstance(v_neu, str):
                try:
                    v_neu = date.fromisoformat(v_neu)
                except ValueError:
                    pass
            if v_alt != v_neu:
                diff_alt[k] = v_alt
                diff_neu[k] = v_neu

        if not diff_neu:
            return 0

        set_clause = ', '.join(f'{k} = %s' for k in diff_neu.keys())
        params = list(diff_neu.values()) + [int(benutzer_ma_id), int(pers_id)]
        cur.execute(
            f"UPDATE XT_PERSONAL_MA "
            f"   SET {set_clause}, GEAEND_AT = NOW(), GEAEND_VON = %s "
            f" WHERE PERS_ID = %s",
            params,
        )
        cur.execute(
            """INSERT INTO XT_PERSONAL_MA_LOG
                 (PERS_ID, OPERATION, FELDER_ALT_JSON, FELDER_NEU_JSON, GEAEND_VON)
               VALUES (%s, 'UPDATE', %s, %s, %s)""",
            (int(pers_id),
             json.dumps(diff_alt, default=_json_default, ensure_ascii=False),
             json.dumps(diff_neu, default=_json_default, ensure_ascii=False),
             int(benutzer_ma_id)),
        )
        return len(diff_neu)


def stundensatz_setzen(pers_id: int, gueltig_ab: date, satz_ct: int,
                       kommentar: str | None, benutzer_ma_id: int) -> int:
    """Fuegt einen Eintrag in XT_PERSONAL_STUNDENSATZ_HIST ein (append-only)."""
    if satz_ct < 0:
        raise ValueError('STUNDENSATZ_CT darf nicht negativ sein')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_STUNDENSATZ_HIST
                 (PERS_ID, GUELTIG_AB, STUNDENSATZ_CT, KOMMENTAR, ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s)""",
            (int(pers_id), gueltig_ab, int(satz_ct), kommentar, int(benutzer_ma_id)),
        )
        return cur.lastrowid


# ── P1b: Lohnart, Arbeitszeitmodelle, Lohnkonstanten ─────────────────────────

# Umrechnungsfaktor Woche ↔ Monat gemaess Steuerbuero-Konvention
# (52 Wochen / 12 Monate ≈ 4,333; nach Praxisrundung: 4,33).
FAKTOR_WOCHE_MONAT = 4.33

# Wochentagsspalten in DB-Reihenfolge (Mo-So deutscher Standard).
WOCHENTAGE = ('STD_MO', 'STD_DI', 'STD_MI', 'STD_DO', 'STD_FR', 'STD_SA', 'STD_SO')


def lohnarten(nur_aktive: bool = True) -> list[dict]:
    sql = 'SELECT LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG, SV_PFLICHTIG_FLAG FROM XT_PERSONAL_LOHNART'
    if nur_aktive:
        sql += ' WHERE AKTIV = 1'
    sql += ' ORDER BY SORT, BEZEICHNUNG'
    with get_db_ro() as cur:
        cur.execute(sql)
        return cur.fetchall()


def az_modelle(pers_id: int) -> list[dict]:
    """Historie aller Modelle eines MA, neuestes zuerst."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT m.*, la.BEZEICHNUNG AS LOHNART_NAME, la.MINIJOB_FLAG
                 FROM XT_PERSONAL_AZ_MODELL m
                 JOIN XT_PERSONAL_LOHNART    la ON la.LOHNART_ID = m.LOHNART_ID
                WHERE m.PERS_ID = %s
                ORDER BY m.GUELTIG_AB DESC, m.REC_ID DESC""",
            (int(pers_id),),
        )
        return cur.fetchall()


def aktuelles_az_modell(pers_id: int, stichtag: date | None = None) -> dict | None:
    stichtag = stichtag or date.today()
    with get_db_ro() as cur:
        cur.execute(
            """SELECT m.*, la.BEZEICHNUNG AS LOHNART_NAME, la.MINIJOB_FLAG
                 FROM XT_PERSONAL_AZ_MODELL m
                 JOIN XT_PERSONAL_LOHNART    la ON la.LOHNART_ID = m.LOHNART_ID
                WHERE m.PERS_ID = %s
                  AND m.GUELTIG_AB <= %s
                  AND (m.GUELTIG_BIS IS NULL OR m.GUELTIG_BIS >= %s)
                ORDER BY m.GUELTIG_AB DESC, m.REC_ID DESC
                LIMIT 1""",
            (int(pers_id), stichtag, stichtag),
        )
        return cur.fetchone()


def lohnkonstanten_aktuell(stichtag: date | None = None) -> dict | None:
    """Liefert die zum Stichtag gueltigen Lohnkonstanten."""
    stichtag = stichtag or date.today()
    with get_db_ro() as cur:
        cur.execute(
            """SELECT MINDESTLOHN_CT, MINIJOB_GRENZE_CT, GUELTIG_AB
                 FROM XT_PERSONAL_LOHNKONSTANTEN
                WHERE GUELTIG_AB <= %s
                ORDER BY GUELTIG_AB DESC LIMIT 1""",
            (stichtag,),
        )
        return cur.fetchone()


def az_modell_speichern(pers_id: int, werte: dict, benutzer_ma_id: int) -> int:
    """Legt einen neuen Arbeitszeitmodell-Eintrag an und schliesst das
    vorherige Modell automatisch (GUELTIG_BIS = neu.GUELTIG_AB - 1 Tag)."""
    pflicht = ('GUELTIG_AB', 'LOHNART_ID', 'TYP', 'STUNDEN_SOLL')
    fehlend = [k for k in pflicht if werte.get(k) in (None, '')]
    if fehlend:
        raise ValueError(f'Pflichtfelder fehlen: {", ".join(fehlend)}')
    if werte['TYP'] not in ('WOCHE', 'MONAT'):
        raise ValueError('TYP muss WOCHE oder MONAT sein')

    with get_db_rw() as cur:
        # Vorheriges offenes Modell schliessen (rolling close)
        cur.execute(
            """UPDATE XT_PERSONAL_AZ_MODELL
                  SET GUELTIG_BIS = DATE_SUB(%s, INTERVAL 1 DAY)
                WHERE PERS_ID = %s AND GUELTIG_BIS IS NULL
                  AND GUELTIG_AB < %s""",
            (werte['GUELTIG_AB'], int(pers_id), werte['GUELTIG_AB']),
        )
        # Neuen Eintrag
        cols = ['PERS_ID', 'GUELTIG_AB', 'GUELTIG_BIS', 'LOHNART_ID', 'TYP',
                'STUNDEN_SOLL', *WOCHENTAGE, 'URLAUB_JAHR_TAGE', 'BEMERKUNG',
                'ERSTELLT_VON']
        vals = [
            int(pers_id), werte['GUELTIG_AB'], werte.get('GUELTIG_BIS'),
            int(werte['LOHNART_ID']), werte['TYP'], werte['STUNDEN_SOLL'],
            *(werte.get(k) for k in WOCHENTAGE),
            werte.get('URLAUB_JAHR_TAGE'), werte.get('BEMERKUNG'),
            int(benutzer_ma_id),
        ]
        placeholders = ', '.join(['%s'] * len(cols))
        cur.execute(
            f"INSERT INTO XT_PERSONAL_AZ_MODELL ({', '.join(cols)}) "
            f"VALUES ({placeholders})",
            vals,
        )
        return cur.lastrowid


def minijob_check(stunden_soll: float, typ: str, stundensatz_ct: int,
                  grenze_ct: int) -> dict:
    """Prueft, ob bei gegebenem Modell die Minijob-Grenze eingehalten wird.

    Returns dict mit:
        brutto_monat_ct   – errechnetes monatliches Brutto
        grenze_ct         – aktuelle Grenze
        ueberschreitet    – True wenn brutto > grenze
        differenz_ct      – brutto - grenze (negativ = noch Puffer)
    """
    if typ == 'WOCHE':
        brutto_monat = float(stunden_soll) * FAKTOR_WOCHE_MONAT * stundensatz_ct
    else:  # MONAT
        brutto_monat = float(stunden_soll) * stundensatz_ct
    brutto_ct = int(round(brutto_monat))
    return {
        'brutto_monat_ct': brutto_ct,
        'grenze_ct':       int(grenze_ct),
        'ueberschreitet':  brutto_ct > int(grenze_ct),
        'differenz_ct':    brutto_ct - int(grenze_ct),
    }


# ── Hilfsfunktionen fuer Templates ────────────────────────────────────────────

def ct_to_eurostr(ct: int | None) -> str:
    if ct is None:
        return ''
    return f'{ct / 100:.2f}'.replace('.', ',')
