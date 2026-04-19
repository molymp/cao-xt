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


def _registry_email_lesen_debug() -> dict:
    r"""Interne Variante von ``_registry_email_lesen`` mit Diagnose-Infos.

    Rueckgabe:
        ``{'daten': {NAME: wert}, 'mainkeys': [...], 'rows': int,
           'fehler': str|None, 'sql': str}``

    Nutzt ``MAINKEY LIKE 'MAIN%EMAIL'`` (%=beliebig, _=1 Zeichen) und matcht
    damit sowohl ``MAIN\EMAIL`` (CAO-Standard, Backslash) als auch
    ``MAIN/EMAIL`` oder ``MAIN_EMAIL``. Backslashes in String-Literalen
    wurden historisch schon mehrfach durch MySQL-Escape-Regeln beschaedigt;
    das ``LIKE`` umgeht das komplett.

    Fail-safe: liefert ``daten={}`` und traegt den Fehler in ``fehler`` ein,
    wenn DB nicht erreichbar ist – damit die Diagnose-Seite das anzeigen kann.
    """
    sql = ("SELECT MAINKEY, NAME, VAL_CHAR, VAL_INT, VAL_INT2, VAL_DOUBLE "
           "FROM REGISTRY WHERE MAINKEY LIKE 'MAIN%EMAIL'")
    info: dict = {'daten': {}, 'mainkeys': [], 'rows': 0,
                  'fehler': None, 'sql': sql}
    try:
        from common.db import get_db  # lazy: vermeidet Zyklus + Init-Order
    except Exception as exc:
        info['fehler'] = f'common.db nicht importierbar: {exc}'
        return info
    try:
        with get_db() as cur:
            cur.execute(sql)
            rows = cur.fetchall() or []
    except Exception as exc:
        info['fehler'] = f'{type(exc).__name__}: {exc}'
        return info

    info['rows'] = len(rows)
    mainkeys: set[str] = set()
    for r in rows:
        mk = r.get('MAINKEY')
        if mk:
            mainkeys.add(str(mk))
        name = (r.get('NAME') or '').strip().upper()
        if not name:
            continue
        val = r.get('VAL_CHAR')
        if val is None or str(val).strip() == '':
            for k in ('VAL_INT2', 'VAL_INT', 'VAL_DOUBLE'):
                if r.get(k) is not None:
                    val = r[k]
                    break
        if val is not None and str(val).strip() != '':
            info['daten'][name] = str(val).strip()
    info['mainkeys'] = sorted(mainkeys)
    return info


def _registry_email_lesen() -> dict:
    r"""Liest alle Eintraege aus CAO-REGISTRY unter ``MAINKEY LIKE 'MAIN%EMAIL'``.

    Rueckgabe: ``{uppercase_name: wert}``. Wert stammt aus ``VAL_CHAR`` und
    faellt auf ``VAL_INT2`` / ``VAL_INT`` / ``VAL_DOUBLE`` zurueck, wenn
    ``VAL_CHAR`` leer ist.

    Fail-safe: gibt ``{}`` zurueck, wenn der DB-Pool nicht initialisiert ist
    (z.B. beim Laden vor App-Start, in Tests) oder die REGISTRY-Tabelle
    nicht erreichbar ist. Dann greifen die ENV/INI-Fallbacks in
    ``load_email_config``.
    """
    return _registry_email_lesen_debug()['daten']


# ── Email-Config ──────────────────────────────────────────────────────────────

