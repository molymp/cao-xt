"""
CAO-XT Kassen-App – Kerngeschäftslogik

Enthält alle Datenbankoperationen für:
 • Mitarbeiter-Authentifizierung (gegen MITARBEITER-Tabelle)
 • MwSt-Sätze aus REGISTRY
 • Artikel-Suche (ARTIKEL) und Schnelltasten (ARTIKEL_SCHNELLZUGRIFF)
 • Vorgänge: erstellen, Position hinzufügen/entfernen, parken, stornieren
 • Zahlung abschließen (TSE-Signatur speichern)
 • Kassenbuch: Einlagen, Entnahmen, Anfangsbestand
 • Tagesabschluss (Z-Bon)
 • Bon → CAO-Lieferschein wandeln
 • Kunden-Suche (ADRESSEN)
"""
import uuid
import hashlib
from datetime import datetime, date
from decimal import Decimal
from db import get_db, get_db_transaction, euro_zu_cent, cent_zu_euro_str
import config
import logging

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Mitarbeiter
# ─────────────────────────────────────────────────────────────

def mitarbeiter_login(login_name: str, passwort: str) -> dict | None:
    """
    Prüft Credentials gegen MITARBEITER-Tabelle.
    CAO speichert Passwörter als MD5-Hash (Großbuchstaben).
    Gibt {MA_ID, LOGIN_NAME, VNAME, NAME} zurück oder None.
    """
    pw_hash = hashlib.md5(passwort.encode('utf-8')).hexdigest().upper()
    with get_db() as cur:
        cur.execute(
            """SELECT MA_ID, LOGIN_NAME, VNAME, NAME
               FROM MITARBEITER
               WHERE LOGIN_NAME = %s AND USER_PASSWORD = %s""",
            (login_name, pw_hash)
        )
        row = cur.fetchone()
    return row


def mitarbeiter_liste() -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT MA_ID, LOGIN_NAME, VNAME, NAME FROM MITARBEITER ORDER BY NAME, VNAME"
        )
        return cur.fetchall()


# ─────────────────────────────────────────────────────────────
# MwSt-Sätze (gecacht, da sich selten ändern)
# ─────────────────────────────────────────────────────────────

_mwst_cache: dict | None = None


def mwst_saetze_laden() -> dict:
    """
    Liest MwSt-Sätze aus REGISTRY (MAINKEY='MAIN\\MWST').
    Gibt {STEUER_CODE: satz_float} zurück, z.B. {1: 19.0, 2: 7.0, 3: 0.0}.
    """
    global _mwst_cache
    if _mwst_cache is not None:
        return _mwst_cache
    with get_db() as cur:
        cur.execute(
            r"SELECT NAME, VAL_DOUBLE, VAL_INT FROM REGISTRY WHERE MAINKEY = 'MAIN\MWST'"
        )
        rows = cur.fetchall()

    result = {}
    for row in rows:
        name = (row['NAME'] or '').upper()
        satz = float(row['VAL_DOUBLE'] or 0)
        code = row.get('VAL_INT')
        # Name-Pattern: MWST1, MWST2, MWST3 oder ähnlich
        if name.startswith('MWST') and name[4:].isdigit():
            code = int(name[4:])
        if code:
            result[code] = satz

    # Fallback wenn REGISTRY leer
    if not result:
        result = {1: 19.0, 2: 7.0, 3: 0.0}

    _mwst_cache = result
    return result


def mwst_cache_invalidieren():
    global _mwst_cache
    _mwst_cache = None


def mwst_satz_fuer_code(steuer_code: int) -> float:
    return mwst_saetze_laden().get(steuer_code, 0.0)


def mwst_berechnen(brutto_cent: int, steuer_code: int) -> tuple[int, int]:
    """Gibt (netto_cent, mwst_cent) zurück."""
    satz = mwst_satz_fuer_code(steuer_code)
    if satz == 0:
        return brutto_cent, 0
    faktor = satz / 100.0
    mwst = round(brutto_cent * faktor / (1 + faktor))
    return brutto_cent - mwst, mwst


# ─────────────────────────────────────────────────────────────
# Artikel
# ─────────────────────────────────────────────────────────────

def artikel_suchen(suchtext: str, limit: int = 30) -> list:
    """Suche in ARTNUM, BARCODE, KURZNAME, MATCHCODE."""
    pat = f"%{suchtext.strip()}%"
    with get_db() as cur:
        cur.execute(
            """SELECT REC_ID, ARTNUM, BARCODE, KURZNAME, MATCHCODE,
                      VK5B AS VK_PREIS, STEUER_CODE, ARTIKELTYP
               FROM ARTIKEL
               WHERE (ARTNUM LIKE %s OR BARCODE LIKE %s
                      OR KURZNAME LIKE %s OR MATCHCODE LIKE %s)
                 AND ARTIKELTYP NOT IN ('L','K')
               ORDER BY KURZNAME
               LIMIT %s""",
            (pat, pat, pat, pat, limit)
        )
        rows = cur.fetchall()
    return [_artikel_aufbereiten(r) for r in rows]


def artikel_per_barcode(barcode: str) -> dict | None:
    with get_db() as cur:
        cur.execute(
            """SELECT REC_ID, ARTNUM, BARCODE, KURZNAME, MATCHCODE,
                      VK5B AS VK_PREIS, STEUER_CODE, ARTIKELTYP
               FROM ARTIKEL WHERE BARCODE = %s LIMIT 1""",
            (barcode,)
        )
        row = cur.fetchone()
    return _artikel_aufbereiten(row) if row else None


def _artikel_aufbereiten(row: dict) -> dict:
    preis_cent = euro_zu_cent(row.get('VK_PREIS'))
    steuer_code = row.get('STEUER_CODE') or 1
    netto, mwst = mwst_berechnen(preis_cent, steuer_code)
    return {
        'id':          row['REC_ID'],
        'artnum':      row.get('ARTNUM', ''),
        'barcode':     row.get('BARCODE', ''),
        'bezeichnung': row.get('KURZNAME', ''),
        'matchcode':   row.get('MATCHCODE', ''),
        'preis_cent':  preis_cent,
        'netto_cent':  netto,
        'mwst_cent':   mwst,
        'steuer_code': steuer_code,
        'mwst_satz':   mwst_satz_fuer_code(steuer_code),
    }


# ─────────────────────────────────────────────────────────────
# Schnelltasten (ARTIKEL_SCHNELLZUGRIFF read-only)
# ─────────────────────────────────────────────────────────────

