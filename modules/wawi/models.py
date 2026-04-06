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

# Cache für WARENGRUPPEN-Schema (TOP_ID-Spalte)
_wg_schema_cache: dict | None = None


def _wg_top_spalte() -> str | None:
    """Ermittelt die Hierarchie-Spalte in WARENGRUPPEN (gecacht).

    Prüft DESCRIBE WARENGRUPPEN für TOP_ID / PARENT_ID / PARENT / OBERGRUPPE_ID.
    Gibt Spaltenname oder None zurück.
    """
    global _wg_schema_cache
    if _wg_schema_cache is not None:
        return _wg_schema_cache.get('top_col')

    kandidaten = ('TOP_ID', 'PARENT_ID', 'PARENT', 'OBERGRUPPE_ID')
    try:
        with get_db() as cur:
            cur.execute('DESCRIBE WARENGRUPPEN')
            cols = {r['Field'] for r in cur.fetchall()}
    except Exception:
        _wg_schema_cache = {'top_col': None}
        return None

    top_col = next((c for c in kandidaten if c in cols), None)
    _wg_schema_cache = {'top_col': top_col}
    return top_col


def _faktor_berechnen(vk5_netto: float, ek: float,
                      vpe_vk: float = 1.0, vpe_ek: float = 1.0) -> float | None:
    """Preisfaktor (VK/EK-Verhältnis, VPE-korrigiert).

    Faktor = (vk5_netto × vpe_ek) / (ek × vpe_vk)

    Beispiel: VPE_EK=12 (Karton à 12 Stk), VPE_VK=1 (Einzelstk),
              EK=12 € (Karton), VK5 Netto=2 € → Faktor = 2×12/(12×1) = 2,0

    Rückgabe None wenn EK oder VK5 fehlen/null.
    """
    divisor = ek * (vpe_vk or 1.0)
    if divisor <= 0 or vk5_netto <= 0:
        return None
    return round(vk5_netto * (vpe_ek or 1.0) / divisor, 3)


def warengruppen_liste() -> list:
    """Alle Warengruppen für Filter-Dropdown (aufsteigend nach Name)."""
    with get_db() as cur:
        cur.execute(
            'SELECT ID AS wgr_id, NAME AS name '
            'FROM WARENGRUPPEN ORDER BY NAME'
        )
        return cur.fetchall()


