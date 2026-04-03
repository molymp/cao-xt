"""
CAO-XT WaWi-App – Datenbankverbindungen
Zwei Connection Pools:
  _cao_pool  – CAO-Faktura-DB (Artikelstamm, read-only)
  _wawi_pool – WaWi-DB (Preise, read-write)
"""
import mysql.connector
from mysql.connector import pooling
from contextlib import contextmanager
import config


# ── CAO-DB Pool (read-only) ───────────────────────────────────

_cao_pool = pooling.MySQLConnectionPool(
    pool_name="wawi_cao_pool",
    pool_size=5,
    host=config.CAO_DB_HOST,
    port=config.CAO_DB_PORT,
    user=config.CAO_DB_USER,
    password=config.CAO_DB_PASSWORD,
    database=config.CAO_DB_NAME,
    charset="utf8mb4",
    use_unicode=True,
    autocommit=True,
    connection_timeout=10,
)


def _get_cao_conn():
    try:
        return _cao_pool.get_connection()
    except Exception:
        return mysql.connector.connect(
            host=config.CAO_DB_HOST,
            port=config.CAO_DB_PORT,
            user=config.CAO_DB_USER,
            password=config.CAO_DB_PASSWORD,
            database=config.CAO_DB_NAME,
            charset="utf8mb4",
            use_unicode=True,
            autocommit=True,
        )


# ── WaWi-DB Pool (read-write) ─────────────────────────────────

_wawi_pool = pooling.MySQLConnectionPool(
    pool_name="wawi_pool",
    pool_size=5,
    host=config.WAWI_DB_HOST,
    port=config.WAWI_DB_PORT,
    user=config.WAWI_DB_USER,
    password=config.WAWI_DB_PASSWORD,
    database=config.WAWI_DB_NAME,
    charset="utf8mb4",
    use_unicode=True,
    autocommit=True,
    connection_timeout=10,
)


def _get_wawi_conn():
    try:
        return _wawi_pool.get_connection()
    except Exception:
        return mysql.connector.connect(
            host=config.WAWI_DB_HOST,
            port=config.WAWI_DB_PORT,
            user=config.WAWI_DB_USER,
            password=config.WAWI_DB_PASSWORD,
            database=config.WAWI_DB_NAME,
            charset="utf8mb4",
            use_unicode=True,
            autocommit=True,
        )


# ── Context-Manager ───────────────────────────────────────────

@contextmanager
def get_cao_db():
    """CAO-DB Verbindung (read-only, autocommit)."""
    conn = _get_cao_conn()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()
        conn.close()


@contextmanager
def get_wawi_db():
    """WaWi-DB Verbindung (read-write, autocommit)."""
    conn = _get_wawi_conn()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()
        conn.close()


@contextmanager
def get_wawi_transaction():
    """Atomare WaWi-DB Transaktion – commit bei Erfolg, rollback bei Fehler."""
    conn = _get_wawi_conn()
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

def de_zu_float(wert) -> float:
    """Konvertiert DE-Dezimalformat ('1,23') oder EN-Format ('1.23') zu float."""
    if wert is None:
        return 0.0
    if isinstance(wert, (int, float)):
        return float(wert)
    bereinigt = str(wert).strip().replace(',', '.')
    try:
        return float(bereinigt)
    except ValueError:
        return 0.0


def test_verbindungen() -> dict:
    """Prüft beide DB-Verbindungen. Gibt {'cao': bool, 'wawi': bool} zurück."""
    result = {'cao': False, 'wawi': False}
    try:
        with get_cao_db() as cur:
            cur.execute("SELECT 1")
        result['cao'] = True
    except Exception:
        pass
    try:
        with get_wawi_db() as cur:
            cur.execute("SELECT 1")
        result['wawi'] = True
    except Exception:
        pass
    return result
