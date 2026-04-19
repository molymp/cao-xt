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

import hashlib
import json
import os as _os
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta
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


def stundensaetze(pers_id: int) -> list[dict]:
    """Vollstaendige Historie der Stundensaetze (neuester zuerst)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, GUELTIG_AB, STUNDENSATZ_CT, KOMMENTAR,
                      ERSTELLT_AT, ERSTELLT_VON
                 FROM XT_PERSONAL_STUNDENSATZ_HIST
                WHERE PERS_ID = %s
                ORDER BY GUELTIG_AB DESC, REC_ID DESC""",
            (int(pers_id),),
        )
        return cur.fetchall()


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


def _log_schreiben(cur, tabelle: str, pers_id: int, ref_rec_id: int,
                   operation: str, alt_werte: dict | None,
                   neu_werte: dict | None,
                   benutzer_ma_id: int | None) -> None:
    """Schreibt einen Audit-Eintrag in XT_PERSONAL_AZ_MODELL_LOG bzw.
    XT_PERSONAL_URLAUB_ANTRAG_LOG. ``benutzer_ma_id=None`` markiert
    System-Uebergaenge (Auto-Abschluss)."""
    def _dump(w):
        if w is None:
            return None
        return json.dumps(w, default=_json_default, ensure_ascii=False)
    cur.execute(
        f"""INSERT INTO {tabelle}
              (PERS_ID, REF_REC_ID, OPERATION,
               FELDER_ALT_JSON, FELDER_NEU_JSON, GEAEND_VON)
            VALUES (%s, %s, %s, %s, %s, %s)""",
        (int(pers_id), int(ref_rec_id), operation,
         _dump(alt_werte), _dump(neu_werte),
         int(benutzer_ma_id) if benutzer_ma_id is not None else None),
    )


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
        # Seiten-Effekt: Austritt setzen → schliesst das genau eine offene
        # AZ-Modell. Austritt wieder aufheben (None) → oeffnet das Modell
        # wieder, dessen GUELTIG_BIS exakt auf dem alten Austrittsdatum stand.
        # Invariante: pro MA existiert immer hoechstens ein offenes Modell
        # (sichergestellt durch az_modell_speichern + az_modell_bearbeiten).
        # Bei Verletzung wird ein Fehler geworfen, statt still mehrere
        # Modelle zu überschreiben.
        if 'AUSTRITT' in diff_neu:
            neu_austritt = diff_neu['AUSTRITT']
            alt_austritt = diff_alt.get('AUSTRITT')
            if isinstance(neu_austritt, str):
                neu_austritt = date.fromisoformat(neu_austritt)
            if isinstance(alt_austritt, str):
                alt_austritt = date.fromisoformat(alt_austritt)
            if neu_austritt:
                cur.execute(
                    """SELECT REC_ID FROM XT_PERSONAL_AZ_MODELL
                        WHERE PERS_ID = %s AND GUELTIG_BIS IS NULL""",
                    (int(pers_id),),
                )
                offen = cur.fetchall()
                if len(offen) > 1:
                    raise RuntimeError(
                        f'Invariantenbruch: PERS_ID {pers_id} hat '
                        f'{len(offen)} offene AZ-Modelle – erwartet: maximal 1.'
                    )
                if len(offen) == 1:
                    cur.execute(
                        """UPDATE XT_PERSONAL_AZ_MODELL
                              SET GUELTIG_BIS = %s,
                                  GEAEND_AT = NOW(), GEAEND_VON = %s
                            WHERE REC_ID = %s""",
                        (neu_austritt, int(benutzer_ma_id), offen[0]['REC_ID']),
                    )
            elif alt_austritt:
                cur.execute(
                    """SELECT REC_ID FROM XT_PERSONAL_AZ_MODELL
                        WHERE PERS_ID = %s AND GUELTIG_BIS = %s""",
                    (int(pers_id), alt_austritt),
                )
                geschlossen = cur.fetchall()
                if len(geschlossen) > 1:
                    raise RuntimeError(
                        f'Invariantenbruch: PERS_ID {pers_id} hat '
                        f'{len(geschlossen)} Modelle mit GUELTIG_BIS '
                        f'{alt_austritt.isoformat()} – erwartet: maximal 1.'
                    )
                if len(geschlossen) == 1:
                    cur.execute(
                        """UPDATE XT_PERSONAL_AZ_MODELL
                              SET GUELTIG_BIS = NULL,
                                  GEAEND_AT = NOW(), GEAEND_VON = %s
                            WHERE REC_ID = %s""",
                        (int(benutzer_ma_id), geschlossen[0]['REC_ID']),
                    )
        return len(diff_neu)


def ma_log(pers_id: int, limit: int = 50) -> list[dict]:
    """Vereintes Aenderungsprotokoll fuer einen Mitarbeiter (neueste zuerst).

    Liest aus drei LOG-Tabellen und kennzeichnet je Zeile den ``BEREICH``:
      - 'Stammdaten'  → XT_PERSONAL_MA_LOG
      - 'Arbeitszeit' → XT_PERSONAL_AZ_MODELL_LOG
      - 'Urlaub'      → XT_PERSONAL_URLAUB_ANTRAG_LOG
    """
    with get_db_ro() as cur:
        cur.execute(
            """SELECT alle.*,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS GEAEND_NAME
                 FROM (
                    SELECT 'Stammdaten'  AS BEREICH, REC_ID,
                           NULL          AS REF_REC_ID, OPERATION,
                           FELDER_ALT_JSON, FELDER_NEU_JSON,
                           GEAEND_AT, GEAEND_VON
                      FROM XT_PERSONAL_MA_LOG
                     WHERE PERS_ID = %s
                    UNION ALL
                    SELECT 'Arbeitszeit' AS BEREICH, REC_ID,
                           REF_REC_ID, OPERATION,
                           FELDER_ALT_JSON, FELDER_NEU_JSON,
                           GEAEND_AT, GEAEND_VON
                      FROM XT_PERSONAL_AZ_MODELL_LOG
                     WHERE PERS_ID = %s
                    UNION ALL
                    SELECT 'Urlaub'      AS BEREICH, REC_ID,
                           REF_REC_ID, OPERATION,
                           FELDER_ALT_JSON, FELDER_NEU_JSON,
                           GEAEND_AT, GEAEND_VON
                      FROM XT_PERSONAL_URLAUB_ANTRAG_LOG
                     WHERE PERS_ID = %s
                 ) alle
            LEFT JOIN MITARBEITER m ON m.MA_ID = alle.GEAEND_VON
                ORDER BY alle.GEAEND_AT DESC, alle.REC_ID DESC
                LIMIT %s""",
            (int(pers_id), int(pers_id), int(pers_id), int(limit)),
        )
        return cur.fetchall()