def warengruppen_mit_faktor() -> list:
    """Warengruppen-Hierarchie mit Ø-Faktor aller aktiven Artikel.

    Rückgabe: [{wgr_id, name, parent_id, anzahl_artikel, avg_faktor}, ...]
    parent_id=None = Wurzelknoten.
    Faktor = vk5_netto × vpe_ek / (ek × vpe_vk), VPE aus ARTIKEL.VPE / ARTIKEL.VPE_EK.
    Aktive Artikel: kein NO_VK_FLAG ('J'/'Y') und kein GELOESCHT.
    """
    top_col = _wg_top_spalte()
    top_sel = f'wg.{top_col}' if top_col else 'NULL'

    sql = f"""
        SELECT
            wg.ID                                              AS wgr_id,
            wg.NAME                                           AS name,
            {top_sel}                                          AS top_id,
            COALESCE(a.VK5B, 0)                              AS vk5,
            COALESCE(a.EK_PREIS, 0)                          AS ek,
            COALESCE(a.STEUER_CODE, 0)                       AS mwst_code,
            COALESCE(a.VPE, 1)                               AS vpe_vk,
            COALESCE(a.VPE_EK, 1)                            AS vpe_ek
        FROM WARENGRUPPEN wg
        LEFT JOIN ARTIKEL a ON a.WARENGRUPPE = wg.ID
            AND a.EK_PREIS > 0
            AND (a.NO_VK_FLAG IS NULL OR a.NO_VK_FLAG NOT IN ('J','Y'))
            AND (a.GELOESCHT IS NULL OR a.GELOESCHT = 0)
        ORDER BY wg.NAME, wg.ID
    """
    try:
        with get_db() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            # Alle WG-IDs für parent_id-Validierung
            cur.execute('SELECT ID FROM WARENGRUPPEN')
            alle_wg_ids = {r['ID'] for r in cur.fetchall()}
    except Exception:
        return warengruppen_liste()

    wgr_map: dict[int, dict] = {}
    for r in rows:
        wid = int(r['wgr_id'])
        if wid not in wgr_map:
            # parent_id nur setzen wenn TOP_ID auf eine andere gültige WG zeigt
            raw_top = r.get('top_id')
            parent_id = None
            if raw_top is not None:
                try:
                    pid = int(raw_top)
                    if pid in alle_wg_ids and pid != wid:
                        parent_id = pid
                except (TypeError, ValueError):
                    pass
            wgr_map[wid] = {
                'wgr_id': wid,
                'name': r['name'] or f'WG {wid}',
                'parent_id': parent_id,
                'faktoren': [],
            }
        vk5 = float(r['vk5'] or 0)
        ek = float(r['ek'] or 0)
        mwst_satz = _MWST_MAP.get(int(r['mwst_code'] or 0), 0.0) / 100.0
        vpe_vk = float(r['vpe_vk'] or 1) or 1.0
        vpe_ek = float(r['vpe_ek'] or 1) or 1.0
        vk5_netto = vk5 / (1.0 + mwst_satz) if mwst_satz > 0 else vk5
        f = _faktor_berechnen(vk5_netto, ek, vpe_vk, vpe_ek)
        if f is not None:
            wgr_map[wid]['faktoren'].append(f)

    result = []
    for wid, data in sorted(wgr_map.items(), key=lambda x: x[1]['name']):
        faktoren = data['faktoren']
        result.append({
            'wgr_id':         wid,
            'name':           data['name'],
            'parent_id':      data['parent_id'],
            'anzahl_artikel': len(faktoren),
            'avg_faktor':     round(sum(faktoren) / len(faktoren), 3) if faktoren else None,
        })
    return result


def preispflege_liste(wgr_id: int | None = None) -> list:
    """Alle aktiven Artikel mit EK, VK5, VPE und Faktor.

    Aktive Artikel: kein VK-Sperre (NO_VK_FLAG != 'J'/'Y') und kein Lösch-Flag.
    VPE: ARTIKEL.VPE (Verkaufseinheit) und ARTIKEL.VPE_EK (Einkaufseinheit).
    Faktor = vk5_netto × vpe_ek / (ek × vpe_vk)  — VPE-korrigiert.
    """
    wgr_filter = ''
    params: list = []
    if wgr_id is not None:
        wgr_filter = 'AND a.WARENGRUPPE = %s '
        params.append(wgr_id)

    sql = f"""
        SELECT
            a.ARTNUM,
            COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE) AS BEZEICHNUNG,
            a.WARENGRUPPE                                  AS wgr_id,
            COALESCE(wg.NAME, '')                         AS WGR_NAME,
            COALESCE(a.VK5B, 0)                          AS VK5,
            COALESCE(a.EK_PREIS, 0)                      AS EK,
            COALESCE(a.STEUER_CODE, 0)                   AS MWST_CODE,
            COALESCE(a.MENGE_AKT, 0)                     AS BESTAND,
            COALESCE(a.VPE, 1)                           AS VPE_VK,
            COALESCE(a.VPE_EK, 1)                        AS VPE_EK,
            a.DEFAULT_LIEF_ID
        FROM ARTIKEL a
        LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE
        WHERE (a.NO_VK_FLAG IS NULL OR a.NO_VK_FLAG NOT IN ('J','Y'))
          AND (a.GELOESCHT IS NULL OR a.GELOESCHT = 0)
          {wgr_filter}
        ORDER BY a.WARENGRUPPE, COALESCE(a.KAS_NAME, a.KURZNAME)
    """
    with get_db() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    result = []
    for r in rows:
        vk5 = float(r['VK5'] or 0)
        ek = float(r['EK'] or 0)
        mwst_code = int(r['MWST_CODE'] or 0)
        mwst_pct = _MWST_MAP.get(mwst_code, 0.0)
        mwst_satz = mwst_pct / 100.0
        vpe_vk = float(r['VPE_VK'] or 1) or 1.0
        vpe_ek = float(r['VPE_EK'] or 1) or 1.0

        vk5_netto = vk5 / (1.0 + mwst_satz) if mwst_satz > 0 else vk5
        faktor = _faktor_berechnen(vk5_netto, ek, vpe_vk, vpe_ek)

        result.append({
            'artnr':           r['ARTNUM'],
            'bezeichnung':     r['BEZEICHNUNG'],
            'wgr_id':          r['wgr_id'],
            'wgr_name':        r['WGR_NAME'],
            'vk5':             round(vk5, 2),
            'vk5_netto':       round(vk5_netto, 4),
            'ek':              round(ek, 2),
            'mwst_code':       mwst_code,
            'mwst_pct':        mwst_pct,
            'bestand':         float(r['BESTAND'] or 0),
            'vpe_vk':          vpe_vk,
            'vpe_ek':          vpe_ek,
            'faktor':          faktor,
            'default_lief_id': r.get('DEFAULT_LIEF_ID'),
        })

    return result


