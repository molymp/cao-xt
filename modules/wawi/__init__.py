"""
CAO-XT WaWi-Modul – Warenwirtschaft Phase 1: Artikelpreispflege & VK-Ermittlung

Registriert den Flask-Blueprint.  Port: 5003 (standalone) oder Blueprint in Haupt-App.

    from modules.wawi import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi')
"""
from .routes import bp as _bp


def create_blueprint():
    return _bp
