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
import time
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

_VK_COLS = 'VK1B, VK2B, VK3B, VK4B, VK5B'


def artikel_suchen(suchtext: str, limit: int = 30) -> list:
    """Suche in ARTNUM, BARCODE, KURZNAME, MATCHCODE."""
    pat = f"%{suchtext.strip()}%"
    with get_db() as cur:
        cur.execute(
            f"""SELECT REC_ID, ARTNUM, BARCODE, KURZNAME, MATCHCODE,
                      {_VK_COLS}, STEUER_CODE, ARTIKELTYP
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
            f"""SELECT REC_ID, ARTNUM, BARCODE, KURZNAME, MATCHCODE,
                      {_VK_COLS}, STEUER_CODE, ARTIKELTYP
               FROM ARTIKEL WHERE BARCODE = %s LIMIT 1""",
            (barcode,)
        )
        row = cur.fetchone()
    return _artikel_aufbereiten(row) if row else None


# ─────────────────────────────────────────────────────────────
# Sonder-EAN (Zeitschriften, Inhouse Preis-/Gewichts-EAN)
# ─────────────────────────────────────────────────────────────

def _ean13_pruefen(ean: str) -> bool:
    """Prüft die EAN-13-Prüfziffer (Stelle 13)."""
    if len(ean) != 13 or not ean.isdigit():
        return False
    summe = sum(int(z) * (3 if i % 2 == 1 else 1) for i, z in enumerate(ean[:12]))
    return (10 - summe % 10) % 10 == int(ean[12])


def _inhouse_artikelteil_pruefen(ean: str) -> bool:
    """
    Prüft die interne Artikelteil-Prüfziffer (Stellen 1–6 → Stelle 7).
    Inhouse-Format: XX AAAA Z PPPPP Z
                    ------          ← diese 6 Stellen → Prüfziffer an Position 7
    """
    if len(ean) < 7 or not ean[:7].isdigit():
        return False
    summe = sum(int(z) * (3 if i % 2 == 1 else 1) for i, z in enumerate(ean[:6]))
    return (10 - summe % 10) % 10 == int(ean[6])


_ean_regeln_cache: list[dict] | None = None
_ean_regeln_cache_ts: float = 0.0
_EAN_CACHE_TTL = 60.0   # Sekunden; nach Migration automatisch neu eingelesen

# WG-Spaltename in ARTIKEL (einmalig per DESCRIBE ermittelt, dann gecacht)
_artikel_wg_col: str | None = None
_artikel_wg_col_detected: bool = False

# WARENGRUPPEN-Schema (einmalig per DESCRIBE ermittelt, dann gecacht)
_wg_schema_cache: dict | None = None


def ean_regeln_cache_loeschen():
    """Leert den EAN-Regeln-Cache (nach Änderungen sofort wirksam)."""
    global _ean_regeln_cache, _ean_regeln_cache_ts
    _ean_regeln_cache = None
    _ean_regeln_cache_ts = 0.0


def _ean_regeln_laden() -> list[dict]:
    """
    Lädt alle aktiven EAN-Regeln, längste Präfixe zuerst.
    Ergebnis wird 60 s gecacht – bei fehlender Tabelle wird leere Liste gecacht
    (verhindert wiederholte DB-Verbindungen die den Pool belasten).
    """
    global _ean_regeln_cache, _ean_regeln_cache_ts
    if _ean_regeln_cache is not None and time.time() - _ean_regeln_cache_ts < _EAN_CACHE_TTL:
        return _ean_regeln_cache
    try:
        with get_db() as cur:
            cur.execute(
                """SELECT REC_ID, EAN_PRAEFIX, TYP, ARTIKEL_LOOKUP,
                          BEZEICHNUNG, WG_ID, ARTIKEL_ID, STEUER_CODE, PREIS_PRO_KG
                   FROM XT_KASSE_EAN_REGELN
                   WHERE AKTIV = 1
                   ORDER BY LENGTH(EAN_PRAEFIX) DESC, EAN_PRAEFIX"""
            )
            result = cur.fetchall() or []
    except Exception as e:
        log.warning('EAN-Regeln nicht ladbar (Migration noch nicht ausgeführt?): %s', e)
        result = []
    _ean_regeln_cache = result
    _ean_regeln_cache_ts = time.time()
    return result


def _artikel_wg_spalte() -> str | None:
    """
    Ermittelt einmalig den Namen der WG-Spalte in ARTIKEL per DESCRIBE.
    CAO verwendet je nach Version WG_ID, WGID oder WARENGRUPPE_ID.
    Ergebnis wird dauerhaft gecacht (ändert sich nicht zur Laufzeit).
    """
    global _artikel_wg_col, _artikel_wg_col_detected
    if _artikel_wg_col_detected:
        return _artikel_wg_col
    try:
        with get_db() as cur:
            cur.execute('DESCRIBE ARTIKEL')
            spalten = {r['Field'] for r in cur.fetchall()}
        _artikel_wg_col = _erste_spalte(
            spalten, ['WG_ID', 'WGID', 'WARENGRUPPE_ID', 'WARENGRUPPE'], None
        )
    except Exception as e:
        log.warning('DESCRIBE ARTIKEL fehlgeschlagen: %s', e)
        _artikel_wg_col = None
    _artikel_wg_col_detected = True
    return _artikel_wg_col


def _wg_schema() -> dict:
    """
    Ermittelt einmalig das Schema der WARENGRUPPEN-Tabelle per DESCRIBE.
    Ergebnis wird dauerhaft gecacht (ändert sich nicht zur Laufzeit).
    Gibt {id_col, name_col, top_col, sort_col, order} zurück.
    """
    global _wg_schema_cache
    if _wg_schema_cache is not None:
        return _wg_schema_cache
    try:
        with get_db() as cur:
            cur.execute('DESCRIBE WARENGRUPPEN')
            spalten = {r['Field'] for r in cur.fetchall()}
    except Exception as e:
        log.warning('DESCRIBE WARENGRUPPEN fehlgeschlagen: %s', e)
        spalten = set()
    id_col   = _erste_spalte(spalten, ['REC_ID', 'WG_ID', 'ID'], 'REC_ID')
    name_col = _erste_spalte(spalten, ['BEZEICHNUNG', 'NAME', 'KURZNAME', 'WGNAME'], None)
    top_col  = _erste_spalte(spalten, ['TOP_ID', 'PARENT_ID', 'PARENT', 'OBERGRUPPE_ID'], None)
    sort_col = _erste_spalte(spalten, ['SORT', 'SORTIERUNG', 'REIHENFOLGE'], None)
    order    = (f"{sort_col}, {name_col}" if sort_col and name_col
                else name_col or sort_col or id_col)
    _wg_schema_cache = {
        'id_col': id_col, 'name_col': name_col,
        'top_col': top_col, 'sort_col': sort_col, 'order': order,
    }
    return _wg_schema_cache


def _artikel_aus_ean(ean: str) -> dict | None:
    """
    Schlägt den CAO-Artikel anhand der in der Inhouse-EAN enthaltenen ARTNUM nach.
    Format: XX AAAA Z ...  → AAAA = ean[2:6]
    Gibt {artikel_id, bezeichnung, steuer_code, mwst_satz, wg_id} zurück oder None.
    Die WG-ID wird direkt aus dem Artikelstamm gelesen (kein Fallback auf Regel nötig).
    """
    artnum = ean[2:6]
    wg_col = _artikel_wg_spalte()
    select_wg = f', {wg_col}' if wg_col else ''
    try:
        with get_db() as cur:
            cur.execute(
                f"""SELECT REC_ID, KURZNAME, STEUER_CODE{select_wg}
                   FROM ARTIKEL WHERE ARTNUM = %s LIMIT 1""",
                (artnum,)
            )
            row = cur.fetchone()
        if not row:
            return None
        steuer = int(row.get('STEUER_CODE') or 1)
        wg_id  = row.get(wg_col) if wg_col else None
        return {
            'artikel_id':    row['REC_ID'],
            'bezeichnung':   row['KURZNAME'] or f'Art. {artnum}',
            'steuer_code':   steuer,
            'mwst_satz':     mwst_satz_fuer_code(steuer),
            'wg_id':         int(wg_id) if wg_id else None,
            'preis_pro_kg':  euro_zu_cent(row.get('VK5B') or 0) or None,
        }
    except Exception as e:
        log.warning('Artikel-Lookup für ARTNUM %s fehlgeschlagen: %s', artnum, e)
        return None


def ean_sonder_erkennen(barcode: str) -> dict | None:
    """
    Erkennt und dekodiert Sonder-EAN-Codes anhand der XT_KASSE_EAN_REGELN.

    Inhouse-Format (13-stellig):  XX AAAA Z PPPPP Z
      XX    = Bereichs-ID  (EAN_PRAEFIX)
      AAAA  = 4-stellige CAO-ARTNUM  (Stellen 3–6, 0-basiert: [2:6])
      Z     = interne Artikelteil-Prüfziffer (Stelle 7)
      PPPPP = 5-stelliger Wert [7:12]: Preis in Cent (TYP=PREIS) oder Gramm (TYP=GEWICHT)
      Z     = EAN-13-Prüfziffer

    Presse-EAN / VDZ-Format (TYP=PRESSE):
      KKK VVVVV PPPP C  (13 Stellen Basis + optionales 2–5-stelliges Add-on)
      KKK   = 3-stellige Kennung: 419 = 7% MwSt, 414 = 19% MwSt
      VVVVV = VDZ-Objektnummer  [3:8]
      PPPP  = Preis in Cent      [8:12]  z.B. 0950 = 9,50 EUR
      C     = EAN-13-Prüfziffer  [12]
      Scanner liefert ggf. 15–18 Stellen (Basis + Add-on für Ausgabennummer).

    Zeitschriften-EAN (z.B. 977xxx): Preis-Dialog, kein Artikel-Lookup.

    Rückgabe-Dict (sonder_ean=True):
      ean_typ, bezeichnung, steuer_code, mwst_satz, wg_id, artikel_id,
      preis_cent (None = Dialog), preis_dialog, gewicht_g
    """
    if not barcode.isdigit() or len(barcode) < 2:
        return None

    # 13-stellige EAN: Prüfziffer validieren (nicht für längere Presse-Codes mit Add-on)
    if len(barcode) == 13 and not _ean13_pruefen(barcode):
        return None

    for regel in _ean_regeln_laden():
        if not barcode.startswith(regel['EAN_PRAEFIX']):
            continue

        typ            = regel['TYP']
        artikel_lookup = int(regel.get('ARTIKEL_LOOKUP') or 0)

        # ── Presse-EAN (VDZ): Preis in EAN[8:12], opt. Add-on-Suffix ────
        if typ == 'PRESSE':
            # Basis = erste 13 Stellen; Add-on (Stellen 14–18) wird ignoriert
            basis = barcode[:13]
            if len(basis) != 13:
                continue
            if not _ean13_pruefen(basis):
                log.warning('Presse-EAN Prüfziffer ungültig: %s', barcode)
                continue
            try:
                preis_cent = int(basis[8:12])
            except ValueError:
                continue
            if not preis_cent:
                log.warning('Presse-EAN Preis = 0: %s', barcode)
                continue
            steuer_code = int(regel['STEUER_CODE'] or 1)
            return {
                'sonder_ean':   True,
                'ean_typ':      'presse',
                'bezeichnung':  regel['BEZEICHNUNG'],
                'steuer_code':  steuer_code,
                'mwst_satz':    mwst_satz_fuer_code(steuer_code),
                'wg_id':        regel.get('WG_ID'),
                'artikel_id':   None,
                'preis_cent':   preis_cent,
                'preis_dialog': False,
                'gewicht_g':    None,
            }

        # ── Zeitschrift: Preis-Dialog, direkte Fallback-Daten ────────
        if typ == 'ZEITSCHRIFT':
            return {
                'sonder_ean':   True,
                'ean_typ':      'zeitschrift',
                'bezeichnung':  regel['BEZEICHNUNG'],
                'steuer_code':  int(regel['STEUER_CODE'] or 1),
                'mwst_satz':    mwst_satz_fuer_code(int(regel['STEUER_CODE'] or 1)),
                'wg_id':        regel.get('WG_ID'),
                'artikel_id':   regel.get('ARTIKEL_ID'),
                'preis_cent':   None,
                'preis_dialog': True,
                'gewicht_g':    None,
            }

        # ── Preis- / Gewichts-EAN: 13-stellig + Artikelteil-Prüfziffer ─
        if len(barcode) != 13:
            log.warning('Inhouse-EAN muss 13-stellig sein: %s', barcode)
            continue

        if not _inhouse_artikelteil_pruefen(barcode):
            log.warning('Inhouse-EAN Artikelteil-Prüfziffer ungültig: %s', barcode)
            continue

        # Wert aus Stellen 8–12 (0-basiert [7:12])
        try:
            wert = int(barcode[7:12])
        except ValueError:
            continue

        # Artikel nachschlagen (Name + Steuer aus ARTIKEL-Tabelle)
        art = _artikel_aus_ean(barcode) if artikel_lookup else None
        bezeichnung = (art and art['bezeichnung']) or regel['BEZEICHNUNG']
        steuer_code = (art and art['steuer_code']) or int(regel['STEUER_CODE'] or 1)
        mwst        = (art and art['mwst_satz'])   or mwst_satz_fuer_code(steuer_code)
        wg_id       = (art and art['wg_id'])       or regel.get('WG_ID')
        artikel_id  = (art and art['artikel_id'])  or regel.get('ARTIKEL_ID')

        if typ == 'PREIS':
            return {
                'sonder_ean':   True,
                'ean_typ':      'preis',
                'bezeichnung':  bezeichnung,
                'steuer_code':  steuer_code,
                'mwst_satz':    mwst,
                'wg_id':        wg_id,
                'artikel_id':   artikel_id,
                'preis_cent':   wert,       # 5-stellig in Cent: 02560 = 25,60 EUR
                'preis_dialog': False,
                'gewicht_g':    None,
            }

        if typ == 'GEWICHT':
            # Preis/kg: Artikel (VK5B) hat Vorrang vor der Regel (PREIS_PRO_KG als Fallback)
            ppkg = (art and art.get('preis_pro_kg')) or int(regel.get('PREIS_PRO_KG') or 0)
            if not ppkg:
                log.warning('Gewichts-EAN ohne Preis/kg (weder VK5B noch PREIS_PRO_KG): %s', barcode)
                continue
            return {
                'sonder_ean':   True,
                'ean_typ':      'gewicht',
                'bezeichnung':  bezeichnung,
                'steuer_code':  steuer_code,
                'mwst_satz':    mwst,
                'wg_id':        wg_id,
                'artikel_id':   artikel_id,
                'preis_cent':   round(wert * ppkg / 1000),
                'preis_dialog': False,
                'gewicht_g':    wert,
            }

    return None


def ean_regeln_liste() -> list[dict]:
    """Gibt alle EAN-Regeln zurück (für Admin-Ansicht)."""
    try:
        with get_db() as cur:
            cur.execute(
                """SELECT REC_ID, EAN_PRAEFIX, TYP, ARTIKEL_LOOKUP, BEZEICHNUNG,
                          WG_ID, ARTIKEL_ID, STEUER_CODE, PREIS_PRO_KG, AKTIV
                   FROM XT_KASSE_EAN_REGELN ORDER BY EAN_PRAEFIX"""
            )
            return cur.fetchall() or []
    except Exception as e:
        log.warning('EAN-Regeln-Liste fehlgeschlagen: %s', e)
        return []


def ean_regel_speichern(praefix: str, typ: str, bezeichnung: str,
                         artikel_lookup: bool,
                         wg_id: int | None, artikel_id: int | None,
                         steuer_code: int, preis_pro_kg: int | None) -> int:
    """Legt eine EAN-Regel an oder aktualisiert die bestehende (per PRAEFIX, UPSERT)."""
    al = 1 if artikel_lookup else 0
    with get_db_transaction() as cur:
        cur.execute(
            """INSERT INTO XT_KASSE_EAN_REGELN
               (EAN_PRAEFIX, TYP, ARTIKEL_LOOKUP, BEZEICHNUNG,
                WG_ID, ARTIKEL_ID, STEUER_CODE, PREIS_PRO_KG, AKTIV)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
               ON DUPLICATE KEY UPDATE
                 TYP=%s, ARTIKEL_LOOKUP=%s, BEZEICHNUNG=%s,
                 WG_ID=%s, ARTIKEL_ID=%s, STEUER_CODE=%s, PREIS_PRO_KG=%s, AKTIV=1""",
            (praefix, typ, al, bezeichnung, wg_id, artikel_id, steuer_code, preis_pro_kg,
             typ, al, bezeichnung, wg_id, artikel_id, steuer_code, preis_pro_kg)
        )
        rid = cur.lastrowid
    ean_regeln_cache_loeschen()
    return rid


def ean_regel_loeschen(rec_id: int):
    """Löscht eine EAN-Regel."""
    with get_db_transaction() as cur:
        cur.execute("DELETE FROM XT_KASSE_EAN_REGELN WHERE REC_ID = %s", (rec_id,))
    ean_regeln_cache_loeschen()


def _artikel_aufbereiten(row: dict) -> dict:
    # Alle VK-Preisebenen 1-5 einlesen; Fallback auf VK5B wenn Ebene = 0
    vk_preise = {}
    for i in range(1, 6):
        vk_preise[i] = euro_zu_cent(row.get(f'VK{i}B') or 0)
    preis_cent  = vk_preise[5]  # Standard = Barverkauf (Ebene 5)
    steuer_code = row.get('STEUER_CODE') or 1
    netto, mwst = mwst_berechnen(preis_cent, steuer_code)
    # KAS_NAME bevorzugen (falls im Row vorhanden), sonst KURZNAME
    bezeichnung = (row.get('KAS_NAME') or '').strip() or row.get('KURZNAME', '')
    result = {
        'id':          row['REC_ID'],
        'artnum':      row.get('ARTNUM', ''),
        'barcode':     row.get('BARCODE', ''),
        'bezeichnung': bezeichnung,
        'matchcode':   row.get('MATCHCODE', ''),
        'preis_cent':  preis_cent,
        'vk_preise':   vk_preise,
        'netto_cent':  netto,
        'mwst_cent':   mwst,
        'steuer_code': steuer_code,
        'mwst_satz':   mwst_satz_fuer_code(steuer_code),
    }
    # ── Erweiterte Felder (nur wenn vom Browser-Query mitgeliefert) ──
    if 'USERFELD_04'   in row: result['plu']              = row.get('USERFELD_04') or ''
    if 'USERFELD_05'   in row: result['plu2']             = row.get('USERFELD_05') or ''
    if 'ARTIKELTYP'    in row: result['artikeltyp']       = row.get('ARTIKELTYP') or 'N'
    if 'MENGE_AKT'     in row: result['bestand']          = float(row['MENGE_AKT']) if row.get('MENGE_AKT') is not None else None
    if 'ME_BEZEICHNUNG'in row: result['me']               = row.get('ME_BEZEICHNUNG') or ''
    if 'NO_EK_FLAG'    in row: result['ek_sperre']        = row.get('NO_EK_FLAG') == 'Y'
    if 'NO_VK_FLAG'    in row: result['vk_sperre']        = row.get('NO_VK_FLAG') == 'Y'
    if 'FSK18_FLAG'    in row: result['fsk18']            = row.get('FSK18_FLAG') == 'Y'
    if 'AKTIONSPREIS'  in row: result['aktionspreis_cent']= euro_zu_cent(row['AKTIONSPREIS']) if row.get('AKTIONSPREIS') else None
    return result


# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# Schnelltasten (ARTIKEL_SCHNELLZUGRIFF read-only)
# Optimiert: Batch-Queries + Server-Cache (5 min TTL)
# ─────────────────────────────────────────────────────────────

_schnell_cache: list | None = None
_schnell_cache_ts: float = 0.0
_SCHNELL_TTL = 300  # Sekunden


def schnelltasten_laden() -> list:
    """Gibt gecachte Schnelltasten zurück, lädt nur bei abgelaufenem Cache neu."""
    global _schnell_cache, _schnell_cache_ts
    if _schnell_cache is not None and (time.time() - _schnell_cache_ts) < _SCHNELL_TTL:
        return _schnell_cache
    t0 = time.time()
    result = _schnelltasten_laden_uncached()
    log.debug('Schnelltasten geladen: %d Einträge in %.2f s', len(result), time.time() - t0)
    _schnell_cache = result
    _schnell_cache_ts = time.time()
    return result


def schnelltasten_cache_invalidieren():
    global _schnell_cache
    _schnell_cache = None
    log.info('Schnelltasten-Cache invalidiert')


def _schnelltasten_laden_uncached() -> list:
    """
    Liest ARTIKEL_SCHNELLZUGRIFF und lädt Artikel/WG-Details per Batch-Query
    (3 DB-Abfragen insgesamt, unabhängig von der Anzahl der Tasten).
    """
    # ── 1. Haupttabelle einlesen ──────────────────────────────
    with get_db() as cur:
        cur.execute("DESCRIBE ARTIKEL_SCHNELLZUGRIFF")
        spalten = {r['Field'] for r in cur.fetchall()}

        pos_col       = _erste_spalte(spalten, ['SORT','POS','POSITION','REIHE','NR','TASTE_NR'], 'REC_ID')
        name_col      = _erste_spalte(spalten, ['BEZEICHNUNG','NAME','KURZNAME'], None)
        farbe_col     = _erste_spalte(spalten, ['FARBE','FARBE_BG','COLOR'], None)
        schrift_col   = _erste_spalte(spalten, ['FARBE_SCHRIFT','SCHRIFTFARBE','COLOR_TEXT','FONT_COLOR','FONT_FARBE'], None)
        seite_col     = _erste_spalte(spalten, ['SEITE','EBENE','TAB'], None)
        kategorie_col = _erste_spalte(spalten, ['KATEGORIE_NAME','KATEGORIE','CATEGORY','GRUPPE','GRUPPENNAME'], None)
        artnr_col     = _erste_spalte(spalten, ['ARTIKEL_ID'], None)
        wg_id_col     = _erste_spalte(spalten, ['WG_ID','WGID','WARENGRUPPE_ID','WARENGRUPPE'], None)

        select = list({'REC_ID', pos_col})
        for col in (name_col, farbe_col, schrift_col, seite_col,
                    kategorie_col, artnr_col, wg_id_col):
            if col:
                select.append(col)

        cur.execute(
            f"SELECT {', '.join(set(select))} FROM ARTIKEL_SCHNELLZUGRIFF ORDER BY {pos_col}"
        )
        rows = cur.fetchall()

    # ── 2. Artikel- und WG-Referenzen sammeln ─────────────────
    ids_num  = []   # ARTIKEL.REC_ID (int)
    ids_text = []   # ARTIKEL.ARTNUM (str)
    wg_ids   = []   # WARENGRUPPEN.REC_ID

    for row in rows:
        art_ref = str(row.get(artnr_col) or '').strip() if artnr_col else ''
        wg_ref  = row.get(wg_id_col) if wg_id_col else None
        # Positive Ganzzahl → Artikel-REC_ID; Text → ARTNUM; ≤0 → Warengruppe
        try:
            art_id_int = int(art_ref) if art_ref else 0
        except ValueError:
            art_id_int = None  # ARTNUM-String
        if art_id_int is None:
            ids_text.append(art_ref)
        elif art_id_int > 0:
            ids_num.append(art_id_int)
        elif wg_ref:
            wg_ids.append(wg_ref)

    # ── 3. Batch-Query: Artikel nach REC_ID ───────────────────
    artikel_by_id: dict = {}
    if ids_num:
        ph = ','.join(['%s'] * len(ids_num))
        with get_db() as cur:
            cur.execute(
                f"SELECT REC_ID, ARTNUM, BARCODE, KURZNAME, {_VK_COLS}, STEUER_CODE "
                f"FROM ARTIKEL WHERE REC_ID IN ({ph})",
                ids_num
            )
            for a in cur.fetchall():
                artikel_by_id[a['REC_ID']] = a

    # ── 4. Batch-Query: Artikel nach ARTNUM ───────────────────
    artikel_by_artnum: dict = {}
    if ids_text:
        ph = ','.join(['%s'] * len(ids_text))
        with get_db() as cur:
            cur.execute(
                f"SELECT REC_ID, ARTNUM, BARCODE, KURZNAME, {_VK_COLS}, STEUER_CODE "
                f"FROM ARTIKEL WHERE ARTNUM IN ({ph})",
                ids_text
            )
            for a in cur.fetchall():
                artikel_by_artnum[a['ARTNUM']] = a

    # ── 5. Batch-Query: Warengruppen ──────────────────────────
    wg_by_id: dict = {}
    if wg_ids:
        wg_unique = list(set(wg_ids))
        try:
            with get_db() as cur:
                cur.execute("DESCRIBE WARENGRUPPEN")
                ws = {r['Field'] for r in cur.fetchall()}
                wg_id_db  = _erste_spalte(ws, ['REC_ID','WG_ID','ID'], 'REC_ID')
                wg_name   = _erste_spalte(ws, ['BEZEICHNUNG','NAME','KURZNAME','WGNAME'], None)
                wg_stcol  = _erste_spalte(ws, ['STEUER_CODE','STEUERSATZ_CODE','MWST_CODE'], None)
                wg_felder = list({wg_id_db, *([wg_name] if wg_name else []),
                                             *([wg_stcol] if wg_stcol else [])})
                ph = ','.join(['%s'] * len(wg_unique))
                cur.execute(
                    f"SELECT {', '.join(wg_felder)} FROM WARENGRUPPEN "
                    f"WHERE {wg_id_db} IN ({ph})",
                    wg_unique
                )
                for r in cur.fetchall():
                    wid = r.get(wg_id_db)
                    sc  = int(r.get(wg_stcol) or 1) if wg_stcol else 1
                    wg_by_id[wid] = {
                        'wg_id':       wid,
                        'bezeichnung': r.get(wg_name, f'WG {wid}') if wg_name else f'WG {wid}',
                        'steuer_code': sc,
                        'mwst_satz':   mwst_satz_fuer_code(sc),
                    }
        except Exception as e:
            log.warning('Warengruppen Batch-Laden fehlgeschlagen: %s', e)

    # ── 6. Ergebnis zusammenbauen ─────────────────────────────
    result = []
    for row in rows:
        art_ref = str(row.get(artnr_col) or '').strip() if artnr_col else ''
        wg_ref  = row.get(wg_id_col) if wg_id_col else None

        eintrag = {
            'rec_id':         row.get('REC_ID'),
            'position':       row.get(pos_col) or row.get('REC_ID'),
            'farbe':          _cao_farbe_zu_css(row.get(farbe_col))   if farbe_col   else None,
            'schriftfarbe':   _cao_farbe_zu_css(row.get(schrift_col)) if schrift_col else None,
            'seite':          row.get(seite_col) or 1 if seite_col else 1,
            'kategorie_name': row.get(kategorie_col) if kategorie_col else None,
        }

        try:
            art_id_val = int(art_ref) if art_ref else 0
        except ValueError:
            art_id_val = None
        if (art_id_val is not None and art_id_val <= 0) and wg_ref:
            # Warengruppe
            wg = wg_by_id.get(wg_ref)
            if wg:
                eintrag.update({
                    'ist_warengruppe': True,
                    'wg_id':           wg['wg_id'],
                    'bezeichnung':     (row.get(name_col) or wg['bezeichnung']) if name_col else wg['bezeichnung'],
                    'steuer_code':     wg['steuer_code'],
                    'mwst_satz':       wg['mwst_satz'],
                })
            result.append(eintrag)
            continue

        if art_ref and art_ref != '0':
            art = (artikel_by_id.get(int(art_ref)) if art_ref.isdigit()
                   else artikel_by_artnum.get(art_ref))
            if art:
                a = _artikel_aufbereiten(art)
                eintrag.update({
                    'artikel_id':  a['id'],
                    'artnum':      a['artnum'],
                    'bezeichnung': (row.get(name_col) or a['bezeichnung']) if name_col else a['bezeichnung'],
                    'preis_cent':  a['preis_cent'],
                    'steuer_code': a['steuer_code'],
                    'mwst_satz':   a['mwst_satz'],
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


def _cao_farbe_zu_css(farbe) -> str | None:
    """
    Konvertiert CAO-Farbzahl (Windows COLORREF: R | G<<8 | B<<16) zu CSS #rrggbb.
    z.B. 39372 → R=204, G=153, B=0 → '#cc9900'
    """
    if not farbe:
        return None
    try:
        n = int(farbe)
        r = n & 0xFF
        g = (n >> 8) & 0xFF
        b = (n >> 16) & 0xFF
        return f'#{r:02x}{g:02x}{b:02x}'
    except (ValueError, TypeError):
        s = str(farbe).strip()
        return s if s.startswith('#') else None


def _warengruppe_laden(wg_id) -> dict | None:
    """Lädt eine Warengruppe aus WARENGRUPPEN und gibt bezeichnung + steuer_code zurück."""
    try:
        with get_db() as cur:
            cur.execute("DESCRIBE WARENGRUPPEN")
            spalten = {r['Field'] for r in cur.fetchall()}
            id_col   = _erste_spalte(spalten, ['REC_ID', 'WG_ID', 'ID'], 'REC_ID')
            name_col = _erste_spalte(spalten, ['BEZEICHNUNG', 'NAME', 'KURZNAME', 'WGNAME'], None)
            st_col   = _erste_spalte(spalten, ['STEUER_CODE', 'STEUERSATZ_CODE', 'MWST_CODE'], None)
            felder   = list({id_col, *(([name_col] if name_col else []) + ([st_col] if st_col else []))})
            cur.execute(
                f"SELECT {', '.join(felder)} FROM WARENGRUPPEN WHERE {id_col} = %s LIMIT 1",
                (wg_id,)
            )
            row = cur.fetchone()
        if not row:
            return None
        steuer_code = int(row.get(st_col) or 1) if st_col else 1
        return {
            'wg_id':       wg_id,
            'bezeichnung': row.get(name_col, f'WG {wg_id}') if name_col else f'WG {wg_id}',
            'steuer_code': steuer_code,
            'mwst_satz':   mwst_satz_fuer_code(steuer_code),
        }
    except Exception as e:
        log.warning('Warengruppe %s nicht ladbar: %s', wg_id, e)
        return None


def warengruppen_alle_laden() -> list:
    """
    Gibt alle Warengruppen mit parent_id und direkter Artikelanzahl.
    parent_id=None bedeutet Wurzel-Knoten (TOP_ID=-1 oder ungültige TOP_ID).
    Sortierung: SORT (falls vorhanden) dann NAME.
    """
    try:
        s = _wg_schema()
        id_col, name_col, top_col, sort_col = (
            s['id_col'], s['name_col'], s['top_col'], s['sort_col']
        )
        with get_db() as cur:
            felder = list({id_col,
                           *([name_col]  if name_col  else []),
                           *([top_col]   if top_col   else []),
                           *([sort_col]  if sort_col  else [])})
            cur.execute(f"SELECT {', '.join(felder)} FROM WARENGRUPPEN ORDER BY {s['order']}")
            rows = cur.fetchall()

            # Direkte Artikelanzahl pro WG (alle Typen, keine Einschränkung)
            wg_art_col = _artikel_wg_spalte()
            anzahl_by_wg: dict = {}
            if wg_art_col:
                cur.execute(
                    f"SELECT {wg_art_col}, COUNT(*) as N FROM ARTIKEL GROUP BY {wg_art_col}"
                )
                for r2 in cur.fetchall():
                    wg_key = r2.get(wg_art_col)
                    if wg_key is not None:
                        anzahl_by_wg[int(wg_key)] = r2['N']

        alle_ids = {r[id_col] for r in rows}
        result = []
        for r in rows:
            raw_top = r.get(top_col) if top_col else None
            parent_id = int(raw_top) if (raw_top is not None
                                         and int(raw_top) in alle_ids
                                         and int(raw_top) != r[id_col]) else None
            result.append({
                'id':             r[id_col],
                'bezeichnung':    (r.get(name_col) or f'WG {r[id_col]}') if name_col else f'WG {r[id_col]}',
                'parent_id':      parent_id,
                'artikel_anzahl': anzahl_by_wg.get(r[id_col], 0),
            })
        return result
    except Exception as e:
        log.warning('warengruppen_alle_laden fehlgeschlagen: %s', e)
        return []


def _wg_nachkommen(wg_id: int, alle_wgs: list) -> set:
    """Gibt wg_id + alle rekursiven Kinder-IDs zurück (BFS)."""
    by_parent: dict[int, list[int]] = {}
    for wg in alle_wgs:
        p = wg['parent_id']
        if p is not None:
            by_parent.setdefault(p, []).append(wg['id'])
    result, queue = set(), [wg_id]
    while queue:
        curr = queue.pop()
        result.add(curr)
        queue.extend(by_parent.get(curr, []))
    return result


_BROWSER_SELECT = """
    a.REC_ID, a.ARTNUM, a.BARCODE,
    a.KURZNAME, a.KAS_NAME, a.MATCHCODE,
    a.VK1B, a.VK2B, a.VK3B, a.VK4B, a.VK5B,
    a.STEUER_CODE, a.ARTIKELTYP,
    a.MENGE_AKT, a.ME_ID,
    a.NO_EK_FLAG, a.NO_VK_FLAG, a.FSK18_FLAG,
    a.USERFELD_04, a.USERFELD_05,
    COALESCE(me.BEZEICHNUNG, '') AS ME_BEZEICHNUNG,
    ap.AKTIONSPREIS
"""

_BROWSER_JOINS = """
    LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID AND me.SPRACHE_ID = 0
    LEFT JOIN (
        SELECT ARTIKEL_ID, MIN(PREIS) AS AKTIONSPREIS
        FROM ARTIKEL_PREIS
        WHERE PT2 = 'AP'
          AND (GUELTIG_VON IS NULL OR GUELTIG_VON <= CURDATE())
          AND (GUELTIG_BIS IS NULL OR GUELTIG_BIS >= CURDATE())
        GROUP BY ARTIKEL_ID
    ) ap ON ap.ARTIKEL_ID = a.REC_ID
"""

_BROWSER_ORDER = "COALESCE(NULLIF(a.KAS_NAME, ''), a.KURZNAME)"


def artikel_nach_warengruppe(wg_id: int | None, limit: int = 1000) -> list:
    """
    Artikel einer Warengruppe inkl. aller Untergruppen (oder alle wenn wg_id=None).
    Gibt alle Artikeltypen zurück (N=Normal, L=Lohn, S=Stückliste usw.)
    mit erweiterten Feldern für den Artikel-Browser.
    """
    wg_col = _artikel_wg_spalte()
    try:
        with get_db() as cur:
            if wg_id is not None and wg_col:
                wg_ids = _wg_nachkommen(wg_id, warengruppen_alle_laden())
                ph = ','.join(['%s'] * len(wg_ids))
                cur.execute(
                    f"""SELECT {_BROWSER_SELECT}
                        FROM ARTIKEL a {_BROWSER_JOINS}
                        WHERE a.{wg_col} IN ({ph})
                        ORDER BY {_BROWSER_ORDER} LIMIT %s""",
                    (*sorted(wg_ids), limit)
                )
            else:
                cur.execute(
                    f"""SELECT {_BROWSER_SELECT}
                        FROM ARTIKEL a {_BROWSER_JOINS}
                        ORDER BY {_BROWSER_ORDER} LIMIT %s""",
                    (limit,)
                )
            rows = cur.fetchall()
        return [_artikel_aufbereiten(r) for r in rows]
    except Exception as e:
        log.warning('artikel_nach_warengruppe wg=%s fehlgeschlagen: %s', wg_id, e)
        return []


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
                          ist_gutschein: bool = False,
                          wg_id: int | None = None,
                          ep_original: int | None = None) -> dict:
    """Fügt eine Position zum Vorgang hinzu und aktualisiert die Summen.

    Für Warengruppen-Buchungen: artikel_id=None, wg_id=<WG-ID>.
    CAO-Konvention: ARTIKEL_ID=-99 in JOURNALPOS für WG-Buchungen.
    """
    # Menge / Rabatt berücksichtigen
    rabatt_faktor = 1.0 - (rabatt_prozent / 100.0)
    ep_nach_rabatt = round(einzelpreis_brutto * rabatt_faktor)
    gesamt = round(ep_nach_rabatt * menge)

    netto, mwst_b = mwst_berechnen(gesamt, steuer_code)
    mwst_satz = mwst_satz_fuer_code(steuer_code)

    # Artikeldaten nachladen für Snapshot; WG-Buchungen: ARTIKEL_ID=-99 (CAO-Konvention)
    artnum = ''
    barcode = ''
    if wg_id and not artikel_id:
        artikel_id = -99          # CAO-Konvention für WG-Buchungen in JOURNALPOS
        artnum = f'WG:{wg_id}'   # WG-Referenz im ARTNUM-Feld speichern
    elif artikel_id and artikel_id > 0:
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
                NETTO_BETRAG, IST_GUTSCHEIN, EP_ORIGINAL)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (vorgang_id, pos_nr, artikel_id, artnum, barcode, bezeichnung,
             menge, ep_nach_rabatt, gesamt,
             rabatt_prozent, steuer_code, mwst_satz, mwst_b, netto,
             1 if ist_gutschein else 0,
             ep_original)
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


def position_menge_aendern(vorgang_id: int, position_id: int, neue_menge: float):
    """Ändert die Menge einer Position in-place (keine Delete+Insert)."""
    with get_db_transaction() as cur:
        cur.execute(
            "SELECT EINZELPREIS_BRUTTO, STEUER_CODE FROM XT_KASSE_VORGAENGE_POS "
            "WHERE ID = %s AND VORGANG_ID = %s AND STORNIERT = 0",
            (position_id, vorgang_id)
        )
        pos = cur.fetchone()
        if not pos:
            return
        gesamt = round(pos['EINZELPREIS_BRUTTO'] * neue_menge)
        netto, mwst_b = mwst_berechnen(gesamt, pos['STEUER_CODE'])
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE_POS "
            "SET MENGE=%s, GESAMTPREIS_BRUTTO=%s, MWST_BETRAG=%s, NETTO_BETRAG=%s "
            "WHERE ID=%s AND VORGANG_ID=%s",
            (neue_menge, gesamt, mwst_b, netto, position_id, vorgang_id)
        )
        _vorgang_summen_aktualisieren(vorgang_id, cur)


def vorgang_preise_neuberechnen(vorgang_id: int, pr_ebene: int):
    """Aktualisiert alle Artikel-Positionen auf die Preisebene des Kunden.

    PR_EBENE 5 = Barverkauf (Standard). Wenn VK{n}B = 0, Fallback auf VK5B.
    WG-Buchungen und bereits stornierte Positionen werden nicht verändert.
    """
    pr_ebene = max(1, min(5, pr_ebene))  # Clamp 1-5
    vk_col = f'VK{pr_ebene}B'

    positionen = vorgang_positionen(vorgang_id)
    art_ids = [
        p['ARTIKEL_ID'] for p in positionen
        if p.get('ARTIKEL_ID') and p['ARTIKEL_ID'] > 0 and not p.get('STORNIERT')
    ]
    if not art_ids:
        return

    # VK-Preise batch laden
    with get_db() as cur:
        ph = ','.join(['%s'] * len(art_ids))
        cur.execute(
            f"SELECT REC_ID, {vk_col}, VK5B FROM ARTIKEL WHERE REC_ID IN ({ph})",
            art_ids
        )
        vk_map = {}
        for r in cur.fetchall():
            # Fallback auf VK5B wenn gewählte Ebene = 0
            preis = euro_zu_cent(r[vk_col] or 0) or euro_zu_cent(r['VK5B'] or 0)
            vk_map[r['REC_ID']] = preis

    with get_db_transaction() as cur:
        for pos in positionen:
            if not pos.get('ARTIKEL_ID') or pos['ARTIKEL_ID'] <= 0 or pos.get('STORNIERT'):
                continue
            neuer_vk = vk_map.get(pos['ARTIKEL_ID'])
            if not neuer_vk:
                continue
            rabatt = float(pos.get('RABATT_PROZENT') or 0)
            neuer_ep = round(neuer_vk * (1 - rabatt / 100))
            gesamt   = round(neuer_ep * float(pos['MENGE']))
            netto, mwst_b = mwst_berechnen(gesamt, pos['STEUER_CODE'])
            cur.execute(
                """UPDATE XT_KASSE_VORGAENGE_POS
                   SET EINZELPREIS_BRUTTO=%s, GESAMTPREIS_BRUTTO=%s,
                       NETTO_BETRAG=%s, MWST_BETRAG=%s
                   WHERE ID=%s""",
                (neuer_ep, gesamt, netto, mwst_b, pos['ID'])
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

    # Leeren offenen Vorgang dieses Terminals wiederverwenden (spart eine Bon-Nummer)
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM XT_KASSE_VORGAENGE "
            "WHERE TERMINAL_NR=%s AND STATUS='OFFEN' ORDER BY ID DESC LIMIT 1",
            (terminal_nr,)
        )
        offen = cur.fetchone()

    if offen and not vorgang_positionen(offen['ID']):
        # Leeren Bon direkt nutzen – keine neue Bon-Nummer nötig
        neuer = offen
    else:
        # Belegter oder kein offener Bon → neuen anlegen
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
    """Aktueller Hauptkasse-Bestand in Cent."""
    with get_db() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(BETRAG), 0) AS SALDO
               FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR = %s AND COALESCE(KASSE,'HAUPT') = 'HAUPT'""",
            (terminal_nr,)
        )
        row = cur.fetchone()
    return int(row['SALDO']) if row else 0


