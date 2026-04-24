"""
Unit-Tests fuer admin-app/app/system_haccp_poller.py.
"""
import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'system_haccp_poller.py')


class _FakeCursor:

    def __init__(self, row):
        self._row = row
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
        self._naechste = [self._row] if self._row else []

    def fetchall(self):
        return self._naechste

    def fetchone(self):
        return self._naechste[0] if self._naechste else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade(db_row, daemon_status, env_overrides=None,
          konfig_werte=None):
    """``konfig_werte``: dict {schluessel: wert} – was common.konfig.get
    zurueckliefern soll. None = als 'nicht gesetzt' behandeln.
    """
    # Fake db
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: _FakeCursor(db_row)
    sys.modules['db'] = fake_db

    # Fake installer.app_manager
    installer_pkg = types.ModuleType('installer')
    installer_pkg.__path__ = []
    sys.modules['installer'] = installer_pkg
    fake_mgr = types.SimpleNamespace(
        APPS={'haccp-poller': {'module': 'modules.haccp.poller'}},
        status_app=lambda n: daemon_status,
    )
    sys.modules['installer.app_manager'] = fake_mgr

    # Fake common.konfig
    werte = dict(konfig_werte or {})
    common_pkg = types.ModuleType('common')
    common_pkg.__path__ = []
    sys.modules['common'] = common_pkg
    fake_konfig = types.SimpleNamespace(
        get=lambda key, default=None: werte.get(key, default),
        set=lambda key, wert, **kw: werte.__setitem__(key, wert),
    )
    sys.modules['common.konfig'] = fake_konfig

    # Env-Variablen setzen
    if env_overrides is not None:
        for k in ('TFA_API_KEY', 'TFA_BASE_URL', 'HACCP_POLL_INTERVALL_S'):
            os.environ.pop(k, None)
        for k, v in env_overrides.items():
            os.environ[k] = v

    sys.modules.pop('hp_test', None)
    spec = importlib.util.spec_from_file_location('hp_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._konfig_werte = werte   # fuer Asserts
    return mod


class TestHaccpPollerStatus(unittest.TestCase):

    def test_keine_heartbeat_zeile(self):
        mod = _lade(db_row=None,
                    daemon_status={'running': False, 'pid': None,
                                   'log': '/tmp/h.log'},
                    env_overrides={})
        s = mod.status()
        self.assertFalse(s['heartbeat']['vorhanden'])
        self.assertFalse(s['daemon']['running'])

    def test_heartbeat_vorhanden(self):
        jetzt = datetime.utcnow()
        row = {
            'LAST_RUN_AT':       jetzt - timedelta(seconds=30),
            'LAST_SUCCESS_AT':   jetzt - timedelta(seconds=30),
            'TFA_OK':            1,
            'LAST_ERROR':        None,
            'ZYKLUS_COUNT':      123,
            'NEU_ENTDECKT':      4,
            'HOSTNAME':          'kasse-01',
            'WATCHDOG_ALARM_AT': None,
        }
        mod = _lade(db_row=row,
                    daemon_status={'running': True, 'pid': 9999,
                                   'log': '/tmp/h.log'},
                    env_overrides={})
        s = mod.status()
        hb = s['heartbeat']
        self.assertTrue(hb['vorhanden'])
        self.assertTrue(hb['tfa_ok'])
        self.assertEqual(hb['zyklus_count'], 123)
        self.assertEqual(hb['neu_entdeckt'], 4)
        self.assertEqual(hb['hostname'], 'kasse-01')
        # Seit-Run in Sekunden liegt um 30 herum
        self.assertIsNotNone(hb['sekunden_seit_run'])
        self.assertLess(abs(hb['sekunden_seit_run'] - 30), 5)

    def test_heartbeat_fehler(self):
        row = {
            'LAST_RUN_AT':     datetime.utcnow(),
            'LAST_SUCCESS_AT': None,
            'TFA_OK':          0,
            'LAST_ERROR':      'HTTP 401: Unauthorized',
            'ZYKLUS_COUNT':    5,
            'NEU_ENTDECKT':    0,
            'HOSTNAME':        'kasse-01',
        }
        mod = _lade(db_row=row,
                    daemon_status={'running': True, 'pid': 123,
                                   'log': '/tmp/h.log'},
                    env_overrides={})
        s = mod.status()
        self.assertFalse(s['heartbeat']['tfa_ok'])
        self.assertEqual(s['heartbeat']['last_error'],
                         'HTTP 401: Unauthorized')
        self.assertIsNone(s['heartbeat']['sekunden_seit_success'])

    def test_konfig_tfa_key_maskiert(self):
        mod = _lade(db_row=None,
                    daemon_status={'running': False, 'pid': None,
                                   'log': ''},
                    env_overrides={
                        'TFA_API_KEY': 'abcdefgh12345678',
                        'TFA_BASE_URL': 'https://go.tfa.me',
                        'HACCP_POLL_INTERVALL_S': '60',
                    })
        s = mod.status()
        k = s['konfig']
        self.assertTrue(k['tfa_api_key_set'])
        # Muss maskiert sein: sieht nicht den Mittelteil
        self.assertIn('abcd', k['tfa_api_key'])
        self.assertIn('5678', k['tfa_api_key'])
        self.assertNotIn('efgh', k['tfa_api_key'])
        self.assertEqual(k['poll_intervall_s'], 60)

    def test_konfig_kein_key(self):
        mod = _lade(db_row=None,
                    daemon_status={'running': False, 'pid': None,
                                   'log': ''},
                    env_overrides={})
        s = mod.status()
        k = s['konfig']
        self.assertFalse(k['tfa_api_key_set'])
        self.assertEqual(k['tfa_api_key'], '')
        # Default-Basis-URL
        self.assertEqual(k['tfa_base_url'], 'https://go.tfa.me')
        self.assertEqual(k['poll_intervall_s'], 120)
        # Alle Quellen 'default' (kein DB, kein Env)
        self.assertEqual(k['quellen']['tfa_base_url'], 'default')
        self.assertEqual(k['quellen']['poll_intervall_s'], 'default')

    def test_db_gewinnt_ueber_env(self):
        mod = _lade(
            db_row=None,
            daemon_status={'running': False, 'pid': None, 'log': ''},
            env_overrides={
                'TFA_API_KEY': 'env-key-xxx',
                'TFA_BASE_URL': 'https://env.example/',
                'HACCP_POLL_INTERVALL_S': '30',
            },
            konfig_werte={
                'haccp.tfa_api_key':     'db-key-yyy',
                'haccp.tfa_base_url':    'https://db.example/',
                'haccp.poll_intervall_s': 60,
            },
        )
        s = mod.status()
        k = s['konfig']
        # Maskierter DB-Key, aber nicht der Env-Key
        self.assertTrue(k['tfa_api_key_set'])
        self.assertIn('db', k['tfa_api_key'])
        self.assertEqual(k['tfa_base_url'], 'https://db.example/')
        self.assertEqual(k['poll_intervall_s'], 60)
        self.assertEqual(k['quellen']['tfa_base_url'], 'db')
        self.assertEqual(k['quellen']['tfa_api_key'], 'db')
        self.assertEqual(k['quellen']['poll_intervall_s'], 'db')


class TestHaccpPollerSpeichern(unittest.TestCase):

    def test_speichern_alle_drei(self):
        mod = _lade(db_row=None,
                    daemon_status={'running': False, 'pid': None, 'log': ''},
                    env_overrides={},
                    konfig_werte={})
        r = mod.speichern(tfa_api_key='neuer-key',
                          tfa_base_url='https://xy.tfa.me',
                          poll_intervall_s=90)
        self.assertTrue(r['ok'])
        self.assertEqual(sorted(r['geaendert']),
                         ['poll_intervall_s', 'tfa_api_key', 'tfa_base_url'])
        # Werte sind wirklich durch den Fake-konfig.set durchgeschleust
        self.assertEqual(mod._konfig_werte['haccp.tfa_api_key'], 'neuer-key')
        self.assertEqual(mod._konfig_werte['haccp.poll_intervall_s'], 90)

    def test_speichern_teilweise(self):
        mod = _lade(db_row=None,
                    daemon_status={'running': False, 'pid': None, 'log': ''},
                    env_overrides={},
                    konfig_werte={})
        r = mod.speichern(tfa_base_url='https://xy.tfa.me')
        self.assertTrue(r['ok'])
        self.assertEqual(r['geaendert'], ['tfa_base_url'])
        self.assertIn('haccp.tfa_base_url', mod._konfig_werte)
        self.assertNotIn('haccp.tfa_api_key', mod._konfig_werte)


if __name__ == '__main__':
    unittest.main()