def az_modell_bearbeiten(rec_id: int, werte: dict, benutzer_ma_id: int) -> int:
    """Retroactive Änderung an einem bestehenden AZ-Modell. Felder, die
    None sind, werden NICHT überschrieben. Loggt GEAEND_AT/GEAEND_VON.

    Wenn GUELTIG_AB geändert wird, wird der direkte Vorgänger automatisch
    auf neu_ab - 1 Tag gekürzt (analog ``az_modell_speichern``). Validiert:
      - neu_ab darf nicht nach dem eigenen GUELTIG_BIS liegen
      - neu_ab darf nicht gleich dem GUELTIG_AB eines anderen Modells sein

    Rückgabe: Anzahl geänderter Felder."""
    erlaubt = ('GUELTIG_AB', 'LOHNART_ID', 'TYP', 'STUNDEN_SOLL',
               'STD_MO', 'STD_DI', 'STD_MI', 'STD_DO', 'STD_FR', 'STD_SA', 'STD_SO',
               'URLAUB_JAHR_TAGE', 'BEMERKUNG')
    sauber = {k: werte[k] for k in erlaubt if k in werte}
    if not sauber:
        return 0
    with get_db_rw() as cur:
        # Alte Werte + PERS_ID/GUELTIG_BIS (fuer Validierung) laden.
        feld_liste = ', '.join(['PERS_ID', 'GUELTIG_BIS', *sauber.keys()])
        cur.execute(
            f"SELECT {feld_liste} FROM XT_PERSONAL_AZ_MODELL "
            f" WHERE REC_ID = %s",
            (int(rec_id),),
        )
        alt = cur.fetchone()
        if not alt:
            return 0
        pers_id = int(alt['PERS_ID'])
        # Diff berechnen: nur wirklich geaenderte Felder loggen/updaten.
        diff_alt = {k: alt.get(k) for k in sauber if alt.get(k) != sauber[k]}
        diff_neu = {k: sauber[k] for k in sauber if alt.get(k) != sauber[k]}
        if not diff_neu:
            return 0

        if 'GUELTIG_AB' in diff_neu:
            neu_ab = diff_neu['GUELTIG_AB']
            if neu_ab is None:
                raise ValueError('GUELTIG_AB darf nicht leer sein')
            eigene_bis = alt['GUELTIG_BIS']
            if eigene_bis is not None and neu_ab > eigene_bis:
                raise ValueError(
                    f'GUELTIG_AB {neu_ab} liegt nach eigenem GUELTIG_BIS '
                    f'{eigene_bis}'
                )
            # Kollision: kein anderer Datensatz darf am selben Tag starten
            cur.execute(
                "SELECT COUNT(*) AS n FROM XT_PERSONAL_AZ_MODELL "
                " WHERE PERS_ID = %s AND REC_ID <> %s AND GUELTIG_AB = %s",
                (pers_id, int(rec_id), neu_ab),
            )
            if cur.fetchone()['n']:
                raise ValueError(
                    f'Ein anderes Modell startet bereits am {neu_ab}'
                )
            # Vorgaenger kuerzen (analog az_modell_speichern):
            cur.execute(
                """UPDATE XT_PERSONAL_AZ_MODELL
                      SET GUELTIG_BIS = DATE_SUB(%s, INTERVAL 1 DAY)
                    WHERE PERS_ID = %s
                      AND REC_ID <> %s
                      AND GUELTIG_AB < %s
                      AND (GUELTIG_BIS IS NULL OR GUELTIG_BIS >= %s)""",
                (neu_ab, pers_id, int(rec_id), neu_ab, neu_ab),
            )
        sets = ', '.join(f'{k} = %s' for k in diff_neu.keys())
        params = [*diff_neu.values(), int(benutzer_ma_id), int(rec_id)]
        cur.execute(
            f"UPDATE XT_PERSONAL_AZ_MODELL "
            f"   SET {sets}, GEAEND_AT = NOW(), GEAEND_VON = %s "
            f" WHERE REC_ID = %s",
            params,
        )
        _log_schreiben(
            cur, 'XT_PERSONAL_AZ_MODELL_LOG',
            pers_id, int(rec_id), 'UPDATE',
            diff_alt, diff_neu, benutzer_ma_id,
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
    sql = ('SELECT LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG, SV_PFLICHTIG_FLAG,'
           '       IN_ZEITERFASSUNG'
           '  FROM XT_PERSONAL_LOHNART')
    if nur_aktive:
        sql += ' WHERE AKTIV = 1'
    sql += ' ORDER BY SORT, BEZEICHNUNG'
    with get_db_ro() as cur:
        cur.execute(sql)
        return cur.fetchall()


def ma_in_zeiterfassung(pers_id: int, stichtag: date | None = None) -> bool:
    """True, wenn der MA am Stichtag eine Lohnart mit IN_ZEITERFASSUNG=1 hat.

    Ohne aktuelles AZ-Modell → True (konservativ: im Zweifel Stundenzettel).
    """
    az = aktuelles_az_modell(pers_id, stichtag=stichtag)
    if not az:
        return True
    with get_db_ro() as cur:
        cur.execute(
            "SELECT IN_ZEITERFASSUNG FROM XT_PERSONAL_LOHNART "
            " WHERE LOHNART_ID = %s",
            (int(az['LOHNART_ID']),),
        )
        row = cur.fetchone()
    if not row:
        return True
    return bool(row['IN_ZEITERFASSUNG'])


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

    neu_ab = werte['GUELTIG_AB']
    with get_db_rw() as cur:
        # 1. Jedes existierende Modell, das neu_ab ueberdeckt (GUELTIG_AB <= neu_ab
        #    < GUELTIG_BIS oder offen), wird auf neu_ab - 1 gekuerzt.
        cur.execute(
            """UPDATE XT_PERSONAL_AZ_MODELL
                  SET GUELTIG_BIS = DATE_SUB(%s, INTERVAL 1 DAY)
                WHERE PERS_ID = %s
                  AND GUELTIG_AB < %s
                  AND (GUELTIG_BIS IS NULL OR GUELTIG_BIS >= %s)""",
            (neu_ab, int(pers_id), neu_ab, neu_ab),
        )
        # 2. Nachfolger-Modell suchen (fuer rueckwirkende Einfuegung): GUELTIG_BIS
        #    des neuen Modells wird GUELTIG_AB des Nachfolgers minus 1.
        cur.execute(
            """SELECT MIN(GUELTIG_AB) AS next_ab
                 FROM XT_PERSONAL_AZ_MODELL
                WHERE PERS_ID = %s AND GUELTIG_AB > %s""",
            (int(pers_id), neu_ab),
        )
        nachfolger = cur.fetchone()
        neu_bis = werte.get('GUELTIG_BIS')
        if neu_bis is None and nachfolger and nachfolger.get('next_ab'):
            neu_bis = nachfolger['next_ab'] - timedelta(days=1)

        # 3. Neues Modell einfuegen.
        cols = ['PERS_ID', 'GUELTIG_AB', 'GUELTIG_BIS', 'LOHNART_ID', 'TYP',
                'STUNDEN_SOLL', *WOCHENTAGE, 'URLAUB_JAHR_TAGE', 'BEMERKUNG',
                'ERSTELLT_VON']
        vals = [
            int(pers_id), neu_ab, neu_bis,
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
        neu_rec_id = cur.lastrowid
        # Audit-Log: Snapshot aller fachlichen Felder (ohne ERSTELLT_VON)
        log_neu = {c: v for c, v in zip(cols, vals) if c != 'ERSTELLT_VON'}
        _log_schreiben(
            cur, 'XT_PERSONAL_AZ_MODELL_LOG',
            int(pers_id), neu_rec_id, 'INSERT',
            None, log_neu, benutzer_ma_id,
        )
        return neu_rec_id


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


# ── P1c: Urlaubsanspruch, Korrekturen, Antraege ──────────────────────────────

_WKD_ZU_SPALTE = {
    0: 'STD_MO', 1: 'STD_DI', 2: 'STD_MI', 3: 'STD_DO',
    4: 'STD_FR', 5: 'STD_SA', 6: 'STD_SO',
}


def _modell_ist_arbeitstag(modell: dict, tag: date) -> bool:
    """Ist `tag` laut Wochenverteilung des Modells ein Arbeitstag?
    Wenn alle STD_* NULL sind: Fallback Mo–Fr = Arbeitstag."""
    spalten = [modell.get(s) for s in WOCHENTAGE]
    if all(v is None for v in spalten):
        return tag.weekday() < 5
    v = modell.get(_WKD_ZU_SPALTE[tag.weekday()])
    return v is not None and float(v) > 0


def urlaub_arbeitstage(pers_id: int, von: date, bis: date) -> float:
    """Zaehlt Arbeitstage zwischen VON und BIS (inklusive) anhand des jeweils
    gueltigen AZ-Modells. Gesetzliche und manuelle Feiertage (im konfigurierten
    Bundesland) reduzieren den Urlaubsverbrauch nicht und werden uebersprungen.
    Liefert 0.0, wenn kein Modell existiert."""
    return urlaub_arbeitstage_detail(pers_id, von, bis)['arbeitstage']


def urlaub_arbeitstage_detail(pers_id: int,
                              von: date, bis: date) -> dict:
    """Wie urlaub_arbeitstage, liefert aber eine Aufschluesselung:
      {
        'arbeitstage': 4.0,            # auf Urlaub angerechnet
        'feiertage':   1,              # Arbeitstage, die auf Feiertag fallen
        'feiertag_namen': ['Ostermontag'],
        'kalendertage': 14,            # VON..BIS inklusive
      }
    """
    leer = {
        'arbeitstage': 0.0, 'feiertage': 0,
        'feiertag_namen': [], 'kalendertage': 0,
    }
    if bis < von:
        return leer
    feiertage = feiertage_im_zeitraum(von, bis)
    summe = 0.0
    ft_namen: list[str] = []
    ft_count = 0
    kalendertage = 0
    tag = von
    while tag <= bis:
        kalendertage += 1
        modell = aktuelles_az_modell(pers_id, tag)
        if modell and _modell_ist_arbeitstag(modell, tag):
            if tag in feiertage:
                ft_count += 1
                ft_namen.append(feiertage[tag])
            else:
                summe += 1.0
        tag += timedelta(days=1)
    return {
        'arbeitstage': summe,
        'feiertage': ft_count,
        'feiertag_namen': ft_namen,
        'kalendertage': kalendertage,
    }


def urlaub_anspruch_basis(pers_id: int, jahr: int) -> float:
    """Basis-Jahresanspruch: URLAUB_JAHR_TAGE des Modells, das zur Jahresmitte
    (01.07.JAHR) gueltig ist. Fallback: letztes im Jahr gueltige Modell.
    Keine unterjaehrige pro-rata-Berechnung – Anpassungen per Korrekturbuchung."""
    modell = aktuelles_az_modell(pers_id, date(jahr, 7, 1))
    if not modell:
        with get_db_ro() as cur:
            cur.execute(
                """SELECT URLAUB_JAHR_TAGE FROM XT_PERSONAL_AZ_MODELL
                    WHERE PERS_ID = %s AND GUELTIG_AB <= %s
                    ORDER BY GUELTIG_AB DESC, REC_ID DESC LIMIT 1""",
                (int(pers_id), date(jahr, 12, 31)),
            )
            row = cur.fetchone()
            if not row or row.get('URLAUB_JAHR_TAGE') is None:
                return 0.0
            return float(row['URLAUB_JAHR_TAGE'])
    return float(modell.get('URLAUB_JAHR_TAGE') or 0)


def urlaub_korrekturen(pers_id: int, jahr: int) -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT k.REC_ID, k.JAHR, k.TAGE, k.GRUND, k.KOMMENTAR,
                      k.VERFAELLT_AM,
                      k.ERSTELLT_AT, k.ERSTELLT_VON,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS ERSTELLT_NAME
                 FROM XT_PERSONAL_URLAUB_KORREKTUR k
            LEFT JOIN MITARBEITER m ON m.MA_ID = k.ERSTELLT_VON
                WHERE k.PERS_ID = %s AND k.JAHR = %s
                ORDER BY k.ERSTELLT_AT DESC, k.REC_ID DESC""",
            (int(pers_id), int(jahr)),
        )
        return cur.fetchall()


def urlaub_antraege(pers_id: int, jahr: int) -> list[dict]:
    """Liefert Urlaubsantraege des Jahres. Ergaenzt pro Zeile:
      FEIERTAGE_ANZAHL  – Arbeitstage in VON..BIS, die auf einen Feiertag fielen
      FEIERTAG_NAMEN    – Liste der Feiertags-Namen (fuer Tooltip)
    Die gespeicherte ARBEITSTAGE-Spalte bleibt unveraendert (historisch); die
    neu berechnete 'Anrechnung' liegt als ARBEITSTAGE_NETTO daneben, damit die
    UI 'X Tage, davon Y Feiertag(e)' anzeigen kann."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT a.REC_ID, a.VON, a.BIS, a.ARBEITSTAGE, a.STATUS,
                      a.KOMMENTAR, a.STATUS_GEAEND_AT, a.STATUS_GEAEND_VON,
                      a.ERSTELLT_AT, a.ERSTELLT_VON,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS ERSTELLT_NAME
                 FROM XT_PERSONAL_URLAUB_ANTRAG a
            LEFT JOIN MITARBEITER m ON m.MA_ID = a.ERSTELLT_VON
                WHERE a.PERS_ID = %s AND YEAR(a.VON) = %s
                ORDER BY a.VON DESC, a.REC_ID DESC""",
            (int(pers_id), int(jahr)),
        )
        zeilen = cur.fetchall() or []
    # Feiertags-Info pro Antrag nachladen. Ein einziger Aufruf pro Antrag –
    # die Menge der Antraege pro Jahr ist klein (<100).
    for z in zeilen:
        det = urlaub_arbeitstage_detail(pers_id, z['VON'], z['BIS'])
        z['FEIERTAGE_ANZAHL'] = det['feiertage']
        z['FEIERTAG_NAMEN']   = det['feiertag_namen']
        z['ARBEITSTAGE_NETTO'] = det['arbeitstage']
    return zeilen


def urlaub_uebertrag_verfall_stichtag(jahr: int) -> date:
    """Ermittelt den Stichtag (Datum) fuer den Verfall von Urlaubsuebertraegen
    im gegebenen Jahr. Liest aus XT_EINSTELLUNGEN.personal_urlaub_uebertrag_verfall
    (Format 'MM-TT'); faellt bei Fehler auf 31.03. zurueck."""
    mm, tt = 3, 31
    try:
        with get_db_ro() as cur:
            cur.execute(
                "SELECT wert FROM XT_EINSTELLUNGEN "
                " WHERE schluessel = 'personal_urlaub_uebertrag_verfall'"
            )
            row = cur.fetchone()
            if row and row.get('wert'):
                parts = str(row['wert']).strip().split('-')
                if len(parts) == 2:
                    mm = int(parts[0])
                    tt = int(parts[1])
    except Exception:
        pass
    try:
        return date(int(jahr), mm, tt)
    except ValueError:
        # z.B. ungueltiges Datum wie 02-30 → Fallback auf 31.03.
        return date(int(jahr), 3, 31)


def urlaub_saldo(pers_id: int, jahr: int) -> dict:
    """Berechnet alle Teilsalden fuer ein Urlaubsjahr. Alle Werte als float
    (Tage mit einer Nachkommastelle).

    Verfall-Logik (simples FIFO): Korrekturen mit VERFAELLT_AM < heute, deren
    Betrag > 0 ist (typisch: Uebertrag aus Vorjahr), gelten nur insoweit, als
    sie bis zum Stichtag durch Urlaubsantraege (BIS <= VERFAELLT_AM, STATUS
    in geplant/genehmigt/genommen) verbraucht wurden; der Restanteil verfaellt.

    Rest = basis + korrektur − verfallen − geplant − genehmigt − genommen.
    """
    basis = urlaub_anspruch_basis(pers_id, jahr)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(TAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_KORREKTUR
                WHERE PERS_ID = %s AND JAHR = %s""",
            (int(pers_id), int(jahr)),
        )
        korrektur = float(cur.fetchone()['summe'])
        # Uebertrags-Korrekturen mit Verfall (positiv, VERFAELLT_AM gesetzt).
        cur.execute(
            """SELECT VERFAELLT_AM, COALESCE(SUM(TAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_KORREKTUR
                WHERE PERS_ID = %s AND JAHR = %s
                  AND VERFAELLT_AM IS NOT NULL
                  AND TAGE > 0
                GROUP BY VERFAELLT_AM
                ORDER BY VERFAELLT_AM""",
            (int(pers_id), int(jahr)),
        )
        uebertrag_nach_datum = cur.fetchall() or []
        cur.execute(
            """SELECT STATUS, COALESCE(SUM(ARBEITSTAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s AND YEAR(VON) = %s
                GROUP BY STATUS""",
            (int(pers_id), int(jahr)),
        )
        nach_status = {row['STATUS']: float(row['summe']) for row in cur.fetchall()}
    heute = date.today()
    # Fuer jeden Verfalls-Stichtag pruefen: Wieviel Urlaub ist bis zu diesem
    # Stichtag genommen/genehmigt/geplant? Uebersteigt der Uebertrag den
    # bis dahin verbrauchten Urlaub, verfaellt die Differenz.
    verfallen = 0.0
    for row in uebertrag_nach_datum:
        stichtag = row['VERFAELLT_AM']
        if stichtag >= heute:
            continue  # Verfall noch nicht eingetreten
        uebertrag_summe = float(row['summe'])
        with get_db_ro() as cur:
            cur.execute(
                """SELECT COALESCE(SUM(ARBEITSTAGE), 0) AS summe
                     FROM XT_PERSONAL_URLAUB_ANTRAG
                    WHERE PERS_ID = %s AND YEAR(VON) = %s
                      AND BIS <= %s
                      AND STATUS IN ('geplant','genehmigt','genommen')""",
                (int(pers_id), int(jahr), stichtag),
            )
            verbraucht_bis_stichtag = float(cur.fetchone()['summe'])
        nicht_genutzt = uebertrag_summe - verbraucht_bis_stichtag
        if nicht_genutzt > 0:
            verfallen += nicht_genutzt
    geplant   = nach_status.get('geplant', 0.0)
    genehmigt = nach_status.get('genehmigt', 0.0)
    genommen  = nach_status.get('genommen', 0.0)
    gesamt    = basis + korrektur - verfallen
    rest      = gesamt - geplant - genehmigt - genommen
    return {
        'basis':     basis,
        'korrektur': korrektur,
        'verfallen': round(verfallen, 1),
        'gesamt':    gesamt,
        'geplant':   geplant,
        'genehmigt': genehmigt,
        'genommen':  genommen,
        'rest':      rest,
    }


def urlaub_korrektur_anlegen(pers_id: int, jahr: int, tage: float,
                             grund: str, kommentar: str | None,
                             benutzer_ma_id: int,
                             verfaellt_am: date | None = None) -> int:
    """Legt eine Urlaubs-Korrekturbuchung an.

    ``verfaellt_am``: optionales Verfallsdatum. Typ. Anwendung = Uebertrag aus
    Vorjahr – dort wird auf ``urlaub_uebertrag_verfall_stichtag(jahr)`` gesetzt,
    damit nach dem Stichtag nicht genommener Rest in ``urlaub_saldo()``
    verfaellt. ``None`` = kein Verfall.
    """
    if not grund or not grund.strip():
        raise ValueError('GRUND ist Pflicht')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_URLAUB_KORREKTUR
                 (PERS_ID, JAHR, TAGE, GRUND, KOMMENTAR, VERFAELLT_AM,
                  ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (int(pers_id), int(jahr), float(tage), grund.strip(),
             kommentar, verfaellt_am, int(benutzer_ma_id)),
        )
        return cur.lastrowid


def urlaub_antrag_anlegen(pers_id: int, von: date, bis: date,
                          kommentar: str | None,
                          benutzer_ma_id: int,
                          status: str = 'geplant') -> int:
    if bis < von:
        raise ValueError('BIS darf nicht vor VON liegen')
    if status not in ('geplant', 'genehmigt', 'genommen'):
        raise ValueError('Status ungueltig')
    arbeitstage = urlaub_arbeitstage(pers_id, von, bis)
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_URLAUB_ANTRAG
                 (PERS_ID, VON, BIS, ARBEITSTAGE, STATUS, KOMMENTAR, ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (int(pers_id), von, bis, arbeitstage, status,
             kommentar, int(benutzer_ma_id)),
        )
        neu_rec_id = cur.lastrowid
        _log_schreiben(
            cur, 'XT_PERSONAL_URLAUB_ANTRAG_LOG',
            int(pers_id), neu_rec_id, 'INSERT',
            None,
            {'VON': von, 'BIS': bis, 'ARBEITSTAGE': arbeitstage,
             'STATUS': status, 'KOMMENTAR': kommentar},
            benutzer_ma_id,
        )
        return neu_rec_id


# Gueltige Statusuebergaenge (gerichtet). Rueckwege sind bewusst nicht erlaubt:
# einmal 'genommen' bleibt genommen, einmal 'abgelehnt'/'storniert' ist terminal.
_STATUS_UEBERGAENGE = {
    'geplant':   {'genehmigt', 'abgelehnt', 'storniert'},
    'genehmigt': {'genommen', 'storniert'},
    'genommen':  set(),
    'abgelehnt': set(),
    'storniert': set(),
}


def urlaub_antraege_abschliessen(pers_id: int | None = None,
                                 stichtag: date | None = None) -> int:
    """Setzt alle 'genehmigten' Antraege, deren BIS-Datum vor dem Stichtag liegt,
    automatisch auf 'genommen'. Idempotent – laeuft bei jedem Detail-Aufruf.
    STATUS_GEAEND_VON bleibt NULL als Marker fuer System-Uebergaenge.
    Wenn pers_id=None, wird global aktualisiert."""
    stichtag = stichtag or date.today()
    with get_db_rw() as cur:
        # Betroffene Antraege zuerst laden, damit wir je Zeile loggen koennen.
        sel_sql = ("SELECT REC_ID, PERS_ID FROM XT_PERSONAL_URLAUB_ANTRAG "
                   " WHERE STATUS = 'genehmigt' AND BIS < %s")
        sel_params: list = [stichtag]
        if pers_id is not None:
            sel_sql += " AND PERS_ID = %s"
            sel_params.append(int(pers_id))
        cur.execute(sel_sql, tuple(sel_params))
        betroffene = cur.fetchall()
        if not betroffene:
            return 0
        # Bulk-UPDATE auf genau diese REC_IDs.
        ids = tuple(r['REC_ID'] for r in betroffene)
        platzhalter = ','.join(['%s'] * len(ids))
        cur.execute(
            f"UPDATE XT_PERSONAL_URLAUB_ANTRAG "
            f"   SET STATUS = 'genommen', "
            f"       STATUS_GEAEND_AT  = NOW(), "
            f"       STATUS_GEAEND_VON = NULL "
            f" WHERE REC_ID IN ({platzhalter})",
            ids,
        )
        geaendert = cur.rowcount
        # Audit-Log: ein Eintrag pro Uebergang, GEAEND_VON = NULL (System).
        for r in betroffene:
            _log_schreiben(
                cur, 'XT_PERSONAL_URLAUB_ANTRAG_LOG',
                int(r['PERS_ID']), int(r['REC_ID']), 'UPDATE',
                {'STATUS': 'genehmigt'}, {'STATUS': 'genommen'},
                None,
            )
        return geaendert


def urlaub_antrag_status_setzen(rec_id: int, neuer_status: str,
                                benutzer_ma_id: int) -> int:
    """Aktualisiert den Status eines Antrags, wenn der Uebergang erlaubt ist."""
    if neuer_status not in ('geplant', 'genehmigt', 'genommen',
                            'abgelehnt', 'storniert'):
        raise ValueError(f'Unbekannter Status: {neuer_status!r}')
    with get_db_rw() as cur:
        cur.execute(
            "SELECT PERS_ID, STATUS FROM XT_PERSONAL_URLAUB_ANTRAG "
            " WHERE REC_ID = %s",
            (int(rec_id),),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Antrag {rec_id} nicht gefunden')
        aktuell = row['STATUS']
        if aktuell == neuer_status:
            return 0
        if neuer_status not in _STATUS_UEBERGAENGE.get(aktuell, set()):
            raise ValueError(
                f'Status-Uebergang {aktuell!r} → {neuer_status!r} nicht erlaubt'
            )
        cur.execute(
            """UPDATE XT_PERSONAL_URLAUB_ANTRAG
                  SET STATUS = %s,
                      STATUS_GEAEND_AT  = NOW(),
                      STATUS_GEAEND_VON = %s
                WHERE REC_ID = %s""",
            (neuer_status, int(benutzer_ma_id), int(rec_id)),
        )
        _log_schreiben(
            cur, 'XT_PERSONAL_URLAUB_ANTRAG_LOG',
            int(row['PERS_ID']), int(rec_id), 'UPDATE',
            {'STATUS': aktuell}, {'STATUS': neuer_status}, benutzer_ma_id,
        )
        return cur.rowcount


# ── P4: Abwesenheiten (Krankheit etc., ergaenzend zu URLAUB_ANTRAG) ─────────

ABWESENHEIT_TYPEN: tuple[str, ...] = (
    'krank', 'kind_krank', 'schulung', 'unbezahlt', 'sonstiges',
)

ABWESENHEIT_TYP_LABELS: dict[str, str] = {
    'krank':      'Krank',
    'kind_krank': 'Kind krank',
    'schulung':   'Schulung / Fortbildung',
    'unbezahlt':  'Unbezahlter Urlaub',
    'sonstiges':  'Sonstiges',
}


# Default BEZAHLT pro TYP: Urlaubsfortzahlung/AU-Lohnfortzahlung ist bezahlt,
# unbezahlter Urlaub natuerlich nicht. UI erlaubt Override pro Eintrag.
_BEZAHLT_DEFAULT: dict[str, int] = {
    'krank':      1,
    'kind_krank': 1,
    'schulung':   1,
    'unbezahlt':  0,
    'sonstiges':  1,
}


def abwesenheit_bezahlt_default(typ: str) -> int:
    """Default fuer BEZAHLT bei Neuanlage einer Abwesenheit."""
    return _BEZAHLT_DEFAULT.get(typ, 1)


# Gueltige Status-Uebergaenge fuer Abwesenheiten (gerichtet, terminal).
# Self-Service legt 'beantragt' an; Backoffice entscheidet → 'genehmigt' oder 'abgelehnt'.
# 'genehmigt' bleibt terminal (Stornierung erfolgt ueber STORNIERT-Flag).
ABWESENHEIT_STATUS_UEBERGAENGE = {
    'beantragt': {'genehmigt', 'abgelehnt'},
    'genehmigt': set(),
    'abgelehnt': set(),
}

ABWESENHEIT_STATUS_LABELS: dict[str, str] = {
    'beantragt': 'Beantragt',
    'genehmigt': 'Genehmigt',
    'abgelehnt': 'Abgelehnt',
}


def abwesenheit_anlegen(pers_id: int, typ: str, von: date, bis: date,
                        ganztags: bool = True,
                        stunden: float | None = None,
                        au_vorgelegt: bool = False,
                        bezahlt: bool | None = None,
                        bemerkung: str | None = None,
                        status: str = 'genehmigt',
                        *, benutzer_ma_id: int) -> int:
    """Legt eine Abwesenheit an und schreibt einen INSERT-Audit-Eintrag.

    ``bezahlt=None`` → Default aus ``_BEZAHLT_DEFAULT`` (je nach TYP).
    ``status``:
      - ``'genehmigt'`` (Default): Backoffice-Anlage, direkt gueltig.
      - ``'beantragt'``: Self-Service-Antrag vom MA, noch nicht genehmigt.
      - ``'abgelehnt'``: nur theoretisch, faktisch nicht von Anlage genutzt.
    Bei ``'beantragt'`` bleiben STATUS_GEAEND_AT/VON NULL (noch keine
    Entscheidung); ansonsten wird NOW()/benutzer_ma_id gesetzt.
    """
    if typ not in ABWESENHEIT_TYPEN:
        raise ValueError(f'Abwesenheits-TYP ungueltig: {typ!r}')
    if status not in ABWESENHEIT_STATUS_UEBERGAENGE:
        raise ValueError(f'Abwesenheits-Status ungueltig: {status!r}')
    if bis < von:
        raise ValueError('BIS darf nicht vor VON liegen')
    if not ganztags and (stunden is None or float(stunden) <= 0):
        raise ValueError('Bei GANZTAGS=0 muss STUNDEN > 0 gesetzt sein')
    if ganztags:
        stunden = None  # ganztags → keine Stundenangabe
    bezahlt_int = (abwesenheit_bezahlt_default(typ) if bezahlt is None
                   else (1 if bezahlt else 0))
    # Bei 'beantragt' noch keine Entscheidungs-Metadaten; sonst stempeln.
    status_at_sql = 'NULL' if status == 'beantragt' else 'NOW()'
    status_von_param = None if status == 'beantragt' else int(benutzer_ma_id)
    with get_db_rw() as cur:
        cur.execute(
            f"""INSERT INTO XT_PERSONAL_ABWESENHEIT
                 (PERS_ID, TYP, VON, BIS, GANZTAGS, STUNDEN,
                  AU_VORGELEGT, BEZAHLT, BEMERKUNG,
                  STATUS, STATUS_GEAEND_AT, STATUS_GEAEND_VON,
                  ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, {status_at_sql}, %s, %s)""",
            (int(pers_id), typ, von, bis,
             1 if ganztags else 0, stunden,
             1 if au_vorgelegt else 0, bezahlt_int, bemerkung,
             status, status_von_param,
             int(benutzer_ma_id)),
        )
        rec_id = cur.lastrowid
        _log_schreiben(
            cur, 'XT_PERSONAL_ABWESENHEIT_LOG',
            int(pers_id), rec_id, 'INSERT', None,
            {'TYP': typ, 'VON': von, 'BIS': bis,
             'GANZTAGS': 1 if ganztags else 0, 'STUNDEN': stunden,
             'AU_VORGELEGT': 1 if au_vorgelegt else 0,
             'BEZAHLT': bezahlt_int,
             'BEMERKUNG': bemerkung,
             'STATUS': status},
            benutzer_ma_id,
        )
        return rec_id


def abwesenheit_status_setzen(rec_id: int, neuer_status: str,
                              benutzer_ma_id: int) -> int:
    """Aktualisiert den Status einer Abwesenheit, wenn der Uebergang erlaubt ist.

    Analog zu ``urlaub_antrag_status_setzen``: nur gerichtete Uebergaenge,
    Audit-Log mit STATUS-Delta, return rowcount (0 wenn bereits im Zielstatus).
    Stornierte Eintraege lassen sich nicht weiter umschalten.
    """
    if neuer_status not in ABWESENHEIT_STATUS_UEBERGAENGE:
        raise ValueError(f'Unbekannter Status: {neuer_status!r}')
    with get_db_rw() as cur:
        cur.execute(
            """SELECT PERS_ID, STATUS, STORNIERT
                 FROM XT_PERSONAL_ABWESENHEIT
                WHERE REC_ID = %s""",
            (int(rec_id),),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Abwesenheit {rec_id} nicht gefunden')
        if row.get('STORNIERT'):
            raise LookupError(f'Abwesenheit {rec_id} ist storniert')
        aktuell = row['STATUS']
        if aktuell == neuer_status:
            return 0
        if neuer_status not in ABWESENHEIT_STATUS_UEBERGAENGE.get(aktuell, set()):
            raise ValueError(
                f'Status-Uebergang {aktuell!r} → {neuer_status!r} nicht erlaubt'
            )
        cur.execute(
            """UPDATE XT_PERSONAL_ABWESENHEIT
                  SET STATUS = %s,
                      STATUS_GEAEND_AT  = NOW(),
                      STATUS_GEAEND_VON = %s
                WHERE REC_ID = %s""",
            (neuer_status, int(benutzer_ma_id), int(rec_id)),
        )
        _log_schreiben(
            cur, 'XT_PERSONAL_ABWESENHEIT_LOG',
            int(row['PERS_ID']), int(rec_id), 'UPDATE',
            {'STATUS': aktuell}, {'STATUS': neuer_status}, benutzer_ma_id,
        )
        return cur.rowcount


def abwesenheit_by_id(rec_id: int) -> dict | None:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, PERS_ID, TYP, VON, BIS, GANZTAGS, STUNDEN,
                      AU_VORGELEGT, BEZAHLT, BEMERKUNG, STORNIERT,
                      STATUS, STATUS_GEAEND_AT, STATUS_GEAEND_VON,
                      ERSTELLT_AT, ERSTELLT_VON, GEAEND_AT, GEAEND_VON
                 FROM XT_PERSONAL_ABWESENHEIT
                WHERE REC_ID = %s""",
            (int(rec_id),),
        )
        return cur.fetchone()


_ABWESENHEIT_UPD_FELDER: tuple[str, ...] = (
    'TYP', 'VON', 'BIS', 'GANZTAGS', 'STUNDEN',
    'AU_VORGELEGT', 'BEZAHLT', 'BEMERKUNG',
)


def abwesenheit_bearbeiten(rec_id: int, werte: dict,
                           benutzer_ma_id: int) -> int:
    """Aktualisiert zulaessige Felder einer Abwesenheit.

    Nur unveraenderte → leere Aenderungsliste → keine DB-Aktion, kein Log.
    Stornierte Eintraege lassen sich nicht mehr bearbeiten (→ LookupError).
    """
    alt = abwesenheit_by_id(rec_id)
    if not alt:
        raise LookupError(f'Abwesenheit {rec_id} nicht gefunden')
    if alt.get('STORNIERT'):
        raise LookupError(f'Abwesenheit {rec_id} ist storniert')

    neu: dict = {}
    for k in _ABWESENHEIT_UPD_FELDER:
        if k not in werte:
            continue
        v = werte[k]
        if k in ('GANZTAGS', 'AU_VORGELEGT', 'BEZAHLT'):
            v = 1 if v else 0
        if k == 'TYP' and v not in ABWESENHEIT_TYPEN:
            raise ValueError(f'TYP ungueltig: {v!r}')
        neu[k] = v
    if not neu:
        return 0

    # Sanity-Regeln nach dem Merge pruefen.
    effektiv = {**alt, **neu}
    if effektiv['BIS'] < effektiv['VON']:
        raise ValueError('BIS darf nicht vor VON liegen')
    if not effektiv['GANZTAGS'] and (effektiv.get('STUNDEN') is None
                                     or float(effektiv['STUNDEN']) <= 0):
        raise ValueError('Bei GANZTAGS=0 muss STUNDEN > 0 gesetzt sein')
    if effektiv['GANZTAGS']:
        neu['STUNDEN'] = None  # ganztags → Stunden leeren

    alt_snapshot = {k: alt.get(k) for k in neu}

    with get_db_rw() as cur:
        setlist = ', '.join(f'{k} = %s' for k in neu) + \
                  ', GEAEND_AT = NOW(), GEAEND_VON = %s'
        params = list(neu.values()) + [int(benutzer_ma_id), int(rec_id)]
        cur.execute(
            f"UPDATE XT_PERSONAL_ABWESENHEIT SET {setlist} WHERE REC_ID = %s",
            tuple(params),
        )
        _log_schreiben(
            cur, 'XT_PERSONAL_ABWESENHEIT_LOG',
            int(alt['PERS_ID']), int(rec_id), 'UPDATE',
            alt_snapshot, neu, benutzer_ma_id,
        )
        return cur.rowcount


def abwesenheit_stornieren(rec_id: int, benutzer_ma_id: int) -> int:
    """Soft-Delete: STORNIERT=1. Fuer echte DELETE gibt es keine Route."""
    alt = abwesenheit_by_id(rec_id)
    if not alt:
        raise LookupError(f'Abwesenheit {rec_id} nicht gefunden')
    if alt.get('STORNIERT'):
        return 0
    with get_db_rw() as cur:
        cur.execute(
            """UPDATE XT_PERSONAL_ABWESENHEIT
                  SET STORNIERT = 1, GEAEND_AT = NOW(), GEAEND_VON = %s
                WHERE REC_ID = %s""",
            (int(benutzer_ma_id), int(rec_id)),
        )
        _log_schreiben(
            cur, 'XT_PERSONAL_ABWESENHEIT_LOG',
            int(alt['PERS_ID']), int(rec_id), 'UPDATE',
            {'STORNIERT': 0}, {'STORNIERT': 1}, benutzer_ma_id,
        )
        return cur.rowcount


def abwesenheiten_ma(pers_id: int, jahr: int | None = None,
                     inkl_storniert: bool = False) -> list[dict]:
    """Liefert alle Abwesenheiten eines MA (optional nur eines Jahres)."""
    sql = ("""SELECT REC_ID, PERS_ID, TYP, VON, BIS, GANZTAGS, STUNDEN,
                     AU_VORGELEGT, BEZAHLT, BEMERKUNG, STORNIERT,
                     STATUS, STATUS_GEAEND_AT, STATUS_GEAEND_VON,
                     ERSTELLT_AT, ERSTELLT_VON, GEAEND_AT, GEAEND_VON
                FROM XT_PERSONAL_ABWESENHEIT
               WHERE PERS_ID = %s""")
    params: list = [int(pers_id)]
    if not inkl_storniert:
        sql += " AND STORNIERT = 0"
    if jahr is not None:
        sql += " AND YEAR(VON) <= %s AND YEAR(BIS) >= %s"
        params.extend([int(jahr), int(jahr)])
    sql += " ORDER BY VON DESC, REC_ID DESC"
    with get_db_ro() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchall() or []


def abwesenheiten_im_zeitraum(von: date, bis: date,
                              typ: str | None = None) -> list[dict]:
    """Liefert alle aktiven Abwesenheiten, die den Zeitraum schneiden.

    Analog zu ``urlaube_im_zeitraum`` – fuer Schichtplan-Konflikt-Pruefung.
    """
    sql = ("""SELECT a.REC_ID, a.PERS_ID, a.TYP, a.VON, a.BIS, a.GANZTAGS,
                     a.STUNDEN, a.BEZAHLT, a.BEMERKUNG, a.STATUS,
                     p.VNAME, p.NAME
                FROM XT_PERSONAL_ABWESENHEIT a
                JOIN XT_PERSONAL_MA p ON p.PERS_ID = a.PERS_ID
               WHERE a.STORNIERT = 0
                 AND a.VON <= %s AND a.BIS >= %s""")
    params: list = [bis, von]
    if typ is not None:
        if typ not in ABWESENHEIT_TYPEN:
            raise ValueError(f'TYP ungueltig: {typ!r}')
        sql += " AND a.TYP = %s"
        params.append(typ)
    sql += " ORDER BY a.PERS_ID, a.VON"
    with get_db_ro() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchall() or []


def abwesenheit_log(pers_id: int, limit: int = 50) -> list[dict]:
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, REF_REC_ID, OPERATION,
                      FELDER_ALT_JSON, FELDER_NEU_JSON,
                      GEAEND_AT, GEAEND_VON
                 FROM XT_PERSONAL_ABWESENHEIT_LOG
                WHERE PERS_ID = %s
                ORDER BY GEAEND_AT DESC, REC_ID DESC
                LIMIT %s""",
            (int(pers_id), int(limit)),
        )
        return cur.fetchall() or []


# ── P4b: Feiertage (gesetzlich + manuell) ────────────────────────────────────
#
# Hybrid-Design: gesetzliche Feiertage werden via `holidays`-Paket einmal pro
# Jahr in XT_PERSONAL_FEIERTAG eingefuegt (QUELLE='paket'). Manuelle Eintraege
# (Betriebsferien) landen mit QUELLE='manuell' in derselben Tabelle. Das
# konfigurierte Bundesland liegt in XT_EINSTELLUNGEN.personal_bundesland
# (gepflegt via Verwaltungs-App).
#

BUNDESLAENDER: tuple[tuple[str, str], ...] = (
    ('BW', 'Baden-Wuerttemberg'),
    ('BY', 'Bayern'),
    ('BE', 'Berlin'),
    ('BB', 'Brandenburg'),
    ('HB', 'Bremen'),
    ('HH', 'Hamburg'),
    ('HE', 'Hessen'),
    ('MV', 'Mecklenburg-Vorpommern'),
    ('NI', 'Niedersachsen'),
    ('NW', 'Nordrhein-Westfalen'),
    ('RP', 'Rheinland-Pfalz'),
    ('SL', 'Saarland'),
    ('SN', 'Sachsen'),
    ('ST', 'Sachsen-Anhalt'),
    ('SH', 'Schleswig-Holstein'),
    ('TH', 'Thueringen'),
)
_BUNDESLAND_KEYS = {k for k, _ in BUNDESLAENDER}
_FEIERTAG_BUNDESLAND_DEFAULT = 'BY'


def aktuelles_bundesland() -> str:
    """Liest das konfigurierte Bundesland (Kurzcode) aus XT_EINSTELLUNGEN.
    Fallback bei fehlender Zeile oder DB-Fehler: 'BY'."""
    try:
        with get_db_ro() as cur:
            cur.execute(
                "SELECT wert FROM XT_EINSTELLUNGEN WHERE schluessel = %s",
                ('personal_bundesland',),
            )
            row = cur.fetchone()
            if row and row.get('wert'):
                kuerzel = str(row['wert']).strip().upper()
                if kuerzel in _BUNDESLAND_KEYS:
                    return kuerzel
    except Exception:
        pass
    return _FEIERTAG_BUNDESLAND_DEFAULT


def ist_feiertag(tag: date,
                 bundesland: str | None = None) -> tuple[bool, str | None]:
    """Ist `tag` ein Feiertag? Sucht BUNDESLAND=<kuerzel> und 'BUND'.
    Liefert (True, NAME) oder (False, None). Manuelle Eintraege haben
    Vorrang vor Paket-Eintraegen am gleichen Tag.
    Bei DB-Fehlern (z.B. Tabelle noch nicht migriert) liefert die Funktion
    (False, None), damit abhaengige Logik nicht crasht."""
    bundesland = (bundesland or aktuelles_bundesland()).upper()
    try:
        with get_db_ro() as cur:
            cur.execute(
                """SELECT NAME FROM XT_PERSONAL_FEIERTAG
                    WHERE DATUM = %s AND BUNDESLAND IN (%s, 'BUND')
                    ORDER BY QUELLE = 'manuell' DESC, REC_ID ASC
                    LIMIT 1""",
                (tag, bundesland),
            )
            row = cur.fetchone()
            if row:
                return True, row['NAME']
    except Exception:
        pass
    return False, None


def feiertage_im_zeitraum(von: date, bis: date,
                          bundesland: str | None = None) -> dict[date, str]:
    """Alle Feiertage in [von, bis] als {datum: name}.
    Dient der Schichtplan-Markierung und der Urlaubs-Berechnung.
    Bei DB-Fehlern liefert die Funktion {}, damit abhaengige Logik nicht
    crasht (z.B. Tabelle noch nicht migriert, kein DB-Connection-Pool)."""
    if bis < von:
        return {}
    bundesland = (bundesland or aktuelles_bundesland()).upper()
    aus: dict[date, str] = {}
    try:
        with get_db_ro() as cur:
            cur.execute(
                """SELECT DATUM, NAME, QUELLE FROM XT_PERSONAL_FEIERTAG
                    WHERE DATUM BETWEEN %s AND %s
                      AND BUNDESLAND IN (%s, 'BUND')
                    ORDER BY DATUM, QUELLE = 'manuell' DESC, REC_ID ASC""",
                (von, bis, bundesland),
            )
            for r in cur.fetchall() or []:
                # erster Treffer pro Datum gewinnt (manuell bevorzugt)
                if r['DATUM'] not in aus:
                    aus[r['DATUM']] = r['NAME']
    except Exception:
        pass
    return aus


def feiertage_jahr(jahr: int,
                   bundesland: str | None = None) -> list[dict]:
    """Alle Feiertage eines Kalenderjahres als Liste von Zeilen-Dicts."""
    bundesland = (bundesland or aktuelles_bundesland()).upper()
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, DATUM, NAME, BUNDESLAND, QUELLE,
                      ERSTELLT_AT, ERSTELLT_VON
                 FROM XT_PERSONAL_FEIERTAG
                WHERE YEAR(DATUM) = %s AND BUNDESLAND IN (%s, 'BUND')
                ORDER BY DATUM, QUELLE = 'manuell' DESC, REC_ID ASC""",
            (int(jahr), bundesland),
        )
        return cur.fetchall() or []


def feiertage_sync_jahr(jahr: int,
                        bundesland: str | None = None) -> int:
    """Synchronisiert gesetzliche Feiertage aus dem `holidays`-Paket in die
    DB fuer (jahr, bundesland). INSERT IGNORE – existierende Eintraege
    bleiben unangetastet. Liefert Anzahl neu eingefuegter Zeilen."""
    import holidays  # lazy import – Paket ist in requirements.txt
    bundesland = (bundesland or aktuelles_bundesland()).upper()
    try:
        kal = holidays.country_holidays(
            'DE', subdiv=bundesland, years=int(jahr),
        )
    except Exception:
        # Fallback: bundesweite Tage, wenn subdiv nicht bekannt
        kal = holidays.country_holidays('DE', years=int(jahr))
    eingefuegt = 0
    with get_db_rw() as cur:
        for tag, name in sorted(kal.items()):
            cur.execute(
                """INSERT IGNORE INTO XT_PERSONAL_FEIERTAG
                     (DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_VON)
                   VALUES (%s, %s, %s, 'paket', NULL)""",
                (tag, str(name), bundesland),
            )
            eingefuegt += cur.rowcount
    return eingefuegt


def feiertag_manuell_anlegen(datum: date, name: str, bundesland: str,
                             benutzer_ma_id: int) -> int:
    """Legt einen manuellen Feiertag an (Betriebsferien, regionales Fest).
    Duplikate werden durch UNIQUE(DATUM, NAME, BUNDESLAND) verhindert."""
    bundesland = bundesland.strip().upper()
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_FEIERTAG
                 (DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_VON)
               VALUES (%s, %s, %s, 'manuell', %s)""",
            (datum, name.strip(), bundesland, int(benutzer_ma_id)),
        )
        return cur.lastrowid


def feiertag_loeschen(rec_id: int) -> int:
    """Loescht einen manuellen Feiertag. Paket-Eintraege (QUELLE='paket')
    lassen sich so nicht entfernen – ein erneuter Sync wuerde sie ohnehin
    wieder anlegen."""
    with get_db_rw() as cur:
        cur.execute(
            "DELETE FROM XT_PERSONAL_FEIERTAG "
            " WHERE REC_ID = %s AND QUELLE = 'manuell'",
            (int(rec_id),),
        )
        return cur.rowcount


# ── P3: Stempeluhr (Kommen/Gehen) ────────────────────────────────────────────
#
# Karten-basierter Self-Service-Stempel im Kiosk. Der Scan loest die KARTEN.GUID
# auf MITARBEITER.MA_ID auf (ueber common.auth.mitarbeiter_login_karte) und
# von dort auf XT_PERSONAL_MA.CAO_MA_ID. MAs ohne Verknuepfung koennen nicht
# stempeln – das ist Absicht, damit Backoffice-Nutzer nicht versehentlich
# stempeln.
#
# Die RICHTUNG wird aus dem letzten Stempel abgeleitet: War der letzte
# Stempel 'kommen', ist der naechste 'gehen' und umgekehrt. Ohne vorherigen
# Stempel startet es mit 'kommen'. Diese "last event wins"-Logik ist robust
# gegen Mitternachts-Uebergaenge und vergessene Ausstempler: die Korrektur
# passiert nachtraeglich im Backoffice.
#

def _ma_by_cao_ma_id(cao_ma_id: int) -> dict | None:
    """Findet XT_PERSONAL_MA anhand der CAO_MA_ID (Verknuepfung optional)."""
    with get_db_ro() as cur:
        cur.execute(
            "SELECT PERS_ID, VNAME, NAME, KUERZEL, AUSTRITT "
            "  FROM XT_PERSONAL_MA WHERE CAO_MA_ID = %s",
            (int(cao_ma_id),),
        )
        return cur.fetchone()


def cao_ma_kandidaten(pers_id: int | None = None) -> list[dict]:
    """CAO-Mitarbeiter mit Karte (KARTEN.TYP='M'), die noch nicht verknuepft
    sind. Die aktuelle Verknuepfung von ``pers_id`` (falls uebergeben) bleibt
    in der Liste, damit das Dropdown den aktuellen Wert anzeigen kann."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT m.MA_ID, m.VNAME, m.NAME, m.LOGIN_NAME, k.GUID,
                      (SELECT p.PERS_ID FROM XT_PERSONAL_MA p
                        WHERE p.CAO_MA_ID = m.MA_ID LIMIT 1) AS BELEGT_VON
                 FROM MITARBEITER m
                 JOIN KARTEN k ON k.ID = m.MA_ID AND k.TYP = 'M'
                WHERE m.VNAME IS NOT NULL
                ORDER BY m.NAME, m.VNAME"""
        )
        rows = cur.fetchall()
    return [r for r in rows if r['BELEGT_VON'] in (None, pers_id)]