def kassenbuch_heute(terminal_nr: int) -> list:
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR = %s AND DATE(BUCHUNGSDATUM) = CURDATE()
               ORDER BY BUCHUNGSDATUM""",
            (terminal_nr,)
        )
        return cur.fetchall()


# ── Kassenbuch – erweiterte manuelle Buchungen ─────────────────────────────────

#: Buchungstypen für manuelle Kassenbuch-Einträge
KASSENBUCH_TYPEN = {
    'EINLAGE':              {'sign': +1, 'text': 'Einlage BAR',               'kasse': 'HAUPT'},
    'ENTNAHME':             {'sign': -1, 'text': 'Entnahme BAR',              'kasse': 'HAUPT'},
    'PRIVATENTNAHME':       {'sign': -1, 'text': 'Privatentnahme',            'kasse': 'HAUPT'},
    'PRIVATEINLAGE':        {'sign': +1, 'text': 'Privateinlage',             'kasse': 'HAUPT'},
    'TRANSFER_KASSE_BANK':  {'sign': -1, 'text': 'Transfer Kasse → Bank',     'kasse': 'HAUPT'},
    'TRANSFER_BANK_KASSE':  {'sign': +1, 'text': 'Transfer Bank → Kasse',     'kasse': 'HAUPT'},
    'TRANSFER_KASSE_NEBEN': {'sign': -1, 'text': 'Transfer Kasse → Nebenkasse','kasse':'HAUPT'},
    'TRANSFER_NEBEN_KASSE': {'sign': +1, 'text': 'Transfer Nebenkasse → Kasse','kasse':'HAUPT'},
}


def kassenbuch_saldo_neben(terminal_nr: int) -> int:
    """Nebenkasse-Saldo in Cent."""
    with get_db() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(BETRAG), 0) AS SALDO "
            "FROM XT_KASSE_KASSENBUCH WHERE TERMINAL_NR=%s AND KASSE='NEBEN'",
            (terminal_nr,)
        )
        return int((cur.fetchone() or {}).get('SALDO', 0))


def kassenbuch_liste(terminal_nr: int, kasse: str = 'HAUPT', tage: int = 30) -> list:
    """Kassenbuch-Einträge der letzten N Tage."""
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR=%s AND COALESCE(KASSE,'HAUPT')=%s
                 AND BUCHUNGSDATUM >= DATE_SUB(NOW(), INTERVAL %s DAY)
               ORDER BY BUCHUNGSDATUM DESC""",
            (terminal_nr, kasse, tage)
        )
        return cur.fetchall()