def schnelltasten_laden() -> list:
    """
    Liest ARTIKEL_SCHNELLZUGRIFF aus CAO.
    Da die Spaltenstruktur variieren kann, werden alle Spalten gelesen
    und flexibel aufbereitet.
    """
    with get_db() as cur:
        # Spalten der Tabelle ermitteln
        cur.execute("DESCRIBE ARTIKEL_SCHNELLZUGRIFF")
        spalten = {r['Field'] for r in cur.fetchall()}

        pos_col    = _erste_spalte(spalten, ['POS','POSITION','REIHE','NR','TASTE_NR'], 'REC_ID')
        name_col   = _erste_spalte(spalten, ['BEZEICHNUNG','NAME','KURZNAME'], None)
        farbe_col  = _erste_spalte(spalten, ['FARBE','FARBE_BG','COLOR'], None)
        schrift_col= _erste_spalte(spalten, ['FARBE_SCHRIFT','SCHRIFTFARBE','COLOR_TEXT','FONT_COLOR'], None)
        seite_col  = _erste_spalte(spalten, ['SEITE','EBENE','TAB'], None)
        gruppe_col = _erste_spalte(spalten, ['GRUPPE','KATEGORIE','CATEGORY','GRUPPENNAME'], None)
        artnr_col  = _erste_spalte(spalten, ['ARTIKEL_ID','ARTNUM','ARTNR'], None)

        select = ['REC_ID', pos_col]
        if name_col:    select.append(name_col)
        if farbe_col:   select.append(farbe_col)
        if schrift_col: select.append(schrift_col)
        if seite_col:   select.append(seite_col)
        if gruppe_col:  select.append(gruppe_col)
        if artnr_col:   select.append(artnr_col)

        cur.execute(
            f"SELECT {', '.join(set(select))} FROM ARTIKEL_SCHNELLZUGRIFF ORDER BY {pos_col}"
        )
        rows = cur.fetchall()

    # Artikel-Details nachladen
    result = []
    for row in rows:
        eintrag = {
            'rec_id':       row.get('REC_ID'),
            'position':     row.get(pos_col) or row.get('REC_ID'),
            'farbe':        row.get(farbe_col)   if farbe_col   else None,
            'schriftfarbe': row.get(schrift_col) if schrift_col else None,
            'seite':        row.get(seite_col) or 1 if seite_col else 1,
            'gruppe':       row.get(gruppe_col)  if gruppe_col  else None,
        }
        # Artikel-Daten laden
        artikel_ref = row.get(artnr_col) if artnr_col else None
        if artikel_ref:
            if str(artikel_ref).isdigit():
                # numerisch → ARTIKEL.REC_ID
                with get_db() as cur2:
                    cur2.execute(
                        """SELECT REC_ID, ARTNUM, BARCODE, KURZNAME,
                                  VK5B AS VK_PREIS, STEUER_CODE
                           FROM ARTIKEL WHERE REC_ID = %s""",
                        (int(artikel_ref),)
                    )
                    art = cur2.fetchone()
            else:
                # Text → ARTNUM
                with get_db() as cur2:
                    cur2.execute(
                        """SELECT REC_ID, ARTNUM, BARCODE, KURZNAME,
                                  VK5B AS VK_PREIS, STEUER_CODE
                           FROM ARTIKEL WHERE ARTNUM = %s LIMIT 1""",
                        (str(artikel_ref),)
                    )
                    art = cur2.fetchone()
            if art:
                art_aufb = _artikel_aufbereiten(art)
                eintrag.update({
                    'artikel_id':  art_aufb['id'],
                    'artnum':      art_aufb['artnum'],
                    'bezeichnung': row.get(name_col) or art_aufb['bezeichnung'] if name_col else art_aufb['bezeichnung'],
                    'preis_cent':  art_aufb['preis_cent'],
                    'steuer_code': art_aufb['steuer_code'],
                    'mwst_satz':   art_aufb['mwst_satz'],
                })
        if 'bezeichnung' not in eintrag:
            eintrag['bezeichnung'] = row.get(name_col, '?') if name_col else '?'
        result.append(eintrag)
    return result


def _erste_spalte(spalten: set, kandidaten: list, fallback) -> str | None:
    for k in kandidaten:
        if k in spalten:
            return k
    return fallback


# ─────────────────────────────────────────────────────────────
# Kunden (ADRESSEN read-only)
# ─────────────────────────────────────────────────────────────

def kunden_suchen(suchtext: str, limit: int = 20) -> list:
    pat = f"%{suchtext.strip()}%"
    with get_db() as cur:
        cur.execute(
            """SELECT REC_ID, KUNNUM1, NAME1, NAME2, ORT, TELE1, EMAIL,
                      PR_EBENE, BRUTTO_FLAG
               FROM ADRESSEN
               WHERE (NAME1 LIKE %s OR NAME2 LIKE %s OR KUNNUM1 LIKE %s
                      OR MATCHCODE LIKE %s)
               ORDER BY NAME1 LIMIT %s""",
            (pat, pat, pat, pat, limit)
        )
        return cur.fetchall()


# ─────────────────────────────────────────────────────────────
# Bon-Nummern (atomar)
# ─────────────────────────────────────────────────────────────

def naechste_bon_nr(terminal_nr: int, cursor) -> int:
    cursor.execute(
        "SELECT BON_NR_LETZT FROM XT_KASSE_ZAEHLER WHERE TERMINAL_NR = %s FOR UPDATE",
        (terminal_nr,)
    )
    row = cursor.fetchone()
    neue_nr = (row['BON_NR_LETZT'] + 1) if row else 1
    cursor.execute(
        "UPDATE XT_KASSE_ZAEHLER SET BON_NR_LETZT = %s WHERE TERMINAL_NR = %s",
        (neue_nr, terminal_nr)
    )
    return neue_nr


def naechste_z_nr(terminal_nr: int, cursor) -> int:
    cursor.execute(
        "SELECT Z_NR_LETZT FROM XT_KASSE_ZAEHLER WHERE TERMINAL_NR = %s FOR UPDATE",
        (terminal_nr,)
    )
    row = cursor.fetchone()
    neue_nr = (row['Z_NR_LETZT'] + 1) if row else 1
    cursor.execute(
        "UPDATE XT_KASSE_ZAEHLER SET Z_NR_LETZT = %s WHERE TERMINAL_NR = %s",
        (neue_nr, terminal_nr)
    )
    return neue_nr


# ─────────────────────────────────────────────────────────────
# Vorgänge
# ─────────────────────────────────────────────────────────────

