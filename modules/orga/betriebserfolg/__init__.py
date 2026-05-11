"""Orga-Betriebserfolg: Monatliche Betriebserfolgsmessung.

Port der Excel-Vorlage des Users. Aggregiert Umsatz/Kunden/Stunden
automatisch aus JOURNAL, kombiniert mit konfigurierbaren Quoten und
pro-Monat-Eingabewerten zur kompletten Betriebserfolgsrechnung.

Siehe ``memory/project_betriebserfolg.md``.
"""
from .routes import create_blueprint  # noqa: F401