def kassenbuch_belegnummer_naechste(terminal_nr: int) -> str:
    """Nächste fortlaufende Belegnummer als String."""
    with get_db() as cur:
        cur.execute(
            """SELECT MAX(CAST(BELEGNUMMER AS UNSIGNED)) AS MAX_NR
               FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR=%s AND BELEGNUMMER REGEXP '^[0-9]+$'""",
            (terminal_nr,)
        )
        row = cur.fetchone()
    return str(int((row or {}).get('MAX_NR') or 0) + 1)


def letzter_abschluss_datum(terminal_nr: int):
    """Datum des letzten Tagesabschlusses (date-Objekt oder None)."""
    with get_db() as cur:
        cur.execute(
            "SELECT MAX(DATUM) AS D FROM XT_KASSE_TAGESABSCHLUSS WHERE TERMINAL_NR=%s",
            (terminal_nr,)
        )
        row = cur.fetchone()
    return (row or {}).get('D')


def kassenbuch_eintrag_manuell(
    terminal_nr: int, typ: str, betrag_cent: int, mitarbeiter_id: int,
    buchungstext: str = '', gegenkonto: str = '', mwst_code=None,
    belegnummer: str = '', buchungsdatum=None
):
    """
    Manuelle Kassenbuch-Buchung.  Bei Transfer-Typen wird automatisch
    eine Gegenbuchung auf die Nebenkasse geschrieben.
    """
    if typ not in KASSENBUCH_TYPEN:
        raise ValueError(f'Unbekannter Buchungstyp: {typ}')
    info = KASSENBUCH_TYPEN[typ]
    wert = info['sign'] * abs(betrag_cent)
    if buchungsdatum is None:
        buchungsdatum = datetime.now()
    btext = buchungstext.strip() or info['text']

    with get_db_transaction() as cur:
        cur.execute(
            """INSERT INTO XT_KASSE_KASSENBUCH
               (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, NOTIZ, BUCHUNGSTEXT,
                GEGENKONTO, MWST_CODE, BELEGNUMMER, KASSE, MITARBEITER_ID)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'HAUPT',%s)""",
            (terminal_nr, buchungsdatum, typ, wert, btext, btext,
             gegenkonto or None, mwst_code or None, belegnummer or None, mitarbeiter_id)
        )
        # Gegenbuchung Nebenkasse für Transfer-Typen
        if typ == 'TRANSFER_KASSE_NEBEN':
            cur.execute(
                """INSERT INTO XT_KASSE_KASSENBUCH
                   (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, NOTIZ, BUCHUNGSTEXT,
                    GEGENKONTO, BELEGNUMMER, KASSE, MITARBEITER_ID)
                   VALUES (%s,%s,'TRANSFER_KASSE_NEBEN',%s,%s,%s,%s,%s,'NEBEN',%s)""",
                (terminal_nr, buchungsdatum, +abs(betrag_cent), btext, btext,
                 gegenkonto or None, belegnummer or None, mitarbeiter_id)
            )
        elif typ == 'TRANSFER_NEBEN_KASSE':
            cur.execute(
                """INSERT INTO XT_KASSE_KASSENBUCH
                   (TERMINAL_NR, BUCHUNGSDATUM, TYP, BETRAG, NOTIZ, BUCHUNGSTEXT,
                    GEGENKONTO, BELEGNUMMER, KASSE, MITARBEITER_ID)
                   VALUES (%s,%s,'TRANSFER_NEBEN_KASSE',%s,%s,%s,%s,%s,'NEBEN',%s)""",
                (terminal_nr, buchungsdatum, -abs(betrag_cent), btext, btext,
                 gegenkonto or None, belegnummer or None, mitarbeiter_id)
            )