def vorgang_neu(terminal_nr: int, mitarbeiter: dict) -> dict:
    """Erstellt einen neuen offenen Kassiervorgang und startet die TSE-Transaktion."""
    import tse as tse_modul
    tse_verfuegbar = tse_modul.tse_verfuegbar(terminal_nr)

    with get_db_transaction() as cur:
        bon_nr = naechste_bon_nr(terminal_nr, cur)
        jetzt  = datetime.now()
        vorgangsnummer = f"{terminal_nr:02d}-{jetzt.strftime('%Y%m%d')}-{bon_nr:06d}"

        cur.execute(
            """INSERT INTO XT_KASSE_VORGAENGE
               (TERMINAL_NR, BON_NR, BON_DATUM, MITARBEITER_ID, MITARBEITER_NAME,
                STATUS, VORGANGSNUMMER)
               VALUES (%s,%s,%s,%s,%s,'OFFEN',%s)""",
            (terminal_nr, bon_nr, jetzt,
             mitarbeiter.get('MA_ID'),
             f"{mitarbeiter.get('VNAME','')} {mitarbeiter.get('NAME','')}".strip(),
             vorgangsnummer)
        )
        vorgang_id = cur.lastrowid

    # TSE-Transaktion starten (außerhalb der DB-Transaktion da externe API)
    if tse_verfuegbar:
        try:
            tse_data = tse_modul.tse_start_transaktion(terminal_nr, vorgang_id)
            with get_db() as cur:
                cur.execute(
                    """UPDATE XT_KASSE_VORGAENGE
                       SET TSE_TX_ID = %s, TSE_TX_REVISION = %s,
                           TSE_ZEITPUNKT_START = %s
                       WHERE ID = %s""",
                    (tse_data['tx_id'], tse_data['revision'],
                     tse_data.get('zeitpunkt_start'), vorgang_id)
                )
        except Exception as e:
            log.error("TSE Start fehlgeschlagen: %s", e)
            # Vorgang trotzdem anlegen (TSE-Fehler darf nicht den Verkauf blockieren,
            # muss aber nachträglich dokumentiert werden)

    return vorgang_laden(vorgang_id)


def vorgang_laden(vorgang_id: int) -> dict | None:
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_VORGAENGE WHERE ID = %s", (vorgang_id,))
        return cur.fetchone()


def vorgang_positionen(vorgang_id: int) -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM XT_KASSE_VORGAENGE_POS WHERE VORGANG_ID = %s ORDER BY POSITION",
            (vorgang_id,)
        )
        return cur.fetchall()


def vorgang_zahlungen(vorgang_id: int) -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM XT_KASSE_ZAHLUNGEN WHERE VORGANG_ID = %s ORDER BY ID",
            (vorgang_id,)
        )
        return cur.fetchall()


