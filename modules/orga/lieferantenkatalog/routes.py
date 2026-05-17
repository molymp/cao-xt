"""Flask-Routes für Orga – Lieferantenkataloge.

Vorerst nur die Landing-Page (Bereich + Berechtigung angelegt). Das
Katalog-Ingest (Excel/E-Mail-Formate) + Markier-Workflow folgt, sobald
ein Beispiel-Format vorliegt.
"""
from __future__ import annotations

import logging

from flask import Blueprint, render_template, session, abort

log = logging.getLogger(__name__)
bp = Blueprint('orga_lieferantenkatalog', __name__,
               template_folder='templates')


def _login_check() -> None:
    if not session.get('ma_id'):
        abort(401)


@bp.get('/')
def uebersicht():
    """Platzhalter-Landing für Lieferantenkataloge."""
    _login_check()
    return render_template('lieferantenkatalog.html')


def create_blueprint():
    return bp