def kassenbuch_info(terminal_nr: int) -> dict:
    """Kassenstand und Workflow-Hinweise für Manager-Seite."""
    saldo_haupt = kassenbuch_saldo(terminal_nr)
    saldo_neben = kassenbuch_saldo_neben(terminal_nr)

    with get_db() as cur:
        # Einnahmen Bar + EC seit letztem Abschluss
        cur.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN z.ZAHLART='BAR' THEN z.BETRAG ELSE 0 END),0) AS BAR,
                 COALESCE(SUM(CASE WHEN z.ZAHLART='EC'  THEN z.BETRAG ELSE 0 END),0) AS EC
               FROM XT_KASSE_ZAHLUNGEN z
               JOIN XT_KASSE_VORGAENGE v ON v.ID=z.VORGANG_ID
               WHERE v.TERMINAL_NR=%s AND v.STATUS='ABGESCHLOSSEN'
                 AND v.BON_DATUM > COALESCE(
                     (SELECT MAX(ZEITPUNKT) FROM XT_KASSE_TAGESABSCHLUSS WHERE TERMINAL_NR=%s),
                     '2000-01-01')""",
            (terminal_nr, terminal_nr)
        )
        zahlarten = cur.fetchone() or {}

        # Letzter Transfer Kasse → Nebenkasse (für Morning Workflow)
        cur.execute(
            """SELECT ABS(BETRAG) AS BETRAG FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR=%s AND TYP='TRANSFER_KASSE_NEBEN' AND KASSE='HAUPT'
               ORDER BY BUCHUNGSDATUM DESC LIMIT 1""",
            (terminal_nr,)
        )
        lt = cur.fetchone()

        # Heute schon Transfer Nebenkasse → Kasse?
        cur.execute(
            """SELECT COUNT(*) AS C FROM XT_KASSE_KASSENBUCH
               WHERE TERMINAL_NR=%s AND TYP='TRANSFER_NEBEN_KASSE'
                 AND KASSE='HAUPT' AND DATE(BUCHUNGSDATUM)=CURDATE()""",
            (terminal_nr,)
        )
        transfer_heute = int((cur.fetchone() or {}).get('C', 0)) > 0

        # Letzter Tagesabschluss
        abschluss_d = letzter_abschluss_datum(terminal_nr)

        # Terminal-Konten (Spalten existieren ggf. noch nicht)
        try:
            cur.execute(
                "SELECT KONTO_BANK, KONTO_NEBENKASSE FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
                (terminal_nr,)
            )
            konten = cur.fetchone() or {}
        except Exception:
            konten = {}

    return {
        'saldo_haupt':           saldo_haupt,
        'saldo_neben':           saldo_neben,
        'einnahmen_bar':         int(zahlarten.get('BAR', 0)),
        'einnahmen_ec':          int(zahlarten.get('EC', 0)),
        'letzter_transfer_neben': int(lt['BETRAG']) if lt else None,
        'transfer_heute':        transfer_heute,
        'letzter_abschluss':     abschluss_d,
        'konto_bank':            konten.get('KONTO_BANK') or '',
        'konto_nebenkasse':      konten.get('KONTO_NEBENKASSE') or '',
    }


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
