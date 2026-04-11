"""
CAO-XT – Gemeinsamer Datenbankzugang

Lazy-initialisierter Connection Pool: der Pool wird erst beim ersten DB-Aufruf
erstellt. Jede App ruft ``init_pool()`` beim Start auf um Pool-Name und
Konfiguration zu setzen.

Verwendung::

    # In app.py nach config-Import:
    from common.db import init_pool, get_db, get_db_transaction
    init_pool("kasse_pool", db_config={
        'host': config.DB_HOST, 'port': config.DB_PORT,
        'name': config.DB_NAME, 'user': config.DB_USER,
        'password': config.DB_PASSWORD,
    })
"""
import threading
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

_pool: pooling.MySQLConnectionPool | None = None
_pool_lock    = threading.Lock()
_pool_name    = "common_pool"
_pool_size    = 5
_pool_config: dict | None = None


def init_pool(
    pool_name: str,
    pool_size: int = 5,
    db_config: dict | None = None,
) -> None:
    """Konfiguriert den globalen Connection Pool.

    Der Pool wird lazy beim ersten DB-Zugriff erstellt. Falls ``db_config``
    nicht angegeben, wird ``common.config.load_db_config()`` als Fallback
    verwendet.

    Args:
        pool_name: Name des Pools (z.B. ``"kasse_pool"``).
        pool_size: Maximale Anzahl gleichzeitiger Verbindungen (Standard 5).
        db_config: dict mit host, port, name, user, password. Optional.
    """
    global _pool_name, _pool_size, _pool_config, _pool
    _pool_name = pool_name
    _pool_size = pool_size
    if db_config is not None:
        _pool_config = db_config
    with _pool_lock:
        _pool = None  # Reset → wird beim naechsten _get_pool() neu erstellt


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool, _pool_config
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                cfg = _pool_config
                if cfg is None:
                    from common.config import load_db_config
                    cfg = load_db_config()
                _pool = pooling.MySQLConnectionPool(
                    pool_name=_pool_name,
                    pool_size=_pool_size,
                    host=cfg['host'],
                    port=cfg['port'],
                    user=cfg['user'],
                    password=cfg['password'],
                    database=cfg['name'],
                    charset='utf8mb4',
                    use_unicode=True,
                    autocommit=True,
                    connection_timeout=10,
                )
    return _pool


def _get_conn() -> mysql.connector.MySQLConnection:
    try:
        return _get_pool().get_connection()
    except Exception:
        cfg = _pool_config or {}
        return mysql.connector.connect(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('port', 3306),
            user=cfg.get('user', ''),
            password=cfg.get('password', ''),
            database=cfg.get('name', ''),
            charset='utf8mb4',
            use_unicode=True,
            autocommit=True,
        )


@contextmanager
def get_db():
    """Context-Manager fuer einfache DB-Operationen (autocommit=True).

    Gibt den Cursor nach Nutzung zurueck in den Pool::

        with get_db() as cur:
            cur.execute("SELECT 1")
    """
    conn = _get_conn()
    cur  = conn.cursor(dictionary=True)
    try:
        yield cur
    finally:
        cur.close()
        conn.close()


@contextmanager
def get_db_transaction():
    """Context-Manager fuer atomare Transaktionen.

    Committet bei Erfolg, rollt bei Exception zurueck::

        with get_db_transaction() as cur:
            cur.execute("INSERT ...")
            cur.execute("UPDATE ...")
    """
    conn = _get_conn()
    conn.autocommit = False
    cur  = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.autocommit = True
        conn.close()


def cent_zu_euro_str(cent: int) -> str:
    """Cent-Betrag als deutschen Euro-String. z.B. ``123`` → ``'1,23 €'``"""
    return f"{cent / 100:.2f} €".replace(".", ",")


def euro_zu_cent(wert) -> int:
    """Euro-Wert (int, float oder str mit Komma/Punkt) in Cent umrechnen."""
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
    """Prueft DB-Verbindung mit SELECT 1. Gibt ``True`` bei Erfolg zurueck."""
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False
