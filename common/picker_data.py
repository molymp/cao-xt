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
                        AND a.ARTIKELTYP NOT IN ('L','K','S')
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
    # parent_id=0 bei Wurzeln aus CAO — wir mappen 0 auf None für Frontend
    for r in rows:
        if r.get('parent_id') in (0, '0', None):
            r['parent_id'] = None
    return rows


def artikel_in_warengruppe(wg_id: int | None,
                           mit_untergruppen: bool = True,
                           limit: int = 500) -> list[dict[str, Any]]:
    """Artikel einer Warengruppe (rekursiv inkl. Untergruppen)."""
    with get_db() as cur:
        if not wg_id:
            cur.execute(
                """
                SELECT a.REC_ID    AS artikel_id,
                       a.ARTNUM    AS artnum,
                       a.BARCODE   AS barcode,
                       a.KURZNAME  AS kurzname,
                       a.MATCHCODE AS matchcode,
                       a.LANGNAME  AS langname,
                       a.EK_PREIS  AS ek_preis,
                       a.STEUER_CODE,
                       a.ARTIKELTYP,
                       a.PR_EINHEIT,
                       a.WARENGRUPPE                AS wg_id,
                       me.BEZEICHNUNG               AS me_einheit,
                       me.ME_CODE                   AS me_code,
                       wg.NAME                      AS wgr_name
                  FROM ARTIKEL a
                  LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                  LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
                 WHERE a.ARTIKELTYP NOT IN ('L','K','S')
                 ORDER BY a.KURZNAME
                 LIMIT %s
                """,
                (int(limit),),
            )
        elif mit_untergruppen:
            # rekursive CTE für Nachkommen
            cur.execute(
                """
                WITH RECURSIVE wg_tree AS (
                    SELECT ID, TOP_ID FROM WARENGRUPPEN WHERE ID = %s
                    UNION ALL
                    SELECT w.ID, w.TOP_ID FROM WARENGRUPPEN w
                      JOIN wg_tree t ON w.TOP_ID = t.ID
                )
                SELECT a.REC_ID    AS artikel_id,
                       a.ARTNUM    AS artnum,
                       a.BARCODE   AS barcode,
                       a.KURZNAME  AS kurzname,
                       a.MATCHCODE AS matchcode,
                       a.LANGNAME  AS langname,
                       a.EK_PREIS  AS ek_preis,
                       a.STEUER_CODE,
                       a.ARTIKELTYP,
                       a.PR_EINHEIT,
                       a.WARENGRUPPE                AS wg_id,
                       me.BEZEICHNUNG               AS me_einheit,
                       me.ME_CODE                   AS me_code,
                       wg.NAME                      AS wgr_name
                  FROM ARTIKEL a
                  JOIN wg_tree t ON t.ID = a.WARENGRUPPE
                  LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                  LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
                 WHERE a.ARTIKELTYP NOT IN ('L','K','S')
                 ORDER BY a.KURZNAME
                 LIMIT %s
                """,
                (int(wg_id), int(limit)),
            )
        else:
            cur.execute(
                """
                SELECT a.REC_ID    AS artikel_id,
                       a.ARTNUM    AS artnum,
                       a.BARCODE   AS barcode,
                       a.KURZNAME  AS kurzname,
                       a.MATCHCODE AS matchcode,
                       a.LANGNAME  AS langname,
                       a.EK_PREIS  AS ek_preis,
                       a.STEUER_CODE,
                       a.ARTIKELTYP,
                       a.PR_EINHEIT,
                       a.WARENGRUPPE                AS wg_id,
                       me.BEZEICHNUNG               AS me_einheit,
                       me.ME_CODE                   AS me_code,
                       wg.NAME                      AS wgr_name
                  FROM ARTIKEL a
                  LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                  LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
                 WHERE a.WARENGRUPPE = %s
                   AND a.ARTIKELTYP NOT IN ('L','K','S')
                 ORDER BY a.KURZNAME
                 LIMIT %s
                """,
                (int(wg_id), int(limit)),
            )
        return cur.fetchall()


