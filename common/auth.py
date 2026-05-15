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


def db_signatur() -> str:
    """Kurzer Fingerprint der aktuell konfigurierten DB (host+name).

    Wird in die Session geschrieben (``db_sig``) und bei jedem Request
    gegen den aktuellen Wert geprueft. Aendert sich die DB (z.B. via
    Admin → Datenbank), passt der gespeicherte Wert nicht mehr → die
    Session wird invalidiert und der User muss sich neu anmelden, statt
    mit einer ma_id der ALTEN DB in der Permission-Hoelle festzuhaengen
    (alle Funktionen ausgegraut, kein Weg raus).

    Bewusst nur host+name (nicht User/Passwort): ein reiner Passwort-
    Wechsel auf derselben DB soll keine Sessions wegwerfen.
    """
    try:
        from common.config import load_db_config
        cfg = load_db_config()
        roh = f"{cfg.get('host', '')}:{cfg.get('port', '')}/{cfg.get('name', '')}"
    except Exception:
        roh = 'unbekannt'
    return hashlib.sha256(roh.encode('utf-8')).hexdigest()[:16]


def session_db_ok() -> bool:
    """True wenn die Session zur aktuell konfigurierten DB passt.

    False, wenn ``db_sig`` fehlt (Alt-Session aus der Zeit vor diesem
    Mechanismus → einmaliger Re-Login nach Deploy, akzeptabel) ODER
    nicht zur aktuellen DB passt (echter DB-Wechsel).
    """
    return session.get('db_sig') == db_signatur()


def login_required(f):
    """Decorator: leitet auf die Route ``'login'`` um, wenn kein MA eingeloggt
    ODER die Session zu einer anderen DB gehoert (DB wurde gewechselt).

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
        if not session_db_ok():
            # DB hat sich geaendert (oder Alt-Session ohne Stempel):
            # harte Invalidierung, sonst landet der User in einem
            # Zustand wo nichts klickbar ist und Logout nicht greift.
            session.clear()
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
    # DB-Stempel: bindet die Session an die DB, gegen die gerade
    # authentifiziert wurde. Wechselt die DB, wird die Session beim
    # naechsten Request via session_db_ok() invalidiert.
    session['db_sig']     = db_signatur()


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
    """Login per Mitarbeiter-Karte (Barcode-Scan) ODER RFID-Tag.

    1. Liest KARTEN.GUID, prueft TYP='M' (Mitarbeiter) und loest ueber
       KARTEN.ID den zugehoerigen MITARBEITER auf (klassische
       Mitarbeiterkarte).
    2. Wenn nichts gefunden, faellt auf XT_MITARBEITER_RFID zurueck:
       Mitarbeiter haben ihren Alarm-RFID-Tag eingetragen, dieser
       authentifiziert sie genauso wie eine Mitarbeiterkarte.

    Args:
        guid: Gescannter Barcode-/RFID-Wert.

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
        treffer = cur.fetchone()
    if treffer:
        return treffer
    # Fallback: Mitarbeiter-RFID-Tag (Dorfkern XT-Tabelle)
    try:
        from common import rfid as _rfid
        return _rfid.finde_ma_per_rfid(guid)
    except Exception as exc:  # pragma: no cover – Modul fehlt nicht
        import logging
        logging.getLogger(__name__).warning(
            "RFID-Fallback fehlgeschlagen: %s", exc)
        return None
