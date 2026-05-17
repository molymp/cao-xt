"""Orga – Stammdaten (Adressen).

CAO-Adressen anlegen/bearbeiten (perfekte CAO-Mimik via
``common.cao_adressen``: ADRESSEN + ADRESSEN_LOG + XT-HMAC,
Record-Lock beim Ändern). Bewusst HIER und nicht im
Lieferantenkatalog — Adressen sind übergreifende Stammdaten.
"""
from .routes import create_blueprint  # noqa: F401
