"""
CAO-XT DB-Initialisierung

Erkennt ob es eine Neuinstallation (leere DB) oder eine CAO-DB ist
und richtet die benötigten XT_*-Tabellen ein.

Strategie:
  SHOW TABLES LIKE 'MITARBEITER' → vorhanden = CAO-DB
  nicht vorhanden = leere/neue DB (Standalone-Modus, Backlog)

Alle Statements sind idempotent (CREATE TABLE IF NOT EXISTS).
"""
import configparser
import os
import sys

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    mysql = None  # type: ignore
    MySQLError = Exception  # type: ignore

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))

# ── Erkennungs-Tabelle für CAO-DB ──────────────────────────────────────────
_CAO_MARKER_TABLE = 'MITARBEITER'


def _connect(host: str, port: int, name: str, user: str, password: str):
    """Öffnet MySQL-Verbindung. Wirft MySQLError bei Fehler."""
    if mysql is None:
        raise ImportError("mysql-connector-python nicht installiert. "
                          "Bitte: pip3 install mysql-connector-python")
    return mysql.connector.connect(
        host=host, port=port, database=name,
        user=user, password=password,
        connection_timeout=10,
    )


def test_connection(host: str, port: int, name: str,
                    user: str, password: str) -> tuple[bool, str]:
    """Testet die DB-Verbindung. Gibt (ok, fehlermeldung) zurück."""
    try:
        conn = _connect(host, port, name, user, password)
        conn.close()
        return True, ""
    except Exception as e:
        return False, str(e)


def detect_db_type(host: str, port: int, name: str,
                   user: str, password: str) -> str:
    """
    Erkennt den DB-Typ.

    Returns:
        'cao'       – CAO-Faktura-Datenbank (MITARBEITER-Tabelle vorhanden)
        'empty'     – Leere/neue Datenbank
        'unknown'   – Verbindungsfehler
    """
    try:
        conn = _connect(host, port, name, user, password)
        cursor = conn.cursor()
        cursor.execute(f"SHOW TABLES LIKE '{_CAO_MARKER_TABLE}'")
        found = cursor.fetchone() is not None
        cursor.close()
        conn.close()
        return 'cao' if found else 'empty'
    except Exception:
        return 'unknown'


def init_cao_db(host: str, port: int, name: str,
                user: str, password: str,
                print_fn=print) -> bool:
    """
    Initialisiert XT_*-Tabellen in einer CAO-DB.
    Ruft die app-eigenen Migrationsfunktionen auf (CREATE TABLE IF NOT EXISTS).

    Gibt True bei Erfolg zurück.
    """
    print_fn("  Erkannt: CAO-Faktura-Datenbank")
    print_fn("  Lege XT_*-Tabellen an (idempotent) …")

    # Jede App initialisiert ihre Tabellen selbst über eine init-Funktion.
    # Wir fügen das Repo-Root zum sys.path hinzu und rufen die Funktionen auf.
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

    errors = []

    # Admin-App Init
    try:
        from admin_app_init import run_migrations  # noqa: F401
        print_fn("  ✓  admin: Tabellen angelegt")
    except ImportError:
        # Kein separates Init-Modul – Flask legt Tabellen beim Start an
        print_fn("  –  admin: Init via App-Start")
    except Exception as e:
        errors.append(f"admin: {e}")

    # Orga Init
    try:
        from orga_app_init import run_migrations  # noqa: F401
        print_fn("  ✓  orga: Tabellen angelegt")
    except ImportError:
        print_fn("  –  orga: Init via App-Start")
    except Exception as e:
        errors.append(f"orga: {e}")

    # Kasse Init
    try:
        from kasse_app_init import run_migrations  # noqa: F401
        print_fn("  ✓  kasse: Tabellen angelegt")
    except ImportError:
        print_fn("  –  kasse: Init via App-Start")
    except Exception as e:
        errors.append(f"kasse: {e}")

    # Kiosk Init (eigene Datenbank wird separat behandelt)
    print_fn("  –  kiosk: nutzt separate DB (in caoxt.ini konfiguriert)")

    if errors:
        for err in errors:
            print_fn(f"  ✗  {err}")
        return False

    print_fn("  ✓  DB-Initialisierung abgeschlossen")
    return True


def init_empty_db(host: str, port: int, name: str,
                  user: str, password: str,
                  print_fn=print) -> bool:
    """
    Standalone-Modus: Legt alle Schema-Tabellen in einer leeren DB an.
    [BACKLOG – noch nicht vollständig unterstützt]
    """
    print_fn("  Erkannt: Leere Datenbank (Standalone-Modus)")
    print_fn("  ⚠  Standalone-Modus ist noch nicht vollständig implementiert (Backlog).")
    print_fn("  ⚠  Bitte eine bestehende CAO-Faktura-Datenbank verwenden.")
    return False


def write_ini(ini_path: str,
              host: str, port: int, name: str,
              user: str, password: str,
              environment: str,
              active_apps: list,
              kiosk_db_name: str = '') -> None:
    """Schreibt (oder überschreibt) caoxt.ini mit den gegebenen Werten."""
    cfg = configparser.ConfigParser()

    # Bestehende Werte laden um nicht-DB-Sektionen zu erhalten
    cfg.read(ini_path)

    cfg['Datenbank'] = {
        'db_loc':  host,
        'db_port': str(port),
        'db_name': name,
        'db_user': user,
        'db_pass': password,
    }
    if kiosk_db_name:
        cfg['DatenbankKiosk'] = {
            'db_loc':  host,
            'db_port': str(port),
            'db_name': kiosk_db_name,
            'db_user': user,
            'db_pass': password,
        }

    cfg['Umgebung'] = {
        'xt_environment': environment,
    }

    cfg['Installation'] = {
        'aktive_apps': ','.join(active_apps),
    }

    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
    with open(ini_path, 'w') as f:
        cfg.write(f)