def stempel_naechste_richtung(pers_id: int) -> str:
    """Leitet die naechste Richtung aus dem letzten Stempel ab.
    'kommen' wenn kein vorheriger Stempel oder der letzte war 'gehen',
    sonst 'gehen'."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT RICHTUNG FROM XT_PERSONAL_STEMPEL
                WHERE PERS_ID = %s
                ORDER BY ZEITPUNKT DESC, REC_ID DESC LIMIT 1""",
            (int(pers_id),),
        )
        row = cur.fetchone()
    if not row or row['RICHTUNG'] == 'gehen':
        return 'kommen'
    return 'gehen'


def stempeln_karte(guid: str, terminal_nr: int | None) -> dict:
    """Fuehrt einen Stempel-Vorgang per Kartenscan aus.

    Returns ein Status-dict mit mindestens ``ok`` (bool) und ``msg`` (str).
    Bei Erfolg zusaetzlich: ``pers_id``, ``vname``, ``name``, ``richtung``,
    ``zeitpunkt`` (datetime).
    """
    if not guid:
        return {'ok': False, 'msg': 'Kein Barcode erkannt.'}
    # Kartenscan aufloesen (CAO-KARTEN → MITARBEITER). Import lokal, damit
    # dieses Modul auch ohne common.auth importierbar bleibt (Tests).
    from common.auth import mitarbeiter_login_karte
    ma = mitarbeiter_login_karte(guid.strip())
    if not ma:
        return {'ok': False, 'msg': 'Karte nicht erkannt oder keine Mitarbeiterkarte.'}
    personal = _ma_by_cao_ma_id(ma['MA_ID'])
    if not personal:
        return {'ok': False,
                'msg': 'Karte gehoert zu einem CAO-Benutzer ohne Personaldatensatz.'}
    if personal.get('AUSTRITT') and personal['AUSTRITT'] <= date.today():
        return {'ok': False,
                'msg': f"{personal['VNAME']} {personal['NAME']} ist ausgetreten."}
    pers_id = int(personal['PERS_ID'])
    richtung = stempel_naechste_richtung(pers_id)
    zeitpunkt = datetime.now().replace(microsecond=0)
    tnr = int(terminal_nr) if terminal_nr else None
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_STEMPEL
                 (PERS_ID, RICHTUNG, ZEITPUNKT, QUELLE, TERMINAL_NR)
               VALUES (%s, %s, %s, 'kiosk', %s)""",
            (pers_id, richtung, zeitpunkt, tnr),
        )
    return {
        'ok':        True,
        'msg':       f"{'Willkommen' if richtung == 'kommen' else 'Tschuess'}, "
                     f"{personal['VNAME']}!",
        'pers_id':   pers_id,
        'vname':     personal['VNAME'],
        'name':      personal['NAME'],
        'richtung':  richtung,
        'zeitpunkt': zeitpunkt,
    }


def stempel_tagesliste(tag: date) -> list[dict]:
    """Alle Stempel eines Kalendertages, sortiert nach Name + Zeitpunkt.
    Liefert auch MA-Name fuer die Anzeige mit."""
    tag_start = datetime.combine(tag, datetime.min.time())
    tag_ende = tag_start + timedelta(days=1)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT s.REC_ID, s.PERS_ID, s.RICHTUNG, s.ZEITPUNKT,
                      s.QUELLE, s.TERMINAL_NR, s.KOMMENTAR,
                      m.VNAME, m.NAME, m.KUERZEL
                 FROM XT_PERSONAL_STEMPEL s
                 JOIN XT_PERSONAL_MA m ON m.PERS_ID = s.PERS_ID
                WHERE s.ZEITPUNKT >= %s AND s.ZEITPUNKT < %s
                ORDER BY m.NAME, m.VNAME, s.ZEITPUNKT, s.REC_ID""",
            (tag_start, tag_ende),
        )
        return cur.fetchall() or []


def stempel_ma_zeitraum(pers_id: int, von: date, bis: date) -> list[dict]:
    """Stempel eines MA im geschlossenen Zeitraum [von, bis]."""
    start = datetime.combine(von, datetime.min.time())
    ende = datetime.combine(bis, datetime.min.time()) + timedelta(days=1)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, RICHTUNG, ZEITPUNKT, QUELLE, TERMINAL_NR, KOMMENTAR
                 FROM XT_PERSONAL_STEMPEL
                WHERE PERS_ID = %s AND ZEITPUNKT >= %s AND ZEITPUNKT < %s
                ORDER BY ZEITPUNKT, REC_ID""",
            (int(pers_id), start, ende),
        )
        return cur.fetchall() or []


def _stempel_paare_tag(stempel: list[dict]) -> list[tuple[datetime, datetime]]:
    """Paart 'kommen'/'gehen' zu Arbeits-Intervallen. Unvollstaendige Paare
    (z.B. 'kommen' ohne zugehoeriges 'gehen') werden ignoriert. Liste ist
    erwartet nach ZEITPUNKT sortiert."""
    paare: list[tuple[datetime, datetime]] = []
    offen: datetime | None = None
    for s in stempel:
        if s['RICHTUNG'] == 'kommen':
            offen = s['ZEITPUNKT']
        elif s['RICHTUNG'] == 'gehen' and offen is not None:
            paare.append((offen, s['ZEITPUNKT']))
            offen = None
    return paare


def stempel_arbeitsdauer_min(pers_id: int, tag: date) -> int:
    """Summe der Kommen/Gehen-Intervalle eines Kalendertages in Minuten.
    Unvollstaendige Paare werden ignoriert (Backoffice muss korrigieren)."""
    stempel = stempel_ma_zeitraum(pers_id, tag, tag)
    total = 0
    for kom, geh in _stempel_paare_tag(stempel):
        delta = geh - kom
        total += int(delta.total_seconds() // 60)
    return max(0, total)


def stempel_tagesminuten_zeitraum(pers_id: int, von: date, bis: date) -> dict[date, int]:
    """Bulk-Variante: liefert {tag: minuten} fuer [von, bis] mit einer DB-Query.

    Fuer Arbeitszeitkonten wichtig: sonst braeuchte man pro MA×Tag eine
    Abfrage (~365 Queries pro MA). Stempel-Paare werden pro Kalendertag
    aggregiert; unvollstaendige Paare werden verworfen.
    """
    aus: dict[date, int] = {}
    stempel = stempel_ma_zeitraum(pers_id, von, bis)
    # Pro Kalendertag bucketen.
    nach_tag: dict[date, list[dict]] = {}
    for s in stempel:
        d = s['ZEITPUNKT'].date()
        nach_tag.setdefault(d, []).append(s)
    for tag, eintraege in nach_tag.items():
        total = 0
        for kom, geh in _stempel_paare_tag(eintraege):
            total += int((geh - kom).total_seconds() // 60)
        if total > 0:
            aus[tag] = total
    return aus


def _stempel_log_schreiben(cur, pers_id: int, ref_rec_id: int | None,
                            operation: str,
                            alt: dict | None, neu: dict | None,
                            grund: str, benutzer_ma_id: int) -> None:
    """Schreibt eine Zeile in XT_PERSONAL_STEMPEL_KORREKTUR (append-only)."""
    def _json(d: dict | None) -> str | None:
        if d is None:
            return None
        # datetime → ISO-String, damit JSON-serialisierbar.
        return json.dumps(
            {k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
             for k, v in d.items()},
            ensure_ascii=False,
        )
    cur.execute(
        """INSERT INTO XT_PERSONAL_STEMPEL_KORREKTUR
             (PERS_ID, REF_REC_ID, OPERATION,
              FELDER_ALT_JSON, FELDER_NEU_JSON, GRUND, GEAEND_VON)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (int(pers_id), ref_rec_id, operation,
         _json(alt), _json(neu), grund, int(benutzer_ma_id)),
    )


