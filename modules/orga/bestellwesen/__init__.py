"""
CAO-XT Orga-Bestellwesen – Übersicht und Bearbeitung von Lieferanten-Bestellungen.

Phase 1: Read-only-Übersicht aller EKBESTELL-Belege mit Detail-View pro
Bestellung. Schreibvorgänge (Liefertermin, Position-Status, Storno) folgen
in Phase 2.

Registrierung:
    from modules.orga.bestellwesen import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/orga/bestellwesen')
"""
from .routes import bp as _bp, create_blueprint  # noqa: F401
