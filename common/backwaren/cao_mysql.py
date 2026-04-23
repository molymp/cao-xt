"""
CAO-MySQL-Adapter fuer Backwaren (produktive Quelle).

Liest ARTIKEL aus der CAO-DB; Filter ueber ``WARENGRUPPE`` (Default
``'101'`` = Backwaren laut Habacher-Konfiguration). Bestand kommt aus
``ARTIKEL.MENGE_LAGER`` falls verfuegbar.
"""
from __future__ import annotations

import logging
from typing import Optional

from common.db import get_db

from .datenquelle import Artikel, BackwarenDatenquelle

log = logging.getLogger(__name__)

_DEFAULT_WARENGRUPPE = '101'


class CaoMysqlQuelle(BackwarenDatenquelle):
    """Liest Artikel direkt aus der CAO-MySQL-DB (Tabelle ``ARTIKEL``)."""
    TYP = 'CAO'

    def __init__(self, warengruppe: str = _DEFAULT_WARENGRUPPE) -> None:
        self.warengruppe = str(warengruppe)

    def artikel_liste(self) -> list[Artikel]:
        sql = """
            SELECT
                a.REC_ID        AS artikel_id,
                a.ARTNUM        AS artnum,
                a.KURZNAME      AS name,
                ROUND(a.VK5B * 100) AS preis_cent,
                a.MENGE_LAGER   AS bestand,
                a.EINHEIT       AS einheit,
                a.GESPERRT      AS gesperrt
              FROM ARTIKEL a
             WHERE a.WARENGRUPPE = %s
             ORDER BY a.KURZNAME
        """
        try:
            with get_db() as cur:
                cur.execute(sql, (self.warengruppe,))
                rows = cur.fetchall() or []
        except Exception as exc:
            log.warning("CaoMysqlQuelle.artikel_liste: DB-Fehler: %s", exc)
            return []
        return [self._zu_artikel(r) for r in rows]

    def bestand(self, artikel_id: int) -> Optional[float]:
        """Schneller Direkt-Lookup (ohne Liste zu materialisieren)."""
        try:
            with get_db() as cur:
                cur.execute(
                    "SELECT MENGE_LAGER FROM ARTIKEL WHERE REC_ID = %s",
                    (int(artikel_id),))
                row = cur.fetchone()
        except Exception as exc:
            log.warning("CaoMysqlQuelle.bestand(%s): %s", artikel_id, exc)
            return None
        if not row:
            return None
        wert = row.get('MENGE_LAGER')
        return float(wert) if wert is not None else None

    @staticmethod
    def _zu_artikel(row: dict) -> Artikel:
        bestand = row.get('bestand')
        return Artikel(
            artikel_id=int(row['artikel_id']),
            artnum=str(row.get('artnum') or ''),
            name=str(row.get('name') or ''),
            preis_cent=int(row.get('preis_cent') or 0),
            bestand=float(bestand) if bestand is not None else None,
            einheit=str(row.get('einheit') or 'Stk'),
            aktiv=not bool(row.get('gesperrt')),
        )
