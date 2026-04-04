"""
Bäckerei Kiosk – Datenbankverbindung mit Connection Pool
"""

import hashlib
import mysql.connector
from mysql.connector import pooling, Error
from contextlib import contextmanager
import config


# ── Connection Pool ───────────────────────────────────────────
# Pool hält bis zu 5 Verbindungen offen und wiederverwendet sie.
# Spart pro Request den TCP-Handshake + MySQL-Authentifizierung (~20–100ms).

_pool = pooling.MySQLConnectionPool(
    pool_name="kiosk_pool",
    pool_size=5,
    host=config.DB_HOST,
    port=config.DB_PORT,
    user=config.DB_USER,
    password=config.DB_PASSWORD,
    database=config.DB_NAME,
    charset="utf8mb4",
    use_unicode=True,
    autocommit=True,
    connection_timeout=10,
)


def _get_connection():
    """Holt eine Verbindung aus dem Pool (oder öffnet eine neue als Fallback)."""
    try:
        return _pool.get_connection()
    except Exception:
        # Fallback: direkte Verbindung wenn Pool erschöpft
        return mysql.connector.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            charset="utf8mb4",
            use_unicode=True,
            autocommit=True,
        )


@contextmanager
def get_db():
    """
    Context-Manager für einfache DB-Operationen (autocommit=True).
    Gibt die Verbindung nach Nutzung zurück in den Pool.
    """
    conn = _get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()   # gibt Verbindung zurück in den Pool


@contextmanager
def get_db_transaction():
    """
    Context-Manager für atomare Transaktionen (z. B. Buchen).
    Committet bei Erfolg, rollt bei Fehler zurück.
    """
    conn = _get_connection()
    conn.autocommit = False
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.autocommit = True
        conn.close()   # gibt Verbindung zurück in den Pool


def euro_zu_cent(wert) -> int:
    if wert is None:
        return 0
    if isinstance(wert, (int, float)):
        return round(float(wert) * 100)
    bereinigt = str(wert).strip().replace(",", ".")
    try:
        return round(float(bereinigt) * 100)
    except ValueError:
        return 0


def cent_zu_euro_str(cent: int) -> str:
    return f"{cent / 100:.2f} €".replace(".", ",")


def mitarbeiter_login(login_name: str, passwort: str) -> dict | None:
    """
    Prüft Credentials gegen MITARBEITER-Tabelle.
    CAO speichert Passwörter als MD5-Hash (Großbuchstaben).
    Gibt {MA_ID, LOGIN_NAME, VNAME, NAME} zurück oder None.
    """
    pw_hash = hashlib.md5(passwort.encode('utf-8')).hexdigest().upper()
    with get_db() as cur:
        cur.execute(
            """SELECT MA_ID, LOGIN_NAME, VNAME, NAME
               FROM MITARBEITER
               WHERE LOGIN_NAME = %s AND USER_PASSWORD = %s""",
            (login_name, pw_hash)
        )
        return cur.fetchone()


def test_verbindung() -> bool:
    try:
        with get_db() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False