def lieferantenpreise_fuer_artikel(artnr: str) -> list:
    """Lieferantenpreise für einen Artikel aus CAO-Stammdaten.

    Primär: ARTIKEL_PREIS (PT2-Einträge außer 'AP') mit ADRESSEN-Join für Lieferantenname.
    Fallback: ARTIKEL_LIEFERANT (falls ARTIKEL_PREIS keine Daten liefert).
    Bei fehlenden Tabellen / Spalten: leere Liste (kein Fehler).

    Rückgabe: [{lief_nr, lief_name, lief_artnr, ek_preis, vpe, ist_standard}, ...]
    """
    # Standard-Lieferant des Artikels für Hervorhebung
    try:
        with get_db() as cur:
            cur.execute('SELECT DEFAULT_LIEF_ID FROM ARTIKEL WHERE ARTNUM = %s', (artnr,))
            row = cur.fetchone()
            default_lief_id = row['DEFAULT_LIEF_ID'] if row else None
    except Exception:
        default_lief_id = None

    def _mark_standard(rows_out):
        for r in rows_out:
            r['ist_standard'] = (
                default_lief_id is not None
                and str(r.get('lief_nr', '')) == str(default_lief_id)
            )
        return rows_out

    # Variante 1: ARTIKEL_PREIS mit ADRESSEN-Join (Lieferantenname)
    try:
        with get_db() as cur:
            cur.execute(
                """
                SELECT
                    ap.KUNDEN_NR                               AS lief_nr,
                    COALESCE(adr.NAME1, adr.MATCHCODE,
                             CONCAT('Lieferant ', ap.KUNDEN_NR)) AS lief_name,
                    ap.PT2                                     AS lief_artnr,
                    COALESCE(ap.PREIS, 0)                      AS ek_preis,
                    COALESCE(ap.MENGE_AB, 1)                   AS vpe
                FROM ARTIKEL_PREIS ap
                LEFT JOIN ADRESSEN adr ON adr.LIEF_NR = ap.KUNDEN_NR
                WHERE ap.ARTNUM = %s
                  AND ap.PT2 NOT IN ('AP')
                  AND ap.KUNDEN_NR IS NOT NULL
                  AND ap.KUNDEN_NR != ''
                ORDER BY ap.KUNDEN_NR, ap.MENGE_AB
                """,
                (artnr,),
            )
            rows = cur.fetchall()
        if rows:
            return _mark_standard([
                {
                    'lief_nr':    r['lief_nr'],
                    'lief_name':  r['lief_name'],
                    'lief_artnr': r.get('lief_artnr') or '',
                    'ek_preis':   float(r['ek_preis'] or 0),
                    'vpe':        float(r['vpe'] or 1) or 1.0,
                }
                for r in rows
            ])
    except Exception:
        pass

    # Variante 2: ARTIKEL_LIEFERANT mit ADRESSEN-Join
    try:
        with get_db() as cur:
            cur.execute(
                """
                SELECT
                    al.LIEF_NR,
                    COALESCE(adr.NAME1, adr.MATCHCODE,
                             CONCAT('Lieferant ', al.LIEF_NR))  AS lief_name,
                    COALESCE(al.LIEF_ARTNR, al.BESTELL_NR, '') AS lief_artnr,
                    COALESCE(al.EK_PREIS, 0)                    AS ek_preis,
                    COALESCE(al.VPE, 1)                         AS vpe
                FROM ARTIKEL_LIEFERANT al
                LEFT JOIN ADRESSEN adr ON adr.LIEF_NR = al.LIEF_NR
                WHERE al.ARTNUM = %s
                ORDER BY al.LIEF_NR
                """,
                (artnr,),
            )
            rows = cur.fetchall()
        if rows:
            return _mark_standard([
                {
                    'lief_nr':    r['LIEF_NR'],
                    'lief_name':  r['lief_name'],
                    'lief_artnr': r['lief_artnr'],
                    'ek_preis':   float(r['ek_preis'] or 0),
                    'vpe':        float(r['vpe'] or 1) or 1.0,
                }
                for r in rows
            ])
    except Exception:
        pass

    # Variante 3: ARTIKEL_LIEFERANT ohne ADRESSEN-Join
    try:
        with get_db() as cur:
            cur.execute(
                """
                SELECT
                    al.LIEF_NR,
                    CONCAT('Lieferant ', al.LIEF_NR) AS lief_name,
                    COALESCE(al.LIEF_ARTNR, '')       AS lief_artnr,
                    COALESCE(al.EK_PREIS, 0)          AS ek_preis,
                    COALESCE(al.VPE, 1)               AS vpe
                FROM ARTIKEL_LIEFERANT al
                WHERE al.ARTNUM = %s
                ORDER BY al.LIEF_NR
                """,
                (artnr,),
            )
            rows = cur.fetchall()
        if rows:
            return _mark_standard([
                {
                    'lief_nr':    r['LIEF_NR'],
                    'lief_name':  r['lief_name'],
                    'lief_artnr': r['lief_artnr'],
                    'ek_preis':   float(r['ek_preis'] or 0),
                    'vpe':        float(r['vpe'] or 1) or 1.0,
                }
                for r in rows
            ])
    except Exception:
        pass

    return []