# Tabelle: Logischer Key → (REGISTRY-NAME-Kandidaten, ENV-Suffix, INI-Key, Fallback)
# Erster Kandidat ist immer der Config-Key in UPPER – das ist unsere Konvention
# in der CAO-REGISTRY. Weitere Eintraege sind Alias-Schreibweisen fuer Kompat.
_EMAIL_KEYS: list[tuple[str, list[str], str, str, str]] = [
    ('smtp_host', ['SMTP_HOST', 'SMTPSERVER', 'SMTP_SERVER', 'SERVER', 'HOST'],
                  'SMTP_HOST', 'smtp_host', ''),
    ('smtp_port', ['SMTP_PORT', 'SMTPPORT', 'PORT'],
                  'SMTP_PORT', 'smtp_port', '587'),
    ('smtp_user', ['SMTP_USER', 'SMTPUSER', 'USER', 'USERNAME', 'LOGIN'],
                  'SMTP_USER', 'smtp_user', ''),
    ('smtp_pass', ['SMTP_PASS', 'SMTPPASS', 'PASSWORD', 'PASS', 'KENNWORT'],
                  'SMTP_PASS', 'smtp_pass', ''),
    ('smtp_tls',  ['SMTP_TLS', 'SMTP_SSLTLS', 'TLS', 'STARTTLS', 'SSL', 'USETLS'],
                  'SMTP_TLS', 'smtp_tls', '1'),
    ('from_addr', ['FROM_ADDR', 'SMTP_SENDER', 'FROMADDR', 'FROM',
                   'ABSENDER', 'EMAIL', 'MAIL'],
                  'FROM_ADDR', 'from_addr', ''),
    ('from_name', ['FROM_NAME', 'SMTP_SENDERNAME', 'FROMNAME', 'NAME',
                   'ABSENDERNAME'],
                  'FROM_NAME', 'from_name', 'CAO-XT Schichtplan'),
    ('dev_mode',  ['DEV_MODE', 'DEVMODE', 'DEV', 'TESTMODUS', 'TEST'],
                  'DEV_MODE', 'dev_mode', '0'),
    # Optionaler Use-Case-spezifischer Absender fuer Schichtplan-Mails.
    # Wenn gesetzt, nutzt ``schichtplan_freigabe_emails_senden`` diesen
    # Wert als ``from_addr`` UND ``reply_to`` (ueberschreibt den generellen
    # ``from_addr``/den Backoffice-User).
    ('sender_shift', ['SENDER_SHIFT', 'SMTP_SENDER_SHIFT',
                      'SHIFT_SENDER', 'SCHICHT_SENDER'],
                     'SENDER_SHIFT', 'sender_shift', ''),
]

# Keys, die als Bool interpretiert werden.
_EMAIL_BOOL_KEYS = {'smtp_tls', 'dev_mode'}
# Keys, die als Int interpretiert werden.
_EMAIL_INT_KEYS = {'smtp_port'}


def _email_as_bool(s: str) -> bool:
    return str(s).strip().lower() not in ('', '0', 'false', 'no', 'nein')


def load_email_config() -> dict:
    r"""Laedt SMTP-/Email-Konfiguration aus CAO-REGISTRY, ENV und caoxt.ini.

    Prioritaet je Key:
      1. CAO-REGISTRY ``MAIN\EMAIL`` (primaere Quelle im Live-Betrieb)
      2. ENV-Variable ``XT_EMAIL_<KEY>`` (Dev-Override)
      3. ``[Email] <key>`` in ``caoxt.ini`` (Standalone-Fallback)

    Der logische Key in UPPER (``SMTP_HOST``, ``FROM_ADDR``, ``DEV_MODE`` …)
    ist der erste REGISTRY-NAME-Kandidat. Fuer Alt-Installationen/Fremd-
    systeme werden auch gaengige Alias-Namen (``SMTPSERVER``/``HOST`` etc.)
    gematcht.

    Returns:
        dict mit ``smtp_host``, ``smtp_port`` (int), ``smtp_user``,
        ``smtp_pass``, ``smtp_tls`` (bool), ``from_addr``, ``from_name``,
        ``dev_mode`` (bool). Leere Strings bleiben leer – der Email-Helper
        prueft selbst, ob Versand moeglich ist (``smtp_host`` + ``from_addr``).
        ``dev_mode=True`` → Aufrufer leitet alle Mails an den jeweiligen
        Absender statt an die eigentlichen Empfaenger um.
    """
    reg = _registry_email_lesen()

    cfg = configparser.ConfigParser()
    cfg.read(_INI_PATH)

    def _get(reg_keys: list[str], env_key: str, ini_key: str,
             fallback: str = '') -> str:
        for k in reg_keys:
            v = reg.get(k.upper())
            if v is not None and str(v).strip():
                return str(v).strip()
        v = os.environ.get(f'XT_EMAIL_{env_key}')
        if v is not None:
            return v
        return cfg.get('Email', ini_key, fallback=fallback)

    out: dict = {}
    for key, reg_kandidaten, env_suffix, ini_key, fallback in _EMAIL_KEYS:
        raw = _get(reg_kandidaten, env_suffix, ini_key, fallback)
        if key in _EMAIL_INT_KEYS:
            out[key] = int(raw or fallback or '0')
        elif key in _EMAIL_BOOL_KEYS:
            out[key] = _email_as_bool(raw)
        else:
            out[key] = raw
    return out


