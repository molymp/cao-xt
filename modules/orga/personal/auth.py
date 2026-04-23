"""
CAO-XT Orga-Personal – Zugriffspruefung auf Basis der CAO-BENUTZERRECHTE.

Ein CAO-Mitarbeiter hat Zugriff auf das Backoffice-Personal-Modul, wenn seine
Gruppenzugehoerigkeit eine der in ``BACKOFFICE_GRUPPEN`` gelisteten
MODUL_NAME-Bezeichnungen traegt (Auflösung dynamisch, keine hardcodierten
GRUPPEN_IDs – siehe DECISIONS.md, Punkt "Klärung 1").
"""
from functools import wraps
from flask import session, redirect, url_for, flash

from .models import get_db_ro


BACKOFFICE_GRUPPEN = ('Administratoren', 'Ladenleitung')


def hat_backoffice_zugriff(cao_ma_id: int | None) -> bool:
    """True, wenn der CAO-User Mitglied einer Backoffice-Gruppe ist."""
    if not cao_ma_id:
        return False
    with get_db_ro() as cur:
        cur.execute(
            """
            SELECT br_grp.MODUL_NAME AS gruppe_name
              FROM BENUTZERRECHTE AS br_user
              JOIN BENUTZERRECHTE AS br_grp
                ON br_grp.GRUPPEN_ID = br_user.GRUPPEN_ID
               AND br_grp.USER_ID    = -1
               AND br_grp.MODUL_ID   = 0
               AND br_grp.SUBMODUL_ID = 0
             WHERE br_user.USER_ID    = %s
               AND br_user.MODUL_ID   = 0
               AND br_user.SUBMODUL_ID = 0
            """,
            (int(cao_ma_id),),
        )
        row = cur.fetchone()
        return bool(row and row['gruppe_name'] in BACKOFFICE_GRUPPEN)


def backoffice_required(f):
    """Decorator: leitet unangemeldete User nach /login,
    andernfalls prueft er den Backoffice-Gruppenzugriff."""
    @wraps(f)
    def _wrapper(*args, **kwargs):
        ma_id = session.get('ma_id')
        if not ma_id:
            return redirect(url_for('login'))
        if not hat_backoffice_zugriff(ma_id):
            flash('Fuer das Personal-Backoffice benoetigst du die Gruppe '
                  '"Administratoren" oder "Ladenleitung".', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return _wrapper
