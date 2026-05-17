"""Orga – Lieferantenkataloge.

Lieferanten stellen ihr Sortiment in unterschiedlichen Formaten bereit
(Excel, regelmäßige Sonderkataloge per E-Mail, z. B. Utz). Ziel des
Bereichs: Kataloge je Lieferant sichten und pro Artikel markieren, ob
er **bestellt** und/oder in den **Artikelstamm übernommen** werden
soll.

Stand: Bereich angelegt (Navigation + Berechtigung). Das konkrete
Katalog-Ingest (Format-Parser) folgt, sobald ein Beispiel-Format
vorliegt.
"""
from .routes import create_blueprint  # noqa: F401