def position_hinzufuegen(vorgang_id: int, artikel_id: int | None,
                          bezeichnung: str, menge: float,
                          einzelpreis_brutto: int, steuer_code: int,
                          rabatt_prozent: float = 0.0,
                          ist_gutschein: bool = False) -> dict:
    """Fügt eine Position zum Vorgang hinzu und aktualisiert die Summen."""
    # Menge / Rabatt berücksichtigen
    rabatt_faktor = 1.0 - (rabatt_prozent / 100.0)
    ep_nach_rabatt = round(einzelpreis_brutto * rabatt_faktor)
    gesamt = round(ep_nach_rabatt * menge)

    netto, mwst_b = mwst_berechnen(gesamt, steuer_code)
    mwst_satz = mwst_satz_fuer_code(steuer_code)

    # Artikeldaten nachladen für Snapshot
    artnum = ''
    barcode = ''
    if artikel_id:
        with get_db() as cur:
            cur.execute(
                "SELECT ARTNUM, BARCODE FROM ARTIKEL WHERE REC_ID = %s", (artikel_id,)
            )
            art = cur.fetchone()
            if art:
                artnum  = art['ARTNUM'] or ''
                barcode = art['BARCODE'] or ''

    with get_db_transaction() as cur:
        # Nächste Positionsnummer
        cur.execute(
            "SELECT COALESCE(MAX(POSITION),0)+1 AS NR FROM XT_KASSE_VORGAENGE_POS "
            "WHERE VORGANG_ID = %s",
            (vorgang_id,)
        )
        pos_nr = cur.fetchone()['NR']

        cur.execute(
            """INSERT INTO XT_KASSE_VORGAENGE_POS
               (VORGANG_ID, POSITION, ARTIKEL_ID, ARTNUM, BARCODE, BEZEICHNUNG,
                MENGE, EINZELPREIS_BRUTTO, GESAMTPREIS_BRUTTO,
                RABATT_PROZENT, STEUER_CODE, MWST_SATZ, MWST_BETRAG,
                NETTO_BETRAG, IST_GUTSCHEIN)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (vorgang_id, pos_nr, artikel_id, artnum, barcode, bezeichnung,
             menge, ep_nach_rabatt, gesamt,
             rabatt_prozent, steuer_code, mwst_satz, mwst_b, netto,
             1 if ist_gutschein else 0)
        )
        pos_id = cur.lastrowid
        _vorgang_summen_aktualisieren(vorgang_id, cur)

    return {'id': pos_id, 'position': pos_nr}


def position_entfernen(vorgang_id: int, position_id: int):
    """Markiert eine Position als storniert (weiche Löschung)."""
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE_POS SET STORNIERT = 1 "
            "WHERE ID = %s AND VORGANG_ID = %s",
            (position_id, vorgang_id)
        )
        _vorgang_summen_aktualisieren(vorgang_id, cur)


def _vorgang_summen_aktualisieren(vorgang_id: int, cursor):
    """Berechnet Summen aus aktiven Positionen neu."""
    cursor.execute(
        """SELECT STEUER_CODE,
                  SUM(GESAMTPREIS_BRUTTO) AS BRUTTO,
                  SUM(NETTO_BETRAG) AS NETTO,
                  SUM(MWST_BETRAG) AS MWST
           FROM XT_KASSE_VORGAENGE_POS
           WHERE VORGANG_ID = %s AND STORNIERT = 0
           GROUP BY STEUER_CODE""",
        (vorgang_id,)
    )
    rows = cursor.fetchall()

    brutto = netto = 0
    mwst = {1: 0, 2: 0, 3: 0}
    netto_codes = {1: 0, 2: 0, 3: 0}
    for r in rows:
        code = r['STEUER_CODE']
        brutto += r['BRUTTO'] or 0
        netto  += r['NETTO'] or 0
        if code in mwst:
            mwst[code]        += r['MWST'] or 0
            netto_codes[code] += r['NETTO'] or 0

    cursor.execute(
        """UPDATE XT_KASSE_VORGAENGE
           SET BETRAG_BRUTTO = %s, BETRAG_NETTO = %s,
               MWST_BETRAG_1 = %s, MWST_BETRAG_2 = %s, MWST_BETRAG_3 = %s,
               NETTO_BETRAG_1 = %s, NETTO_BETRAG_2 = %s, NETTO_BETRAG_3 = %s
           WHERE ID = %s""",
        (brutto, netto,
         mwst[1], mwst[2], mwst[3],
         netto_codes[1], netto_codes[2], netto_codes[3],
         vorgang_id)
    )


def vorgang_parken(vorgang_id: int):
    with get_db() as cur:
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE SET STATUS='GEPARKT' WHERE ID=%s AND STATUS='OFFEN'",
            (vorgang_id,)
        )


def vorgang_entparken(vorgang_id: int):
    with get_db() as cur:
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE SET STATUS='OFFEN' WHERE ID=%s AND STATUS='GEPARKT'",
            (vorgang_id,)
        )


def geparkte_vorgaenge(terminal_nr: int) -> list:
    with get_db() as cur:
        cur.execute(
            """SELECT v.*, COUNT(p.ID) AS ANZAHL_POS
               FROM XT_KASSE_VORGAENGE v
               LEFT JOIN XT_KASSE_VORGAENGE_POS p ON p.VORGANG_ID = v.ID AND p.STORNIERT=0
               WHERE v.TERMINAL_NR = %s AND v.STATUS = 'GEPARKT'
               GROUP BY v.ID ORDER BY v.BON_DATUM""",
            (terminal_nr,)
        )
        return cur.fetchall()


# ─────────────────────────────────────────────────────────────
# Zahlung abschließen
# ─────────────────────────────────────────────────────────────

def zahlung_abschliessen(vorgang_id: int, terminal_nr: int,
                          zahlungen: list) -> dict:
    """
    Schließt den Kassiervorgang ab:
      1. Zahlungen speichern
      2. TSE-Transaktion beenden (Signatur holen)
      3. Vorgang auf ABGESCHLOSSEN setzen
      4. Kassenbuch-Eintrag für BAR-Zahlungen

    zahlungen: [{'zahlart': 'BAR', 'betrag': 1500,
                  'betrag_gegeben': 2000, 'wechselgeld': 500}, ...]
    """
    import tse as tse_modul
    vorgang = vorgang_laden(vorgang_id)
    if not vorgang or vorgang['STATUS'] not in ('OFFEN',):
        raise ValueError("Vorgang nicht gefunden oder nicht offen.")

    positionen = vorgang_positionen(vorgang_id)
    mwst_saetze = mwst_saetze_laden()

    # TSE abschließen
    tse_data = {}
    if vorgang.get('TSE_TX_ID'):
        try:
            tse_data = tse_modul.tse_finish_transaktion(
                terminal_nr, vorgang_id,
                tx_id=vorgang['TSE_TX_ID'],
                revision=vorgang['TSE_TX_REVISION'],
                positionen=positionen,
                zahlarten=zahlungen,
                mwst_saetze=mwst_saetze,
            )
        except Exception as e:
            log.error("TSE Finish fehlgeschlagen (Vorgang %d): %s", vorgang_id, e)
            # Fehler protokollieren aber Kassiervorgang nicht blockieren

    with get_db_transaction() as cur:
        # Zahlungen speichern
        for z in zahlungen:
            cur.execute(
                """INSERT INTO XT_KASSE_ZAHLUNGEN
                   (VORGANG_ID, ZAHLART, BETRAG, BETRAG_GEGEBEN, WECHSELGELD,
                    REFERENZ, ADRESSEN_ID)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (vorgang_id, z['zahlart'], z['betrag'],
                 z.get('betrag_gegeben'), z.get('wechselgeld'),
                 z.get('referenz'), z.get('adressen_id'))
            )

        # Vorgang abschließen + TSE-Daten speichern
        cur.execute(
            """UPDATE XT_KASSE_VORGAENGE
               SET STATUS = 'ABGESCHLOSSEN',
                   TSE_TX_ID             = COALESCE(%s, TSE_TX_ID),
                   TSE_TX_REVISION       = COALESCE(%s, TSE_TX_REVISION),
                   TSE_SIGNATUR          = %s,
                   TSE_SIGNATUR_ZAEHLER  = %s,
                   TSE_ZEITPUNKT_START   = COALESCE(%s, TSE_ZEITPUNKT_START),
                   TSE_ZEITPUNKT_ENDE    = %s,
                   TSE_SERIAL            = %s,
                   TSE_LOG_TIME_FORMAT   = %s,
                   TSE_PROCESS_TYPE      = %s,
                   TSE_PROCESS_DATA      = %s
               WHERE ID = %s""",
            (tse_data.get('tx_id'), tse_data.get('revision'),
             tse_data.get('signatur'), tse_data.get('signatur_zaehler'),
             tse_data.get('zeitpunkt_start'), tse_data.get('zeitpunkt_ende'),
             tse_data.get('tss_serial'), tse_data.get('log_time_format'),
             tse_data.get('process_type'), tse_data.get('process_data'),
             vorgang_id)
        )

        # Kassenbuch-Eintrag für BAR
        bar_gesamt = sum(z['betrag'] for z in zahlungen if z['zahlart'] == 'BAR')
        if bar_gesamt:
            cur.execute(
                """INSERT INTO XT_KASSE_KASSENBUCH
                   (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, VORGANG_ID, MITARBEITER_ID)
                   VALUES (%s, %s, 'UMSATZ_BAR', %s, %s, %s)""",
                (terminal_nr, datetime.now(), bar_gesamt,
                 vorgang_id, vorgang.get('MITARBEITER_ID'))
            )

    return vorgang_laden(vorgang_id)


# ─────────────────────────────────────────────────────────────
# Storno
# ─────────────────────────────────────────────────────────────

