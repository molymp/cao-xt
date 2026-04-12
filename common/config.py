"""
CAO-XT – Gemeinsame Datenbank-Konfiguration

Laedt DB-Parameter in der Prioritaet:
  app_prefix-Env-Vars > generische Env-Vars > caoxt.ini > Fallbacks

Beispiel:
    from common.config import load_db_config, load_environment
    env = load_environment()   # 'produktion' | 'training'
    cfg = load_db_config("KASSE")   # prueft KASSE_DB_LOC, dann DB_LOC, dann caoxt.ini
"""
import os
import configparser

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_INI_PATH  = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

_VALID_ENVIRONMENTS = {'produktion', 'training'}


def load_environment() -> str:
    """Laedt die aktuelle Betriebsumgebung der Kasse.

    Prioritaet: ``XT_ENVIRONMENT`` Env-Var > ``[Umgebung] xt_environment`` in caoxt.ini > ``'produktion'``

    Returns:
        ``'produktion'`` (Normalbetrieb) oder ``'training'`` (Trainingsmodus).
        Unbekannte Werte werden auf ``'produktion'`` normalisiert (fail-safe).

    Hinweis: Alle Apps nutzen dieselbe Datenbank – dieser Wert steuert nur
    den Kasse-Betriebsmodus, nicht die DB-Auswahl.
    """
    val = os.environ.get('XT_ENVIRONMENT', '').strip().lower()
    if val in _VALID_ENVIRONMENTS:
        return val

    cfg = configparser.ConfigParser()
    cfg.read(_INI_PATH)
    val = cfg.get('Umgebung', 'xt_environment', fallback='produktion').strip().lower()
    return val if val in _VALID_ENVIRONMENTS else 'produktion'


def load_db_config(app_prefix: str | None = None) -> dict:
    """Laedt DB-Konfiguration aus Env-Vars und caoxt.ini.

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

    return {
        'host':     _get('DB_LOC',  'db_loc',  'localhost'),
        'port':     int(_get('DB_PORT', 'db_port', '3306')),
        'name':     _get('DB_NAME', 'db_name', ''),
        'user':     _get('DB_USER', 'db_user', ''),
        'password': _get('DB_PASS', 'db_pass', ''),
    }
