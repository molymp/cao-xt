"""
CAO-XT WaWi-Modul – Datenbankmodelle & Geschäftslogik (Phase 1)

Konventionen (analog kasse-app):
  - Kein ORM – direktes SQL mit DictCursor (mysql.connector)
  - Alle Geldbeträge als Integer-Cent (kein DECIMAL für Geld)
  - GoBD §146 Abs. 4 AO: kein UPDATE / DELETE auf abgeschlossenen Belegen,
    stattdessen append-only Preishistorie
  - Buchungsrelevante Tabellen: created_at, created_by in jeder Zeile
  - CAO-DB-Stammdaten (ARTIKEL, WARENGRUPPEN, ARTIKEL_PREIS) werden read-only genutzt
"""

from contextlib import contextmanager
import mysql.connector
from mysql.connector import pooling
import configparser
import os

# ── DB-Verbindung ─────────────────────────────────────────────────────────────
_INI = os.path.join(os.path.dirname(__file__), '..', '..', 'caoxt', 'caoxt.ini')
_cfg = configparser.ConfigParser()
_cfg.read(_INI)


def _db(key, fallback=''):
    return os.environ.get(key.upper(), _cfg.get('Datenbank', key.lower(), fallback=fallback))


_pool = pooling.MySQLConnectionPool(
    pool_name='wawi_pool',
    pool_size=5,
    host=_db('db_loc', 'localhost'),
    port=int(_db('db_port', '3306')),
    user=_db('db_user', ''),
    password=_db('db_pass', ''),
    database=_db('db_name', ''),
    charset='utf8mb4',
    use_unicode=True,
    autocommit=True,
    connection_timeout=10,
)


def _get_conn():
    try:
        return _pool.get_connection()
    except Exception:
        return mysql.connector.connect(
            host=_db('db_loc', 'localhost'),
            port=int(_db('db_port', '3306')),
            user=_db('db_user', ''),
            password=_db('db_pass', ''),
            database=_db('db_name', ''),
            charset='utf8mb4',
            use_unicode=True,
            autocommit=True,
        )


@contextmanager
def get_db():
    """Einfacher Context-Manager; kein Transaktions-Commit (autocommit=True)."""
    conn = _get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()
        conn.close()


@contextmanager
def get_db_transaction():
    """Context-Manager mit explizitem Commit / Rollback."""
    conn = _get_conn()
    conn.autocommit = False
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ── CAO-Stammdaten (read-only) ─────────────────────────────────────────────────

def artikel_suche(q: str, limit: int = 50) -> list:
    """Artikelsuche auf CAO-ARTIKEL-Tabelle (read-only)."""
    like = f'%{q}%'
    with get_db() as cur:
        cur.execute(
            """
            SELECT a.ARTNUM,
                   COALESCE(a.KAS_NAME, a.KURZNAME, a.SUCHNAME) AS BEZEICHNUNG,
                   a.BARCODE,
                   a.VK1B, a.VK2B, a.VK3B, a.VK4B, a.VK5B,
                   a.MWST_CODE,
                   a.MENGE_AKT,
                   a.ARTIKELTYP,
                   wg.BEZEICHNUNG AS WG_NAME
              FROM ARTIKEL a
         LEFT JOIN WARENGRUPPEN wg ON wg.REC_ID = a.WG
             WHERE a.GELOESCHT = 0
               AND (a.ARTNUM LIKE %s OR a.KURZNAME LIKE %s
                    OR a.KAS_NAME LIKE %s OR a.BARCODE LIKE %s)
          ORDER BY a.KAS_NAME
             LIMIT %s
            """,
            (like, like, like, like, limit),
        )
        return cur.fetchall()