def vorgang_stornieren(original_id: int, terminal_nr: int,
                        mitarbeiter: dict) -> dict:
    """
    Erstellt einen Storno-Vorgang zum Original-Beleg.
    Die TSE wird mit CANCELLATION-Typ signiert.
    """
    import tse as tse_modul

    original = vorgang_laden(original_id)
    if not original or original['STATUS'] != 'ABGESCHLOSSEN':
        raise ValueError("Nur abgeschlossene Vorgänge können storniert werden.")

    orig_pos = vorgang_positionen(original_id)
    mwst_saetze = mwst_saetze_laden()

    tse_data = {}
    if tse_modul.tse_verfuegbar(terminal_nr):
        try:
            tse_data = tse_modul.tse_storno_transaktion(
                terminal_nr, original_id, orig_pos, mwst_saetze
            )
        except Exception as e:
            log.error("TSE Storno fehlgeschlagen: %s", e)

    with get_db_transaction() as cur:
        bon_nr = naechste_bon_nr(terminal_nr, cur)
        jetzt  = datetime.now()
        vorgangsnummer = f"{terminal_nr:02d}-{jetzt.strftime('%Y%m%d')}-{bon_nr:06d}-S"

        cur.execute(
            """INSERT INTO XT_KASSE_VORGAENGE
               (TERMINAL_NR, BON_NR, BON_DATUM, MITARBEITER_ID, MITARBEITER_NAME,
                STATUS, STORNO_VON_ID, VORGANGSNUMMER, VORGANG_TYP,
                BETRAG_BRUTTO, BETRAG_NETTO,
                MWST_BETRAG_1, MWST_BETRAG_2, MWST_BETRAG_3,
                NETTO_BETRAG_1, NETTO_BETRAG_2, NETTO_BETRAG_3,
                TSE_TX_ID, TSE_TX_REVISION, TSE_SIGNATUR, TSE_SIGNATUR_ZAEHLER,
                TSE_ZEITPUNKT_START, TSE_ZEITPUNKT_ENDE, TSE_SERIAL)
               VALUES (%s,%s,%s,%s,%s,'ABGESCHLOSSEN',%s,%s,'Beleg',
                       %s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s)""",
            (terminal_nr, bon_nr, jetzt,
             mitarbeiter.get('MA_ID'),
             f"{mitarbeiter.get('VNAME','')} {mitarbeiter.get('NAME','')}".strip(),
             original_id, vorgangsnummer,
             -original['BETRAG_BRUTTO'], -original['BETRAG_NETTO'],
             -original['MWST_BETRAG_1'], -original['MWST_BETRAG_2'], -original['MWST_BETRAG_3'],
             -original['NETTO_BETRAG_1'], -original['NETTO_BETRAG_2'], -original['NETTO_BETRAG_3'],
             tse_data.get('tx_id'), tse_data.get('revision'),
             tse_data.get('signatur'), tse_data.get('signatur_zaehler'),
             tse_data.get('zeitpunkt_start'), tse_data.get('zeitpunkt_ende'),
             tse_data.get('tss_serial'))
        )
        storno_id = cur.lastrowid

        # Originalpositionen als Storno-Positionen mit negativem Vorzeichen
        for pos in orig_pos:
            cur.execute(
                """INSERT INTO XT_KASSE_VORGAENGE_POS
                   (VORGANG_ID, POSITION, ARTIKEL_ID, ARTNUM, BARCODE, BEZEICHNUNG,
                    MENGE, EINZELPREIS_BRUTTO, GESAMTPREIS_BRUTTO,
                    STEUER_CODE, MWST_SATZ, MWST_BETRAG, NETTO_BETRAG)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (storno_id, pos['POSITION'], pos['ARTIKEL_ID'],
                 pos['ARTNUM'], pos['BARCODE'], pos['BEZEICHNUNG'],
                 pos['MENGE'],
                 -pos['EINZELPREIS_BRUTTO'], -pos['GESAMTPREIS_BRUTTO'],
                 pos['STEUER_CODE'], pos['MWST_SATZ'],
                 -pos['MWST_BETRAG'], -pos['NETTO_BETRAG'])
            )

        # Original als storniert markieren
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE SET STATUS='STORNIERT' WHERE ID=%s",
            (original_id,)
        )

        # BAR-Kassenbuch (negativ)
        bar_orig = sum(
            z['BETRAG'] for z in vorgang_zahlungen(original_id)
            if z['ZAHLART'] == 'BAR'
        )
        if bar_orig:
            cur.execute(
                """INSERT INTO XT_KASSE_KASSENBUCH
                   (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, VORGANG_ID, MITARBEITER_ID)
                   VALUES (%s, %s, 'UMSATZ_BAR', %s, %s, %s)""",
                (terminal_nr, jetzt, -bar_orig,
                 storno_id, mitarbeiter.get('MA_ID'))
            )

    return vorgang_laden(storno_id)


def vorgang_kopieren(original_id: int, terminal_nr: int, mitarbeiter: dict) -> dict:
    """
    Erstellt einen neuen offenen Vorgang mit den Positionen des Originals.
    Ein leerer offener Vorgang desselben Terminals wird vorher automatisch
    abgebrochen (TSE-Cancel + Löschung), damit kein Waisen-Bon entsteht.
    """
    import tse as tse_modul

    original = vorgang_laden(original_id)
    if not original:
        raise ValueError("Vorgang nicht gefunden.")
    positionen = vorgang_positionen(original_id)
    aktive_pos = [p for p in positionen if not p.get('STORNIERT')]
    if not aktive_pos:
        raise ValueError("Keine kopierbaren Positionen vorhanden.")

    # Leeren offenen Vorgang dieses Terminals aufräumen
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM XT_KASSE_VORGAENGE "
            "WHERE TERMINAL_NR=%s AND STATUS='OFFEN' ORDER BY ID DESC LIMIT 1",
            (terminal_nr,)
        )
        offen = cur.fetchone()
    if offen and not vorgang_positionen(offen['ID']):
        if offen.get('TSE_TX_ID'):
            try:
                tse_modul.tse_cancel_transaktion(
                    terminal_nr, offen['ID'],
                    offen['TSE_TX_ID'], offen['TSE_TX_REVISION']
                )
            except Exception:
                pass
        with get_db() as cur:
            cur.execute(
                "DELETE FROM XT_KASSE_VORGAENGE WHERE ID=%s AND STATUS='OFFEN'",
                (offen['ID'],)
            )

    # Neuen Vorgang anlegen (inkl. TSE-Start)
    neuer = vorgang_neu(terminal_nr, mitarbeiter)

    # Positionen 1:1 übertragen
    for pos in aktive_pos:
        position_hinzufuegen(
            vorgang_id=neuer['ID'],
            artikel_id=pos.get('ARTIKEL_ID'),
            bezeichnung=pos['BEZEICHNUNG'],
            menge=float(pos['MENGE']),
            einzelpreis_brutto=pos['EINZELPREIS_BRUTTO'],
            steuer_code=pos['STEUER_CODE'],
            rabatt_prozent=float(pos.get('RABATT_PROZENT', 0)),
            ist_gutschein=bool(pos.get('IST_GUTSCHEIN', 0)),
        )

    return vorgang_laden(neuer['ID'])


# ─────────────────────────────────────────────────────────────
# Kassenbuch
# ─────────────────────────────────────────────────────────────

def kassenbuch_eintrag(terminal_nr: int, typ: str, betrag_cent: int,
                        mitarbeiter_id: int, notiz: str = ''):
    """typ: 'EINLAGE' | 'ENTNAHME' | 'ANFANGSBESTAND'"""
    wert = betrag_cent if typ in ('EINLAGE', 'ANFANGSBESTAND') else -abs(betrag_cent)
    with get_db() as cur:
        cur.execute(
            """INSERT INTO XT_KASSE_KASSENBUCH
               (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, NOTIZ, MITARBEITER_ID)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (terminal_nr, datetime.now(), typ, wert, notiz, mitarbeiter_id)
        )


