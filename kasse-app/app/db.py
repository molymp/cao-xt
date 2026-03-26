"""
CAO-XT Kassen-App – Datenbankverbindung
Gleiche Muster wie kiosk-app: Connection Pool + Context-Manager.
"""
import mysql.connector
from mysql.connector import pooling
from contextlib import contextmanager
import config

_pool = pooling.MySQLConnectionPool(
    pool_name="kasse_pool",
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


@contextmanager
def get_db_transaction():
    """Atomare Transaktion – commit bei Erfolg, rollback bei Fehler."""
    conn = _get_conn()
    conn.autocommit = False
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.autocommit = True
        conn.close()


# ── Hilfsfunktionen ───────────────────────────────────────────

def cent_zu_euro_str(cent: int) -> str:
    return f"{cent / 100:.2f} €".replace(".", ",")


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


def test_verbindung() -> bool:
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False