def artikel_by_artnum(artnum: str) -> dict | None:
    """Einzelnen Artikel anhand ARTNUM laden."""
    with get_db() as cur:
        cur.execute(
            """
            SELECT a.ARTNUM,
                   COALESCE(a.KAS_NAME, a.KURZNAME, a.SUCHNAME) AS BEZEICHNUNG,
                   a.BARCODE,
                   a.VK1B, a.VK2B, a.VK3B, a.VK4B, a.VK5B,
                   a.EK_PREIS,
                   a.MWST_CODE,
                   a.MENGE_AKT,
                   a.ARTIKELTYP,
                   wg.BEZEICHNUNG AS WG_NAME
              FROM ARTIKEL a
         LEFT JOIN WARENGRUPPEN wg ON wg.REC_ID = a.WG
             WHERE a.ARTNUM = %s
               AND a.GELOESCHT = 0
            """,
            (artnum,),
        )
        return cur.fetchone()


def preisgruppen_fuer_artikel(artnum: str) -> list:
    """
    Alle gültigen Aktionspreise (ARTIKEL_PREIS) für einen Artikel.
    read-only auf CAO-Tabelle.
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT REC_ID, PT2, PREIS, MENGE_AB, MENGE_BIS,
                   DATUM_AB, DATUM_BIS, KUNDEN_NR
              FROM ARTIKEL_PREIS
             WHERE ARTNUM = %s
               AND PT2 = 'AP'
               AND (DATUM_BIS IS NULL OR DATUM_BIS >= CURDATE())
          ORDER BY DATUM_AB DESC
            """,
            (artnum,),
        )
        return cur.fetchall()


# ── WaWi-eigene Tabellen (XT_WAWI_) ───────────────────────────────────────────

def preishistorie_fuer_artikel(artnum: str) -> list:
    """Gesamte Preishistorie eines Artikels (alle Ebenen, chronologisch)."""
    with get_db() as cur:
        cur.execute(
            """
            SELECT REC_ID, ARTNUM, PREISEBENE,
                   PREIS_BRUTTO_CT, GUELTIG_AB, GUELTIG_BIS,
                   KOMMENTAR, CREATED_AT, CREATED_BY
              FROM XT_WAWI_PREISHISTORIE
             WHERE ARTNUM = %s
          ORDER BY PREISEBENE, GUELTIG_AB DESC
            """,
            (artnum,),
        )
        return cur.fetchall()


def aktuellen_preis_holen(artnum: str, preisebene: int) -> dict | None:
    """
    Aktuell gültigen WaWi-Preis für Artikel + Preisebene.
    NULL GUELTIG_BIS = unbefristet gültig.
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT REC_ID, ARTNUM, PREISEBENE,
                   PREIS_BRUTTO_CT, GUELTIG_AB, GUELTIG_BIS,
                   KOMMENTAR, CREATED_AT, CREATED_BY
              FROM XT_WAWI_PREISHISTORIE
             WHERE ARTNUM = %s
               AND PREISEBENE = %s
               AND GUELTIG_AB <= CURDATE()
               AND (GUELTIG_BIS IS NULL OR GUELTIG_BIS >= CURDATE())
          ORDER BY GUELTIG_AB DESC
             LIMIT 1
            """,
            (artnum, preisebene),
        )
        return cur.fetchone()