def stempel_korrektur_insert(pers_id: int, richtung: str, zeitpunkt: datetime,
                              grund: str, benutzer_ma_id: int,
                              kommentar: str | None = None) -> int:
    """Admin fuegt manuell einen fehlenden Stempel ein."""
    if richtung not in ('kommen', 'gehen'):
        raise ValueError(f"RICHTUNG muss 'kommen' oder 'gehen' sein, nicht {richtung!r}")
    if not grund or not grund.strip():
        raise ValueError('Grund ist Pflicht bei manueller Korrektur.')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_STEMPEL
                 (PERS_ID, RICHTUNG, ZEITPUNKT, QUELLE, KOMMENTAR, ERSTELLT_VON)
               VALUES (%s, %s, %s, 'korrektur', %s, %s)""",
            (int(pers_id), richtung, zeitpunkt, kommentar, int(benutzer_ma_id)),
        )
        neue_id = cur.lastrowid
        _stempel_log_schreiben(
            cur, pers_id, neue_id, 'INSERT',
            None,
            {'RICHTUNG': richtung, 'ZEITPUNKT': zeitpunkt, 'QUELLE': 'korrektur'},
            grund.strip(), benutzer_ma_id,
        )
        return neue_id


def stempel_korrektur_update(rec_id: int, richtung: str, zeitpunkt: datetime,
                              grund: str, benutzer_ma_id: int) -> int:
    """Admin aendert RICHTUNG und/oder ZEITPUNKT eines bestehenden Stempels."""
    if richtung not in ('kommen', 'gehen'):
        raise ValueError(f"RICHTUNG muss 'kommen' oder 'gehen' sein, nicht {richtung!r}")
    if not grund or not grund.strip():
        raise ValueError('Grund ist Pflicht bei manueller Korrektur.')
    with get_db_rw() as cur:
        cur.execute(
            "SELECT PERS_ID, RICHTUNG, ZEITPUNKT FROM XT_PERSONAL_STEMPEL "
            " WHERE REC_ID = %s",
            (int(rec_id),),
        )
        alt = cur.fetchone()
        if not alt:
            return 0
        cur.execute(
            "UPDATE XT_PERSONAL_STEMPEL "
            "   SET RICHTUNG = %s, ZEITPUNKT = %s "
            " WHERE REC_ID = %s",
            (richtung, zeitpunkt, int(rec_id)),
        )
        _stempel_log_schreiben(
            cur, int(alt['PERS_ID']), int(rec_id), 'UPDATE',
            {'RICHTUNG': alt['RICHTUNG'], 'ZEITPUNKT': alt['ZEITPUNKT']},
            {'RICHTUNG': richtung, 'ZEITPUNKT': zeitpunkt},
            grund.strip(), benutzer_ma_id,
        )
        return 1


def stempel_korrektur_delete(rec_id: int, grund: str,
                              benutzer_ma_id: int) -> int:
    """Admin loescht einen Stempel (Fehl-Scan). Log behaelt den Original-Wert."""
    if not grund or not grund.strip():
        raise ValueError('Grund ist Pflicht bei manueller Korrektur.')
    with get_db_rw() as cur:
        cur.execute(
            "SELECT PERS_ID, RICHTUNG, ZEITPUNKT, QUELLE "
            "  FROM XT_PERSONAL_STEMPEL WHERE REC_ID = %s",
            (int(rec_id),),
        )
        alt = cur.fetchone()
        if not alt:
            return 0
        cur.execute(
            "DELETE FROM XT_PERSONAL_STEMPEL WHERE REC_ID = %s",
            (int(rec_id),),
        )
        _stempel_log_schreiben(
            cur, int(alt['PERS_ID']), int(rec_id), 'DELETE',
            {'RICHTUNG':  alt['RICHTUNG'],
             'ZEITPUNKT': alt['ZEITPUNKT'],
             'QUELLE':    alt['QUELLE']},
            None, grund.strip(), benutzer_ma_id,
        )
        return 1


def stempel_korrektur_log(pers_id: int, limit: int = 50) -> list[dict]:
    """Korrektur-Historie eines MA (neuester zuerst)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, REF_REC_ID, OPERATION,
                      FELDER_ALT_JSON, FELDER_NEU_JSON,
                      GRUND, GEAEND_AT, GEAEND_VON
                 FROM XT_PERSONAL_STEMPEL_KORREKTUR
                WHERE PERS_ID = %s
                ORDER BY GEAEND_AT DESC, REC_ID DESC
                LIMIT %s""",
            (int(pers_id), int(limit)),
        )
        return cur.fetchall() or []


# ── P2: Schichtplanung ───────────────────────────────────────────────────────

SCHICHT_FELDER: tuple[str, ...] = (
    'BEZEICHNUNG', 'KUERZEL', 'TYP', 'STARTZEIT', 'ENDZEIT',
    'FARBE', 'AKTIV', 'SORT',
)

SCHICHT_TYPEN = ('fix', 'flex', 'aufgabe')


def schichten(nur_aktive: bool = True) -> list[dict]:
    sql = ("""SELECT SCHICHT_ID, BEZEICHNUNG, KUERZEL, TYP, STARTZEIT, ENDZEIT,
                     FARBE, AKTIV, SORT
                FROM XT_PERSONAL_SCHICHT""")
    if nur_aktive:
        sql += " WHERE AKTIV = 1"
    sql += " ORDER BY SORT, BEZEICHNUNG"
    with get_db_ro() as cur:
        cur.execute(sql)
        return cur.fetchall()


def schicht_by_id(schicht_id: int) -> dict | None:
    with get_db_ro() as cur:
        cur.execute("SELECT * FROM XT_PERSONAL_SCHICHT WHERE SCHICHT_ID = %s",
                    (int(schicht_id),))
        return cur.fetchone()


def _schicht_normalisiere(werte: dict) -> dict:
    out: dict[str, Any] = {}
    for k in SCHICHT_FELDER:
        if k in werte:
            v = werte[k]
            if isinstance(v, str) and v.strip() == '':
                v = None
            out[k] = v
    # fix-Schichten: STARTZEIT/ENDZEIT Pflicht; flex/aufgabe: Zeiten werden auf
    # NULL gezwungen, damit das UI nicht versehentlich Reste speichert.
    typ = out.get('TYP')
    if typ in ('flex', 'aufgabe'):
        out['STARTZEIT'] = None
        out['ENDZEIT']   = None
    return out


def schicht_insert(werte: dict, benutzer_ma_id: int) -> int:
    werte = _schicht_normalisiere(werte)
    if werte.get('TYP') not in SCHICHT_TYPEN:
        raise ValueError(f'Unbekannter Typ: {werte.get("TYP")!r}')
    for pflicht in ('BEZEICHNUNG', 'KUERZEL'):
        if not werte.get(pflicht):
            raise ValueError(f'Pflichtfeld fehlt: {pflicht}')
    if werte['TYP'] == 'fix' and (not werte.get('STARTZEIT')
                                   or not werte.get('ENDZEIT')):
        raise ValueError('Bei Typ "fix" sind Start- und Endzeit Pflicht.')
    cols = list(werte.keys()) + ['ERSTELLT_VON']
    placeholders = ', '.join(['%s'] * len(cols))
    params = tuple(list(werte.values()) + [int(benutzer_ma_id)])
    with get_db_rw() as cur:
        cur.execute(
            f"INSERT INTO XT_PERSONAL_SCHICHT ({', '.join(cols)}) "
            f"VALUES ({placeholders})",
            params,
        )
        return cur.lastrowid


def schicht_update(schicht_id: int, werte: dict, benutzer_ma_id: int) -> int:
    werte = _schicht_normalisiere(werte)
    if not werte:
        return 0
    if 'TYP' in werte and werte['TYP'] not in SCHICHT_TYPEN:
        raise ValueError(f'Unbekannter Typ: {werte["TYP"]!r}')
    sets = ', '.join(f'{k} = %s' for k in werte.keys())
    params = list(werte.values()) + [int(benutzer_ma_id), int(schicht_id)]
    with get_db_rw() as cur:
        cur.execute(
            f"UPDATE XT_PERSONAL_SCHICHT "
            f"   SET {sets}, GEAEND_AT = NOW(), GEAEND_VON = %s "
            f" WHERE SCHICHT_ID = %s",
            params,
        )
        return cur.rowcount


def _zeit_zu_min(t) -> int:
    if isinstance(t, timedelta):
        return int(t.total_seconds() // 60)
    return t.hour * 60 + t.minute


def schicht_brutto_min(schicht: dict, dauer_min: int | None = None) -> int:
    """Brutto-Arbeitsminuten einer Zuordnung (vor Pausenabzug).

    - TYP='fix':     Differenz STARTZEIT→ENDZEIT (Nachtschicht: +24h wenn ENDE<=START).
    - TYP='flex':    dauer_min (aus Zuordnung).
    - TYP='aufgabe': 0 (keine Arbeitszeitwirkung).
    """
    typ = schicht.get('TYP', 'fix')
    if typ == 'aufgabe':
        return 0
    if typ == 'flex':
        return int(dauer_min or 0)
    if not schicht.get('STARTZEIT') or not schicht.get('ENDZEIT'):
        return 0
    start = _zeit_zu_min(schicht['STARTZEIT'])
    ende  = _zeit_zu_min(schicht['ENDZEIT'])
    return ende - start if ende > start else (24 * 60 - start) + ende


# ── Pausenregelung ──────────────────────────────────────────────────────────

def pause_regelung_aktuell(stichtag: date | None = None) -> dict | None:
    stichtag = stichtag or date.today()
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, GUELTIG_AB, SCHWELLE1_MIN, PAUSE1_MIN,
                      SCHWELLE2_MIN, PAUSE2_MIN, PAUSE_BEZAHLT_FLAG, KOMMENTAR
                 FROM XT_PERSONAL_PAUSE_REGELUNG
                WHERE GUELTIG_AB <= %s
                ORDER BY GUELTIG_AB DESC LIMIT 1""",
            (stichtag,),
        )
        return cur.fetchone()


def pause_min_fuer_dauer(brutto_min: int,
                         regelung: dict | None) -> int:
    """Pausenminuten fuer eine gegebene Tages-Brutto-Arbeitszeit."""
    if not regelung or brutto_min <= 0:
        return 0
    if brutto_min > int(regelung['SCHWELLE2_MIN']):
        return int(regelung['PAUSE2_MIN'])
    if brutto_min > int(regelung['SCHWELLE1_MIN']):
        return int(regelung['PAUSE1_MIN'])
    return 0


def tagesarbeitszeit_min(zuordnungen: list[dict],
                         regelung: dict | None = None) -> dict:
    """Aggregiert eine Liste Zuordnungen (eines MAs an einem Tag) zu
    {'brutto_min', 'pause_min', 'netto_min'} entsprechend der Pausenregelung.
    Jeder Eintrag muss die Schicht-Stammdaten (TYP/STARTZEIT/ENDZEIT) und bei
    TYP=flex das Feld DAUER_MIN mitliefern (wie schicht_zuordnungen_woche)."""
    brutto = 0
    for z in zuordnungen:
        brutto += schicht_brutto_min(z, z.get('DAUER_MIN'))
    pause = pause_min_fuer_dauer(brutto, regelung)
    if regelung and regelung.get('PAUSE_BEZAHLT_FLAG'):
        netto = brutto  # Pause bezahlt → kein Abzug
    else:
        netto = max(0, brutto - pause)
    return {'brutto_min': brutto, 'pause_min': pause, 'netto_min': netto}


# ── Schicht-Zuordnungen ──────────────────────────────────────────────────────

def montag_der_woche(d: date) -> date:
    """Montag der Kalenderwoche, zu der d gehoert."""
    return d - timedelta(days=d.weekday())


def schicht_zuordnungen_woche(montag: date) -> list[dict]:
    """Alle Zuordnungen der KW, in der montag liegt – inkl. Schicht-Stammdaten."""
    sonntag = montag + timedelta(days=6)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT z.REC_ID, z.PERS_ID, z.DATUM, z.SCHICHT_ID, z.DAUER_MIN,
                      z.KOMMENTAR,
                      s.BEZEICHNUNG, s.KUERZEL, s.TYP,
                      s.STARTZEIT, s.ENDZEIT, s.FARBE, s.SORT
                 FROM XT_PERSONAL_SCHICHT_ZUORDNUNG z
                 JOIN XT_PERSONAL_SCHICHT s ON s.SCHICHT_ID = z.SCHICHT_ID
                WHERE z.DATUM BETWEEN %s AND %s
                ORDER BY z.DATUM, s.SORT, s.STARTZEIT""",
            (montag, sonntag),
        )
        return cur.fetchall()


def schicht_zuordnung_insert(pers_id: int, datum: date, schicht_id: int,
                             kommentar: str | None,
                             benutzer_ma_id: int,
                             dauer_min: int | None = None) -> int:
    # Schicht-Typ pruefen und DAUER_MIN validieren
    schicht = schicht_by_id(schicht_id)
    if not schicht:
        raise LookupError(f'Schicht {schicht_id} nicht gefunden.')
    typ = schicht['TYP']
    if typ == 'flex':
        if not dauer_min or int(dauer_min) <= 0:
            raise ValueError('Bei Typ "flex" ist DAUER_MIN (>0) Pflicht.')
        dauer_min = int(dauer_min)
    else:
        # fix/aufgabe → DAUER_MIN immer NULL (Daten konsistent halten)
        dauer_min = None
    # Gesperrt-Schutz: freigegebene Woche sperrt jede Aenderung der Zuordnungen.
    if ist_woche_gesperrt(datum):
        jahr, kw = _iso_jahr_kw(datum)
        raise ValueError(
            f'KW {kw:02d}/{jahr} ist freigegeben und gesperrt. '
            f'Bitte zuerst entsperren.'
        )
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_SCHICHT_ZUORDNUNG
                 (PERS_ID, DATUM, SCHICHT_ID, DAUER_MIN, KOMMENTAR, ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (int(pers_id), datum, int(schicht_id), dauer_min, kommentar,
             int(benutzer_ma_id)),
        )
        return cur.lastrowid


def schicht_zuordnung_delete(rec_id: int) -> int:
    with get_db_rw() as cur:
        # DATUM der Zuordnung laden, damit wir die KW-Sperre pruefen koennen.
        cur.execute(
            "SELECT DATUM FROM XT_PERSONAL_SCHICHT_ZUORDNUNG WHERE REC_ID = %s",
            (int(rec_id),),
        )
        row = cur.fetchone()
        if row and ist_woche_gesperrt(row['DATUM']):
            jahr, kw = _iso_jahr_kw(row['DATUM'])
            raise ValueError(
                f'KW {kw:02d}/{jahr} ist freigegeben und gesperrt. '
                f'Bitte zuerst entsperren.'
            )
        cur.execute(
            "DELETE FROM XT_PERSONAL_SCHICHT_ZUORDNUNG WHERE REC_ID = %s",
            (int(rec_id),),
        )
        return cur.rowcount


# ── Wochen-Status (Freigabe-Workflow, Iteration 1) ──────────────────────────

def _iso_jahr_kw(datum: date) -> tuple[int, int]:
    """(ISO-Jahr, ISO-KW) fuer ein Datum. Die KW-Grenzen folgen ISO 8601;
    das ISO-Jahr kann vom Kalenderjahr abweichen (z.B. 31.12.2024 → 2025-W01)."""
    iso = datum.isocalendar()
    return int(iso[0]), int(iso[1])


def woche_status(jahr: int, kw: int) -> dict:
    """Liest den Workflow-Status einer KW. Gibt immer ein Dict zurueck:
    kein Eintrag in der Tabelle → virtueller 'offen'-Status ohne Metadaten."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT w.JAHR, w.KW, w.STATUS, w.FREIGEGEBEN_AT,
                      w.FREIGEGEBEN_VON, w.KOMMENTAR,
                      w.GEAEND_AT, w.GEAEND_VON,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS FREIGEGEBEN_NAME
                 FROM XT_PERSONAL_SCHICHTPLAN_WOCHE w
            LEFT JOIN MITARBEITER m ON m.MA_ID = w.FREIGEGEBEN_VON
                WHERE w.JAHR = %s AND w.KW = %s""",
            (int(jahr), int(kw)),
        )
        row = cur.fetchone()
    if row:
        return row
    return {
        'JAHR': int(jahr), 'KW': int(kw), 'STATUS': 'offen',
        'FREIGEGEBEN_AT': None, 'FREIGEGEBEN_VON': None,
        'FREIGEGEBEN_NAME': None, 'KOMMENTAR': None,
        'GEAEND_AT': None, 'GEAEND_VON': None,
    }


def ist_woche_gesperrt(datum_oder_jahr: date | int, kw: int | None = None) -> bool:
    """True, wenn die KW (zu der datum gehoert, bzw. explizit uebergeben)
    STATUS='freigegeben' hat.

    Zwei Aufrufformen:
        ist_woche_gesperrt(datum)           # ISO-KW aus Datum ableiten
        ist_woche_gesperrt(jahr, kw)        # explizite KW
    """
    if isinstance(datum_oder_jahr, date) and kw is None:
        jahr, kw = _iso_jahr_kw(datum_oder_jahr)
    else:
        jahr = int(datum_oder_jahr)
        if kw is None:
            raise TypeError('kw fehlt')
    with get_db_ro() as cur:
        cur.execute(
            """SELECT 1 FROM XT_PERSONAL_SCHICHTPLAN_WOCHE
                WHERE JAHR = %s AND KW = %s AND STATUS = 'freigegeben'""",
            (int(jahr), int(kw)),
        )
        return cur.fetchone() is not None


def _woche_log_schreiben(cur, jahr: int, kw: int, ereignis: str,
                         detail: str | None,
                         benutzer_ma_id: int | None) -> None:
    cur.execute(
        """INSERT INTO XT_PERSONAL_SCHICHTPLAN_WOCHE_LOG
             (JAHR, KW, EREIGNIS, DETAIL, GEAEND_VON)
           VALUES (%s, %s, %s, %s, %s)""",
        (int(jahr), int(kw), ereignis, detail,
         int(benutzer_ma_id) if benutzer_ma_id is not None else None),
    )


def woche_freigeben(jahr: int, kw: int, benutzer_ma_id: int,
                    kommentar: str | None = None) -> int:
    """Setzt STATUS offen→freigegeben, schreibt Log-Eintrag 'freigegeben'.
    Idempotent: bereits freigegebene Wochen werfen ValueError."""
    with get_db_rw() as cur:
        cur.execute(
            "SELECT STATUS FROM XT_PERSONAL_SCHICHTPLAN_WOCHE "
            " WHERE JAHR = %s AND KW = %s FOR UPDATE",
            (int(jahr), int(kw)),
        )
        row = cur.fetchone()
        if row and row['STATUS'] == 'freigegeben':
            raise ValueError(f'KW {kw:02d}/{jahr} ist bereits freigegeben.')
        if row:
            cur.execute(
                """UPDATE XT_PERSONAL_SCHICHTPLAN_WOCHE
                      SET STATUS = 'freigegeben',
                          FREIGEGEBEN_AT  = NOW(),
                          FREIGEGEBEN_VON = %s,
                          KOMMENTAR       = %s,
                          GEAEND_VON      = %s
                    WHERE JAHR = %s AND KW = %s""",
                (int(benutzer_ma_id), kommentar, int(benutzer_ma_id),
                 int(jahr), int(kw)),
            )
        else:
            cur.execute(
                """INSERT INTO XT_PERSONAL_SCHICHTPLAN_WOCHE
                     (JAHR, KW, STATUS, FREIGEGEBEN_AT, FREIGEGEBEN_VON,
                      KOMMENTAR, GEAEND_VON)
                   VALUES (%s, %s, 'freigegeben', NOW(), %s, %s, %s)""",
                (int(jahr), int(kw), int(benutzer_ma_id), kommentar,
                 int(benutzer_ma_id)),
            )
        _woche_log_schreiben(cur, jahr, kw, 'freigegeben', kommentar,
                             benutzer_ma_id)
        return cur.rowcount


def woche_entsperren(jahr: int, kw: int, benutzer_ma_id: int,
                     kommentar: str | None = None) -> int:
    """Setzt STATUS freigegeben→offen, schreibt Log-Eintrag 'entsperrt'.
    Bei bereits offener Woche: ValueError."""
    with get_db_rw() as cur:
        cur.execute(
            "SELECT STATUS FROM XT_PERSONAL_SCHICHTPLAN_WOCHE "
            " WHERE JAHR = %s AND KW = %s FOR UPDATE",
            (int(jahr), int(kw)),
        )
        row = cur.fetchone()
        if not row or row['STATUS'] != 'freigegeben':
            raise ValueError(f'KW {kw:02d}/{jahr} ist nicht freigegeben.')
        cur.execute(
            """UPDATE XT_PERSONAL_SCHICHTPLAN_WOCHE
                  SET STATUS = 'offen',
                      KOMMENTAR  = %s,
                      GEAEND_VON = %s
                WHERE JAHR = %s AND KW = %s""",
            (kommentar, int(benutzer_ma_id), int(jahr), int(kw)),
        )
        _woche_log_schreiben(cur, jahr, kw, 'entsperrt', kommentar,
                             benutzer_ma_id)
        return cur.rowcount


def schichtplan_kopieren_in_woche(quelle_montag: date, ziel_montag: date,
                                  benutzer_ma_id: int) -> dict:
    """Kopiert alle Zuordnungen der Quell-KW tagesweise in die Ziel-KW.

    Regeln (Iteration 2):
      - Quell- und Ziel-Montag muessen Wochenanfang sein (Mo).
      - Ziel-KW muss in der Zukunft liegen (ziel_montag > heute).
      - Ziel-KW muss leer sein (keine Zuordnungen) → sonst Abbruch.
      - Ziel-KW darf nicht freigegeben sein.
      - Urlaub / Austritt im Ziel: Zuordnung wird trotzdem angelegt, aber
        als Warnung im Ergebnis-Dict gemeldet (Planer nacharbeiten).

    Rueckgabe: {'kopiert': n, 'warnungen': [str, ...]}."""
    if quelle_montag.weekday() != 0 or ziel_montag.weekday() != 0:
        raise ValueError('Quell- und Ziel-Datum muessen Montage sein.')
    if ziel_montag <= date.today():
        raise ValueError('Ziel-KW muss in der Zukunft liegen.')
    if quelle_montag == ziel_montag:
        raise ValueError('Quell- und Ziel-KW duerfen nicht gleich sein.')

    ziel_jahr, ziel_kw = _iso_jahr_kw(ziel_montag)
    quell_jahr, quell_kw = _iso_jahr_kw(quelle_montag)
    ziel_sonntag = ziel_montag + timedelta(days=6)
    tag_verschiebung = (ziel_montag - quelle_montag).days

    warnungen: list[str] = []
    with get_db_rw() as cur:
        # Ziel-KW darf nicht freigegeben sein.
        cur.execute(
            """SELECT STATUS FROM XT_PERSONAL_SCHICHTPLAN_WOCHE
                WHERE JAHR = %s AND KW = %s""",
            (ziel_jahr, ziel_kw),
        )
        row = cur.fetchone()
        if row and row['STATUS'] == 'freigegeben':
            raise ValueError(
                f'Ziel-KW {ziel_kw:02d}/{ziel_jahr} ist freigegeben. '
                f'Bitte zuerst entsperren.'
            )
        # Ziel-KW muss leer sein.
        cur.execute(
            """SELECT COUNT(*) AS n FROM XT_PERSONAL_SCHICHT_ZUORDNUNG
                WHERE DATUM BETWEEN %s AND %s""",
            (ziel_montag, ziel_sonntag),
        )
        n_ziel = int(cur.fetchone()['n'])
        if n_ziel > 0:
            raise ValueError(
                f'Ziel-KW {ziel_kw:02d}/{ziel_jahr} enthaelt bereits '
                f'{n_ziel} Zuordnungen. Bitte zuerst leeren.'
            )
        # Quell-Zuordnungen laden.
        quell_sonntag = quelle_montag + timedelta(days=6)
        cur.execute(
            """SELECT PERS_ID, DATUM, SCHICHT_ID, DAUER_MIN, KOMMENTAR
                 FROM XT_PERSONAL_SCHICHT_ZUORDNUNG
                WHERE DATUM BETWEEN %s AND %s""",
            (quelle_montag, quell_sonntag),
        )
        quell = cur.fetchall()
        if not quell:
            raise ValueError(
                f'Quell-KW {quell_kw:02d}/{quell_jahr} enthaelt keine '
                f'Zuordnungen zum Kopieren.'
            )
        # Urlaube im Ziel-Zeitraum laden (fuer Warnungen).
        cur.execute(
            """SELECT PERS_ID, VON, BIS, STATUS
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE STATUS IN ('geplant','genehmigt','genommen')
                  AND NOT (BIS < %s OR VON > %s)""",
            (ziel_montag, ziel_sonntag),
        )
        urlaube = cur.fetchall()
        # Aktive MA am Ziel-Sonntag (Austritt-Check).
        cur.execute(
            """SELECT PERS_ID, VNAME, NAME, EINTRITT, AUSTRITT
                 FROM XT_PERSONAL_MA""",
        )
        ma_index = {r['PERS_ID']: r for r in cur.fetchall()}

        kopiert = 0
        for z in quell:
            neu_datum = z['DATUM'] + timedelta(days=tag_verschiebung)
            cur.execute(
                """INSERT INTO XT_PERSONAL_SCHICHT_ZUORDNUNG
                     (PERS_ID, DATUM, SCHICHT_ID, DAUER_MIN, KOMMENTAR,
                      ERSTELLT_VON)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (int(z['PERS_ID']), neu_datum, int(z['SCHICHT_ID']),
                 z['DAUER_MIN'], z['KOMMENTAR'], int(benutzer_ma_id)),
            )
            kopiert += 1
            # Warnung: Urlaub am neu_datum?
            for u in urlaube:
                if (u['PERS_ID'] == z['PERS_ID']
                        and u['VON'] <= neu_datum <= u['BIS']):
                    ma = ma_index.get(z['PERS_ID'], {})
                    warnungen.append(
                        f"{ma.get('VNAME','')} {ma.get('NAME','')} hat "
                        f"{u['STATUS']}-Urlaub am "
                        f"{neu_datum.strftime('%d.%m.%Y')}"
                    )
                    break
            # Warnung: MA am Ziel-Datum nicht mehr aktiv?
            ma = ma_index.get(z['PERS_ID'], {})
            austritt = ma.get('AUSTRITT')
            eintritt = ma.get('EINTRITT')
            if austritt and neu_datum > austritt:
                warnungen.append(
                    f"{ma.get('VNAME','')} {ma.get('NAME','')} ist am "
                    f"{neu_datum.strftime('%d.%m.%Y')} nicht mehr aktiv "
                    f"(Austritt {austritt.strftime('%d.%m.%Y')})"
                )
            elif eintritt and neu_datum < eintritt:
                warnungen.append(
                    f"{ma.get('VNAME','')} {ma.get('NAME','')} ist am "
                    f"{neu_datum.strftime('%d.%m.%Y')} noch nicht aktiv "
                    f"(Eintritt {eintritt.strftime('%d.%m.%Y')})"
                )
        # Log-Eintrag an der Quell-KW: "kopiert-nach JAHR/KW"
        _woche_log_schreiben(
            cur, quell_jahr, quell_kw, 'kopiert-nach',
            f'{ziel_kw:02d}/{ziel_jahr} ({kopiert} Zuordnungen'
            + (f', {len(warnungen)} Warnung(en)' if warnungen else '') + ')',
            benutzer_ma_id,
        )
    return {'kopiert': kopiert, 'warnungen': warnungen}