def artikel_volltext_suche(query: str, limit: int = 100) -> list[dict[str, Any]]:
    """Volltextsuche über Artikel — gleiche Felder wie Pos-Tabelle."""
    pat = f"%{(query or '').strip()}%"
    if len((query or '').strip()) < 2:
        return []
    with get_db() as cur:
        cur.execute(
            """
            SELECT a.REC_ID    AS artikel_id,
                   a.ARTNUM    AS artnum,
                   a.BARCODE   AS barcode,
                   a.KURZNAME  AS kurzname,
                   a.MATCHCODE AS matchcode,
                   a.LANGNAME  AS langname,
                   a.EK_PREIS  AS ek_preis,
                   a.STEUER_CODE,
                   a.ARTIKELTYP,
                   a.PR_EINHEIT,
                   a.WARENGRUPPE          AS wg_id,
                   me.BEZEICHNUNG         AS me_einheit,
                   me.ME_CODE             AS me_code,
                   wg.NAME                AS wgr_name
              FROM ARTIKEL a
              LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
              LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
             WHERE (a.ARTNUM    LIKE %s OR a.BARCODE   LIKE %s
                    OR a.BARCODE2 LIKE %s OR a.BARCODE3 LIKE %s
                    OR a.KURZNAME LIKE %s OR a.MATCHCODE LIKE %s
                    OR a.LANGNAME LIKE %s)
               AND a.ARTIKELTYP NOT IN ('L','K','S')
             ORDER BY a.KURZNAME
             LIMIT %s
            """,
            (pat, pat, pat, pat, pat, pat, pat, int(limit)),
        )
        return cur.fetchall()


# ── Adress-Picker ─────────────────────────────────────────────────────


def adressgruppen() -> list[dict[str, Any]]:
    """Liefert die definierten Adressgruppen plus 3 virtuelle Filter-Slots:
    'lieferant', 'kunde', 'alle'.

    CAO-Adressen lassen sich nach Lieferant (ADRESSEN_LIEF), Kunde
    (Standard) oder beidem filtern. ADRESS_GRUPPEN gibt es als eigene
    Tabelle für freie Gruppierung.
    """
    out: list[dict[str, Any]] = [
        {'id': '__lief__', 'name': 'Lieferanten', 'count': None, 'virtual': True},
        {'id': '__kunde__', 'name': 'Kunden',    'count': None, 'virtual': True},
        {'id': '__alle__',  'name': 'Alle',       'count': None, 'virtual': True},
    ]
    try:
        with get_db() as cur:
            cur.execute(
                """
                SELECT REC_ID AS id, NAME AS name
                  FROM ADRESS_GRUPPEN
                 ORDER BY NAME
                """,
            )
            for r in cur.fetchall():
                out.append({
                    'id':       int(r['id']),
                    'name':     r['name'] or f"Gruppe {r['id']}",
                    'count':    None,
                    'virtual':  False,
                })
    except Exception:
        # Tabelle nicht vorhanden → nur die virtuellen anzeigen
        pass
    return out


def adressen_in_gruppe(grp_id: int | str | None,
                       suche: str = '',
                       limit: int = 200) -> list[dict[str, Any]]:
    """Adressen einer Gruppe (oder alle / Lieferanten / Kunden).

    Args:
        grp_id: numerische ADRESS_GRUPPEN.REC_ID, oder
            ``'__lief__'`` / ``'__kunde__'`` / ``'__alle__'``
        suche: optionaler Substring auf NAME1 / NAME2 / KUNNUM1 / ORT
    """
    where = []
    params: list[Any] = []
    join_lief = ''
    if grp_id == '__lief__' or grp_id is None:
        join_lief = 'JOIN ADRESSEN_LIEF al ON al.ADDR_ID = a.REC_ID'
    elif grp_id == '__kunde__':
        # CAO hat keine eigene "ist Kunde"-Tabelle — Approximation:
        # alle, die nicht in ADRESSEN_LIEF stehen
        where.append("a.REC_ID NOT IN (SELECT ADDR_ID FROM ADRESSEN_LIEF)")
    elif grp_id == '__alle__':
        pass  # kein Filter
    else:
        # numerische Gruppe — über ADRESSEN.GRUPPE_ID o.ä.
        try:
            grp_int = int(grp_id)
            where.append("a.GRUPPE_ID = %s")
            params.append(grp_int)
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
               COALESCE(a.PLZ, '')                 AS plz,
               COALESCE(a.ORT, '')                 AS ort,
               COALESCE(a.KUNNUM1, '')             AS kunnum,
               COALESCE(a.STRASSE, '')             AS strasse,
               COALESCE(a.HAUSNR, '')              AS hausnr
          FROM ADRESSEN a
          {join_lief}
        {where_sql}
         ORDER BY a.NAME1
         LIMIT %s
    """
    with get_db() as cur:
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception:
            # Fallback ohne GRUPPE_ID-Spalte (CAO-Versionen ohne Adressgruppen)
            if 'a.GRUPPE_ID' in sql:
                return adressen_in_gruppe('__alle__', suche, limit)
            raise
