"""
CAO-XT Orga-Personal – Mitarbeiter- und Zeitmanagement.

Teil der Zeitmanagement-Reihe (P1: Stammdaten, P2: Schichtplanung, P3: Stempeluhr,
P4: Abwesenheiten, P5: Auswertungen). Aktuelle Phase: P1 Stammdaten.

Registrierung:
    from modules.orga.personal import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/orga/personal')
"""
from .routes import bp as _bp, create_blueprint  # noqa: F401
