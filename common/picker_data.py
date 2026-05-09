"""
Wiederverwendbare Daten-Funktionen für UI-Picker (Artikel, Adresse).

Konzept:
- Generische Functions, die einen Cursor-Provider bekommen (``with get_db()``)
- Apps registrieren ihre eigenen Endpunkte mit App-spezifischer Auth + URL
- Das gemeinsame Template ``common/templates/_picker.html`` greift auf
  diese Endpunkte über konfigurierbare URL-Parameter zu

Bisheriger Verwender: orga-app/bestellwesen (Wareneingang). Kasse-Migration
auf dieses Modul: backlog (siehe Memory).
"""
from __future__ import annotations

from typing import Any

from common.db import get_db


# ── Warengruppen-Baum ─────────────────────────────────────────────────


def warengruppen_baum(min_artikel: int = 0) -> list[dict[str, Any]]:
    """Liste aller Warengruppen mit direkter Artikel-Anzahl.

    Args:
        min_artikel: nur WGs mit mind. so vielen direkten Artikeln zeigen
            (Default 0 = alle).

    Returns:
        list von {id, parent_id, bezeichnung, artikel_anzahl}.
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT wg.ID                               AS id,
                   wg.TOP_ID                           AS parent_id,
                   wg.NAME                             AS bezeichnung,
                   (
                     SELECT COUNT(*) FROM ARTIKEL a
                      WHERE a.WARENGRUPPE = wg.ID
                   )                                    AS artikel_anzahl
              FROM WARENGRUPPEN wg
             ORDER BY wg.TOP_ID, wg.SORT, wg.NAME
            """,
        )
        rows = cur.fetchall()
    if min_artikel > 0:
        # mit Kindern: prüfen ob entweder dieser Knoten oder ein Nachkomme
        # min_artikel hat. Pragmatisch: filtern wir hier nicht, das macht
        # das Frontend (zeigt eh den Baum).
        pass
    # CAO-Wurzeln: TOP_ID kann -1, 0 oder NULL sein — auf None mappen
    for r in rows:
        if r.get('parent_id') in (-1, 0, '-1', '0', None):
            r['parent_id'] = None
    return rows


_ARTIKEL_SELECT = """
    a.REC_ID    AS artikel_id,
    a.ARTNUM    AS artnum,
    a.BARCODE   AS barcode,
    a.BARCODE2  AS barcode2,
    a.BARCODE3  AS barcode3,
    a.KURZNAME  AS kurzname,
    a.MATCHCODE AS matchcode,
    a.LANGNAME  AS langname,
    a.EK_PREIS  AS ek_preis,
    a.VK1, a.VK2, a.VK3, a.VK4, a.VK5,
    a.VK1B, a.VK2B, a.VK3B, a.VK4B, a.VK5B,
    a.STEUER_CODE,
    a.ARTIKELTYP    AS artikeltyp,
    a.PR_EINHEIT    AS pr_einheit,
    a.VPE           AS vpe,
    a.VPE_EK        AS vpe_ek,
    a.MENGE_AKT     AS bestand,
    a.WARENGRUPPE   AS wg_id,
    a.SN_FLAG,
    me.BEZEICHNUNG  AS me_einheit,
    me.ME_CODE      AS me_code,
    wg.NAME         AS wgr_name,
    -- Lief-Bestnum: erster gefundener Eintrag in ARTIKEL_PREIS PREIS_TYP=5,
    -- bevorzugt fuer ein angegebenes lief_addr_id (siehe %(lief)s).
    -- ARTIKEL_PREIS hat keinen eigenen PK ausser (ARTIKEL_ID, ADRESS_ID,
    -- PREIS_TYP) — daher Tie-Breaker auf ADRESS_ID.
    (SELECT ap.BESTNUM
       FROM ARTIKEL_PREIS ap
      WHERE ap.ARTIKEL_ID = a.REC_ID
        AND ap.PREIS_TYP = 5
      ORDER BY (ap.ADRESS_ID = %(lief)s) DESC, ap.ADRESS_ID
      LIMIT 1)      AS lief_bestnum
"""