# ── Diagnose ──────────────────────────────────────────────────────────────────


def email_config_diagnose() -> dict:
    r"""Liefert die Email-Config inkl. Herkunft pro Key – fuer UI-Diagnose.

    Returns:
        dict mit:
          * ``config``      – effektives Ergebnis wie ``load_email_config()``
                              (``smtp_pass`` maskiert)
          * ``sources``     – pro logischem Key ein Dict
                              ``{'quelle': 'registry|env|ini|fallback',
                                 'detail': str, 'roh': str}``
          * ``registry``    – Roh-Eintraege aus ``MAIN\EMAIL`` (passwort-maskiert)
          * ``env``         – gesetzte ``XT_EMAIL_*``-Variablen (maskiert)
          * ``ini_vorhanden`` – bool, ob ``caoxt.ini`` die ``[Email]``-Sektion hat
    """
    reg_debug = _registry_email_lesen_debug()
    reg = reg_debug['daten']

    ini = configparser.ConfigParser()
    ini.read(_INI_PATH)
    ini_vorhanden = ini.has_section('Email')

    def _mask(v: str) -> str:
        if not v:
            return ''
        return v[:2] + '…' + v[-1:] if len(v) > 4 else '…'

    cfg = load_email_config()
    cfg_maskiert = dict(cfg)
    if cfg_maskiert.get('smtp_pass'):
        cfg_maskiert['smtp_pass'] = _mask(cfg_maskiert['smtp_pass'])

    sources: dict[str, dict] = {}
    for key, reg_kandidaten, env_suffix, ini_key, fallback in _EMAIL_KEYS:
        quelle = 'fallback'
        detail = f'caoxt.ini-Default "{fallback}"'
        roh = fallback
        # 1) REGISTRY
        treffer_reg = None
        for name in reg_kandidaten:
            v = reg.get(name.upper())
            if v is not None and str(v).strip():
                treffer_reg = (name.upper(), str(v).strip())
                break
        env_name = f'XT_EMAIL_{env_suffix}'
        env_val = os.environ.get(env_name)
        ini_val = ini.get('Email', ini_key, fallback=None) if ini_vorhanden else None

        if treffer_reg is not None:
            quelle = 'registry'
            detail = f"REGISTRY MAIN\\EMAIL / {treffer_reg[0]}"
            roh = treffer_reg[1]
        elif env_val is not None:
            quelle = 'env'
            detail = env_name
            roh = env_val
        elif ini_val is not None and ini_val != '':
            quelle = 'ini'
            detail = f'caoxt.ini [Email] {ini_key}'
            roh = ini_val
        # Passwort nicht im Klartext zeigen
        if key == 'smtp_pass':
            roh = _mask(roh)
        sources[key] = {'quelle': quelle, 'detail': detail, 'roh': roh}

    # Roh-REGISTRY (maskiert)
    reg_anzeige = {k: (_mask(v) if 'PASS' in k else v) for k, v in reg.items()}

    env_anzeige = {}
    for _key, _reg, env_suffix, _ini, _fb in _EMAIL_KEYS:
        name = f'XT_EMAIL_{env_suffix}'
        if name in os.environ:
            v = os.environ[name]
            env_anzeige[name] = _mask(v) if 'PASS' in env_suffix else v

    return {
        'config':         cfg_maskiert,
        'sources':        sources,
        'registry':       reg_anzeige,
        'registry_debug': {
            'sql':      reg_debug['sql'],
            'rows':     reg_debug['rows'],
            'mainkeys': reg_debug['mainkeys'],
            'fehler':   reg_debug['fehler'],
        },
        'env':            env_anzeige,
        'ini_vorhanden':  ini_vorhanden,
    }
