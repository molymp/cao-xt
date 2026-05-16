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


def _pruefe_db_whitelist(db_name: str) -> None:
    """Blockt harte Writes gegen bekannte Produktions-DBs aus Dev-Instanzen.

    Liest ``[Sicherheit] verbotene_db_namen`` aus ``caoxt.ini`` (oder
    ``XT_FORBIDDEN_DB_NAMES``-Env-Var). Passt ``db_name`` auf einen dieser
    Werte (case-insensitiv), wird der App-Start mit ``RuntimeError``
    abgebrochen – bevor eine Verbindung entsteht.

    Leere Blacklist (Default) = kein Check, kein Verhaltensunterschied zu v2.0.
    """
    from common.config import load_security_config
    sec = load_security_config()
    verboten = sec.get('verbotene_db_namen') or []
    if db_name and db_name.lower() in verboten:
        raise RuntimeError(
            f"DB-Sicherheits-Sperre: Verbindung zu '{db_name}' ist in dieser "
            f"Instanz verboten (caoxt.ini [Sicherheit] verbotene_db_namen). "
            f"Korrigiere [Datenbank] db_name auf eine Entwicklungs-DB, "
            f"oder entferne den Eintrag aus der Blacklist."
        )


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool, _pool_config
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                cfg = _pool_config
                if cfg is None:
                    from common.config import load_db_config
                    cfg = load_db_config()
                _pruefe_db_whitelist(cfg.get('name', ''))
                _pool = pooling.MySQLConnectionPool(
                    pool_name=_pool_name,
                    pool_size=_pool_size,
                    pool_reset_session=False,   # !! Performance-kritisch
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
                # Hintergrund: pool_reset_session=True (Default) ruft bei
                # jedem ``close()`` ein ``cnx.reset_session()`` auf — das
                # ist ein zusaetzlicher Roundtrip pro Pool-Return UND macht
                # alle SESSION-Variablen platt (z.B. unsere
                # max_statement_time-Settings, siehe _setze_query_timeout).
                # Mit reset_session=False sparen wir 30-100ms pro
                # ``get_db()``-Aufruf, und die Timeout-Caching-Logik in
                # ``_setze_query_timeout`` wird tatsaechlich wirksam.
                # Trade-off: SESSION-State (User-Variablen, temporaere
                # Tabellen) lebt ueber den Pool-Return hinaus. Wir nutzen
                # nichts davon — die einzigen SESSION-Variablen sind unsere
                # eigenen Timeout-Settings, die wir explizit verwalten wollen.
    return _pool


# Server-seitiger Query-Timeout (Sekunden). MariaDB nutzt
# ``max_statement_time`` (FLOAT, Sekunden), MySQL nutzt
# ``max_execution_time`` (INT, Millisekunden) — wir setzen beide,
# der Server ignoriert die jeweils andere.
#
# Hintergrund: ohne diesen Timeout hingen Picker-SELECTs mehrere
# Stunden in State "Sending data", weil das TCP-FIN vom Python-Client
# durch MyFRITZ-NAT verloren ging und der Server beim ``send()``
# blockierte — und dabei den MyISAM-READ-Lock auf ADRESSEN hielt.
# Mit 30s SELF-Kill loest sich der Stau automatisch nach einer halben Minute.
_QUERY_TIMEOUT_SEC = 30


def _setze_query_timeout(conn) -> None:
    """Setzt ``max_statement_time`` (MariaDB) und ``max_execution_time``
    (MySQL) je Session, ignoriert wenn die Variable nicht existiert.

    Performance-Kritisch: SESSION-Variablen ueberleben Pool-Checkout/Return,
    daher cachen wir per Connection-Objekt, dass die Variablen schon
    gesetzt sind, und ueberspringen den Roundtrip beim naechsten Aufruf.
    Spart 30-50ms pro ``get_db()``-Call.

    ``conn`` kann ein PooledMySQLConnection-Wrapper sein — der Pool legt
    pro Checkout einen frischen Wrapper an, das umschliessende
    ``_cnx``-Objekt aber bleibt stabil. Wir markieren daher das innere
    ``_cnx`` (Fallback: ``conn`` selbst, falls kein Pool-Wrapper).
    """
    target = getattr(conn, '_cnx', conn)
    if getattr(target, '_xt_timeout_set', False):
        return
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"SET SESSION max_statement_time = {_QUERY_TIMEOUT_SEC}")
            target._xt_server_var = 'max_statement_time'
        except mysql.connector.Error:
            try:
                cur.execute(
                    f"SET SESSION max_execution_time = {_QUERY_TIMEOUT_SEC * 1000}"
                )
                target._xt_server_var = 'max_execution_time'
            except mysql.connector.Error:
                target._xt_server_var = None
        cur.close()
        target._xt_timeout_set = True
    except Exception:
        # Best effort — falls Setup fehlschlaegt, lieber ohne Timeout
        # weiterarbeiten als die Connection verlieren
        pass


