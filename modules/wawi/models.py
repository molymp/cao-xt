"""
CAO-XT WaWi-Modul – Datenbankmodelle & Geschäftslogik (Phase 1)

Konventionen (analog kasse-app):
  - Kein ORM – direktes SQL mit DictCursor (mysql.connector)
  - Alle Geldbeträge als Integer-Cent (kein DECIMAL für Geld)
  - GoBD §146 Abs. 4 AO: kein UPDATE / DELETE auf abgeschlossenen Belegen,
    stattdessen append-only Preishistorie
  - Buchungsrelevante Tabellen: created_at, created_by in jeder Zeile
  - CAO-DB-Stammdaten (ARTIKEL, WARENGRUPPEN, ARTIKEL_PREIS) werden read-only genutzt
    Ausnahme: artikel_vk5_setzen() schreibt direkt ARTIKEL.VK5B (Preispflege HAB-235)
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


_pool = None
_pool_lock = None  # threading.Lock(), lazy um Importfehler zu vermeiden


def _db_params() -> dict:
    """Liest DB-Verbindungsparameter.

    Priorität: Flask-App-Config (sys.modules['config']) > caoxt.ini / Env-Vars.
    Dadurch startet das Blueprint auch wenn caoxt.ini Platzhalter enthält –
    analog zum Lazy-Pool-Pattern in wawi-app/app/db.py.
    """
    import sys
    try:
        cfg = sys.modules.get('config')
        if cfg and hasattr(cfg, 'DB_HOST') and str(cfg.DB_HOST) not in ('', '[server-URL]'):
            return dict(
                host=cfg.DB_HOST,
                port=int(cfg.DB_PORT),
                user=cfg.DB_USER,
                password=getattr(cfg, 'DB_PASSWORD', ''),
                database=cfg.DB_NAME,
            )
    except Exception:
        pass
    return dict(
        host=_db('db_loc', 'localhost'),
        port=int(_db('db_port', '3306')),
        user=_db('db_user', ''),
        password=_db('db_pass', ''),
        database=_db('db_name', ''),
    )


def _get_conn():
    import threading
    global _pool, _pool_lock
    if _pool_lock is None:
        _pool_lock = threading.Lock()
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pooling.MySQLConnectionPool(
                    pool_name='wawi_pool',
                    pool_size=5,
                    charset='utf8mb4',
                    use_unicode=True,
                    autocommit=True,
                    connection_timeout=10,
                    **_db_params(),
                )
    try:
        return _pool.get_connection()
    except Exception:
        return mysql.connector.connect(
            charset='utf8mb4',
            use_unicode=True,
            autocommit=True,
            **_db_params(),
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
                   COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE) AS BEZEICHNUNG,
                   a.BARCODE,
                   a.VK1B, a.VK2B, a.VK3B, a.VK4B, a.VK5B,
                   a.STEUER_CODE AS MWST_CODE,
                   a.MENGE_AKT,
                   a.ARTIKELTYP,
                   wg.NAME AS WG_NAME
              FROM ARTIKEL a
         LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE
             WHERE (a.ARTNUM LIKE %s OR a.KURZNAME LIKE %s
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
                   COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE) AS BEZEICHNUNG,
                   a.BARCODE,
                   a.VK1B, a.VK2B, a.VK3B, a.VK4B, a.VK5B,
                   a.EK_PREIS,
                   a.STEUER_CODE AS MWST_CODE,
                   a.MENGE_AKT,
                   a.ARTIKELTYP,
                   wg.NAME AS WG_NAME
              FROM ARTIKEL a
         LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE
             WHERE a.ARTNUM = %s
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


# ── Preispflege-Tabelle (HAB-235) ─────────────────────────────────────────────

# MwSt-Sätze je CAO-Steuercode (in Prozent)
_MWST_MAP: dict[int, float] = {0: 0.0, 1: 19.0, 2: 7.0, 3: 7.8}


def warengruppen_liste() -> list:
    """Alle aktiven Warengruppen für Filter-Dropdown (aufsteigend nach Bezeichnung)."""
    with get_db() as cur:
        cur.execute(
            "SELECT ID AS wgr_id, NAME AS name "
            "FROM WARENGRUPPEN ORDER BY NAME"
        )
        return cur.fetchall()


def preispflege_liste(wgr_id: int | None = None) -> list:
    """
    Alle Normalartikel (ARTIKELTYP='N', VK5B>0) mit EK, VK5 und berechneter Marge.

    EK wird aus ARTIKEL.EK_PREIS gelesen (CAO-Stammdaten).
    Marge-Berechnung:
        vk5_netto    = VK5B / (1 + mwst_satz)
        marge_pct    = (vk5_netto - EK) / vk5_netto * 100
    """
    wgr_filter = ''
    params: list = []
    if wgr_id is not None:
        wgr_filter = 'AND a.WARENGRUPPE = %s '
        params.append(wgr_id)

    with get_db() as cur:
        cur.execute(
            f"""
            SELECT
                a.ARTNUM,
                COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE) AS BEZEICHNUNG,
                a.WARENGRUPPE                                  AS wgr_id,
                COALESCE(wg.NAME, '')                         AS WGR_NAME,
                COALESCE(a.VK5B, 0)                          AS VK5,
                COALESCE(a.EK_PREIS, 0)                      AS EK,
                COALESCE(a.STEUER_CODE, 0)                   AS MWST_CODE
            FROM ARTIKEL a
            LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE
            WHERE a.ARTIKELTYP = 'N'
              AND a.VK5B > 0
              {wgr_filter}
            ORDER BY a.WARENGRUPPE, COALESCE(a.KAS_NAME, a.KURZNAME)
            """,
            params,
        )
        rows = cur.fetchall()

    result = []
    for r in rows:
        vk5 = float(r['VK5'] or 0)
        ek = float(r['EK'] or 0)
        mwst_code = int(r['MWST_CODE'] or 0)
        mwst_pct = _MWST_MAP.get(mwst_code, 0.0)
        mwst_satz = mwst_pct / 100.0

        vk5_netto = vk5 / (1.0 + mwst_satz) if mwst_satz > 0 else vk5
        if vk5_netto > 0:
            marge_pct = round((vk5_netto - ek) / vk5_netto * 100, 1)
        else:
            marge_pct = None

        result.append({
            'artnr':       r['ARTNUM'],
            'bezeichnung': r['BEZEICHNUNG'],
            'wgr_id':      r['wgr_id'],
            'wgr_name':    r['WGR_NAME'],
            'vk5':         round(vk5, 2),
            'ek':          round(ek, 2),
            'mwst_code':   mwst_code,
            'mwst_pct':    mwst_pct,
            'vk5_netto':   round(vk5_netto, 4),
            'marge_pct':   marge_pct,
        })

    return result


def artikel_vk5_setzen(artnum: str, vk5_brutto: float) -> dict:
    """
    Schreibt VK5B direkt in ARTIKEL.VK5B (CAO-Stammdatenpflege).

    Hinweis: Abweichung von der read-only-Konvention für CAO-Tabellen –
    begründet in DECISIONS.md (HAB-235): Preispflege erfordert Rückschreiben
    in CAO-ARTIKEL, da die Kassenintegration VK5B direkt aus ARTIKEL liest.

    Gibt dict zurück: {'ok': True, 'artnr': ..., 'vk5_neu': ..., 'marge_pct': ...}
    """
    if vk5_brutto < 0:
        raise ValueError('VK5 darf nicht negativ sein')

    artikel = artikel_by_artnum(artnum)
    if not artikel:
        raise ValueError(f'Artikel {artnum!r} nicht gefunden')

    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE ARTIKEL SET VK5B = %s WHERE ARTNUM = %s",
            (vk5_brutto, artnum),
        )
        if cur.rowcount == 0:
            raise ValueError(f'Artikel {artnum!r} konnte nicht aktualisiert werden')

    ek = float(artikel.get('EK_PREIS') or 0)
    mwst_code = int(artikel.get('MWST_CODE') or 0)
    mwst_satz = _MWST_MAP.get(mwst_code, 0.0) / 100.0
    vk5_netto = vk5_brutto / (1.0 + mwst_satz) if mwst_satz > 0 else vk5_brutto
    marge_pct = round((vk5_netto - ek) / vk5_netto * 100, 1) if vk5_netto > 0 else None

    return {
        'ok':       True,
        'artnr':    artnum,
        'vk5_neu':  vk5_brutto,
        'marge_pct': marge_pct,
    }
