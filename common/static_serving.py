"""
Dorfkern – gemeinsame statische Assets aus ``common/static/``.

Jede App kann die Funktion ``register_common_static(app)`` aufrufen;
danach liefert Flask ``/common-static/<datei>`` aus dem Verzeichnis
``common/static/`` des Repos (inkl. ``dorfkern.css``,
``dorfkern-admin.css`` und ggf. weiterer gemeinsamer Assets).

Warum nicht einfach ``app.static_folder`` umhaengen?
- ``static_folder`` ist pro App, und Flask akzeptiert nur einen.
- Eine zweite Route ist trivial, und kollidiert nicht mit der
  ``/static/``-Default-Route der App.
"""
from __future__ import annotations

import os


def register_common_static(app, url_prefix: str = '/common-static') -> None:
    """Registriert eine Flask-Route fuer ``common/static/``.

    Args:
        app:         Flask-App.
        url_prefix:  URL-Praefix (default ``/common-static``).
    """
    from flask import send_from_directory

    # common/ liegt ein Verzeichnis oberhalb von common/static_serving.py
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'static')

    endpoint = f'_common_static_{url_prefix.strip("/").replace("/", "_")}'

    # Doppelregistrierung verhindern (falls mehrere Apps im selben
    # Python-Prozess laufen – in Tests vorgekommen).
    if endpoint in app.view_functions:
        return

    def _serve(dateiname):
        return send_from_directory(static_dir, dateiname,
                                   max_age=60 * 60 * 24)

    _serve.__name__ = endpoint
    app.add_url_rule(f'{url_prefix}/<path:dateiname>',
                     endpoint=endpoint,
                     view_func=_serve)
