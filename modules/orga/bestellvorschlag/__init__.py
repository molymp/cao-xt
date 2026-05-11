"""Orga-Bestellvorschlag: Backwaren-Bedarfsprognose (Luidl).

Datenquellen:
* JOURNALPOS WG=1 (Backwaren, Baecker) — 8+ Jahre Verkaufshistorie
* Open-Meteo Archive (Habach, Lkr. Weilheim-Schongau)
* Schulferien Bayern (openholidaysapi.org)
* Feiertage Bayern (python-holidays, offline)

Architektur: pro Wochentag lineares Regressionsmodell, Features
Wetter + Feiertag + Ferien + Saison. Siehe project_backwaren_bedarf.md.
"""
from .routes import create_blueprint  # noqa: F401