def artikel_vk5_setzen(artnum: str, vk5_brutto: float) -> dict:
    """
    Schreibt VK5B direkt in ARTIKEL.VK5B (CAO-Stammdatenpflege).

    Hinweis: Abweichung von der read-only-Konvention für CAO-Tabellen –
    begründet in DECISIONS.md (HAB-235): Preispflege erfordert Rückschreiben
    in CAO-ARTIKEL, da die Kassenintegration VK5B direkt aus ARTIKEL liest.

    Gibt dict zurück: {'ok': True, 'artnr': ..., 'vk5_neu': ..., 'faktor': ...}
    """
    if vk5_brutto < 0:
        raise ValueError('VK5 darf nicht negativ sein')

    artikel = artikel_by_artnum(artnum)
    if not artikel:
        raise ValueError(f'Artikel {artnum!r} nicht gefunden')

    with get_db_transaction() as cur:
        cur.execute(
            'UPDATE ARTIKEL SET VK5B = %s WHERE ARTNUM = %s',
            (vk5_brutto, artnum),
        )
        if cur.rowcount == 0:
            raise ValueError(f'Artikel {artnum!r} konnte nicht aktualisiert werden')

    ek = float(artikel.get('EK_PREIS') or 0)
    mwst_code = int(artikel.get('MWST_CODE') or 0)
    mwst_satz = _MWST_MAP.get(mwst_code, 0.0) / 100.0
    vk5_netto = vk5_brutto / (1.0 + mwst_satz) if mwst_satz > 0 else vk5_brutto
    faktor = _faktor_berechnen(vk5_netto, ek)

    return {
        'ok':      True,
        'artnr':   artnum,
        'vk5_neu': vk5_brutto,
        'vk5_netto': round(vk5_netto, 4),
        'faktor':  faktor,
    }
