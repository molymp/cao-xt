"""
CAO-XT WaWi-Personal – Mitarbeiter- und Zeitmanagement.

Teil der Zeitmanagement-Reihe (P1: Stammdaten, P2: Schichtplanung, P3: Stempeluhr,
P4: Abwesenheiten, P5: Auswertungen). Aktuelle Phase: P1 Stammdaten.

Registrierung:
    from modules.wawi.personal import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi/personal')
"""
from .routes import bp as _bp, create_blueprint  # noqa: F401
