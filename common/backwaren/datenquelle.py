"""
Interface + Artikel-Datenklasse fuer Backwaren-Datenquellen.

Adapter implementieren :class:`BackwarenDatenquelle` und liefern
Artikel als :class:`Artikel`-Instanzen.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Artikel:
    """Minimales Artikel-Datenmodell fuer Backwaren-Adapter.

    Nur Kern-Stammdaten; kiosk-spezifische Metadaten (Kategorie-Sortierung,
    Zutaten, Bild-Pfad, Wochentage) bleiben in der Kiosk-App und werden
    per ``artikel_id`` verknuepft.
    """
    artikel_id: int
    artnum: str
    name: str
    preis_cent: int           # VK brutto
    bestand: Optional[float] = None
    einheit: str = 'Stk'
    aktiv: bool = True
    extras: dict = field(default_factory=dict)

    def als_dict(self) -> dict:
        """Serialisierung fuer JSON-APIs."""
        return {
            'artikel_id': self.artikel_id,
            'artnum':     self.artnum,
            'name':       self.name,
            'preis_cent': self.preis_cent,
            'bestand':    self.bestand,
            'einheit':    self.einheit,
            'aktiv':      self.aktiv,
            'extras':     dict(self.extras),
        }


class BackwarenDatenquelle(ABC):
    """Abstrakter Adapter fuer Artikel-Stammdaten + Bestaende.

    In v2 rein lesend. :meth:`schreibe_verkauf` ist in v2 ein Kontrakt-
    Platzhalter und wirft :class:`NotImplementedError` (v3+).
    """

    #: Kennung fuer Admin-UI / Logs. Muss eindeutig pro Adapter-Typ sein.
    TYP: str = 'ABSTRAKT'

    @abstractmethod
    def artikel_liste(self) -> list[Artikel]:
        """Alle Artikel des Adapters."""

    def bestand(self, artikel_id: int) -> Optional[float]:
        """Bestand eines Artikels (optional; Default sucht in Liste)."""
        for art in self.artikel_liste():
            if art.artikel_id == artikel_id:
                return art.bestand
        return None

    def schreibe_verkauf(self, *_args, **_kwargs) -> None:
        """v2: NICHT implementiert (Release-Entscheidung #7).

        Adapter muessen diese Methode in v3+ ueberschreiben.
        """
        raise NotImplementedError(
            f'{self.TYP}: Schreiben (Verkauf) ist in v2 nicht vorgesehen.')
