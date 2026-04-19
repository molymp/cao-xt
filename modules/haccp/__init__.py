"""HACCP-Temperaturueberwachung.

Separates Modul (nicht unter wawi/), weil HACCP fachlich orthogonal zu WaWi ist.
Host: WaWi-App (Sidebar-Menuepunkt "Hygiene / HACCP"). Poller laeuft als
eigener Prozess: ``python -m modules.haccp.poller``.

Registrierung:
    from modules.haccp import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi/haccp')
"""
from .routes import bp as _bp, create_blueprint  # noqa: F401
