"""
CAO-XT WaWi-App – Preis-Logik

Formeln:
  VK_brutto = EK_netto × (1 + Marge/100) × (1 + MwSt/100)
  Marge      = (VK_brutto / (1 + MwSt/100) / EK_netto − 1) × 100

GoBD: WAWI_PREISHISTORIE ist append-only – kein UPDATE/DELETE.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from db import get_cao_db, get_wawi_db, get_wawi_transaction, de_zu_float


# ── Preis-Formeln ─────────────────────────────────────────────

def berechne_vk(ek_netto: float, marge_prozent: float, mwst_satz: float) -> float:
    """Berechnet VK brutto aus EK netto, Marge und MwSt-Satz.

    VK_brutto = EK_netto × (1 + Marge/100) × (1 + MwSt/100)
    Ergebnis wird auf 2 Dezimalstellen kaufmännisch gerundet.
    """
    if ek_netto <= 0:
        return 0.0
    vk = Decimal(str(ek_netto)) * (1 + Decimal(str(marge_prozent)) / 100) * \
         (1 + Decimal(str(mwst_satz)) / 100)
    return float(vk.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def berechne_marge(ek_netto: float, vk_brutto: float, mwst_satz: float) -> float:
    """Berechnet Marge in Prozent aus EK netto, VK brutto und MwSt-Satz.

    Marge = (VK_brutto / (1 + MwSt/100) / EK_netto − 1) × 100
    Gibt 0.0 zurück wenn EK oder VK fehlen/ungültig.
    """
    if ek_netto <= 0 or vk_brutto <= 0:
        return 0.0
    marge = (Decimal(str(vk_brutto)) / (1 + Decimal(str(mwst_satz)) / 100) /
             Decimal(str(ek_netto)) - 1) * 100
    return float(marge.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


# ── Artikel-Stammdaten (CAO-DB, read-only) ────────────────────

def artikel_liste(
    seite: int = 1,
    pro_seite: int = 50,
    suche: str = '',
    warengruppe_id: int | None = None,
    lieferant_id: int | None = None,
    preisgruppe_id: int = 1,
) -> dict:
    """Gibt paginierte Artikelliste mit aktuellem Normalpreis zurück.

    Liest Stammdaten aus CAO-DB (ARTIKEL), joined mit v_aktuelle_preise aus
    WaWi-DB. Der JOIN erfolgt in Python, da es sich um zwei DBs handelt.
    """
    bedingungen = ["a.LOESCHKENNZEICHEN IS NULL OR a.LOESCHKENNZEICHEN = ''"]
    params: list[Any] = []

    if suche:
        bedingungen.append("(a.ART_NR LIKE %s OR a.BEZEICHNUNG LIKE %s)")
        s = f'%{suche}%'
        params.extend([s, s])
    if warengruppe_id:
        bedingungen.append("a.WARENGRUPPE = %s")
        params.append(warengruppe_id)
    if lieferant_id:
        bedingungen.append("a.LIEFERANT_ID = %s")
        params.append(lieferant_id)

    where = ' AND '.join(bedingungen)
    offset = (seite - 1) * pro_seite

    with get_cao_db() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM ARTIKEL a WHERE {where}",
            params
        )
        gesamt = cur.fetchone()['n']

        cur.execute(
            f"""SELECT a.REC_ID AS artikel_id, a.ART_NR, a.BEZEICHNUNG,
                       a.WARENGRUPPE, a.LIEFERANT_ID, a.MWST_SATZ,
                       a.MENGE_AKT, a.EK_PREIS
                FROM ARTIKEL a
                WHERE {where}
                ORDER BY a.ART_NR
                LIMIT %s OFFSET %s""",
            params + [pro_seite, offset]
        )
        artikel = cur.fetchall()

    # Aktuelle Preise aus WaWi-DB nachladen
    if artikel:
        ids = [a['artikel_id'] for a in artikel]
        preise_map = _aktuelle_preise_batch(ids, preisgruppe_id)
        for a in artikel:
            p = preise_map.get(a['artikel_id'])
            a['vk_preis']     = float(p['vk_preis'])     if p else None
            a['ek_preis_wawi'] = float(p['ek_preis'])    if p and p['ek_preis'] else None
            a['marge_prozent'] = float(p['marge_prozent']) if p and p['marge_prozent'] else None

    return {
        'artikel':   artikel,
        'gesamt':    gesamt,
        'seite':     seite,
        'pro_seite': pro_seite,
        'seiten':    max(1, (gesamt + pro_seite - 1) // pro_seite),
    }


def artikel_detail(artikel_id: int) -> dict | None:
    """Gibt einen einzelnen Artikel aus der CAO-DB zurück."""
    with get_cao_db() as cur:
        cur.execute(
            """SELECT a.REC_ID AS artikel_id, a.ART_NR, a.BEZEICHNUNG,
                      a.WARENGRUPPE, a.LIEFERANT_ID, a.MWST_SATZ,
                      a.MENGE_AKT, a.EK_PREIS
               FROM ARTIKEL a
               WHERE a.REC_ID = %s""",
            (artikel_id,)
        )
        return cur.fetchone()


def warengruppen_liste() -> list:
    """Gibt alle Warengruppen aus der CAO-DB zurück."""
    with get_cao_db() as cur:
        cur.execute(
            "SELECT DISTINCT WARENGRUPPE AS id, WARENGRUPPE AS name "
            "FROM ARTIKEL WHERE LOESCHKENNZEICHEN IS NULL OR LOESCHKENNZEICHEN = '' "
            "ORDER BY WARENGRUPPE"
        )
        return cur.fetchall()


def lieferanten_liste() -> list:
    """Gibt alle aktiven Lieferanten aus der CAO-DB zurück."""
    with get_cao_db() as cur:
        cur.execute(
            "SELECT DISTINCT a.LIEFERANT_ID AS id, "
            "COALESCE(l.NAME1, CONCAT('Lieferant ', a.LIEFERANT_ID)) AS name "
            "FROM ARTIKEL a "
            "LEFT JOIN LIEFERANT l ON l.REC_ID = a.LIEFERANT_ID "
            "WHERE (a.LOESCHKENNZEICHEN IS NULL OR a.LOESCHKENNZEICHEN = '') "
            "AND a.LIEFERANT_ID IS NOT NULL AND a.LIEFERANT_ID > 0 "
            "ORDER BY name"
        )
        return cur.fetchall()


# ── Preisgruppen (WaWi-DB) ────────────────────────────────────

def preisgruppen_liste() -> list:
    """Gibt alle aktiven Preisgruppen zurück."""
    with get_wawi_db() as cur:
        cur.execute(
            "SELECT id, name, beschreibung FROM WAWI_PREISGRUPPEN "
            "WHERE aktiv = 1 ORDER BY id"
        )
        return cur.fetchall()


# ── Preise lesen (WaWi-DB) ────────────────────────────────────

def _aktuelle_preise_batch(artikel_ids: list[int], preisgruppe_id: int) -> dict:
    """Liest aktuelle Preise für eine Liste von Artikel-IDs aus WaWi-DB.

    Gibt ein Dict {artikel_id: Preis-Row} zurück.
    """
    if not artikel_ids:
        return {}
    placeholders = ','.join(['%s'] * len(artikel_ids))
    with get_wawi_db() as cur:
        cur.execute(
            f"SELECT * FROM v_aktuelle_preise "
            f"WHERE artikel_id IN ({placeholders}) AND preisgruppe_id = %s",
            artikel_ids + [preisgruppe_id]
        )
        rows = cur.fetchall()
    return {r['artikel_id']: r for r in rows}


def aktuelle_preise_artikel(artikel_id: int) -> list:
    """Gibt alle aktuellen Preise eines Artikels (alle Preisgruppen) zurück."""
    with get_wawi_db() as cur:
        cur.execute(
            "SELECT vap.*, pg.name AS preisgruppe_name "
            "FROM v_aktuelle_preise vap "
            "JOIN WAWI_PREISGRUPPEN pg ON pg.id = vap.preisgruppe_id "
            "WHERE vap.artikel_id = %s ORDER BY vap.preisgruppe_id",
            (artikel_id,)
        )
        return cur.fetchall()


def preishistorie_artikel(
    artikel_id: int,
    tage: int = 90,
    preisgruppe_id: int | None = None,
) -> list:
    """Gibt die Preishistorie eines Artikels zurück (neueste zuerst)."""
    params: list[Any] = [artikel_id, tage]
    extra = ""
    if preisgruppe_id:
        extra = " AND ph.preisgruppe_id = %s"
        params.append(preisgruppe_id)

    with get_wawi_db() as cur:
        cur.execute(
            f"""SELECT ph.*, pg.name AS preisgruppe_name
                FROM WAWI_PREISHISTORIE ph
                JOIN WAWI_PREISGRUPPEN pg ON pg.id = ph.preisgruppe_id
                WHERE ph.artikel_id = %s
                  AND ph.erstellt_am >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  {extra}
                ORDER BY ph.erstellt_am DESC
                LIMIT 200""",
            params
        )
        return cur.fetchall()


# ── Preis speichern (append-only INSERT) ─────────────────────

def preis_speichern(
    artikel_id: int,
    preisgruppe_id: int,
    ek_preis: float | None,
    vk_preis: float,
    mwst_satz: float,
    erstellt_von: str,
    aenderungsgrund: str = '',
    import_ref: str | None = None,
) -> int:
    """Speichert einen neuen Preis (INSERT in WAWI_PREISHISTORIE).

    Berechnet Marge automatisch wenn EK vorhanden.
    Gibt die neue ID zurück.
    GoBD: Diese Funktion darf keine bestehenden Einträge verändern.
    """
    marge = berechne_marge(ek_preis or 0.0, vk_preis, mwst_satz) if ek_preis else None

    with get_wawi_transaction() as cur:
        cur.execute(
            """INSERT INTO WAWI_PREISHISTORIE
               (artikel_id, preisgruppe_id, ek_preis, vk_preis, marge_prozent,
                mwst_satz, erstellt_von, aenderungsgrund, import_ref)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (artikel_id, preisgruppe_id,
             ek_preis, vk_preis, marge,
             mwst_satz, erstellt_von, aenderungsgrund or '', import_ref)
        )
        return cur.lastrowid