def preis_setzen(
    artnum: str,
    preisebene: int,
    preis_brutto_ct: int,
    gueltig_ab: str,
    gueltig_bis: str | None,
    benutzer: str,
    kommentar: str = '',
) -> int:
    """
    Neuen Preis in die append-only Preishistorie eintragen.

    GoBD: bestehende Einträge werden NICHT verändert; vorheriger Eintrag
    erhält automatisch GUELTIG_BIS = gueltig_ab - 1 Tag (soft-close).

    Gibt die neue REC_ID zurück.
    """
    if preis_brutto_ct < 0:
        raise ValueError('Preis darf nicht negativ sein')

    with get_db_transaction() as cur:
        # Vorherigen offenen Eintrag schließen (GoBD: kein DELETE, kein UPDATE inhaltlicher Felder)
        cur.execute(
            """
            UPDATE XT_WAWI_PREISHISTORIE
               SET GUELTIG_BIS = DATE_SUB(%s, INTERVAL 1 DAY)
             WHERE ARTNUM = %s
               AND PREISEBENE = %s
               AND (GUELTIG_BIS IS NULL OR GUELTIG_BIS >= %s)
               AND GUELTIG_AB < %s
            """,
            (gueltig_ab, artnum, preisebene, gueltig_ab, gueltig_ab),
        )
        # Neuen Eintrag hinzufügen (append-only)
        cur.execute(
            """
            INSERT INTO XT_WAWI_PREISHISTORIE
                (ARTNUM, PREISEBENE, PREIS_BRUTTO_CT,
                 GUELTIG_AB, GUELTIG_BIS, KOMMENTAR,
                 CREATED_BY)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (artnum, preisebene, preis_brutto_ct,
             gueltig_ab, gueltig_bis, kommentar, benutzer),
        )
        cur.execute('SELECT LAST_INSERT_ID() AS id')
        return cur.fetchone()['id']


def preishistorie_alle(
    limit: int = 200,
    offset: int = 0,
    artnum: str | None = None,
) -> list:
    """Preishistorie-Übersicht, optional gefiltert nach Artikel."""
    params: list = []
    where = ''
    if artnum:
        where = 'WHERE h.ARTNUM = %s '
        params.append(artnum)
    params += [limit, offset]
    with get_db() as cur:
        cur.execute(
            f"""
            SELECT h.REC_ID, h.ARTNUM,
                   COALESCE(a.KAS_NAME, a.KURZNAME) AS BEZEICHNUNG,
                   h.PREISEBENE, h.PREIS_BRUTTO_CT,
                   h.GUELTIG_AB, h.GUELTIG_BIS,
                   h.KOMMENTAR, h.CREATED_AT, h.CREATED_BY
              FROM XT_WAWI_PREISHISTORIE h
         LEFT JOIN ARTIKEL a ON a.ARTNUM = h.ARTNUM
             {where}
          ORDER BY h.CREATED_AT DESC
             LIMIT %s OFFSET %s
            """,
            params,
        )
        return cur.fetchall()


def vk_berechnen(artnum: str, preisebene: int) -> dict:
    """
    VK-Preis ermitteln: Priorität WaWi-Preishistorie > CAO ARTIKEL_PREIS (Aktionspreis) > CAO VKxB.

    Rückgabe:
        {
            'preis_ct': <int>,      # Bruttopreis in Cent
            'quelle': 'wawi' | 'aktion' | 'cao',
            'mwst_code': <str>,
            'artnum': <str>,
        }
    """
    artikel = artikel_by_artnum(artnum)
    if not artikel:
        raise ValueError(f'Artikel {artnum!r} nicht gefunden')

    # 1. WaWi-Preishistorie
    wawi_preis = aktuellen_preis_holen(artnum, preisebene)
    if wawi_preis:
        return {
            'preis_ct': wawi_preis['PREIS_BRUTTO_CT'],
            'quelle': 'wawi',
            'mwst_code': artikel['MWST_CODE'],
            'artnum': artnum,
        }

    # 2. Aktionspreis aus CAO (ARTIKEL_PREIS PT2='AP')
    aktionen = preisgruppen_fuer_artikel(artnum)
    if aktionen:
        return {
            'preis_ct': round(aktionen[0]['PREIS'] * 100),
            'quelle': 'aktion',
            'mwst_code': artikel['MWST_CODE'],
            'artnum': artnum,
        }

    # 3. CAO-Standardpreis (VK1B–VK5B), Ebene 5 = Barverkauf
    vk_col = f'VK{preisebene}B'
    preis_raw = artikel.get(vk_col) or artikel.get('VK5B') or 0
    return {
        'preis_ct': round(float(preis_raw) * 100),
        'quelle': 'cao',
        'mwst_code': artikel['MWST_CODE'],
        'artnum': artnum,
    }