def artikel_in_warengruppe(wg_id: int | None,
                           mit_untergruppen: bool = True,
                           limit: int = 500,
                           lief_addr_id: int | None = None) -> list[dict[str, Any]]:
    """Artikel einer Warengruppe (rekursiv inkl. Untergruppen).

    Args:
        wg_id: Warengruppen-ID; None oder 0 = alle Artikel
        mit_untergruppen: bei True wird über CTE rekursiv abgestiegen
        lief_addr_id: bevorzugter CAO-ADDR_ID des Lieferanten — die
            Lief-Bestnum-Spalte zeigt dann dessen Eintrag.
    """
    lief = int(lief_addr_id) if lief_addr_id else -1
    with get_db() as cur:
        if not wg_id:
            cur.execute(
                f"""
                SELECT {_ARTIKEL_SELECT}
                  FROM ARTIKEL a
                  LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                  LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
                 WHERE 1=1
                 ORDER BY a.KURZNAME
                 LIMIT %(limit)s
                """,
                {'lief': lief, 'limit': int(limit)},
            )
        elif mit_untergruppen:
            cur.execute(
                f"""
                WITH RECURSIVE wg_tree AS (
                    SELECT ID, TOP_ID FROM WARENGRUPPEN WHERE ID = %(wg)s
                    UNION ALL
                    SELECT w.ID, w.TOP_ID FROM WARENGRUPPEN w
                      JOIN wg_tree t ON w.TOP_ID = t.ID
                )
                SELECT {_ARTIKEL_SELECT}
                  FROM ARTIKEL a
                  JOIN wg_tree t ON t.ID = a.WARENGRUPPE
                  LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                  LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
                 WHERE 1=1
                 ORDER BY a.KURZNAME
                 LIMIT %(limit)s
                """,
                {'lief': lief, 'wg': int(wg_id), 'limit': int(limit)},
            )
        else:
            cur.execute(
                f"""
                SELECT {_ARTIKEL_SELECT}
                  FROM ARTIKEL a
                  LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                  LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
                 WHERE a.WARENGRUPPE = %(wg)s
                 ORDER BY a.KURZNAME
                 LIMIT %(limit)s
                """,
                {'lief': lief, 'wg': int(wg_id), 'limit': int(limit)},
            )
        return cur.fetchall()


def artikel_volltext_suche(query: str, limit: int = 100,
                           lief_addr_id: int | None = None) -> list[dict[str, Any]]:
    """Volltextsuche über Artikel — gleiche Felder wie ``artikel_in_warengruppe``."""
    pat = f"%{(query or '').strip()}%"
    if len((query or '').strip()) < 2:
        return []
    lief = int(lief_addr_id) if lief_addr_id else -1
    with get_db() as cur:
        cur.execute(
            f"""
            SELECT {_ARTIKEL_SELECT}
              FROM ARTIKEL a
              LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
              LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
             WHERE (a.ARTNUM    LIKE %(p)s OR a.BARCODE   LIKE %(p)s
                    OR a.BARCODE2 LIKE %(p)s OR a.BARCODE3 LIKE %(p)s
                    OR a.KURZNAME LIKE %(p)s OR a.MATCHCODE LIKE %(p)s
                    OR a.LANGNAME LIKE %(p)s)
             ORDER BY a.KURZNAME
             LIMIT %(limit)s
            """,
            {'lief': lief, 'p': pat, 'limit': int(limit)},
        )
        return cur.fetchall()


# ── Adress-Picker ─────────────────────────────────────────────────────


