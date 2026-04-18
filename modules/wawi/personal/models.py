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
    """Änderungsprotokoll für einen Mitarbeiter (neueste zuerst)."""
    with get_db_ro() as cur:
        cur.execute(
            """SELECT l.REC_ID, l.OPERATION, l.FELDER_ALT_JSON, l.FELDER_NEU_JSON,
                      l.GEAEND_AT, l.GEAEND_VON,
                      CONCAT_WS(' ', m.VNAME, m.NAME) AS GEAEND_NAME
                 FROM XT_PERSONAL_MA_LOG l
            LEFT JOIN MITARBEITER m ON m.MA_ID = l.GEAEND_VON
                WHERE l.PERS_ID = %s
                ORDER BY l.GEAEND_AT DESC, l.REC_ID DESC
                LIMIT %s""",
            (int(pers_id), int(limit)),
        )
        return cur.fetchall()


def az_modell_bearbeiten(rec_id: int, werte: dict, benutzer_ma_id: int) -> int:
    """Retroactive Änderung an einem bestehenden AZ-Modell. Felder, die
    None sind, werden NICHT überschrieben. Loggt GEAEND_AT/GEAEND_VON.

    Rückgabe: Anzahl geänderter Felder."""
    erlaubt = ('LOHNART_ID', 'TYP', 'STUNDEN_SOLL',
               'STD_MO', 'STD_DI', 'STD_MI', 'STD_DO', 'STD_FR', 'STD_SA', 'STD_SO',
               'URLAUB_JAHR_TAGE', 'BEMERKUNG')
    sauber = {k: werte[k] for k in erlaubt if k in werte}
    if not sauber:
        return 0
    sets = ', '.join(f'{k} = %s' for k in sauber.keys())
    params = [*sauber.values(), int(benutzer_ma_id), int(rec_id)]
    with get_db_rw() as cur:
        cur.execute(
            f"UPDATE XT_PERSONAL_AZ_MODELL "
            f"   SET {sets}, GEAEND_AT = NOW(), GEAEND_VON = %s "
            f" WHERE REC_ID = %s",
            params,
        )
        return cur.rowcount


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
    gueltigen AZ-Modells. Liefert 0.0, wenn kein Modell existiert."""
    if bis < von:
        return 0.0
    summe = 0.0
    tag = von
    while tag <= bis:
        modell = aktuelles_az_modell(pers_id, tag)
        if modell and _modell_ist_arbeitstag(modell, tag):
            summe += 1.0
        tag += timedelta(days=1)
    return summe


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
        return cur.fetchall()


def urlaub_saldo(pers_id: int, jahr: int) -> dict:
    """Berechnet alle Teilsalden fuer ein Urlaubsjahr. Alle Werte als float
    (Tage mit einer Nachkommastelle). Rest = basis + korrektur − geplant − genehmigt − genommen."""
    basis = urlaub_anspruch_basis(pers_id, jahr)
    with get_db_ro() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(TAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_KORREKTUR
                WHERE PERS_ID = %s AND JAHR = %s""",
            (int(pers_id), int(jahr)),
        )
        korrektur = float(cur.fetchone()['summe'])
        cur.execute(
            """SELECT STATUS, COALESCE(SUM(ARBEITSTAGE), 0) AS summe
                 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s AND YEAR(VON) = %s
                GROUP BY STATUS""",
            (int(pers_id), int(jahr)),
        )
        nach_status = {row['STATUS']: float(row['summe']) for row in cur.fetchall()}
    geplant   = nach_status.get('geplant', 0.0)
    genehmigt = nach_status.get('genehmigt', 0.0)
    genommen  = nach_status.get('genommen', 0.0)
    gesamt    = basis + korrektur
    rest      = gesamt - geplant - genehmigt - genommen
    return {
        'basis':     basis,
        'korrektur': korrektur,
        'gesamt':    gesamt,
        'geplant':   geplant,
        'genehmigt': genehmigt,
        'genommen':  genommen,
        'rest':      rest,
    }


def urlaub_korrektur_anlegen(pers_id: int, jahr: int, tage: float,
                             grund: str, kommentar: str | None,
                             benutzer_ma_id: int) -> int:
    if not grund or not grund.strip():
        raise ValueError('GRUND ist Pflicht')
    with get_db_rw() as cur:
        cur.execute(
            """INSERT INTO XT_PERSONAL_URLAUB_KORREKTUR
                 (PERS_ID, JAHR, TAGE, GRUND, KOMMENTAR, ERSTELLT_VON)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (int(pers_id), int(jahr), float(tage), grund.strip(),
             kommentar, int(benutzer_ma_id)),
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
        return cur.lastrowid


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
    sql = ("""UPDATE XT_PERSONAL_URLAUB_ANTRAG
                 SET STATUS = 'genommen',
                     STATUS_GEAEND_AT  = NOW(),
                     STATUS_GEAEND_VON = NULL
               WHERE STATUS = 'genehmigt' AND BIS < %s""")
    params: tuple = (stichtag,)
    if pers_id is not None:
        sql += " AND PERS_ID = %s"
        params = (stichtag, int(pers_id))
    with get_db_rw() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def urlaub_antrag_status_setzen(rec_id: int, neuer_status: str,
                                benutzer_ma_id: int) -> int:
    """Aktualisiert den Status eines Antrags, wenn der Uebergang erlaubt ist."""
    if neuer_status not in ('geplant', 'genehmigt', 'genommen',
                            'abgelehnt', 'storniert'):
        raise ValueError(f'Unbekannter Status: {neuer_status!r}')
    with get_db_rw() as cur:
        cur.execute(
            "SELECT STATUS FROM XT_PERSONAL_URLAUB_ANTRAG WHERE REC_ID = %s",
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
        return cur.rowcount


# ── Hilfsfunktionen fuer Templates ────────────────────────────────────────────

def ct_to_eurostr(ct: int | None) -> str:
    if ct is None:
        return ''
    return f'{ct / 100:.2f}'.replace('.', ',')
