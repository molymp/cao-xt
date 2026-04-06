"""
CAO-XT WaWi-App – Datenbankverbindung
Lazy-initialisierter Connection Pool: der Pool wird erst beim ersten
DB-Aufruf erstellt, nicht schon beim Import. So startet die App auch
dann, wenn die DB beim Start nicht erreichbar ist (z. B. keine
config_local.py vorhanden).
"""
import mysql.connector
from mysql.connector import pooling
from contextlib import contextmanager
import threading
import config

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
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
    return _pool


def _get_conn():
    try:
        return _get_pool().get_connection()
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
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


# Alias: CFO-Berichte lesen aus derselben CAO-DB wie der WaWi-Pool
get_cao_db = get_db
