"""
CAO-XT WaWi-App – Datenbankverbindung
Analoges Muster zu kasse-app/app/db.py: Connection Pool + Context-Manager.
"""
import mysql.connector
from mysql.connector import pooling
from contextlib import contextmanager
import config

_pool = pooling.MySQLConnectionPool(
    pool_name="wawi_pool",
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


def _get_conn():
    try:
        return _pool.get_connection()
    except Exception:
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
    """Einfache DB-Operation (autocommit)."""
    conn = _get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()
        conn.close()


def test_verbindung() -> bool:
    """Gibt True zurück wenn die Datenbankverbindung funktioniert."""
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False