def kassenbuch_saldo(terminal_nr: int) -> int:
    """Aktueller Kassenbestand in Cent."""
    with get_db() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(BETRAG), 0) AS SALDO
               FROM XT_KASSE_KASSENBUCH WHERE TERMINAL_NR = %s""",
            (terminal_nr,)
        )
        row = cur.fetchone()
    return row['SALDO'] if row else 0


def kassenbuch_heute(terminal_nr: int) -> list:
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR = %s AND DATE(BUCHUNGSDATUM) = CURDATE()
               ORDER BY BUCHUNGSDATUM""",
            (terminal_nr,)
        )
        return cur.fetchall()


# ─────────────────────────────────────────────────────────────
# Tagesabschluss
# ─────────────────────────────────────────────────────────────

def tagesabschluss_erstellen(terminal_nr: int, mitarbeiter_id: int) -> dict:
    """
    Erstellt den Z-Bon für heute:
      1. Tagessummen berechnen
      2. TSE-Transaktion für Tagesabschluss
      3. Z-Bon in DB speichern
      4. Kassenbuch abschließen
    """
    import tse as tse_modul

    heute = date.today()
    with get_db() as cur:
        # Umsätze des Tages
        cur.execute(
            """SELECT
                 COUNT(DISTINCT v.ID) AS ANZAHL_BELEGE,
                 COALESCE(SUM(v.BETRAG_BRUTTO),0) AS UMSATZ_BRUTTO,
                 COALESCE(SUM(v.BETRAG_NETTO),0)  AS UMSATZ_NETTO,
                 COALESCE(SUM(v.MWST_BETRAG_1),0) AS MWST_1,
                 COALESCE(SUM(v.MWST_BETRAG_2),0) AS MWST_2,
                 COALESCE(SUM(v.MWST_BETRAG_3),0) AS MWST_3,
                 COALESCE(SUM(v.NETTO_BETRAG_1),0) AS NETTO_1,
                 COALESCE(SUM(v.NETTO_BETRAG_2),0) AS NETTO_2,
                 COALESCE(SUM(v.NETTO_BETRAG_3),0) AS NETTO_3
               FROM XT_KASSE_VORGAENGE v
               WHERE v.TERMINAL_NR = %s
                 AND DATE(v.BON_DATUM) = %s
                 AND v.STATUS = 'ABGESCHLOSSEN'
                 AND v.VORGANG_TYP = 'Beleg'
                 AND (v.STORNO_VON_ID IS NULL)""",
            (terminal_nr, heute)
        )
        umsatz = cur.fetchone()

        cur.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN z.ZAHLART='BAR' THEN z.BETRAG ELSE 0 END),0) AS BAR,
                 COALESCE(SUM(CASE WHEN z.ZAHLART='EC'  THEN z.BETRAG ELSE 0 END),0) AS EC,
                 COALESCE(SUM(CASE WHEN z.ZAHLART='KUNDENKONTO' THEN z.BETRAG ELSE 0 END),0) AS KK
               FROM XT_KASSE_ZAHLUNGEN z
               JOIN XT_KASSE_VORGAENGE v ON v.ID = z.VORGANG_ID
               WHERE v.TERMINAL_NR = %s AND DATE(v.BON_DATUM) = %s
                 AND v.STATUS = 'ABGESCHLOSSEN'""",
            (terminal_nr, heute)
        )
        zahlarten = cur.fetchone()

        cur.execute(
            """SELECT COUNT(*) AS ANZ, COALESCE(SUM(ABS(BETRAG_BRUTTO)),0) AS BET
               FROM XT_KASSE_VORGAENGE
               WHERE TERMINAL_NR = %s AND DATE(BON_DATUM) = %s
                 AND STATUS = 'STORNIERT'""",
            (terminal_nr, heute)
        )
        stornos = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(CASE WHEN TYP='EINLAGE' THEN BETRAG ELSE 0 END),0) AS EIN,
                      COALESCE(SUM(CASE WHEN TYP='ENTNAHME' THEN ABS(BETRAG) ELSE 0 END),0) AS ENT
               FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR = %s AND DATE(BUCHUNGSDATUM) = %s""",
            (terminal_nr, heute)
        )
        kb = cur.fetchone()

    kassenbestand_anfang = kassenbuch_saldo(terminal_nr) - \
        (umsatz['UMSATZ_BAR'] or 0) - (kb['EIN'] or 0) + (kb['ENT'] or 0)
    kassenbestand_ende   = kassenbuch_saldo(terminal_nr)

    # TSE Tagesabschluss
    tse_data = {}
    jetzt = datetime.now()

    with get_db_transaction() as cur:
        z_nr = naechste_z_nr(terminal_nr, cur)
        cur.execute(
            """INSERT INTO XT_KASSE_TAGESABSCHLUSS
               (TERMINAL_NR, DATUM, ZEITPUNKT, Z_NR, MITARBEITER_ID,
                ANZAHL_BELEGE, UMSATZ_BRUTTO, UMSATZ_NETTO,
                MWST_1, MWST_2, MWST_3, NETTO_1, NETTO_2, NETTO_3,
                UMSATZ_BAR, UMSATZ_EC, UMSATZ_KUNDENKONTO,
                KASSENBESTAND_ANFANG, EINLAGEN, ENTNAHMEN, KASSENBESTAND_ENDE,
                ANZAHL_STORNOS, BETRAG_STORNOS)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (terminal_nr, heute, jetzt, z_nr, mitarbeiter_id,
             umsatz['ANZAHL_BELEGE'], umsatz['UMSATZ_BRUTTO'], umsatz['UMSATZ_NETTO'],
             umsatz['MWST_1'], umsatz['MWST_2'], umsatz['MWST_3'],
             umsatz['NETTO_1'], umsatz['NETTO_2'], umsatz['NETTO_3'],
             zahlarten['BAR'], zahlarten['EC'], zahlarten['KK'],
             kassenbestand_anfang, kb['EIN'], kb['ENT'], kassenbestand_ende,
             stornos['ANZ'], stornos['BET'])
        )
        ta_id = cur.lastrowid

        # Kassenbuch-Abschlusszeile
        cur.execute(
            """INSERT INTO XT_KASSE_KASSENBUCH
               (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, TAGESABSCHLUSS_ID, MITARBEITER_ID)
               VALUES (%s, %s, 'TAGESABSCHLUSS', 0, %s, %s)""",
            (terminal_nr, jetzt, ta_id, mitarbeiter_id)
        )

    # TSE außerhalb der DB-Transaktion
    if tse_modul.tse_verfuegbar(terminal_nr):
        try:
            tse_data = tse_modul.tse_tagesabschluss(
                terminal_nr, ta_id, umsatz['UMSATZ_BRUTTO']
            )
            with get_db() as cur:
                cur.execute(
                    """UPDATE XT_KASSE_TAGESABSCHLUSS
                       SET TSE_TX_ID=%s, TSE_SIGNATUR=%s,
                           TSE_SIGNATUR_ZAEHLER=%s, TSE_SERIAL=%s
                       WHERE ID=%s""",
                    (tse_data.get('tx_id'), tse_data.get('signatur'),
                     tse_data.get('signatur_zaehler'), tse_data.get('tss_serial'),
                     ta_id)
                )
        except Exception as e:
            log.error("TSE Tagesabschluss fehlgeschlagen: %s", e)

    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TAGESABSCHLUSS WHERE ID = %s", (ta_id,))
        return cur.fetchone()


# ─────────────────────────────────────────────────────────────
# Bon → CAO-Lieferschein
# ─────────────────────────────────────────────────────────────

def vorgang_zu_lieferschein(vorgang_id: int, adressen_id: int,
                              erstellt_von: str) -> dict:
    """
    Wandelt einen abgeschlossenen Kassiervorgang in einen CAO-Lieferschein.
    Schreibt in LIEFERSCHEIN + LIEFERSCHEIN_POS (CAO-Tabellen).
    Gibt die Lieferscheinnummer zurück.
    """
    vorgang    = vorgang_laden(vorgang_id)
    positionen = vorgang_positionen(vorgang_id)
    mwst       = mwst_saetze_laden()

    if not vorgang:
        raise ValueError("Vorgang nicht gefunden.")

    # Adresse laden
    with get_db() as cur:
        cur.execute(
            """SELECT KUNNUM1, NAME1, NAME2, ANREDE, ABTEILUNG,
                      STRASSE, LAND, PLZ, ORT, BRUTTO_FLAG, PR_EBENE
               FROM ADRESSEN WHERE REC_ID = %s""",
            (adressen_id,)
        )
        adresse = cur.fetchone()
    if not adresse:
        raise ValueError("Adresse nicht gefunden.")

    # Nächste Lieferscheinnummer aus REGISTRY holen und erhöhen
    with get_db_transaction() as cur:
        cur.execute(
            r"SELECT VAL_INT2, VAL_INT3 FROM REGISTRY "
            r"WHERE MAINKEY='MAIN\NUMBERS' AND NAME='EDIT' FOR UPDATE"
        )
        reg = cur.fetchone()
        naechste_nr = ((reg['VAL_INT2'] or 0) + 1) if reg else 1
        ls_prefix = reg['VAL_INT3'] if reg else 0

        if reg:
            cur.execute(
                r"UPDATE REGISTRY SET VAL_INT2 = %s "
                r"WHERE MAINKEY='MAIN\NUMBERS' AND NAME='EDIT'",
                (naechste_nr,)
            )
        vlsnum = f"LS{naechste_nr:06d}"

        jetzt  = datetime.now()

        # MwSt-Summen je Steuersatz berechnen
        mwst_totals = {0: 0, 1: 0, 2: 0, 3: 0}
        nsumme_totals = {0: 0, 1: 0, 2: 0, 3: 0}
        bsumme_totals = {0: 0, 1: 0, 2: 0, 3: 0}
        for pos in positionen:
            if pos.get('STORNIERT'):
                continue
            code = pos['STEUER_CODE']
            if code in mwst_totals:
                mwst_totals[code]   += pos['MWST_BETRAG']
                nsumme_totals[code] += pos['NETTO_BETRAG']
                bsumme_totals[code] += pos['GESAMTPREIS_BRUTTO']

        cur.execute(
            """INSERT INTO LIEFERSCHEIN
               (VLSNUM, EDI_FLAG, STORNO_FLAG, ADDR_ID, PR_EBENE,
                ZAHLART, WERT_NETTO, WARE,
                MWST_1, MWST_2, MWST_3,
                NSUMME_1, NSUMME_2, NSUMME_3,
                BSUMME_1, BSUMME_2, BSUMME_3,
                NSUMME, MSUMME, BSUMME,
                WAEHRUNG, KURS,
                ERSTELLT, LDATUM, ERST_NAME,
                KUN_NUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2,
                KUN_ABTEILUNG, KUN_STRASSE, KUN_LAND, KUN_PLZ, KUN_ORT,
                BRUTTO_FLAG, INFO)
               VALUES (%s,0,0,%s,%s,
                       'BAR',%s,%s,
                       %s,%s,%s,
                       %s,%s,%s,
                       %s,%s,%s,
                       %s,%s,%s,
                       'EUR',1,
                       %s,%s,%s,
                       %s,%s,%s,%s,
                       %s,%s,%s,%s,%s,
                       1,%s)""",
            (vlsnum, adressen_id, adresse.get('PR_EBENE') or 1,
             vorgang['BETRAG_NETTO'], vorgang['BETRAG_NETTO'],
             mwst_totals[1], mwst_totals[2], mwst_totals[3],
             nsumme_totals[1], nsumme_totals[2], nsumme_totals[3],
             bsumme_totals[1], bsumme_totals[2], bsumme_totals[3],
             vorgang['BETRAG_NETTO'],
             vorgang['BETRAG_BRUTTO'] - vorgang['BETRAG_NETTO'],
             vorgang['BETRAG_BRUTTO'],
             jetzt, jetzt.date(), erstellt_von,
             adresse.get('KUNNUM1', ''), adresse.get('ANREDE', ''),
             adresse.get('NAME1', ''), adresse.get('NAME2', ''),
             adresse.get('ABTEILUNG', ''), adresse.get('STRASSE', ''),
             adresse.get('LAND', 'DE'), adresse.get('PLZ', ''), adresse.get('ORT', ''),
             f"Aus Kassenbeleg {vorgang['VORGANGSNUMMER']}")
        )
        ls_id = cur.lastrowid

        # Positionen
        for pos in positionen:
            if pos.get('STORNIERT'):
                continue
            ep_netto = pos['NETTO_BETRAG']
            gp_netto = pos['NETTO_BETRAG']
            cur.execute(
                """INSERT INTO LIEFERSCHEIN_POS
                   (LIEFERSCHEIN_ID, ARTIKELTYP, ARTIKEL_ID, VLSNUM, POSITION,
                    MATCHCODE, ARTNUM, BARCODE,
                    MENGE, ME_EINHEIT, VPE,
                    EK_PREIS, EPREIS, GPREIS, STEUER_CODE,
                    BEZEICHNUNG, GEBUCHT, BRUTTO_FLAG)
                   VALUES (%s,'A',%s,%s,%s,
                           %s,%s,%s,
                           %s,'Stk',1,
                           0,%s,%s,%s,
                           %s,0,1)""",
                (ls_id, pos['ARTIKEL_ID'], vlsnum, pos['POSITION'],
                 pos['BEZEICHNUNG'][:30], pos['ARTNUM'] or '', pos['BARCODE'] or '',
                 pos['MENGE'],
                 pos['EINZELPREIS_BRUTTO'] / 100.0,
                 pos['GESAMTPREIS_BRUTTO'] / 100.0,
                 pos['STEUER_CODE'],
                 pos['BEZEICHNUNG'])
            )

        # Zuordnung speichern
        cur.execute(
            """INSERT INTO XT_KASSE_LIEFERSCHEINE
               (VORGANG_ID, LIEFERSCHEIN_ID, VLSNUM)
               VALUES (%s, %s, %s)""",
            (vorgang_id, ls_id, vlsnum)
        )

    return {'lieferschein_id': ls_id, 'vlsnum': vlsnum}


# ─────────────────────────────────────────────────────────────
# X-Bon Daten
# ─────────────────────────────────────────────────────────────

def xbon_daten(terminal_nr: int) -> dict:
    """Sammelt Zwischenabschluss-Daten ohne Nullstellung."""
    heute = date.today()
    with get_db() as cur:
        cur.execute(
            """SELECT
                 COUNT(DISTINCT v.ID) AS ANZAHL_BELEGE,
                 COALESCE(SUM(v.BETRAG_BRUTTO),0) AS UMSATZ_BRUTTO,
                 COALESCE(SUM(v.BETRAG_NETTO),0)  AS UMSATZ_NETTO,
                 COALESCE(SUM(v.MWST_BETRAG_1),0) AS MWST_1,
                 COALESCE(SUM(v.MWST_BETRAG_2),0) AS MWST_2,
                 COALESCE(SUM(v.MWST_BETRAG_3),0) AS MWST_3,
                 COALESCE(SUM(v.NETTO_BETRAG_1),0) AS NETTO_1,
                 COALESCE(SUM(v.NETTO_BETRAG_2),0) AS NETTO_2,
                 COALESCE(SUM(v.NETTO_BETRAG_3),0) AS NETTO_3
               FROM XT_KASSE_VORGAENGE v
               WHERE v.TERMINAL_NR = %s AND DATE(v.BON_DATUM) = %s
                 AND v.STATUS = 'ABGESCHLOSSEN'""",
            (terminal_nr, heute)
        )
        umsatz = cur.fetchone()

        cur.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN z.ZAHLART='BAR' THEN z.BETRAG ELSE 0 END),0) AS BAR,
                 COALESCE(SUM(CASE WHEN z.ZAHLART='EC'  THEN z.BETRAG ELSE 0 END),0) AS EC,
                 COALESCE(SUM(CASE WHEN z.ZAHLART='KUNDENKONTO' THEN z.BETRAG ELSE 0 END),0) AS KK
               FROM XT_KASSE_ZAHLUNGEN z
               JOIN XT_KASSE_VORGAENGE v ON v.ID = z.VORGANG_ID
               WHERE v.TERMINAL_NR = %s AND DATE(v.BON_DATUM) = %s
                 AND v.STATUS = 'ABGESCHLOSSEN'""",
            (terminal_nr, heute)
        )
        zahlarten = cur.fetchone()

        cur.execute(
            """SELECT COUNT(*) AS ANZ, COALESCE(SUM(ABS(BETRAG_BRUTTO)),0) AS BET
               FROM XT_KASSE_VORGAENGE
               WHERE TERMINAL_NR = %s AND DATE(BON_DATUM) = %s AND STATUS='STORNIERT'""",
            (terminal_nr, heute)
        )
        stornos = cur.fetchone()

        cur.execute(
            """SELECT COALESCE(SUM(CASE WHEN TYP='EINLAGE' THEN BETRAG ELSE 0 END),0) AS EIN,
                      COALESCE(SUM(CASE WHEN TYP='ENTNAHME' THEN ABS(BETRAG) ELSE 0 END),0) AS ENT
               FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR = %s AND DATE(BUCHUNGSDATUM) = %s""",
            (terminal_nr, heute)
        )
        kb = cur.fetchone()

    saldo = kassenbuch_saldo(terminal_nr)
    anfang = saldo - (zahlarten['BAR'] or 0) - (kb['EIN'] or 0) + (kb['ENT'] or 0)

    return {
        'anzahl_belege':        umsatz['ANZAHL_BELEGE'],
        'umsatz_brutto':        umsatz['UMSATZ_BRUTTO'],
        'umsatz_netto':         umsatz['UMSATZ_NETTO'],
        'mwst_1':               umsatz['MWST_1'],
        'mwst_2':               umsatz['MWST_2'],
        'mwst_3':               umsatz['MWST_3'],
        'netto_1':              umsatz['NETTO_1'],
        'netto_2':              umsatz['NETTO_2'],
        'netto_3':              umsatz['NETTO_3'],
        'umsatz_bar':           zahlarten['BAR'],
        'umsatz_ec':            zahlarten['EC'],
        'umsatz_kundenkonto':   zahlarten['KK'],
        'umsatz_sonstige':      0,
        'anzahl_stornos':       stornos['ANZ'],
        'betrag_stornos':       stornos['BET'],
        'kassenbestand_anfang': anfang,
        'einlagen':             kb['EIN'],
        'entnahmen':            kb['ENT'],
        'kassenbestand_ende':   saldo,
    }
