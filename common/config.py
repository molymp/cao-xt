"""
CAO-XT – Gemeinsame Datenbank-Konfiguration

Laedt DB-Parameter in der Prioritaet:
  app_prefix-Env-Vars > generische Env-Vars > caoxt.ini > Fallbacks

Beispiel:
    from common.config import load_db_config, load_environment
    env = load_environment()            # 'production' | 'training' | 'sandbox'
    cfg = load_db_config("KASSE")       # prueft KASSE_DB_LOC, dann DB_LOC, dann caoxt.ini
                                        # DB-Name wird automatisch je Umgebung gewaehlt
"""
import os
import configparser

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_INI_PATH  = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

_VALID_ENVIRONMENTS = {'production', 'training', 'sandbox'}


def load_environment() -> str:
    """Laedt die aktuelle Betriebsumgebung.

    Prioritaet: ``XT_ENVIRONMENT`` Env-Var > ``[Umgebung] xt_environment`` in caoxt.ini > ``'production'``

    Returns:
        Einer der Werte: ``'production'``, ``'training'``, ``'sandbox'``.
        Unbekannte Werte werden auf ``'production'`` normalisiert (fail-safe).
    """
    val = os.environ.get('XT_ENVIRONMENT', '').strip().lower()
    if val in _VALID_ENVIRONMENTS:
        return val

    cfg = configparser.ConfigParser()
    cfg.read(_INI_PATH)
    val = cfg.get('Umgebung', 'xt_environment', fallback='production').strip().lower()
    return val if val in _VALID_ENVIRONMENTS else 'production'


def load_db_config(app_prefix: str | None = None) -> dict:
    """Laedt DB-Konfiguration aus Env-Vars und caoxt.ini.

    Der DB-Name wird automatisch je Betriebsumgebung gewaehlt:
    - ``production``  → ``db_name`` (direkt, kein Suffix)
    - ``training``    → ``db_name_training`` falls gesetzt, sonst ``<db_name>_training``
    - ``sandbox``     → ``db_name_sandbox``  falls gesetzt, sonst ``<db_name>_sandbox``

    Expliziter app-spezifischer Env-Var (z.B. ``KASSE_DB_NAME``) oder generischer
    ``DB_NAME`` Env-Var ueberschreiben die automatische Auswahl immer.

    Args:
        app_prefix: Optionales App-Praefix fuer app-spezifische Env-Vars.
                    z.B. ``"KASSE"`` → ``KASSE_DB_LOC`` ueberschreibt ``DB_LOC``.

    Returns:
        dict mit den Schluesseln ``host``, ``port``, ``name``, ``user``, ``password``.
    """
    cfg = configparser.ConfigParser()
    cfg.read(_INI_PATH)

    def _get(env_key: str, ini_key: str, fallback: str = '') -> str:
        # 1. App-spezifischer Env-Var (z.B. KASSE_DB_LOC)
        if app_prefix:
            val = os.environ.get(f'{app_prefix}_{env_key}')
            if val is not None:
                return val
        # 2. Generischer Env-Var
        val = os.environ.get(env_key)
        if val is not None:
            return val
        # 3. caoxt.ini
        return cfg.get('Datenbank', ini_key, fallback=fallback)

    # DB-Name: expliziter Env-Var schlaegt Umgebungslogik
    explicit_name = None
    if app_prefix:
        explicit_name = os.environ.get(f'{app_prefix}_DB_NAME')
    if explicit_name is None:
        explicit_name = os.environ.get('DB_NAME')

    if explicit_name is not None:
        db_name = explicit_name
    else:
        env = load_environment()
        base_name = cfg.get('Datenbank', 'db_name', fallback='')
        if env == 'training':
            db_name = cfg.get('Datenbank', 'db_name_training', fallback='').strip() or f'{base_name}_training'
        elif env == 'sandbox':
            db_name = cfg.get('Datenbank', 'db_name_sandbox', fallback='').strip() or f'{base_name}_sandbox'
        else:
            db_name = base_name

    return {
        'host':     _get('DB_LOC',  'db_loc',  'localhost'),
        'port':     int(_get('DB_PORT', 'db_port', '3306')),
        'name':     db_name,
        'user':     _get('DB_USER', 'db_user', ''),
        'password': _get('DB_PASS', 'db_pass', ''),
    }
