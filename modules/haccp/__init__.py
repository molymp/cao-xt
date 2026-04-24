"""HACCP-Temperaturueberwachung.

Separates Modul (nicht unter orga/), weil HACCP fachlich orthogonal zu Orga ist.
Host: Orga-App (Sidebar-Menuepunkt "Hygiene / HACCP"). Poller laeuft als
eigener Prozess: ``python -m modules.haccp.poller``.

Registrierung:
    from modules.haccp import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/orga/haccp')
"""
from .routes import bp as _bp, create_blueprint  # noqa: F401