def vorlage_liste() -> list[dict]:
    """Alle verfuegbaren Vorlagen, neueste zuerst, mit Anzahl Zuordnungen."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT v.REC_ID, v.NAME, v.BESCHREIBUNG,
                      v.ERSTELLT_AT, v.ERSTELLT_VON,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS ERSTELLT_NAME,
                      (SELECT COUNT(*)
                         FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE_ZUORDNUNG z
                        WHERE z.VORLAGE_REC_ID = v.REC_ID) AS ANZAHL
                 FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE v
            LEFT JOIN MITARBEITER m ON m.MA_ID = v.ERSTELLT_VON
                ORDER BY v.ERSTELLT_AT DESC, v.REC_ID DESC"""
        )
        return cur.fetchall()


def vorlage_speichern(quelle_montag: date, name: str,
                      benutzer_ma_id: int,
                      beschreibung: str | None = None) -> int:
    """Speichert die Zuordnungen der Quell-KW als Vorlage.

    DATUM wird in WOCHENTAG (0=Mo..6=So) uebersetzt; keine KW-Bindung.
    NAME muss eindeutig sein.
    Leere Quell-KW → ValueError."""
    if quelle_montag.weekday() != 0:
        raise ValueError('Quell-Datum muss ein Montag sein.')
    name = (name or '').strip()
    if not name:
        raise ValueError('Vorlagen-Name darf nicht leer sein.')
    quell_sonntag = quelle_montag + timedelta(days=6)

    with get_db_rw() as cur:
        cur.execute(
            """SELECT PERS_ID, DATUM, SCHICHT_ID, DAUER_MIN, KOMMENTAR
                 FROM XT_PERSONAL_SCHICHT_ZUORDNUNG
                WHERE DATUM BETWEEN %s AND %s""",
            (quelle_montag, quell_sonntag),
        )
        quell = cur.fetchall()
        if not quell:
            raise ValueError(
                'Quell-KW enthaelt keine Zuordnungen zum Speichern.'
            )
        cur.execute(
            """SELECT REC_ID FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE
                WHERE NAME = %s""",
            (name,),
        )
        if cur.fetchone():
            raise ValueError(f'Vorlage "{name}" existiert bereits.')

        cur.execute(
            """INSERT INTO XT_PERSONAL_SCHICHTPLAN_VORLAGE
                 (NAME, BESCHREIBUNG, ERSTELLT_VON)
               VALUES (%s, %s, %s)""",
            (name, beschreibung, int(benutzer_ma_id)),
        )
        vorlage_id = int(cur.lastrowid)
        for z in quell:
            wtag = (z['DATUM'] - quelle_montag).days
            cur.execute(
                """INSERT INTO XT_PERSONAL_SCHICHTPLAN_VORLAGE_ZUORDNUNG
                     (VORLAGE_REC_ID, WOCHENTAG, PERS_ID, SCHICHT_ID,
                      DAUER_MIN, KOMMENTAR)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (vorlage_id, int(wtag), int(z['PERS_ID']),
                 int(z['SCHICHT_ID']), z['DAUER_MIN'], z['KOMMENTAR']),
            )
        return vorlage_id


def vorlage_laden(rec_id: int) -> dict | None:
    """Liefert Vorlage-Header + Zuordnungen (sortiert nach WOCHENTAG)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, NAME, BESCHREIBUNG, ERSTELLT_AT, ERSTELLT_VON
                 FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE
                WHERE REC_ID = %s""",
            (int(rec_id),),
        )
        v = cur.fetchone()
        if not v:
            return None
        cur.execute(
            """SELECT WOCHENTAG, PERS_ID, SCHICHT_ID, DAUER_MIN, KOMMENTAR
                 FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE_ZUORDNUNG
                WHERE VORLAGE_REC_ID = %s
                ORDER BY WOCHENTAG, REC_ID""",
            (int(rec_id),),
        )
        v['zuordnungen'] = cur.fetchall()
        return v


def vorlage_loeschen(rec_id: int) -> int:
    """Loescht Vorlage + alle Zuordnungen. Gibt Anzahl geloeschte Header zurueck."""
    with get_db_rw() as cur:
        cur.execute(
            """DELETE FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE_ZUORDNUNG
                WHERE VORLAGE_REC_ID = %s""",
            (int(rec_id),),
        )
        cur.execute(
            """DELETE FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE
                WHERE REC_ID = %s""",
            (int(rec_id),),
        )
        return cur.rowcount


def vorlage_anwenden(rec_id: int, ziel_montag: date,
                     benutzer_ma_id: int) -> dict:
    """Wendet Vorlage auf Ziel-KW an.

    Regeln (analog Kopieren):
      - ziel_montag muss Montag sein, in der Zukunft, nicht freigegeben.
      - Ziel-KW muss leer sein.
      - Warnungen fuer Urlaub- / Austritt- / Eintritt-Konflikte.

    Rueckgabe: {'angelegt': n, 'warnungen': [...]}."""
    if ziel_montag.weekday() != 0:
        raise ValueError('Ziel-Datum muss ein Montag sein.')
    if ziel_montag <= date.today():
        raise ValueError('Ziel-KW muss in der Zukunft liegen.')

    ziel_jahr, ziel_kw = _iso_jahr_kw(ziel_montag)
    ziel_sonntag = ziel_montag + timedelta(days=6)
    warnungen: list[str] = []

    with get_db_rw() as cur:
        cur.execute(
            """SELECT REC_ID, NAME FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE
                WHERE REC_ID = %s""",
            (int(rec_id),),
        )
        v = cur.fetchone()
        if not v:
            raise ValueError(f'Vorlage {rec_id} nicht gefunden.')
        cur.execute(
            """SELECT STATUS FROM XT_PERSONAL_SCHICHTPLAN_WOCHE
                WHERE JAHR = %s AND KW = %s""",
            (ziel_jahr, ziel_kw),
        )
        row = cur.fetchone()
        if row and row['STATUS'] == 'freigegeben':
            raise ValueError(
                f'Ziel-KW {ziel_kw:02d}/{ziel_jahr} ist freigegeben. '
                f'Bitte zuerst entsperren.'
            )
        cur.execute(
            """SELECT COUNT(*) AS n FROM XT_PERSONAL_SCHICHT_ZUORDNUNG
                WHERE DATUM BETWEEN %s AND %s""",
            (ziel_montag, ziel_sonntag),
        )
        n_ziel = int(cur.fetchone()['n'])
        if n_ziel > 0:
            raise ValueError(
                f'Ziel-KW {ziel_kw:02d}/{ziel_jahr} enthaelt bereits '
                f'{n_ziel} Zuordnungen. Bitte zuerst leeren.'
            )
        cur.execute(
            """SELECT WOCHENTAG, PERS_ID, SCHICHT_ID, DAUER_MIN, KOMMENTAR
                 FROM XT_PERSONAL_SCHICHTPLAN_VORLAGE_ZUORDNUNG
                WHERE VORLAGE_REC_ID = %s""",
            (int(rec_id),),
        )
        vzs = cur.fetchall()
        if not vzs:
            raise ValueError(f'Vorlage "{v["NAME"]}" enthaelt keine Zuordnungen.')

        cur.execute(
            """SELECT PERS_ID, VON, BIS, STATUS
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE STATUS IN ('geplant','genehmigt','genommen')
                  AND NOT (BIS < %s OR VON > %s)""",
            (ziel_montag, ziel_sonntag),
        )
        urlaube = cur.fetchall()
        cur.execute(
            """SELECT PERS_ID, VNAME, NAME, EINTRITT, AUSTRITT
                 FROM XT_PERSONAL_MA"""
        )
        ma_index = {r['PERS_ID']: r for r in cur.fetchall()}

        angelegt = 0
        for z in vzs:
            neu_datum = ziel_montag + timedelta(days=int(z['WOCHENTAG']))
            cur.execute(
                """INSERT INTO XT_PERSONAL_SCHICHT_ZUORDNUNG
                     (PERS_ID, DATUM, SCHICHT_ID, DAUER_MIN, KOMMENTAR,
                      ERSTELLT_VON)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (int(z['PERS_ID']), neu_datum, int(z['SCHICHT_ID']),
                 z['DAUER_MIN'], z['KOMMENTAR'], int(benutzer_ma_id)),
            )
            angelegt += 1
            for u in urlaube:
                if (u['PERS_ID'] == z['PERS_ID']
                        and u['VON'] <= neu_datum <= u['BIS']):
                    ma = ma_index.get(z['PERS_ID'], {})
                    warnungen.append(
                        f"{ma.get('VNAME','')} {ma.get('NAME','')} hat "
                        f"{u['STATUS']}-Urlaub am "
                        f"{neu_datum.strftime('%d.%m.%Y')}"
                    )
                    break
            ma = ma_index.get(z['PERS_ID'], {})
            austritt = ma.get('AUSTRITT')
            eintritt = ma.get('EINTRITT')
            if austritt and neu_datum > austritt:
                warnungen.append(
                    f"{ma.get('VNAME','')} {ma.get('NAME','')} ist am "
                    f"{neu_datum.strftime('%d.%m.%Y')} nicht mehr aktiv "
                    f"(Austritt {austritt.strftime('%d.%m.%Y')})"
                )
            elif eintritt and neu_datum < eintritt:
                warnungen.append(
                    f"{ma.get('VNAME','')} {ma.get('NAME','')} ist am "
                    f"{neu_datum.strftime('%d.%m.%Y')} noch nicht aktiv "
                    f"(Eintritt {eintritt.strftime('%d.%m.%Y')})"
                )
        _woche_log_schreiben(
            cur, ziel_jahr, ziel_kw, 'vorlage-angewendet',
            f'{v["NAME"]} ({angelegt} Zuordnungen'
            + (f', {len(warnungen)} Warnung(en)' if warnungen else '') + ')',
            benutzer_ma_id,
        )
    return {'angelegt': angelegt, 'warnungen': warnungen}


def woche_log(jahr: int, kw: int, limit: int = 50) -> list[dict]:
    """Workflow-Log einer KW (neueste zuerst)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT l.REC_ID, l.JAHR, l.KW, l.EREIGNIS, l.DETAIL,
                      l.GEAEND_AT, l.GEAEND_VON,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS GEAEND_NAME
                 FROM XT_PERSONAL_SCHICHTPLAN_WOCHE_LOG l
            LEFT JOIN MITARBEITER m ON m.MA_ID = l.GEAEND_VON
                WHERE l.JAHR = %s AND l.KW = %s
                ORDER BY l.GEAEND_AT DESC, l.REC_ID DESC
                LIMIT %s""",
            (int(jahr), int(kw), int(limit)),
        )
        return cur.fetchall()


def urlaube_im_zeitraum(von: date, bis: date) -> list[dict]:
    """Genehmigte/geplante/genommene Urlaubsantraege, die sich mit [von, bis]
    ueberschneiden. Fuer UI-Sperre in der Schichtplanung."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, PERS_ID, VON, BIS, STATUS
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE STATUS IN ('geplant','genehmigt','genommen')
                  AND NOT (BIS < %s OR VON > %s)""",
            (von, bis),
        )
        return cur.fetchall()


def urlaub_antraege_offen(limit: int = 20) -> list[dict]:
    """Offene (noch nicht genehmigte/abgelehnte) Urlaubsantraege, aelteste zuerst.
    Fuer Dashboard-Widget und spaeter Genehmigungs-Liste."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT a.REC_ID, a.PERS_ID, a.VON, a.BIS, a.ARBEITSTAGE,
                     a.KOMMENTAR, a.ERSTELLT_AT,
                     p.VNAME, p.NAME, p.KUERZEL
                FROM XT_PERSONAL_URLAUB_ANTRAG a
                JOIN XT_PERSONAL_MA p ON p.PERS_ID = a.PERS_ID
               WHERE a.STATUS = 'geplant'
               ORDER BY a.ERSTELLT_AT ASC
               LIMIT %s""",
            (int(limit),),
        )
        return cur.fetchall() or []


def status_fuer_dashboard(heute: date, preview_n: int = 3) -> dict:
    """Aggregat fuer das WaWi-Hauptdashboard: Abwesenheiten heute + offene
    Urlaubsantraege.

    Liefert Dict mit:
        abw_heute_count, abw_heute_preview (bis preview_n Eintraege),
        antraege_offen_count, antraege_offen_preview (bis preview_n),
        ampel ∈ {'gruen','gelb','rot'}.

    Ampel:
        rot  – offene Antraege liegen vor (Aktion noetig)
        gelb – niemand offen, aber Abwesenheiten heute (Info)
        gruen – keine offenen Antraege und keine Abwesenheiten heute
    """
    abw_heute = abwesenheiten_im_zeitraum(heute, heute)
    antraege  = urlaub_antraege_offen(limit=max(preview_n, 20))

    abw_heute_count = len(abw_heute)
    antraege_offen_count = len(antraege)

    if antraege_offen_count > 0:
        ampel = 'rot'
    elif abw_heute_count > 0:
        ampel = 'gelb'
    else:
        ampel = 'gruen'

    # TYP-Label pro Abwesenheits-Eintrag dazupacken (spart Jinja-Lookup).
    preview_abw = []
    for a in abw_heute[:preview_n]:
        a2 = dict(a)
        a2['TYP_LABEL'] = ABWESENHEIT_TYP_LABELS.get(a['TYP'], a['TYP'])
        preview_abw.append(a2)

    return {
        'ampel': ampel,
        'abw_heute_count':       abw_heute_count,
        'abw_heute_preview':     preview_abw,
        'antraege_offen_count':  antraege_offen_count,
        'antraege_offen_preview': antraege[:preview_n],
    }


def ma_aktiv_am(tag: date) -> list[dict]:
    """Aktive MA am Stichtag (EINTRITT <= tag < AUSTRITT)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT PERS_ID, VNAME, NAME, KUERZEL, EINTRITT, AUSTRITT
                 FROM XT_PERSONAL_MA
                WHERE (EINTRITT IS NULL OR EINTRITT <= %s)
                  AND (AUSTRITT IS NULL OR AUSTRITT >= %s)
                ORDER BY NAME, VNAME""",
            (tag, tag),
        )
        return cur.fetchall()


def az_soll_woche_min(pers_id: int, montag: date) -> int | None:
    """Soll-Arbeitsminuten der Woche gemaess AZ-Modell. Summe STD_MO..STD_SO
    wenn Verteilung gepflegt; sonst STUNDEN_SOLL (×60) bei TYP=WOCHE,
    STUNDEN_SOLL × 60 / 4.33 bei TYP=MONAT. Gibt None zurueck, wenn kein
    gueltiges Modell existiert."""
    sonntag = montag + timedelta(days=6)
    modell = aktuelles_az_modell(pers_id, stichtag=sonntag)
    if not modell:
        return None
    verteilung = [modell.get(k) for k in WOCHENTAGE]
    if any(v is not None for v in verteilung):
        summe_h = sum(float(v) for v in verteilung if v is not None)
        return int(round(summe_h * 60))
    try:
        soll = float(modell['STUNDEN_SOLL']) if modell.get('STUNDEN_SOLL') else 0.0
    except (TypeError, ValueError):
        return None
    if modell.get('TYP') == 'MONAT':
        soll = soll / FAKTOR_WOCHE_MONAT
    return int(round(soll * 60))


# ── Schichtplan-Freigabe-Emails ──────────────────────────────────────────────
#
# Nach dem Freigeben einer KW erhaelt jeder zugeordnete MA mit hinterlegter
# Email-Adresse seinen persoenlichen Schichtplan als Benachrichtigung. Der
# Dev-Debug-Mode (caoxt.ini [Email] dev_empfaenger oder ENV) leitet alle
# Mails an die konfigurierte Test-Adresse um – siehe common/email.py.

def _freigabe_zuordnungen_lesen(cur, montag: date, sonntag: date) -> list[dict]:
    """Liest die aktuellen Schicht-Zuordnungen einer KW (fuer Mail + Snapshot)."""
    cur.execute(
        """SELECT z.REC_ID, z.PERS_ID, z.DATUM, z.SCHICHT_ID, z.DAUER_MIN,
                  s.BEZEICHNUNG, s.KUERZEL, s.TYP, s.STARTZEIT, s.ENDZEIT,
                  p.VNAME, p.NAME, p.EMAIL
             FROM XT_PERSONAL_SCHICHT_ZUORDNUNG z
             JOIN XT_PERSONAL_SCHICHT s ON s.SCHICHT_ID = z.SCHICHT_ID
             JOIN XT_PERSONAL_MA      p ON p.PERS_ID    = z.PERS_ID
            WHERE z.DATUM BETWEEN %s AND %s
            ORDER BY z.PERS_ID, z.DATUM""",
        (montag, sonntag),
    )
    return cur.fetchall() or []


def _snapshot_lesen(jahr: int, kw: int) -> list[dict]:
    """Liest den zuletzt gespeicherten Freigabe-Snapshot fuer (JAHR, KW).

    Rueckgabe: Liste von Zuordnungen mit denselben Keys wie der Live-Plan
    (PERS_ID, DATUM, SCHICHT_ID, BEZEICHNUNG, TYP, STARTZEIT, ENDZEIT,
    DAUER_MIN). Leere Liste = noch nie freigegeben.
    """
    with get_db_ro() as cur:
        cur.execute(
            """SELECT PERS_ID, DATUM, SCHICHT_ID, BEZEICHNUNG, TYP,
                      STARTZEIT, ENDZEIT, DAUER_MIN
                 FROM XT_PERSONAL_SCHICHTPLAN_WOCHE_SNAPSHOT
                WHERE JAHR = %s AND KW = %s
                ORDER BY PERS_ID, DATUM""",
            (int(jahr), int(kw)),
        )
        return cur.fetchall() or []


