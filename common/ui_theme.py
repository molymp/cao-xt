"""
Dorfkern – zentrales UI-Theme aus DORFKERN_KONFIG.

Das Theme wird global im Admin gepflegt (Schluessel ``ui.theme`` in
DORFKERN_KONFIG) und gilt fuer ALLE Apps. Jede App registriert per
``register_theme_context(app)`` einen Flask-Context-Processor, der
in jedes Template die Variable ``ui_theme`` liefert.

base.html jeder App setzt damit::

    <html data-theme="{{ ui_theme }}">

So entfaellt das clientseitige localStorage-Hin-und-Her – Admin
schreibt einmal, common.konfig cacht 60 s, alle anderen Apps sehen
das neue Theme beim naechsten Page-Render.
"""
from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger(__name__)

# Erlaubte Theme-Werte (zur Validierung beim Setzen)
ERLAUBTE_THEMES: tuple[str, ...] = (
    'dorfkern-light',
    'dorfkern-dark',
    'dorfkern-gruen',
)
DEFAULT_THEME = 'dorfkern-gruen'

# Konfig-Schluessel
KEY = 'ui.theme'


def get_theme() -> str:
    """Liest das aktive Theme aus DORFKERN_KONFIG.

    Faellt auf ``DEFAULT_THEME`` zurueck wenn nichts gesetzt ist
    oder die DB voruebergehend nicht erreichbar ist (common.konfig
    fail-soft).
    """
    try:
        from common import konfig
    except Exception:
        return DEFAULT_THEME
    wert = konfig.get(KEY, default=None)
    if wert and wert in ERLAUBTE_THEMES:
        return wert
    return DEFAULT_THEME


def set_theme(theme: str, ma_id: int | None = None) -> dict:
    """Speichert ein neues Theme in DORFKERN_KONFIG.

    Args:
        theme:  einer der Werte aus ``ERLAUBTE_THEMES``.
        ma_id:  optional fuer GEAENDERT_VON.

    Returns:
        ``{'ok': True}`` oder ``{'ok': False, 'msg': str}``.
    """
    if theme not in ERLAUBTE_THEMES:
        return {'ok': False,
                'msg': f'Unbekanntes Theme: {theme}. '
                       f'Erlaubt: {", ".join(ERLAUBTE_THEMES)}'}
    try:
        from common import konfig
        konfig.set(
            KEY, theme, typ='STRING', kategorie='UI',
            beschreibung='Aktives UI-Theme fuer alle Dorfkern-Apps',
            ma_id=ma_id,
        )
    except Exception as e:
        log.exception('Theme-Speichern fehlgeschlagen')
        return {'ok': False, 'msg': str(e)}
    return {'ok': True, 'theme': theme}


def register_theme_context(app, var_name: str = 'ui_theme') -> None:
    """Registriert einen Flask-Context-Processor mit ``ui_theme``.

    Aufruf in der App::

        from common.ui_theme import register_theme_context
        register_theme_context(app)

    Im Template dann:

        <html data-theme="{{ ui_theme }}">
    """
    @app.context_processor
    def _ui_theme_ctx():
        return {var_name: get_theme()}
