"""
CAO-XT – Gemeinsame Authentifizierungs-Hilfsfunktionen

Stellt den ``login_required``-Decorator sowie Session-Helpers bereit.
Login/Logout-**Routen** verbleiben app-lokal (app-spezifische Templates).

Alle Apps verwenden dieselben Session-Schluessel:
  ``ma_id``, ``login_name``, ``vname``, ``ma_name``
"""
import hashlib
from functools import wraps

from flask import session, redirect, url_for


def login_required(f):
    """Decorator: leitet auf die Route ``'login'`` um, wenn kein MA eingeloggt.

    Identisch mit dem frueher app-lokalen ``_login_required``::

        @app.get('/kasse')
        @login_required
        def kasse():
            ...
    """
    @wraps(f)
    def _wrapper(*args, **kwargs):
        if not session.get('ma_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return _wrapper


def get_current_user() -> dict | None:
    """Gibt den angemeldeten Mitarbeiter als Dict oder ``None`` zurueck.

    Returns:
        dict mit ``MA_ID``, ``LOGIN_NAME``, ``VNAME``, ``NAME`` oder ``None``.
    """
    ma_id = session.get('ma_id')
    if not ma_id:
        return None
    return {
        'MA_ID':      ma_id,
        'LOGIN_NAME': session.get('login_name'),
        'VNAME':      session.get('vname'),
        'NAME':       session.get('ma_name'),
    }


def login_user(ma: dict) -> None:
    """Setzt Session-Keys nach erfolgreichem Login.

    Args:
        ma: dict mit ``MA_ID``, ``LOGIN_NAME``, ``VNAME``, ``NAME``
            (wie von ``mitarbeiter_login()`` zurueckgegeben).
    """
    session['ma_id']      = ma['MA_ID']
    session['login_name'] = ma['LOGIN_NAME']
    session['vname']      = ma['VNAME']
    session['ma_name']    = ma['NAME']


def logout_user() -> None:
    """Loescht die gesamte Session (Logout)."""
    session.clear()


def mitarbeiter_login(login_name: str, passwort: str) -> dict | None:
    """Prueft Credentials gegen die MITARBEITER-Tabelle.

    CAO speichert Passwoerter als MD5-Hash (Grossbuchstaben).

    Args:
        login_name: CAO-Benutzername.
        passwort:   Klartextpasswort.

    Returns:
        dict mit ``MA_ID``, ``LOGIN_NAME``, ``VNAME``, ``NAME`` oder ``None``.
    """
    from common.db import get_db
    pw_hash = hashlib.md5(passwort.encode('utf-8')).hexdigest().upper()
    with get_db() as cur:
        cur.execute(
            "SELECT MA_ID, LOGIN_NAME, VNAME, NAME FROM MITARBEITER "
            "WHERE LOGIN_NAME = %s AND USER_PASSWORD = %s",
            (login_name, pw_hash),
        )
        return cur.fetchone()


def mitarbeiter_login_karte(guid: str) -> dict | None:
    """Login per Mitarbeiter-Karte (Barcode-Scan).

    Liest KARTEN.GUID, prueft TYP='M' (Mitarbeiter) und loest ueber
    KARTEN.ID den zugehoerigen MITARBEITER auf.

    Args:
        guid: Gescannter Barcode-Wert (KARTEN.GUID).

    Returns:
        dict mit ``MA_ID``, ``LOGIN_NAME``, ``VNAME``, ``NAME`` oder ``None``.
    """
    if not guid:
        return None
    from common.db import get_db
    with get_db() as cur:
        cur.execute(
            """SELECT m.MA_ID, m.LOGIN_NAME, m.VNAME, m.NAME
               FROM KARTEN k
               JOIN MITARBEITER m ON m.MA_ID = k.ID
               WHERE k.GUID = %s AND k.TYP = 'M'""",
            (guid,)
        )
        return cur.fetchone()