def _snapshot_schreiben(jahr: int, kw: int, zuordnungen: list[dict]) -> None:
    """Ueberschreibt den Snapshot fuer (JAHR, KW) mit dem aktuellen Plan."""
    with get_db_rw() as cur:
        cur.execute(
            """DELETE FROM XT_PERSONAL_SCHICHTPLAN_WOCHE_SNAPSHOT
                WHERE JAHR = %s AND KW = %s""",
            (int(jahr), int(kw)),
        )
        for z in zuordnungen:
            cur.execute(
                """INSERT INTO XT_PERSONAL_SCHICHTPLAN_WOCHE_SNAPSHOT
                     (JAHR, KW, PERS_ID, DATUM, SCHICHT_ID, BEZEICHNUNG,
                      TYP, STARTZEIT, ENDZEIT, DAUER_MIN)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (int(jahr), int(kw), int(z['PERS_ID']), z['DATUM'],
                 int(z['SCHICHT_ID']), z.get('BEZEICHNUNG', '') or '',
                 z.get('TYP'), z.get('STARTZEIT'), z.get('ENDZEIT'),
                 z.get('DAUER_MIN')),
            )


def _zuordnung_signatur(z: dict) -> tuple:
    """Vergleichsschluessel fuer Delta-Erkennung (robust gegen Formate)."""
    return (
        int(z['PERS_ID']),
        z['DATUM'],
        int(z['SCHICHT_ID']),
        (z.get('BEZEICHNUNG') or '').strip(),
        z.get('TYP'),
        _zeit_hhmm(z.get('STARTZEIT')),
        _zeit_hhmm(z.get('ENDZEIT')),
        int(z['DAUER_MIN']) if z.get('DAUER_MIN') is not None else None,
    )


def _delta_pro_ma(alt: list[dict], neu: list[dict]) -> dict[int, dict]:
    """Vergleicht alten Snapshot mit neuem Plan pro (PERS_ID, DATUM).

    Rueckgabe: ``{pers_id: {'tage': [{'datum': d,
                                      'alt': [..], 'neu': [..]}, ...]}}``
    Nur MAs mit mindestens einem geaenderten Tag erscheinen.
    """
    def _nach_pers_datum(rows):
        out: dict[tuple[int, date], list[dict]] = {}
        for r in rows:
            out.setdefault((int(r['PERS_ID']), r['DATUM']), []).append(r)
        return out

    alt_map = _nach_pers_datum(alt)
    neu_map = _nach_pers_datum(neu)
    alle_keys = set(alt_map) | set(neu_map)

    delta: dict[int, dict] = {}
    for pers_id, datum in sorted(alle_keys):
        alt_rows = alt_map.get((pers_id, datum), [])
        neu_rows = neu_map.get((pers_id, datum), [])
        alt_sig = sorted(_zuordnung_signatur(r) for r in alt_rows)
        neu_sig = sorted(_zuordnung_signatur(r) for r in neu_rows)
        if alt_sig == neu_sig:
            continue
        delta.setdefault(pers_id, {'tage': []})['tage'].append({
            'datum': datum, 'alt': alt_rows, 'neu': neu_rows,
        })
    return delta


def cao_benutzer_email(ma_id: int) -> str | None:
    """Liefert die Email-Adresse des CAO-Backoffice-Users (fuer Reply-To)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT EMAIL FROM MITARBEITER WHERE MA_ID = %s""",
            (int(ma_id),),
        )
        row = cur.fetchone()
        email = (row or {}).get('EMAIL')
        return email.strip() if email and email.strip() else None


def _zeit_hhmm(t) -> str:
    """Formatiert TIME / timedelta (wie MySQL liefert) als 'HH:MM'."""
    if t is None:
        return ''
    if hasattr(t, 'total_seconds'):
        total = int(t.total_seconds())
        return f'{total // 3600:02d}:{(total % 3600) // 60:02d}'
    return f'{t.hour:02d}:{t.minute:02d}'


_SIGNATUR_TEXT = ('Bitte zeitnah pruefen.\n'
                  'Viele Gruesse aus dem Habacher Dorfladen!')
_SIGNATUR_HTML = ('<p>Bitte zeitnah pruefen.<br>'
                  'Viele Gruesse aus dem Habacher Dorfladen!</p>')


def _eintrag_zeit(e: dict) -> str:
    """Formatiert den Zeit-Teil eines Schicht-Eintrags fuer die Mail."""
    if e.get('TYP') == 'fix':
        return f'{_zeit_hhmm(e.get("STARTZEIT"))}–{_zeit_hhmm(e.get("ENDZEIT"))}'
    if e.get('TYP') == 'flex':
        d = e.get('DAUER_MIN')
        return f'{d // 60}:{d % 60:02d} h' if d else 'flexibel'
    return 'Aufgabe'


def _freigabe_body_bauen(ma: dict, montag: date, jahr: int, kw: int,
                         eintraege: list[dict],
                         aenderungs_tage: list[dict] | None = None
                         ) -> tuple[str, str]:
    """Baut Plain- und HTML-Body fuer eine MA-Freigabe-Email.

    Args:
        ma: MA-Dict (VNAME/NAME/EMAIL).
        montag, jahr, kw: Wochen-Identifikation.
        eintraege: Aktuelle Zuordnungen (fuer Erstfreigabe-Modus).
        aenderungs_tage: Wenn gesetzt → Delta-Modus. Liste von
            ``{'datum': d, 'alt': [rows], 'neu': [rows]}``. Nur diese
            Tage werden aufgelistet (alt → neu).

    Returns: ``(text, html)``.
    """
    wtage = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
             'Freitag', 'Samstag', 'Sonntag']

    def _tag_string(d: date) -> str:
        wt = wtage[d.weekday()]
        return f'{wt}, {d.strftime("%d.%m.%Y")}'

    def _eintrag_line(e: dict) -> str:
        return f'{e.get("BEZEICHNUNG","")} ({_eintrag_zeit(e)})'

    zeilen_text: list[str] = []
    zeilen_html: list[str] = []

    if aenderungs_tage is not None:
        # ── Delta-Modus: nur geaenderte Tage, als alt→neu ───────────────
        for tag in aenderungs_tage:
            datum = tag['datum']
            alt, neu = tag['alt'], tag['neu']
            datum_str = _tag_string(datum)
            alt_txt = ('frei' if not alt
                       else ' + '.join(_eintrag_line(e) for e in alt))
            neu_txt = ('frei' if not neu
                       else ' + '.join(_eintrag_line(e) for e in neu))
            zeilen_text.append(f'  {datum_str}: {alt_txt}  →  {neu_txt}')
            zeilen_html.append(
                f'<tr><td style="padding:4px 10px;">{datum_str}</td>'
                f'<td style="padding:4px 10px; color:#888;">{alt_txt}</td>'
                f'<td style="padding:4px 10px;">→</td>'
                f'<td style="padding:4px 10px;"><strong>{neu_txt}</strong></td></tr>'
            )
        einleitung_text = 'Folgende Aenderungen gab es zu Deinen Schichten:'
        einleitung_html = ('<p><strong>Folgende Aenderungen gab es zu '
                           'Deinen Schichten:</strong></p>')
        tabellen_kopf_html = (
            '<table style="border-collapse:collapse; font-family:sans-serif;">'
            '<thead><tr>'
            '<th style="text-align:left; padding:4px 10px;">Tag</th>'
            '<th style="text-align:left; padding:4px 10px;">bisher</th>'
            '<th></th>'
            '<th style="text-align:left; padding:4px 10px;">neu</th>'
            '</tr></thead><tbody>'
        )
        tabellen_fuss_html = '</tbody></table>'
    else:
        # ── Vollstaendig-Modus: kompletter Wochenplan ───────────────────
        nach_datum: dict[date, list[dict]] = {}
        for e in eintraege:
            nach_datum.setdefault(e['DATUM'], []).append(e)
        for lst in nach_datum.values():
            lst.sort(key=lambda x: (_zeit_hhmm(x.get('STARTZEIT')) or '99:99',
                                    x.get('BEZEICHNUNG') or ''))
        for i in range(7):
            tag = montag + timedelta(days=i)
            es = nach_datum.get(tag, [])
            datum_str = _tag_string(tag)
            if not es:
                zeilen_text.append(f'  {datum_str}: frei')
                zeilen_html.append(
                    f'<tr><td style="padding:4px 10px; color:#888;">{datum_str}</td>'
                    f'<td style="padding:4px 10px; color:#888;">frei</td></tr>'
                )
                continue
            for e in es:
                zeilen_text.append(f'  {datum_str}: {_eintrag_line(e)}')
                zeilen_html.append(
                    f'<tr><td style="padding:4px 10px;">{datum_str}</td>'
                    f'<td style="padding:4px 10px;">'
                    f'<strong>{e.get("BEZEICHNUNG","")}</strong> '
                    f'<span style="color:#555;">{_eintrag_zeit(e)}</span>'
                    f'</td></tr>'
                )
        einleitung_text = 'Deine Schichten:'
        einleitung_html = '<p><strong>Deine Schichten:</strong></p>'
        tabellen_kopf_html = (
            '<table style="border-collapse:collapse; font-family:sans-serif;">'
        )
        tabellen_fuss_html = '</table>'

    text = (
        f'Hallo {ma.get("VNAME","") or ""},\n\n'
        f'der Schichtplan fuer KW {kw:02d}/{jahr} '
        f'(ab {montag.strftime("%d.%m.%Y")}) ist freigegeben.\n\n'
        f'{einleitung_text}\n'
        + '\n'.join(zeilen_text)
        + f'\n\n{_SIGNATUR_TEXT}'
    )
    html = (
        f'<p>Hallo {ma.get("VNAME","") or ""},</p>'
        f'<p>der Schichtplan fuer <strong>KW {kw:02d}/{jahr}</strong> '
        f'(ab {montag.strftime("%d.%m.%Y")}) ist freigegeben.</p>'
        f'{einleitung_html}'
        f'{tabellen_kopf_html}'
        + ''.join(zeilen_html)
        + tabellen_fuss_html
        + _SIGNATUR_HTML
    )
    return text, html


def schichtplan_freigabe_emails_senden(montag: date,
                                       sender_ma_id: int) -> dict:
    """Sendet pro MA mit Email-Adresse die Schichtplan-Benachrichtigung.

    Greift auf ``common.email.email_senden`` zurueck. Ist SMTP nicht
    konfiguriert, meldet die Funktion Modus ``'disabled'`` – kein Fehler.

    Delta-Versand bei Re-Freigabe:
        Existiert bereits ein Snapshot fuer (JAHR, KW), wird der aktuelle
        Plan gegen den Snapshot diff'ed. Nur MAs mit geaenderten Tagen
        bekommen eine Mail – Text zeigt "Folgende Aenderungen..." mit
        alt→neu pro Tag. Ohne Snapshot (Erstfreigabe) gehen Vollmails an
        alle MAs. Nach erfolgreichem Lauf wird der Snapshot ueberschrieben.

    Absender:
        Wenn ``load_email_config()['sender_shift']`` gesetzt ist, wird
        diese Adresse als ``From`` UND ``Reply-To`` verwendet (Registry-Key
        ``SMTP_SENDER_SHIFT``). Sonst faellt die Funktion auf den Config-
        Default (``from_addr``) zurueck; Reply-To ist dann die Email des
        freigebenden Benutzers.

    Dev-Modus (``load_email_config()['dev_mode'] == True``):
        Alle Mails gehen an den **freigebenden Benutzer** (``sender_ma_id`` →
        ``MITARBEITER.EMAIL``), Betreff bekommt ``[DEV]``-Prefix. Hat der
        Freigebende keine Email, wird ``modus='disabled'`` zurueckgegeben –
        nichts wird versendet.

    Rueckgabe:
        ``{'gesendet': n, 'uebersprungen': m, 'modus': str, 'fehler': [...]}``
        ``modus`` ist ``'dev'`` bei aktivem Dev-Modus, sonst spiegelt er
        den letzten Versand-Modus (``'ok'`` / ``'disabled'`` / ``'fehler'``).
    """
    from common.email import email_senden  # Lazy: Email erst beim Bedarf
    from common.config import load_email_config

    jahr, kw = _iso_jahr_kw(montag)
    sonntag = montag + timedelta(days=6)
    cfg = load_email_config()
    dev_mode = bool(cfg.get('dev_mode'))
    sender_shift = (cfg.get('sender_shift') or '').strip() or None

    with get_db_ro() as cur:
        zuordnungen = _freigabe_zuordnungen_lesen(cur, montag, sonntag)

    absender_email = cao_benutzer_email(sender_ma_id)
    reply_to = sender_shift or absender_email
    from_override = sender_shift  # None → Config-Default

    if dev_mode and not absender_email:
        # Dev-Modus ohne Sender-Email → sicherheitshalber gar nicht versenden.
        return {'gesendet': 0, 'uebersprungen': len(zuordnungen),
                'modus': 'disabled', 'fehler': []}

    # Delta gegen letzten Snapshot berechnen.
    alt = _snapshot_lesen(jahr, kw)
    delta_modus = bool(alt)
    delta = _delta_pro_ma(alt, zuordnungen) if delta_modus else {}

    nach_ma: dict[int, dict] = {}
    for z in zuordnungen:
        d = nach_ma.setdefault(int(z['PERS_ID']), {
            'MA': {'VNAME': z['VNAME'], 'NAME': z['NAME'], 'EMAIL': z['EMAIL']},
            'eintraege': [],
        })
        d['eintraege'].append(z)

    # Delta-Modus: MAs, deren komplette Woche verschwindet (nur in alt, nicht
    # in neu), fehlen in ``nach_ma``. MA-Stammdaten dann aus alt nachziehen.
    if delta_modus:
        for pers_id in delta:
            if pers_id in nach_ma:
                continue
            alt_rows = [r for r in alt if int(r['PERS_ID']) == pers_id]
            if not alt_rows:
                continue
            r0 = alt_rows[0]
            # VNAME/NAME/EMAIL liegen im alten Plan nicht vor – wir muessen
            # sie aus der MA-Tabelle holen.
            ma_info = ma_by_id(pers_id) or {}
            nach_ma[pers_id] = {
                'MA': {'VNAME': ma_info.get('VNAME', ''),
                       'NAME':  ma_info.get('NAME',  ''),
                       'EMAIL': ma_info.get('EMAIL')},
                'eintraege': [],
            }

    gesendet = 0
    uebersprungen = 0
    fehler: list[str] = []
    modus = 'disabled'
    for pers_id, info in nach_ma.items():
        if delta_modus and pers_id not in delta:
            continue  # Unveraenderter MA → ueberspringen (keine Mail).
        aenderungs_tage = delta[pers_id]['tage'] if delta_modus else None

        ma_email = (info['MA'].get('EMAIL') or '').strip()
        if dev_mode:
            # Dev-Modus: immer an den Freigebenden, MA ohne Mail nicht skippen.
            ziel_email = absender_email
        else:
            if not ma_email:
                uebersprungen += 1
                continue
            ziel_email = ma_email
        text, html = _freigabe_body_bauen(
            info['MA'], montag, jahr, kw, info['eintraege'],
            aenderungs_tage=aenderungs_tage,
        )
        betreff = f'Schichtplan KW {kw:02d}/{jahr} ab {montag.strftime("%d.%m.%Y")}'
        if delta_modus:
            betreff = f'[Aenderung] {betreff}'
        if dev_mode:
            betreff = f'[DEV] {betreff}'
        ergebnis = email_senden(ziel_email, betreff, text, html=html,
                                reply_to=reply_to,
                                from_addr=from_override)
        if ergebnis['versendet'] > 0:
            gesendet += 1
            modus = 'dev' if dev_mode else ergebnis['modus']
        elif ergebnis['modus'] == 'fehler':
            fehler.append(
                f"{info['MA'].get('VNAME','')} {info['MA'].get('NAME','')}: "
                f"{ergebnis.get('fehler','?')}"
            )
            modus = 'fehler'
        elif ergebnis['modus'] == 'disabled':
            uebersprungen += 1

    # Snapshot aktualisieren (auch wenn keine Mails gingen – der Plan ist
    # jetzt freigegeben und gilt als neue Referenz fuer kuenftige Deltas).
    try:
        _snapshot_schreiben(jahr, kw, zuordnungen)
    except Exception as exc:  # noqa: BLE001 – Mail-Versand hat Vorrang
        import logging
        logging.getLogger(__name__).exception(
            'Snapshot-Schreiben fehlgeschlagen: %s', exc)

    return {
        'gesendet': gesendet,
        'uebersprungen': uebersprungen,
        'modus': modus,
        'fehler': fehler,
    }


# ── PIN fuer Kiosk-Stempeluhr (Self-Service) ────────────────────────────────
#
# Die PIN ist eine 4-stellige Zahl, die als Alternative zum Kartenscan am
# Kiosk-Terminal dient. Gespeichert wird nur der pbkdf2-sha256-Hash inkl.
# zufaelligem Salt; Klartext existiert nur kurzzeitig bei Eingabe. Der
# Admin kann die PIN zuruecksetzen (auf NULL), der MA kann sie am Kiosk
# selbst aendern.
#
# Format im PIN_HASH-Feld:
#   pbkdf2_sha256$<iterationen>$<salt_hex>$<hash_hex>

_PIN_ITER = 200_000
PIN_ALGO = 'pbkdf2_sha256'


def _pin_hash(pin: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = _os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt, _PIN_ITER)
    return f'{PIN_ALGO}${_PIN_ITER}${salt.hex()}${dk.hex()}'


def _pin_verify(pin: str, stored: str | None) -> bool:
    """Constant-time-Vergleich. Bei unbekanntem Format oder leerem stored False."""
    if not stored or not pin:
        return False
    try:
        algo, iter_str, salt_hex, hash_hex = stored.split('$', 3)
    except ValueError:
        return False
    if algo != PIN_ALGO:
        return False
    try:
        iters = int(iter_str)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt, iters)
    return secrets.compare_digest(dk.hex(), hash_hex)


def pin_validieren(pin: str) -> None:
    """Wirft ValueError, wenn ``pin`` nicht genau 4 Ziffern ist."""
    if not pin or len(pin) != 4 or not pin.isdigit():
        raise ValueError('PIN muss aus genau 4 Ziffern bestehen.')


def _pin_bereits_vergeben(cur, pin: str, ausser_pers_id: int) -> bool:
    """Prueft, ob die 4-stellige PIN schon bei einem anderen (nicht
    ausgetretenen) MA hinterlegt ist. Da jeder Hash einen eigenen Salt
    hat, muss die PIN gegen jeden gesetzten Hash einzeln verifiziert
    werden — bei <30 aktiven MAs akzeptabler Kostenaufwand beim Setzen."""
    cur.execute(
        """SELECT PERS_ID, PIN_HASH
             FROM XT_PERSONAL_MA
            WHERE PIN_HASH IS NOT NULL
              AND PERS_ID <> %s
              AND (AUSTRITT IS NULL OR AUSTRITT >= CURDATE())""",
        (int(ausser_pers_id),),
    )
    for row in cur.fetchall():
        if _pin_verify(pin, row['PIN_HASH']):
            return True
    return False


def pin_setzen(pers_id: int, neue_pin: str | None,
               benutzer_ma_id: int) -> int:
    """Setzt oder loescht die PIN des MA.

    ``neue_pin=None`` → PIN entfernen (Admin-Reset).
    Im Log wird nur vermerkt, dass PIN gesetzt/geloescht wurde — weder der
    Klartext noch der Hash werden dort abgelegt.

    Wirft ``ValueError`` wenn die neue PIN bereits bei einem anderen
    aktiven MA hinterlegt ist (PINs muessen unternehmensweit eindeutig
    sein — fuer saubere UX; die Auth selbst ist per-MA gescopt).
    """
    if neue_pin is not None:
        pin_validieren(neue_pin)
    pin_hash = _pin_hash(neue_pin) if neue_pin is not None else None
    with get_db_rw() as cur:
        # Vorherigen Zustand laden, damit wir im Log korrekt festhalten
        # koennen, ob eine PIN geaendert oder erst gesetzt wurde.
        cur.execute(
            "SELECT PIN_HASH FROM XT_PERSONAL_MA WHERE PERS_ID = %s",
            (int(pers_id),),
        )
        zeile = cur.fetchone()
        if zeile is None:
            return 0
        # Eindeutigkeits-Pruefung nur bei Neu-Setzen (nicht bei Reset)
        if neue_pin is not None and _pin_bereits_vergeben(cur, neue_pin, int(pers_id)):
            raise ValueError('Diese PIN ist bereits vergeben. Bitte andere PIN waehlen.')
        vorher_gesetzt = 1 if zeile.get('PIN_HASH') else 0
        nachher_gesetzt = 1 if pin_hash is not None else 0
        cur.execute(
            """UPDATE XT_PERSONAL_MA
                  SET PIN_HASH = %s,
                      PIN_GEAEND_AT = NOW(),
                      GEAEND_AT = NOW(), GEAEND_VON = %s
                WHERE PERS_ID = %s""",
            (pin_hash, int(benutzer_ma_id), int(pers_id)),
        )
        geaendert = cur.rowcount
        # XT_PERSONAL_MA_LOG hat kein REF_REC_ID — direkter Insert analog
        # ma_insert/ma_update. Nur der boolesche Status wird geloggt, nie
        # der Hash oder Klartext der PIN.
        cur.execute(
            """INSERT INTO XT_PERSONAL_MA_LOG
                 (PERS_ID, OPERATION, FELDER_ALT_JSON, FELDER_NEU_JSON, GEAEND_VON)
               VALUES (%s, 'UPDATE', %s, %s, %s)""",
            (int(pers_id),
             json.dumps({'PIN_GESETZT': vorher_gesetzt}, ensure_ascii=False),
             json.dumps({'PIN_GESETZT': nachher_gesetzt}, ensure_ascii=False),
             int(benutzer_ma_id)),
        )
        return geaendert


def pin_ist_gesetzt(pers_id: int) -> bool:
    """True, wenn fuer den MA eine PIN hinterlegt ist."""
    with get_db_ro() as cur:
        cur.execute(
            "SELECT PIN_HASH FROM XT_PERSONAL_MA WHERE PERS_ID = %s",
            (int(pers_id),),
        )
        row = cur.fetchone()
    return bool(row and row.get('PIN_HASH'))


def ma_mit_pin_liste() -> list[dict]:
    """Aktive MA mit gesetzter PIN (fuer Kiosk-Auswahl-Kacheln)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT PERS_ID, PERSONALNUMMER, VNAME, NAME, KUERZEL
                 FROM XT_PERSONAL_MA
                WHERE PIN_HASH IS NOT NULL
                  AND (AUSTRITT IS NULL OR AUSTRITT >= CURDATE())
                ORDER BY VNAME, NAME"""
        )
        return cur.fetchall() or []


def authentifiziere_pers_pin(pers_id: int, pin: str) -> dict | None:
    """Prueft PIN gegen gespeicherten Hash. Gibt MA-Dict (ohne Hash) oder None."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT PERS_ID, PERSONALNUMMER, VNAME, NAME, KUERZEL,
                      PIN_HASH, AUSTRITT
                 FROM XT_PERSONAL_MA WHERE PERS_ID = %s""",
            (int(pers_id),),
        )
        row = cur.fetchone()
    if not row or not row.get('PIN_HASH'):
        return None
    if row.get('AUSTRITT') and row['AUSTRITT'] <= date.today():
        return None
    if not _pin_verify(pin, row['PIN_HASH']):
        return None
    row.pop('PIN_HASH', None)
    return row


def stempeln_mit_pers_pin(pers_id: int, pin: str,
                          terminal_nr: int | None) -> dict:
    """Analog ``stempeln_karte`` — PIN-basiert statt Kartenscan."""
    if not pin:
        return {'ok': False, 'msg': 'Bitte PIN eingeben.'}
    personal = authentifiziere_pers_pin(int(pers_id), pin)
    if not personal:
        return {'ok': False, 'msg': 'PIN stimmt nicht.'}
    richtung = stempel_naechste_richtung(pers_id)
    zeitpunkt = datetime.now().replace(microsecond=0)
    tnr = int(terminal_nr) if terminal_nr else None
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_STEMPEL
                 (PERS_ID, RICHTUNG, ZEITPUNKT, QUELLE, TERMINAL_NR)
               VALUES (%s, %s, %s, 'kiosk', %s)""",
            (int(pers_id), richtung, zeitpunkt, tnr),
        )
    return {
        'ok':        True,
        'msg':       f"{'Willkommen' if richtung == 'kommen' else 'Tschuess'}, "
                     f"{personal['VNAME']}!",
        'pers_id':   int(pers_id),
        'vname':     personal['VNAME'],
        'name':      personal['NAME'],
        'richtung':  richtung,
        'zeitpunkt': zeitpunkt,
    }