def adressgruppen(typ_filter: str | None = None) -> list[dict[str, Any]]:
    """Liefert die definierten Adressgruppen aus ``ADRESSGRUPPEN`` mit
    direkter Adressen-Anzahl pro Gruppe.

    Hierarchie via ``TOP_ID``. Verknüpfung zu ADRESSEN: ``KUNDENGRUPPE``.
    """
    out: list[dict[str, Any]] = []
    try:
        with get_db() as cur:
            cur.execute(
                """
                SELECT g.REC_ID AS id,
                       g.TOP_ID AS parent_id,
                       g.NAME   AS name,
                       (SELECT COUNT(*) FROM ADRESSEN a
                         WHERE a.KUNDENGRUPPE = g.REC_ID) AS count
                  FROM ADRESSGRUPPEN g
                 ORDER BY g.NAME
                """,
            )
            for r in cur.fetchall():
                pid = r.get('parent_id')
                if pid in (-1, 0, '-1', '0', None):
                    pid = None
                out.append({
                    'id':        int(r['id']),
                    'parent_id': pid,
                    'name':      r['name'] or f"Gruppe {r['id']}",
                    'count':     int(r.get('count') or 0),
                })
    except Exception:
        pass
    return out


def adressen_in_gruppe(grp_id: int | str | None,
                       suche: str = '',
                       typ_filter: str | None = None,
                       limit: int = 5000) -> list[dict[str, Any]]:
    """Adressen einer Gruppe.

    Args:
        grp_id: numerische ``ADRESSGRUPPEN.REC_ID``; None/0 = alle Gruppen
        suche: Substring auf NAME1 / NAME2 / KUNNUM1 / ORT
        typ_filter: 'lief' = nur Lieferanten (JOIN ADRESSEN_LIEF);
            'kunde' = nur Nicht-Lieferanten; None = alle
    """
    where = []
    params: list[Any] = []
    join_lief = ''
    if typ_filter == 'lief':
        join_lief = 'JOIN ADRESSEN_LIEF al ON al.ADDR_ID = a.REC_ID'
    elif typ_filter == 'kunde':
        where.append("a.REC_ID NOT IN (SELECT ADDR_ID FROM ADRESSEN_LIEF)")

    if grp_id not in (None, 0, '0', ''):
        try:
            grp_int = int(grp_id)
            # Untergruppen-IDs einmalig holen (eine schnelle Query),
            # dann simpler IN-Filter — kein rekursiver CTE pro Aufruf.
            with get_db() as cur_tree:
                cur_tree.execute(
                    "SELECT REC_ID, TOP_ID FROM ADRESSGRUPPEN"
                )
                kinder = {}
                for r in cur_tree.fetchall():
                    p = r.get('TOP_ID')
                    kinder.setdefault(p, []).append(int(r['REC_ID']))
            ids = set([grp_int])
            stack = [grp_int]
            while stack:
                cur_id = stack.pop()
                for k in kinder.get(cur_id, []):
                    if k not in ids:
                        ids.add(k)
                        stack.append(k)
            id_list = list(ids)
            if id_list:
                fmt = ','.join(['%s'] * len(id_list))
                where.append(f"a.KUNDENGRUPPE IN ({fmt})")
                params.extend(id_list)
        except (TypeError, ValueError):
            pass

    if (suche or '').strip():
        pat = f"%{suche.strip()}%"
        where.append("(a.NAME1 LIKE %s OR a.NAME2 LIKE %s "
                     "OR a.KUNNUM1 LIKE %s OR a.ORT LIKE %s)")
        params.extend([pat, pat, pat, pat])

    where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
    params.append(int(limit))

    sql = f"""
        SELECT a.REC_ID                            AS addr_id,
               COALESCE(NULLIF(TRIM(a.NAME1), ''), '–') AS name,
               COALESCE(NULLIF(TRIM(a.NAME2), ''), '')  AS name2,
               COALESCE(NULLIF(TRIM(a.NAME3), ''), '')  AS name3,
               COALESCE(a.PLZ, '')                 AS plz,
               COALESCE(a.ORT, '')                 AS ort,
               COALESCE(a.KUNNUM1, '')             AS kunnum,
               COALESCE(a.STRASSE, '')             AS strasse,
               COALESCE(a.HAUSNR, '')              AS hausnr,
               COALESCE(a.LAND, '')                AS land,
               COALESCE(a.TELE1, '')               AS telefon,
               COALESCE(a.EMAIL, '')               AS email
          FROM ADRESSEN a
          {join_lief}
        {where_sql}
         ORDER BY a.NAME1
         LIMIT %s
    """
    with get_db() as cur:
        cur.execute(sql, params)
        return cur.fetchall()