# ── Massenaktualisierung ──────────────────────────────────────

def massenupdate_vorschau(
    prozent: float,
    warengruppe_id: int | None = None,
    lieferant_id: int | None = None,
    preisgruppe_id: int = 1,
) -> list:
    """Berechnet Vorher/Nachher-Preise für einen Massenupdate ohne zu speichern.

    Entweder warengruppe_id ODER lieferant_id muss angegeben sein.
    """
    artikel_ids = _artikel_ids_fuer_filter(warengruppe_id, lieferant_id)
    if not artikel_ids:
        return []

    preise_map = _aktuelle_preise_batch(artikel_ids, preisgruppe_id)

    with get_cao_db() as cur:
        placeholders = ','.join(['%s'] * len(artikel_ids))
        cur.execute(
            f"SELECT REC_ID AS artikel_id, ART_NR, BEZEICHNUNG, MWST_SATZ "
            f"FROM ARTIKEL WHERE REC_ID IN ({placeholders})",
            artikel_ids
        )
        artikel_rows = {r['artikel_id']: r for r in cur.fetchall()}

    vorschau = []
    for aid in artikel_ids:
        art = artikel_rows.get(aid)
        p   = preise_map.get(aid)
        if not art or not p:
            continue
        vk_alt = float(p['vk_preis'])
        vk_neu = berechne_vk(
            float(p['ek_preis'] or 0) if p.get('ek_preis') else 0,
            float(p['marge_prozent'] or 0) * (1 + prozent / 100)
            if p.get('marge_prozent') else 0,
            float(art['MWST_SATZ'])
        ) if p.get('ek_preis') and p.get('marge_prozent') else round(vk_alt * (1 + prozent / 100), 2)
        vorschau.append({
            'artikel_id':  aid,
            'art_nr':      art['ART_NR'],
            'bezeichnung': art['BEZEICHNUNG'],
            'mwst_satz':   float(art['MWST_SATZ']),
            'vk_alt':      vk_alt,
            'vk_neu':      vk_neu,
            'ek_preis':    float(p['ek_preis']) if p.get('ek_preis') else None,
        })
    return vorschau


