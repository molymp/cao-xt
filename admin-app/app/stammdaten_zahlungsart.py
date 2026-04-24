"""
CAO-Stammdaten: Zahlungsarten – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``ZAHLUNGSARTEN`` fuer die Admin-Ansicht. In
cao_admin.exe findet sich dieselbe Liste unter
*Einstellungen → Zahlungsarten*.

Schema (CAO-Faktura 1.5, aus SetupForm/ZahlartTab extrahiert)::

    REC_ID         int          PK
    NAME           varchar      Kurzname in der Liste
    TEXT_KURZ      varchar      Kurztext (Belegzeile)
    TEXT_LANG      memo         Langtext (Belegfuss)
    FIBU_KONTEN    varchar      komma-separierte Kontenliste
    SKONTO_PROZ    float        Skonto in %
    AKTIV_FLAG     char(1)      'Y' = Zahlart aktiv, sonst inaktiv
    NETTO_TAGE     int          Zahlungsziel netto (Tage)
    SKONTO_TAGE    int          Skontofrist (Tage)
    AUTOZAHL_FLAG  char(1)      'Y' = automatisch als bezahlt buchen

Y/N-Flags werden als echte Booleans ausgeliefert, FIBU_KONTEN wird zu
einer aufgeraeumten Liste.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)


def _ja(wert: Any) -> bool:
    """CAO-Y/N-Flag -> Bool (None/'' -> False)."""
    return str(wert or '').strip().upper() == 'Y'


def _konten(roh: Any) -> list[str]:
    """FIBU_KONTEN splittet auf Komma, trimmt, entfernt leere."""
    if not roh:
        return []
    return [t.strip() for t in str(roh).split(',') if t.strip()]


def liste() -> list[dict[str, Any]]:
    """Liefert alle ZAHLUNGSARTEN-Zeilen, sortiert nach REC_ID.

    Rueckgabe-Format (pro Eintrag)::

        {
          'id':          int,
          'name':        str,
          'text_kurz':   str,
          'text_lang':   str,
          'fibu_konten': list[str],    # aufgeteilt
          'skonto_proz': float,        # 0.0 wenn leer
          'netto_tage':  int,          # 0 wenn leer
          'skonto_tage': int,
          'aktiv':       bool,
          'autozahl':    bool,
        }
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT REC_ID, NAME, TEXT_KURZ, TEXT_LANG, FIBU_KONTEN,
                   SKONTO_PROZ, AKTIV_FLAG, NETTO_TAGE, SKONTO_TAGE,
                   AUTOZAHL_FLAG
            FROM ZAHLUNGSARTEN
            ORDER BY REC_ID
            """
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        eintraege.append({
            'id':          r.get('REC_ID'),
            'name':        (r.get('NAME') or '').strip(),
            'text_kurz':   (r.get('TEXT_KURZ') or '').strip(),
            'text_lang':   (r.get('TEXT_LANG') or '').strip(),
            'fibu_konten': _konten(r.get('FIBU_KONTEN')),
            'skonto_proz': float(r.get('SKONTO_PROZ') or 0.0),
            'netto_tage':  int(r.get('NETTO_TAGE') or 0),
            'skonto_tage': int(r.get('SKONTO_TAGE') or 0),
            'aktiv':       _ja(r.get('AKTIV_FLAG')),
            'autozahl':    _ja(r.get('AUTOZAHL_FLAG')),
        })
    return eintraege