def pin_aendern_self(pers_id: int, alte_pin: str, neue_pin: str) -> bool:
    """Self-Service: MA aendert seine eigene PIN. Prueft alte PIN und setzt
    neue; der MA gilt als eigener Editor im Log."""
    with get_db_ro() as cur:
        cur.execute(
            "SELECT PIN_HASH, CAO_MA_ID FROM XT_PERSONAL_MA WHERE PERS_ID = %s",
            (int(pers_id),),
        )
        row = cur.fetchone()
    if not row or not _pin_verify(alte_pin, row.get('PIN_HASH')):
        return False
    pin_validieren(neue_pin)
    # Log: Benutzer ist der MA selbst (CAO_MA_ID sofern verknuepft, sonst PERS_ID
    # als Platzhalter, damit der Log-Eintrag nicht 0 wird).
    benutzer = int(row.get('CAO_MA_ID') or 0) or int(pers_id)
    pin_setzen(int(pers_id), neue_pin, benutzer_ma_id=benutzer)
    return True


# ── Stunden-Korrekturen (Tages-Delta) ─────────────────────────────────────────

def stundenkorrektur_insert(pers_id: int, datum: date, minuten: int,
                            grund: str | None = None,
                            quelle: str = 'manuell',
                            *, benutzer_ma_id: int) -> int:
    """Legt einen Stunden-Korrektur-Eintrag an (Delta in Minuten, vorzeichenbehaftet).

    ``quelle='import'`` kennzeichnet aus der CSV importierte Zeilen – diese
    koennen beim Re-Import per :func:`stundenkorrektur_import_loeschen`
    gezielt entfernt werden, ohne manuelle Korrekturen anzutasten.

    Schreibt INSERT-Audit-Eintrag in XT_PERSONAL_STUNDEN_KORREKTUR_LOG.
    """
    if quelle not in ('manuell', 'import'):
        raise ValueError(f'Ungueltige QUELLE: {quelle!r}')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_STUNDEN_KORREKTUR
                 (PERS_ID, DATUM, MINUTEN, GRUND, QUELLE, ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (int(pers_id), datum, int(minuten),
             grund, quelle, int(benutzer_ma_id)),
        )
        rec_id = cur.lastrowid
        _log_schreiben(
            cur, 'XT_PERSONAL_STUNDEN_KORREKTUR_LOG',
            int(pers_id), rec_id, 'INSERT',
            None,
            {'DATUM':   datum,
             'MINUTEN': int(minuten),
             'GRUND':   grund,
             'QUELLE':  quelle},
            benutzer_ma_id,
        )
        return rec_id


def stundenkorrektur_import_loeschen(pers_id: int,
                                     von: date, bis: date) -> int:
    """Hard-Delete aller QUELLE='import'-Korrekturen eines MA im Zeitraum.

    Wird vor einem Re-Import aufgerufen, um Idempotenz zu garantieren.
    Manuelle Korrekturen (QUELLE='manuell') bleiben unberuehrt.

    Jede geloeschte Zeile erhaelt einen DELETE-Audit-Eintrag in
    XT_PERSONAL_STUNDEN_KORREKTUR_LOG (GEAEND_VON=NULL → System).
    """
    with get_db_rw() as cur:
        # Zeilen vor dem Delete einlesen, damit wir pro Datensatz einen
        # Log-Eintrag mit dem Vorher-Zustand schreiben koennen.
        cur.execute(
            """SELECT REC_ID, DATUM, MINUTEN, GRUND, QUELLE
                 FROM XT_PERSONAL_STUNDEN_KORREKTUR
                WHERE PERS_ID = %s AND QUELLE = 'import'
                  AND DATUM BETWEEN %s AND %s""",
            (int(pers_id), von, bis),
        )
        zeilen = cur.fetchall() or []
        cur.execute(
            """DELETE FROM XT_PERSONAL_STUNDEN_KORREKTUR
                WHERE PERS_ID = %s AND QUELLE = 'import'
                  AND DATUM BETWEEN %s AND %s""",
            (int(pers_id), von, bis),
        )
        geloescht = cur.rowcount or 0
        for z in zeilen:
            _log_schreiben(
                cur, 'XT_PERSONAL_STUNDEN_KORREKTUR_LOG',
                int(pers_id), int(z['REC_ID']), 'DELETE',
                {'DATUM':   z['DATUM'],
                 'MINUTEN': int(z['MINUTEN']),
                 'GRUND':   z['GRUND'],
                 'QUELLE':  z['QUELLE']},
                None,
                None,   # benutzer_ma_id = NULL → System
            )
        return geloescht


def stundenkorrektur_summe_min(pers_id: int, von: date, bis: date) -> int:
    """Summe aller nicht-stornierten Korrektur-Minuten im Zeitraum."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(MINUTEN), 0) AS s
                 FROM XT_PERSONAL_STUNDEN_KORREKTUR
                WHERE PERS_ID = %s AND STORNIERT = 0
                  AND DATUM BETWEEN %s AND %s""",
            (int(pers_id), von, bis),
        )
        row = cur.fetchone()
        return int(row['s']) if row else 0


# ── Arbeitszeitkonto (Aggregate pro Zeitraum) ─────────────────────────────────

def _abwesenheit_tagesstunden(a: dict, stunden_pro_tag: float = 8.0) -> float:
    """Umrechnung Abwesenheits-Eintrag → Arbeitsstunden.

    Ganztags → ``stunden_pro_tag`` (Default: 8 h) multipliziert mit Tagen
    im Zeitraum. Teilweise → ``STUNDEN`` exakt. STATUS='abgelehnt' und
    stornierte Eintraege werden vom Aufrufer ausgefiltert.
    """
    if not a.get('GANZTAGS'):
        return float(a.get('STUNDEN') or 0)
    tage = (a['BIS'] - a['VON']).days + 1
    return tage * float(stunden_pro_tag)