def massenupdate_ausfuehren(
    prozent: float,
    warengruppe_id: int | None,
    lieferant_id: int | None,
    preisgruppe_id: int,
    erstellt_von: str,
) -> int:
    """Führt Massenpreisupdate durch. Gibt Anzahl aktualisierter Artikel zurück.

    Für jeden Artikel wird ein neuer INSERT in WAWI_PREISHISTORIE erstellt.
    GoBD: bestehende Einträge werden nicht verändert.
    """
    vorschau = massenupdate_vorschau(prozent, warengruppe_id, lieferant_id, preisgruppe_id)
    if not vorschau:
        return 0

    grund = f"Massenupdate: {prozent:+.2f}%"
    if warengruppe_id:
        grund += f" (Warengruppe {warengruppe_id})"
    elif lieferant_id:
        grund += f" (Lieferant {lieferant_id})"

    # Aktuelle EK/MwSt für alle Artikel nachladen
    artikel_ids = [v['artikel_id'] for v in vorschau]
    preise_map = _aktuelle_preise_batch(artikel_ids, preisgruppe_id)

    rows = []
    for v in vorschau:
        p = preise_map.get(v['artikel_id'])
        ek = float(p['ek_preis']) if p and p.get('ek_preis') else None
        marge_neu = (
            float(p['marge_prozent']) * (1 + prozent / 100)
            if p and p.get('marge_prozent') else None
        )
        vk_neu = v['vk_neu']
        marge_calc = berechne_marge(ek or 0, vk_neu, v['mwst_satz']) if ek else marge_neu
        rows.append((
            v['artikel_id'], preisgruppe_id,
            ek, vk_neu,
            marge_calc, v['mwst_satz'],
            erstellt_von, grund, None
        ))

    with get_wawi_transaction() as cur:
        cur.executemany(
            """INSERT INTO WAWI_PREISHISTORIE
               (artikel_id, preisgruppe_id, ek_preis, vk_preis, marge_prozent,
                mwst_satz, erstellt_von, aenderungsgrund, import_ref)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            rows
        )
    return len(rows)


# ── CSV-Import ────────────────────────────────────────────────

def csv_import_vorschau(
    dateiinhalt: bytes,
    preisgruppe_id: int = 1,
    encoding: str = 'auto',
) -> dict:
    """Parst CSV und gibt Vorschau (ohne Speichern) zurück.

    Format: art_nr;ek_preis_netto;[bezeichnung_optional]
    Semikolon-getrennt, DE-Zahlenformat (Komma als Dezimaltrennzeichen).
    Gibt {'zeilen': [...], 'fehler': [...], 'ok_count': int} zurück.
    """
    text = _decode_csv(dateiinhalt, encoding)
    zeilen_ok = []
    fehler = []

    # Artikel-Nr → REC_ID + MwSt aus CAO-DB vorholen
    art_nr_map = _artikel_by_artnr()

    reader = csv.reader(io.StringIO(text), delimiter=';')
    for i, row in enumerate(reader, start=1):
        if not any(c.strip() for c in row):
            continue  # Leerzeile
        if len(row) < 2:
            fehler.append({'zeile': i, 'grund': 'Zu wenige Spalten', 'raw': ';'.join(row)})
            continue

        art_nr   = row[0].strip()
        ek_str   = row[1].strip()
        bezeich  = row[2].strip() if len(row) > 2 else ''

        try:
            ek_netto = de_zu_float(ek_str)
            if ek_netto <= 0:
                raise ValueError("EK muss > 0 sein")
        except (ValueError, TypeError):
            fehler.append({'zeile': i, 'grund': f'Ungültiger EK-Preis: {ek_str!r}', 'raw': ';'.join(row)})
            continue

        art = art_nr_map.get(art_nr)
        if not art:
            fehler.append({'zeile': i, 'grund': f'Artikelnummer {art_nr!r} nicht in CAO-DB', 'raw': ';'.join(row)})
            continue

        mwst = float(art['mwst_satz'])
        # Aktuelle Marge laden um VK beizubehalten oder Standardmarge 30% zu verwenden
        zeilen_ok.append({
            'zeile':      i,
            'art_nr':     art_nr,
            'artikel_id': art['artikel_id'],
            'bezeichnung': bezeich or art['bezeichnung'],
            'ek_neu':     ek_netto,
            'mwst_satz':  mwst,
        })

    return {
        'zeilen':    zeilen_ok,
        'fehler':    fehler,
        'ok_count':  len(zeilen_ok),
        'err_count': len(fehler),
    }


def csv_import_ausfuehren(
    vorschau_zeilen: list,
    preisgruppe_id: int,
    dateiname: str,
    erstellt_von: str,
    marge_standard: float = 30.0,
) -> dict:
    """Importiert valide CSV-Zeilen in WAWI_PREISHISTORIE.

    Berechnet VK aus EK und bisheriger Marge (oder Standardmarge).
    Schreibt Import-Log. Gibt Batch-Statistik zurück.
    """
    if not vorschau_zeilen:
        return {'batch_id': None, 'zeilen_ok': 0, 'zeilen_fehler': 0}

    batch_id = str(uuid.uuid4())
    artikel_ids = [z['artikel_id'] for z in vorschau_zeilen]
    preise_map = _aktuelle_preise_batch(artikel_ids, preisgruppe_id)

    rows = []
    for z in vorschau_zeilen:
        p     = preise_map.get(z['artikel_id'])
        marge = float(p['marge_prozent']) if p and p.get('marge_prozent') else marge_standard
        vk    = berechne_vk(z['ek_neu'], marge, z['mwst_satz'])
        rows.append((
            z['artikel_id'], preisgruppe_id,
            z['ek_neu'], vk,
            marge, z['mwst_satz'],
            erstellt_von, f'CSV-Import: {dateiname}', batch_id
        ))

    fehler_detail: list = []
    ok_count = 0

    with get_wawi_transaction() as cur:
        for row in rows:
            try:
                cur.execute(
                    """INSERT INTO WAWI_PREISHISTORIE
                       (artikel_id, preisgruppe_id, ek_preis, vk_preis, marge_prozent,
                        mwst_satz, erstellt_von, aenderungsgrund, import_ref)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    row
                )
                ok_count += 1
            except Exception as e:
                fehler_detail.append({'artikel_id': row[0], 'fehler': str(e)})

        # Import-Log schreiben
        cur.execute(
            """INSERT INTO WAWI_IMPORT_LOG
               (batch_id, dateiname, zeilen_total, zeilen_ok, zeilen_fehler,
                fehler_detail, erstellt_von)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (batch_id, dateiname, len(rows),
             ok_count, len(fehler_detail),
             str(fehler_detail) if fehler_detail else None,
             erstellt_von)
        )

    return {
        'batch_id':     batch_id,
        'zeilen_ok':    ok_count,
        'zeilen_fehler': len(fehler_detail),
        'fehler':       fehler_detail,
    }


# ── Interne Hilfsfunktionen ───────────────────────────────────

def _artikel_ids_fuer_filter(
    warengruppe_id: int | None,
    lieferant_id: int | None,
) -> list[int]:
    """Gibt Artikel-IDs für Warengruppen- oder Lieferanten-Filter zurück."""
    if not warengruppe_id and not lieferant_id:
        return []
    with get_cao_db() as cur:
        if warengruppe_id:
            cur.execute(
                "SELECT REC_ID FROM ARTIKEL "
                "WHERE WARENGRUPPE = %s "
                "AND (LOESCHKENNZEICHEN IS NULL OR LOESCHKENNZEICHEN = '')",
                (warengruppe_id,)
            )
        else:
            cur.execute(
                "SELECT REC_ID FROM ARTIKEL "
                "WHERE LIEFERANT_ID = %s "
                "AND (LOESCHKENNZEICHEN IS NULL OR LOESCHKENNZEICHEN = '')",
                (lieferant_id,)
            )
        return [r['REC_ID'] for r in cur.fetchall()]


def _artikel_by_artnr() -> dict:
    """Gibt Dict {ART_NR: {artikel_id, bezeichnung, mwst_satz}} aus CAO-DB zurück."""
    with get_cao_db() as cur:
        cur.execute(
            "SELECT REC_ID AS artikel_id, ART_NR AS art_nr, "
            "BEZEICHNUNG AS bezeichnung, MWST_SATZ AS mwst_satz "
            "FROM ARTIKEL "
            "WHERE LOESCHKENNZEICHEN IS NULL OR LOESCHKENNZEICHEN = ''"
        )
        return {r['art_nr']: r for r in cur.fetchall()}


def _decode_csv(inhalt: bytes, encoding: str = 'auto') -> str:
    """Dekodiert CSV-Bytes. 'auto' versucht UTF-8, dann Latin-1."""
    if encoding == 'auto':
        try:
            return inhalt.decode('utf-8-sig')
        except UnicodeDecodeError:
            return inhalt.decode('latin-1')
    return inhalt.decode(encoding, errors='replace')