def _get_conn() -> mysql.connector.MySQLConnection:
    """Holt eine Pool-Verbindung und prueft per ping, dass sie lebt.

    NAT-Middleboxes (FritzBox MyFRITZ, viele Consumer-Router) droppen
    idle TCP-Flows nach 2-5 Minuten, ohne dass MySQL-Server oder Pool
    das mitbekommen. Der Pool haelt also tote Sockets fuer Stunden,
    und der naechste ``cursor.execute()`` blockt minutenlang auf
    Kernel-TCP-Retransmits. Mit ``ping(reconnect=True)`` erkennen
    wir den toten Socket billig (1 Byte Write + ACK) und bauen ihn
    transparent neu auf.

    Zusaetzlich setzen wir je Connection ``max_statement_time``
    (MariaDB) bzw. ``max_execution_time`` (MySQL) auf 30s — siehe
    ``_QUERY_TIMEOUT_SEC``.

    Faellt der Pool komplett aus oder schlaegt ping auch nach Retry
    fehl, wird eine frische (nicht gepoolte) Verbindung als Fallback
    aufgebaut – wie frueher.
    """
    try:
        conn = _get_pool().get_connection()
        conn.ping(reconnect=True, attempts=2, delay=0)
        _setze_query_timeout(conn)
        return conn
    except Exception:
        cfg = _pool_config or {}
        _pruefe_db_whitelist(cfg.get('name', ''))
        conn = mysql.connector.connect(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('port', 3306),
            user=cfg.get('user', ''),
            password=cfg.get('password', ''),
            database=cfg.get('name', ''),
            charset='utf8mb4',
            use_unicode=True,
            autocommit=True,
        )
        _setze_query_timeout(conn)
        return conn


def effektive_db_config() -> dict:
    """Liefert die tatsächlich genutzte DB-Konfiguration.

    Bevorzugt das per :func:`init_pool` gesetzte ``_pool_config`` (= das,
    womit die laufende App wirklich verbunden ist – z.B. aus
    ``config_local.py``); sonst Fallback auf
    :func:`common.config.load_db_config` (Env/caoxt.ini).

    Zweck: Standalone-Helfer (z.B. der von Jameica via ``-P`` gestartete
    ``installer.hibiscus_pw``) bekommen so die echten Zugangsdaten als
    Env mit, ohne ein App-``config``-Modul importieren zu müssen.
    """
    if _pool_config is not None:
        return dict(_pool_config)
    from common.config import load_db_config
    return load_db_config()


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


# Prozess-weit gecachtes Ergebnis von test_verbindung() — wird in
# Context-Processors ALLER Apps pro Page-Render aufgerufen, was bei
# 170ms pro DB-Roundtrip ueber MyFRITZ-NAT direkt 170ms Latenz pro
# Seite kostet. 30s TTL: bei Ausfall sieht der User die rote Ampel
# spaetestens nach einer halben Minute.
import time as _time
_test_verbindung_cache: tuple[float, bool] | None = None
_TEST_VERBINDUNG_TTL_SEC = 30


def test_verbindung(force: bool = False) -> bool:
    """Prueft DB-Verbindung mit SELECT 1. Gibt ``True`` bei Erfolg zurueck.

    Ergebnis wird prozess-weit fuer 30 Sekunden gecached, damit
    Context-Processors auf jeder Page-Render-Iteration nicht eine
    eigene DB-Roundtrip aufmachen. Mit ``force=True`` cache umgehen
    (z.B. fuer explizite Healthcheck-Routen).
    """
    global _test_verbindung_cache
    if not force and _test_verbindung_cache is not None:
        ts, val = _test_verbindung_cache
        if _time.time() - ts < _TEST_VERBINDUNG_TTL_SEC:
            return val
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        result = True
    except Exception:
        result = False
    _test_verbindung_cache = (_time.time(), result)
    return result