def arbeitszeitkonto_periode(pers_id: int, von: date, bis: date) -> dict:
    """Aggregiert die Arbeitszeit-Kennzahlen fuer einen MA im Zeitraum.

    Rueckgabe (alle Minuten-Werte als int, Tage als float):
      regel_min           – Sollstunden anteilig auf [von, bis]
      plan_min            – Planzeit aus Schicht-Zuordnungen (netto, inkl. Pausen)
      gebucht_min         – Gestempelte Arbeitszeit (Kommen/Gehen-Paare)
      abwesenheit_min     – Bezahlte Abwesenheit in Minuten
      korrektur_min       – Summe XT_PERSONAL_STUNDEN_KORREKTUR im Zeitraum
      summe_min           – gebucht + abwesenheit + korrektur
      diff_min            – summe − regel
      urlaub_tage         – Urlaubs-Arbeitstage im Zeitraum (aus Antraegen)
      regel_az_label      – Anzeige-Label "40h/Woche" etc. fuer UI
    """
    tage_im_zeitraum = (bis - von).days + 1
    # 1. Regel-AZ: anteilig aus aktuellem Modell. TYP=WOCHE → SOLL/7 pro Tag,
    #    TYP=MONAT → SOLL/30. Pragmatische Approximation (kalendarisch sauber
    #    waere komplexer – monatsweise variierende Tagzahlen). Fuer einen
    #    Stundennachweis reicht das in erster Naeherung.
    az = aktuelles_az_modell(pers_id, stichtag=von) or {}
    soll_stunden = float(az.get('STUNDEN_SOLL') or 0)
    az_typ = az.get('TYP') or 'WOCHE'
    if az_typ == 'MONAT':
        regel_min = int(round(soll_stunden * 60 * tage_im_zeitraum / 30))
        regel_label = f'{soll_stunden:g} h/Monat'
    else:
        regel_min = int(round(soll_stunden * 60 * tage_im_zeitraum / 7))
        regel_label = f'{soll_stunden:g} h/Woche'

    # 2. Planzeit aus Schicht-Zuordnungen (pro Tag Pausen abziehen).
    regelung = pause_regelung_aktuell(stichtag=von)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT z.DATUM, z.DAUER_MIN, s.TYP, s.STARTZEIT, s.ENDZEIT
                 FROM XT_PERSONAL_SCHICHT_ZUORDNUNG z
                 JOIN XT_PERSONAL_SCHICHT s ON s.SCHICHT_ID = z.SCHICHT_ID
                WHERE z.PERS_ID = %s AND z.DATUM BETWEEN %s AND %s
                ORDER BY z.DATUM""",
            (int(pers_id), von, bis),
        )
        zuordnungen = cur.fetchall() or []
    plan_pro_tag: dict[date, list[dict]] = {}
    for z in zuordnungen:
        plan_pro_tag.setdefault(z['DATUM'], []).append(z)
    plan_min = 0
    for tag, eintraege in plan_pro_tag.items():
        plan_min += tagesarbeitszeit_min(eintraege, regelung)['netto_min']

    # 3. Gebuchte Zeit aus Stempeln (Bulk-Query).
    gebucht_map = stempel_tagesminuten_zeitraum(pers_id, von, bis)
    gebucht_min = sum(gebucht_map.values())

    # 4. Bezahlte Abwesenheiten im Zeitraum (nur genehmigt / nicht storniert).
    #    STUNDEN_PRO_TAG aus AZ-Modell: Wochensoll/5 (WOCHE) bzw. MONAT/22.
    if az_typ == 'MONAT':
        stunden_pro_arbeitstag = soll_stunden / 22.0 if soll_stunden else 8.0
    else:
        stunden_pro_arbeitstag = soll_stunden / 5.0 if soll_stunden else 8.0
    abw_min = 0.0
    with get_db_ro() as cur:
        cur.execute(
            """SELECT VON, BIS, GANZTAGS, STUNDEN, STATUS
                 FROM XT_PERSONAL_ABWESENHEIT
                WHERE PERS_ID = %s AND STORNIERT = 0
                  AND BEZAHLT = 1
                  AND (STATUS IS NULL OR STATUS = 'genehmigt')
                  AND VON <= %s AND BIS >= %s""",
            (int(pers_id), bis, von),
        )
        for a in cur.fetchall() or []:
            # Ueberlappung mit Zeitraum ermitteln, dann Stunden-Anteil.
            if a['GANZTAGS']:
                start = max(a['VON'], von)
                ende = min(a['BIS'], bis)
                tage = (ende - start).days + 1
                abw_min += tage * stunden_pro_arbeitstag * 60
            else:
                # Stundenweise Abwesenheit liegt an EINEM Tag (VON==BIS lt. Model).
                if a['VON'] >= von and a['VON'] <= bis:
                    abw_min += float(a['STUNDEN'] or 0) * 60
    abwesenheit_min = int(round(abw_min))

    # 5. Korrekturen: Summe aus XT_PERSONAL_STUNDEN_KORREKTUR (Delta in Min).
    korrektur_min = stundenkorrektur_summe_min(pers_id, von, bis)

    summe_min = gebucht_min + abwesenheit_min + korrektur_min
    diff_min = summe_min - regel_min

    # 6. Urlaubstage im Zeitraum (aus genehmigten/genommenen Antraegen).
    urlaub_tage = 0.0
    with get_db_ro() as cur:
        cur.execute(
            """SELECT VON, BIS, ARBEITSTAGE, STATUS
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s
                  AND STATUS IN ('genehmigt', 'genommen')
                  AND VON <= %s AND BIS >= %s""",
            (int(pers_id), bis, von),
        )
        for u in cur.fetchall() or []:
            # Arbeitstage anteilig zum Ueberlappungsbereich.
            start = max(u['VON'], von)
            ende = min(u['BIS'], bis)
            if ende < start:
                continue
            gesamt_tage = (u['BIS'] - u['VON']).days + 1
            ueberlapp = (ende - start).days + 1
            anteil = ueberlapp / gesamt_tage if gesamt_tage else 0
            urlaub_tage += float(u['ARBEITSTAGE']) * anteil

    return {
        'regel_min': regel_min,
        'plan_min': plan_min,
        'gebucht_min': gebucht_min,
        'abwesenheit_min': abwesenheit_min,
        'korrektur_min': korrektur_min,
        'summe_min': summe_min,
        'diff_min': diff_min,
        'urlaub_tage': round(urlaub_tage, 1),
        'regel_az_label': regel_label,
    }


def minuten_zu_hstr(minuten: int) -> str:
    """'325 min' → '5:25 h'. Negative Werte werden mit Vorzeichen dargestellt."""
    if minuten is None:
        return ''
    neg = minuten < 0
    m = abs(int(minuten))
    h, rest = divmod(m, 60)
    vz = '-' if neg else ''
    return f'{vz}{h}:{rest:02d}'


# ── Arbeitszeitkonto: Jahres-Drill-Down (Perioden → Tage → Stempel) ──────────
#
# Performance-Hinweis: Fuer die Jahresansicht laedt der Helfer pro MA ALLES
# einmal bulk (Stempel, Abwesenheiten, Urlaube, Feiertage, Korrekturen,
# Schicht-Zuordnungen) und aggregiert dann in Python. Das haelt die DB-
# Last bei N×MA konstant bei ~6 Queries pro MA – unabhaengig von der
# Periodenanzahl (12 Monate oder 53 Wochen).

# Label-Map Tages-Typ → Anzeige. 'feiertag' wird dynamisch durch den
# Feiertagsnamen ersetzt; 'leer' = Wochenende/Nicht-Arbeitstag ohne Aktivitaet.
_TAG_TYP_LABEL: dict[str, str] = {
    'arbeit':     'Arbeitszeit',
    'urlaub':     'Urlaub',
    'krank':      'Krankheit',
    'kind_krank': 'Kind krank',
    'schulung':   'Schulung',
    'unbezahlt':  'Unbezahlter Urlaub',
    'sonstiges':  'Sonstiges',
    'leer':       '',
}

# Deutsche Monatsnamen (strftime('%B') ist Locale-abhaengig; wir liefern
# garantiert deutsch, damit das UI unabhaengig von LC_TIME/LANG ist).
_MONATSNAMEN_DE: tuple[str, ...] = (
    '', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
    'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
)


def arbeitszeitkonto_jahr(pers_id: int, jahr: int, modus: str = 'monat') -> dict:
    """Jahresweiter Arbeitszeitkonto-Drill-Down fuer die UI.

    ``modus`` = ``'woche'`` → ISO-Kalenderwochen; ``'monat'`` → 12 Monate.

    Rueckgabe::

        {
          'jahr': int,
          'modus': 'woche'|'monat',
          'regel_az_label': str,
          'perioden': [
            { 'nr': int,                    # KW-Nr oder Monat
              'label': str,                 # "KW 03" / "Januar"
              'von': date, 'bis': date,
              'w': { regel_min, plan_min, gebucht_min, bezahlt_min,
                     korrektur_min, summe_min, diff_min, urlaub_tage },
              'tage': [
                { 'datum': date, 'typ': str, 'typ_label': str,
                  'regel_min': int, 'plan_min': int, 'gebucht_min': int,
                  'bezahlt_min': int, 'korrektur_min': int, 'summe_min': int,
                  'stempel_paare': [
                    { 'kommen_at', 'gehen_at', 'dauer_min',
                      'quelle', 'kommentar' }
                  ]
                }, ...
              ],
            }, ...
          ],
          'summe': { ...wie 'w'..., 'urlaub_tage' },
        }
    """
    from datetime import date as _date, timedelta as _td
    modus = (modus or 'monat').lower()
    if modus not in ('woche', 'monat'):
        modus = 'monat'

    jahr_von = _date(jahr, 1, 1)
    jahr_bis = _date(jahr, 12, 31)

    # ── AZ-Modell: Tagessoll ermitteln ───────────────────────────────────
    az = aktuelles_az_modell(pers_id, stichtag=jahr_von) or {}
    soll_stunden = float(az.get('STUNDEN_SOLL') or 0)
    az_typ = az.get('TYP') or 'WOCHE'
    if az_typ == 'MONAT':
        tagessoll_min = int(round((soll_stunden * 60) / 22)) if soll_stunden else 0
        regel_az_label = f'{soll_stunden:g} h/Monat'
    else:
        tagessoll_min = int(round((soll_stunden * 60) / 5)) if soll_stunden else 0
        regel_az_label = f'{soll_stunden:g} h/Woche'

    # ── Bulk-Queries fuer das Jahr ───────────────────────────────────────
    feiertage = feiertage_im_zeitraum(jahr_von, jahr_bis)  # {datum: name}

    # Stempel (Paare pro Tag, inkl. Einzel-Stempel fuer Drill-Down).
    stempel = stempel_ma_zeitraum(pers_id, jahr_von, jahr_bis)
    stempel_pro_tag: dict[_date, list[dict]] = {}
    for s in stempel:
        d = s['ZEITPUNKT'].date()
        stempel_pro_tag.setdefault(d, []).append(s)

    # Abwesenheiten (alle Typen) als tag->list[abw].
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, TYP, VON, BIS, GANZTAGS, STUNDEN, BEZAHLT, STATUS
                 FROM XT_PERSONAL_ABWESENHEIT
                WHERE PERS_ID = %s AND STORNIERT = 0
                  AND (STATUS IS NULL OR STATUS = 'genehmigt')
                  AND VON <= %s AND BIS >= %s""",
            (int(pers_id), jahr_bis, jahr_von),
        )
        abw_rows = cur.fetchall() or []
    abw_pro_tag: dict[_date, list[dict]] = {}
    for a in abw_rows:
        d = max(a['VON'], jahr_von)
        end = min(a['BIS'], jahr_bis)
        while d <= end:
            abw_pro_tag.setdefault(d, []).append(a)
            d += _td(days=1)

    # Urlaub (genommen/genehmigt) pro Tag.
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, VON, BIS, ARBEITSTAGE, STATUS
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s
                  AND STATUS IN ('genehmigt','genommen')
                  AND VON <= %s AND BIS >= %s""",
            (int(pers_id), jahr_bis, jahr_von),
        )
        urlaub_rows = cur.fetchall() or []
    urlaub_pro_tag: dict[_date, dict] = {}
    for u in urlaub_rows:
        d = max(u['VON'], jahr_von)
        end = min(u['BIS'], jahr_bis)
        while d <= end:
            urlaub_pro_tag.setdefault(d, u)
            d += _td(days=1)

    # Korrekturen pro Tag.
    with get_db_ro() as cur:
        cur.execute(
            """SELECT DATUM, MINUTEN
                 FROM XT_PERSONAL_STUNDEN_KORREKTUR
                WHERE PERS_ID = %s AND STORNIERT = 0
                  AND DATUM BETWEEN %s AND %s""",
            (int(pers_id), jahr_von, jahr_bis),
        )
        korrektur_rows = cur.fetchall() or []
    korrektur_pro_tag: dict[_date, int] = {}
    for k in korrektur_rows:
        korrektur_pro_tag[k['DATUM']] = (
            korrektur_pro_tag.get(k['DATUM'], 0) + int(k['MINUTEN']))

    # Schicht-Zuordnungen (Planzeit) pro Tag.
    regelung = pause_regelung_aktuell(stichtag=jahr_von)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT z.DATUM, z.DAUER_MIN, s.TYP, s.STARTZEIT, s.ENDZEIT
                 FROM XT_PERSONAL_SCHICHT_ZUORDNUNG z
                 JOIN XT_PERSONAL_SCHICHT s ON s.SCHICHT_ID = z.SCHICHT_ID
                WHERE z.PERS_ID = %s AND z.DATUM BETWEEN %s AND %s""",
            (int(pers_id), jahr_von, jahr_bis),
        )
        plan_rows = cur.fetchall() or []
    plan_pro_tag_raw: dict[_date, list[dict]] = {}
    for p in plan_rows:
        plan_pro_tag_raw.setdefault(p['DATUM'], []).append(p)
    plan_pro_tag_min: dict[_date, int] = {}
    for tag, eintr in plan_pro_tag_raw.items():
        plan_pro_tag_min[tag] = tagesarbeitszeit_min(eintr, regelung)['netto_min']

    # ── Pro Tag aufbereiten ──────────────────────────────────────────────
    def _stempel_paare(stempel_rows: list[dict]) -> list[dict]:
        ergebnis: list[dict] = []
        offen: dict | None = None
        for s in stempel_rows:
            if s['RICHTUNG'] == 'kommen':
                offen = s
            elif s['RICHTUNG'] == 'gehen' and offen is not None:
                dauer = int((s['ZEITPUNKT'] - offen['ZEITPUNKT']).total_seconds() // 60)
                ergebnis.append({
                    'kommen_at': offen['ZEITPUNKT'],
                    'gehen_at':  s['ZEITPUNKT'],
                    'dauer_min': max(0, dauer),
                    'quelle':    offen.get('QUELLE') or s.get('QUELLE'),
                    'kommentar': offen.get('KOMMENTAR') or s.get('KOMMENTAR'),
                })
                offen = None
        return ergebnis

    tage: list[dict] = []
    t = jahr_von
    while t <= jahr_bis:
        wochenende = t.weekday() >= 5  # Sa/So
        feiertag = feiertage.get(t)
        urlaub = urlaub_pro_tag.get(t)
        abw_liste = abw_pro_tag.get(t) or []
        paare = _stempel_paare(stempel_pro_tag.get(t) or [])
        gebucht = sum(p['dauer_min'] for p in paare)
        korrektur = korrektur_pro_tag.get(t, 0)

        # Regel-AZ pro Tag: nur Mo–Fr (5-Tage-Woche). Bei MONAT-Modell
        # analog: 22 Arbeitstage/Monat-Approximation, hier aber pro Wochentag.
        regel_tag = 0 if wochenende else tagessoll_min

        # Typ + Bezahlt-Min bestimmen.
        typ = 'leer'
        typ_label = ''
        bezahlt_min = 0
        urlaub_tag = 0.0  # Urlaubstage (Tagesbasis), floatet nur bei Halbtag
        if feiertag:
            typ = 'feiertag'
            typ_label = feiertag
            # Feiertag auf Werktag → Tagessoll als Gutschrift.
            if not wochenende:
                bezahlt_min = tagessoll_min
        elif urlaub:
            typ = 'urlaub'
            typ_label = _TAG_TYP_LABEL['urlaub']
            if not wochenende:
                bezahlt_min = tagessoll_min
                urlaub_tag = 1.0
        elif abw_liste:
            # Erste aktive Abwesenheit gewinnt (meist ist es nur eine).
            a = abw_liste[0]
            typ = str(a['TYP'])
            typ_label = _TAG_TYP_LABEL.get(typ, typ)
            if a['BEZAHLT']:
                if a['GANZTAGS']:
                    bezahlt_min = 0 if wochenende else tagessoll_min
                else:
                    bezahlt_min = int(round(float(a['STUNDEN'] or 0) * 60))
        elif gebucht > 0:
            typ = 'arbeit'
            typ_label = _TAG_TYP_LABEL['arbeit']
        # else: 'leer' (nichts gebucht, kein Urlaub, keine Abwesenheit)

        summe_min = gebucht + bezahlt_min + korrektur
        tage.append({
            'datum':        t,
            'wochenende':   wochenende,
            'typ':          typ,
            'typ_label':    typ_label,
            'regel_min':    regel_tag,
            'plan_min':     plan_pro_tag_min.get(t, 0),
            'gebucht_min':  gebucht,
            'bezahlt_min':  bezahlt_min,
            'korrektur_min': korrektur,
            'summe_min':    summe_min,
            'urlaub_tag':   urlaub_tag,
            'stempel_paare': paare,
        })
        t += _td(days=1)

    # ── In Perioden gruppieren ───────────────────────────────────────────
    if modus == 'woche':
        # ISO-Wochen: key = (iso-jahr, iso-kw). Der Anzeige-"jahr"-Filter
        # sortiert nach Kalenderjahr – die erste Woche kann zu KW 52/53 des
        # Vorjahres gehoeren, die letzte zu KW 01 des Folgejahres. Wir
        # gruppieren sauber nach (iso_jahr, iso_kw) und zeigen das Label so.
        gruppen: dict[tuple, list[dict]] = {}
        reihenfolge: list[tuple] = []
        for tag in tage:
            iso = tag['datum'].isocalendar()
            key = (iso.year, iso.week)
            if key not in gruppen:
                gruppen[key] = []
                reihenfolge.append(key)
            gruppen[key].append(tag)
        perioden = []
        for (iso_jahr, iso_kw) in reihenfolge:
            tage_liste = gruppen[(iso_jahr, iso_kw)]
            von = tage_liste[0]['datum']
            bis = tage_liste[-1]['datum']
            label = (f'KW {iso_kw:02d}/{iso_jahr}' if iso_jahr != jahr
                     else f'KW {iso_kw:02d}')
            perioden.append({
                'nr': iso_kw, 'iso_jahr': iso_jahr, 'label': label,
                'von': von, 'bis': bis,
                'tage': tage_liste,
            })
    else:  # monat
        perioden = []
        for monat in range(1, 13):
            von = _date(jahr, monat, 1)
            bis = (_date(jahr, monat + 1, 1) - _td(days=1)
                   if monat < 12 else _date(jahr, 12, 31))
            tage_liste = [tg for tg in tage if von <= tg['datum'] <= bis]
            perioden.append({
                'nr': monat, 'label': _MONATSNAMEN_DE[monat],
                'von': von, 'bis': bis,
                'tage': tage_liste,
            })

    # ── Summen pro Periode + Gesamt ──────────────────────────────────────
    def _summe(tg_liste: list[dict]) -> dict:
        return {
            'regel_min':     sum(t['regel_min']     for t in tg_liste),
            'plan_min':      sum(t['plan_min']      for t in tg_liste),
            'gebucht_min':   sum(t['gebucht_min']   for t in tg_liste),
            'bezahlt_min':   sum(t['bezahlt_min']   for t in tg_liste),
            'korrektur_min': sum(t['korrektur_min'] for t in tg_liste),
            'summe_min':     sum(t['summe_min']     for t in tg_liste),
            'urlaub_tage':   round(sum(t['urlaub_tag'] for t in tg_liste), 1),
        }

    for p in perioden:
        w = _summe(p['tage'])
        w['diff_min'] = w['summe_min'] - w['regel_min']
        p['w'] = w

    jahres_summe = _summe(tage)
    jahres_summe['diff_min'] = jahres_summe['summe_min'] - jahres_summe['regel_min']

    return {
        'jahr': jahr,
        'modus': modus,
        'regel_az_label': regel_az_label,
        'perioden': perioden,
        'summe': jahres_summe,
    }


# ── Stundenzettel (monatlicher Nachweis pro MA) ──────────────────────────────

# Wochentage deutsch (Mo..So). datetime.date.weekday() liefert 0=Mo.
_WOCHENTAG_DE_KURZ: tuple[str, ...] = ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')


def _ist_uebertrag_korrektur(grund: str | None) -> bool:
    """Heuristik: Korrektur-Grund mit 'Uebertrag'/'Vortrag' → Uebertrag.

    Case-insensitive, toleriert Umlaut-Schreibweisen (Uebertrag/Übertrag).
    Normale Fehlerkorrekturen fallen nicht darunter und gehen in den Saldo ein.
    """
    if not grund:
        return False
    g = grund.lower()
    return ('übertrag' in g) or ('uebertrag' in g) or ('vortrag' in g)


def _ist_abbau_ueberstunden(grund: str | None) -> bool:
    """Heuristik: Korrektur-Grund mit 'Abbau'/'Ueberstunden abbauen' → Abbau.

    Dient nur dem Tages-Ausweis im Stundenzettel (eigene Spalte); der Saldo
    ist davon unberuehrt (Abbau ist eine normale negative Korrektur).
    """
    if not grund:
        return False
    g = grund.lower()
    return 'abbau' in g


def stundenzettel_monat_daten(pers_id: int, jahr: int, monat: int) -> dict:
    """Aufbereitete Daten fuer den monatlichen Stundenzettel eines MA.

    Nutzt :func:`arbeitszeitkonto_jahr` als Datenbasis und zieht den gewaehlten
    Monat heraus, plus kumulierten Jahres-Saldo bis Monatsende.

    Korrekturen werden semantisch getrennt:
      * Normale Korrekturen (Fehlerkorrektur) fliessen in ``korrektur_monat_min``
        ein und somit in den Saldo.
      * Korrekturen mit Grund "Uebertrag"/"Vortrag" werden separat als
        ``uebertrag_korrektur_min`` ausgewiesen (Vortrag aus Vorjahr).

    Zuschlaege (Sonntags-, Feiertagsarbeit) werden rechnerisch aus den
    gestempelten Arbeitsminuten an Sonntagen bzw. Feiertagen ermittelt.

    Rueckgabe::

        {
          'pers_id': int, 'jahr': int, 'monat': int,
          'monats_name': str,
          'ma': dict,                  # Stammdaten (PERS_ID, NAME, VNAME, ...)
          'regel_az_label': str,
          'tage': [
            { 'datum', 'wochentag', 'feiertag_name', 'wochenende',
              'arbeit_min',            # gestempelt
              'abwesenheit_min',       # betrieblich (schulung, sonstiges)
              'urlaub_min',
              'krank_min',
              'abbau_ueberstunden_min',
              'feiertag_min',          # Feiertags-Gutschrift
            }, ...
          ],
          'summe': {
             'gesamt_min', 'soll_min',
             'saldo_monat_min',          # gesamt + korrekturen(ohne uebertrag) − soll
             'korrektur_monat_min',      # nicht-Uebertrag-Korrekturen im Monat (inkl. Abbau)
             'uebertrag_korrektur_min',  # separat: 'Uebertrag'-Korrekturen (Jahresbasis)
             'saldo_vormonate_min',      # Summe diff_min Jan..(monat−1)
             'saldo_kumuliert_min',      # vormonate + aktueller Monat (inkl. aller Korrekturen)
             'sonntagsarbeit_min',
             'feiertagsarbeit_min',
             'urlaub_beginn_tage',
             'urlaub_monat_tage',
             'urlaub_ende_tage',
          },
        }
    """
    import calendar as _calendar
    from datetime import date as _date

    if not (1 <= int(monat) <= 12):
        raise ValueError(f'Monat ausserhalb 1..12: {monat!r}')

    monat = int(monat)
    jahr = int(jahr)

    ma = ma_by_id(pers_id) or {}
    if not ma:
        raise ValueError(f'Mitarbeiter nicht gefunden: {pers_id}')

    monat_von = _date(jahr, monat, 1)
    letzter_tag = _calendar.monthrange(jahr, monat)[1]
    monat_bis = _date(jahr, monat, letzter_tag)

    # Jahres-Drill-Down erzeugt alle Tageszellen inkl. Typ-Klassifikation.
    jahr_data = arbeitszeitkonto_jahr(pers_id, jahr, modus='monat')

    # Tage des Monats isolieren.
    monats_tage_roh: list[dict] = []
    for p in jahr_data['perioden']:
        if p['nr'] == monat:
            monats_tage_roh = p['tage']
            break

    # Korrekturen mit Grund laden (fuer Uebertrag/Abbau-Klassifikation).
    with get_db_ro() as cur:
        cur.execute(
            """SELECT DATUM, MINUTEN, GRUND
                 FROM XT_PERSONAL_STUNDEN_KORREKTUR
                WHERE PERS_ID = %s AND STORNIERT = 0
                  AND DATUM BETWEEN %s AND %s""",
            (int(pers_id), _date(jahr, 1, 1), monat_bis),
        )
        korrektur_rows = cur.fetchall() or []

    # Uebertrags-Korrekturen (Jahresbasis, nicht tagesgebunden relevant fuer
    # die Monatsansicht): Summe aus Jahresbeginn bis Monatsende.
    uebertrag_korrektur_min = sum(
        int(r['MINUTEN']) for r in korrektur_rows
        if _ist_uebertrag_korrektur(r['GRUND'])
    )
    # Normale Korrekturen im aktuellen Monat (ohne Uebertrag).
    korrektur_monat_min = sum(
        int(r['MINUTEN']) for r in korrektur_rows
        if monat_von <= r['DATUM'] <= monat_bis
        and not _ist_uebertrag_korrektur(r['GRUND'])
    )
    # Abbau-Korrekturen (Teilmenge normaler Korrekturen) pro Tag, um sie im
    # Stundenzettel in eigener Spalte anzuzeigen.
    abbau_pro_tag: dict[_date, int] = {}
    for r in korrektur_rows:
        if (monat_von <= r['DATUM'] <= monat_bis
                and _ist_abbau_ueberstunden(r['GRUND'])):
            abbau_pro_tag[r['DATUM']] = (
                abbau_pro_tag.get(r['DATUM'], 0) + int(r['MINUTEN'])
            )

    # Pro-Tag-Zeilen zusammenbauen (Stundenzettel-Spalten).
    # Wichtig: Abbau-Minuten werden in der EIGENEN Spalte angezeigt und fliessen
    # NICHT in `gesamt_min` ein. `korrektur_monat_min` (Summenblock) enthaelt
    # ohnehin die Abbau-Korrekturen → sie wirken ueber die Korrektur-Summe im
    # Saldo (keine Doppelzaehlung). Fuer die Anzeige geben wir Abbau als
    # absoluten Betrag aus (Abbau wird in der DB typischerweise negativ
    # gespeichert), damit die Spalte eine positive Zahl zeigt.
    tage: list[dict] = []
    gesamt_min = 0
    soll_min = 0
    sonntagsarbeit_min = 0
    feiertagsarbeit_min = 0
    for tg in monats_tage_roh:
        d: _date = tg['datum']
        typ = tg['typ']
        feiertag_name = tg['typ_label'] if typ == 'feiertag' else ''
        arbeit = int(tg['gebucht_min'] or 0)
        urlaub_min = int(tg['bezahlt_min']) if typ == 'urlaub' else 0
        krank_min = int(tg['bezahlt_min']) if typ in ('krank', 'kind_krank') else 0
        abwesenheit_min = (int(tg['bezahlt_min'])
                           if typ in ('schulung', 'sonstiges') else 0)
        feiertag_min = int(tg['bezahlt_min']) if typ == 'feiertag' else 0
        abbau_min_raw = int(abbau_pro_tag.get(d, 0))
        abbau_min_display = abs(abbau_min_raw)

        # Gesamt (Ist, aus den angezeigten Spalten): Arbeit + Urlaub + Krank
        # + Abwesenheit + Feiertag. Abbau wird SEPARAT ueber Korrekturen verbucht.
        tag_gesamt = (arbeit + urlaub_min + krank_min + abwesenheit_min
                      + feiertag_min)

        gesamt_min += tag_gesamt
        soll_min += int(tg['regel_min'] or 0)

        if d.weekday() == 6 and arbeit > 0:
            sonntagsarbeit_min += arbeit
        if feiertag_name and arbeit > 0:
            feiertagsarbeit_min += arbeit

        tage.append({
            'datum':       d,
            'wochentag':   _WOCHENTAG_DE_KURZ[d.weekday()],
            'wochenende':  d.weekday() >= 5,
            'feiertag_name': feiertag_name,
            'arbeit_min':  arbeit,
            'abwesenheit_min': abwesenheit_min,
            'urlaub_min':  urlaub_min,
            'krank_min':   krank_min,
            'abbau_ueberstunden_min': abbau_min_display,
            'feiertag_min': feiertag_min,
        })

    # Saldo aktueller Monat = Ist + Korrekturen (ohne Uebertrag) − Soll.
    #   Vorzeichen: negatives Saldo = Fehlstunden. Beispiel Ist 51h, Soll 53h,
    #   Korrekturen 0 → Saldo −2h.
    saldo_monat_min = gesamt_min + korrektur_monat_min - soll_min

    # Saldo Vormonate: Summe der diff_min (summe − regel, inkl. aller
    # Korrekturen in den jeweiligen Monaten) fuer Jan..(monat−1). Damit sind
    # aufgelaufene Ueber-/Unterstunden aus Vormonaten enthalten, inklusive
    # Uebertrag-Korrektur (sofern zu Jahresbeginn gebucht).
    saldo_vormonate_min = sum(
        int(p['w']['diff_min']) for p in jahr_data['perioden']
        if p['nr'] < monat
    )
    # Saldo kumuliert = Vormonate + aktueller Monat (Korrekturen sind in beiden
    # Teilen bereits berueckrichtigt).
    saldo_kumuliert_min = saldo_vormonate_min + saldo_monat_min

    # Urlaubs-Anspruch zu Monatsbeginn / -ende.
    basis = urlaub_anspruch_basis(pers_id, jahr)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(TAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_KORREKTUR
                WHERE PERS_ID = %s AND JAHR = %s""",
            (int(pers_id), jahr),
        )
        korrektur_urlaub = float(cur.fetchone()['summe'])
        # Urlaub, der VOR dem Monat bereits angetreten/geplant war.
        cur.execute(
            """SELECT COALESCE(SUM(ARBEITSTAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s AND YEAR(VON) = %s
                  AND STATUS IN ('geplant','genehmigt','genommen')
                  AND BIS < %s""",
            (int(pers_id), jahr, monat_von),
        )
        urlaub_vor_monat = float(cur.fetchone()['summe'])

    urlaub_jahres_anspruch = basis + korrektur_urlaub
    urlaub_beginn_tage = urlaub_jahres_anspruch - urlaub_vor_monat
    # Urlaubstage im Monat aus Antraegen (anteilig bei Monatsuebergriff).
    with get_db_ro() as cur:
        cur.execute(
            """SELECT VON, BIS, ARBEITSTAGE
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s
                  AND STATUS IN ('geplant','genehmigt','genommen')
                  AND VON <= %s AND BIS >= %s""",
            (int(pers_id), monat_bis, monat_von),
        )
        urlaub_tage_monat = 0.0
        for u in cur.fetchall() or []:
            start = max(u['VON'], monat_von)
            ende = min(u['BIS'], monat_bis)
            if ende < start:
                continue
            gesamt_tage = (u['BIS'] - u['VON']).days + 1
            ueberlapp = (ende - start).days + 1
            anteil = ueberlapp / gesamt_tage if gesamt_tage else 0
            urlaub_tage_monat += float(u['ARBEITSTAGE']) * anteil
    urlaub_monat_tage = round(urlaub_tage_monat, 1)
    urlaub_ende_tage = round(urlaub_beginn_tage - urlaub_monat_tage, 1)

    return {
        'pers_id': int(pers_id),
        'jahr': jahr, 'monat': monat,
        'monats_name': _MONATSNAMEN_DE[monat],
        'ma': ma,
        'regel_az_label': jahr_data['regel_az_label'],
        'tage': tage,
        'summe': {
            'gesamt_min':             gesamt_min,
            'soll_min':               soll_min,
            'saldo_monat_min':        saldo_monat_min,
            'korrektur_monat_min':    korrektur_monat_min,
            'uebertrag_korrektur_min': uebertrag_korrektur_min,
            'saldo_vormonate_min':    saldo_vormonate_min,
            'saldo_kumuliert_min':    saldo_kumuliert_min,
            'sonntagsarbeit_min':     sonntagsarbeit_min,
            'feiertagsarbeit_min':    feiertagsarbeit_min,
            'urlaub_beginn_tage':     round(urlaub_beginn_tage, 1),
            'urlaub_monat_tage':      urlaub_monat_tage,
            'urlaub_ende_tage':       urlaub_ende_tage,
        },
    }


# ── Benachrichtigungs-Hook (E-Mail-Verteiler aus Verwaltung) ──────────────────

def benachrichtigung_empfaenger(bereich: str) -> list[str]:
    """Liefert aktive Empfaenger-Mailadressen fuer einen Bereich.

    Die Liste wird in der Verwaltungs-App unter /benachrichtigungen gepflegt.
    Fehlt die Tabelle (z.B. alte DB), liefert die Funktion eine leere Liste –
    Aufrufer behandeln das wie "keine Empfaenger" (best-effort).
    """
    try:
        with get_db_ro() as cur:
            cur.execute(
                """SELECT EMAIL FROM XT_BENACHRICHTIGUNG_EMPFAENGER
                    WHERE BEREICH = %s AND AKTIV = 1
                    ORDER BY EMAIL""",
                (bereich,),
            )
            return [r['EMAIL'] for r in (cur.fetchall() or []) if r.get('EMAIL')]
    except Exception:
        return []


def benachrichtigung_antrag_senden(*, bereich: str,
                                   pers_id: int,
                                   titel: str,
                                   details: str) -> dict:
    """Best-effort-Mail an alle aktiven Empfaenger des ``bereich``.

    Wirft nicht – Fehler landen im Log (via ``common.email``). Rueckgabe-Dict
    wie ``email_senden``, plus ``'empfaenger_count'`` und ``'modus'='leer'``,
    wenn keine Empfaenger konfiguriert sind.
    """
    empf = benachrichtigung_empfaenger(bereich)
    if not empf:
        return {'versendet': 0, 'modus': 'leer', 'empfaenger_count': 0}
    ma = ma_by_id(pers_id) or {}
    ma_name = f"{ma.get('VNAME','')} {ma.get('NAME','')}".strip() or f'MA {pers_id}'
    betreff = f'[CAO-XT] {titel} – {ma_name}'
    text = (
        f'{titel}\n\n'
        f'Mitarbeiter: {ma_name}\n'
        f'{details}\n\n'
        f'Bitte im Backoffice (WaWi → Personal) pruefen und entscheiden.\n'
    )
    try:
        from common.email import email_senden  # Lazy
        ergebnis = email_senden(empf, betreff, text)
        ergebnis['empfaenger_count'] = len(empf)
        return ergebnis
    except Exception as exc:
        return {'versendet': 0, 'modus': 'fehler',
                'empfaenger_count': len(empf), 'fehler': str(exc)}


# ── Hilfsfunktionen fuer Templates ────────────────────────────────────────────

def ct_to_eurostr(ct: int | None) -> str:
    if ct is None:
        return ''
    return f'{ct / 100:.2f}'.replace('.', ',')
