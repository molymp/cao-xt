"""
Unit-Tests fuer admin-app/app/system_mittagstisch.py.
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'system_mittagstisch.py')


def _fake_konfig(werte: dict | None = None):
    """Registriert einen Fake fuer common.konfig und gibt das 'werte'-Dict
    zurueck, damit Tests Zugriff haben (assert + Setter)."""
    werte = dict(werte or {})
    common_pkg = types.ModuleType('common')
    common_pkg.__path__ = []
    sys.modules['common'] = common_pkg
    fake = types.SimpleNamespace(
        get=lambda key, default=None: werte.get(key, default),
        set=lambda key, wert, **kw: werte.__setitem__(key, wert),
    )
    sys.modules['common.konfig'] = fake
    return werte


def _lade(config_local_text: str | None,
          credentials_inhalt: bytes | None = None,
          credentials_relativ: bool = True,
          konfig_werte: dict | None = None):
    """Setzt ein Temp-Kiosk-Verzeichnis mit config_local.py + optional
    einer Credentials-Datei auf, ladet dann system_mittagstisch mit
    korrigierten Pfaden.
    """
    tempdir = tempfile.mkdtemp(prefix='mtt_test_')
    kiosk_app_dir = os.path.join(tempdir, 'kiosk-app', 'app')
    admin_app_dir = os.path.join(tempdir, 'admin-app', 'app')
    os.makedirs(kiosk_app_dir, exist_ok=True)
    os.makedirs(admin_app_dir, exist_ok=True)

    if config_local_text is not None:
        with open(os.path.join(kiosk_app_dir, 'config_local.py'), 'w') as f:
            f.write(config_local_text)

    cred_name = 'creds.json'
    if credentials_inhalt is not None:
        ziel = (os.path.join(kiosk_app_dir, cred_name) if credentials_relativ
                else os.path.join(tempdir, cred_name))
        with open(ziel, 'wb') as f:
            f.write(credentials_inhalt)

    # Admin-Config stubben (fuer KIOSK_URL/PORT-Lookup)
    stub = types.ModuleType('config')
    stub.KIOSK_URL = ''
    stub.KIOSK_PORT = 5001
    sys.modules['config'] = stub

    # common.konfig stubben
    werte = _fake_konfig(konfig_werte)

    # Modul mit angepassten Pfaden laden
    sys.modules.pop('mtt_test', None)
    spec = importlib.util.spec_from_file_location('mtt_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Pfade ueberschreiben, sonst zeigen sie auf das echte Repo
    mod._KIOSK_CONFIG_LOCAL = os.path.join(kiosk_app_dir, 'config_local.py')
    mod._KIOSK_APP_DIR = kiosk_app_dir
    mod._konfig_werte = werte   # fuer Asserts
    return mod, tempdir, cred_name


class TestMittagstischStatus(unittest.TestCase):

    def test_ohne_config_local(self):
        mod, _, _ = _lade(config_local_text=None)
        s = mod.status()
        self.assertFalse(s['config_local_exists'])
        self.assertEqual(s['spreadsheet_id'], '')
        self.assertEqual(s['credentials']['existiert'], False)

    def test_mit_spreadsheet_und_credentials(self):
        cfg_text = (
            'DEBUG = True\n'
            'MITTAGSTISCH_SPREADSHEET_ID = "1Fr2INvHllH61SjIkuTOCrMATrC78xxYW0W-2Rre2ALQ"\n'
            'MITTAGSTISCH_CREDENTIALS_FILE = "creds.json"\n'
        )
        mod, tempdir, _ = _lade(
            config_local_text=cfg_text,
            credentials_inhalt=b'{"type": "service_account"}')
        s = mod.status()
        self.assertTrue(s['config_local_exists'])
        self.assertEqual(s['spreadsheet_id'],
                         '1Fr2INvHllH61SjIkuTOCrMATrC78xxYW0W-2Rre2ALQ')
        self.assertIn('docs.google.com', s['spreadsheet_url'])
        c = s['credentials']
        self.assertTrue(c['existiert'])
        self.assertEqual(c['pfad_roh'], 'creds.json')
        self.assertEqual(c['groesse'], len(b'{"type": "service_account"}'))
        self.assertIsNotNone(c['alter_tage'])

    def test_credentials_pfad_absolut(self):
        import tempfile as _tf
        tmp = _tf.NamedTemporaryFile(
            mode='wb', suffix='.json', delete=False)
        tmp.write(b'{}'); tmp.close()
        try:
            cfg_text = (f'MITTAGSTISCH_SPREADSHEET_ID = "sid"\n'
                        f"MITTAGSTISCH_CREDENTIALS_FILE = '{tmp.name}'\n")
            mod, _, _ = _lade(
                config_local_text=cfg_text,
                credentials_inhalt=None)
            s = mod.status()
            self.assertEqual(s['credentials']['pfad_absolut'], tmp.name)
            self.assertTrue(s['credentials']['existiert'])
        finally:
            os.unlink(tmp.name)

    def test_credentials_fehlen(self):
        cfg_text = (
            'MITTAGSTISCH_SPREADSHEET_ID = "abc"\n'
            'MITTAGSTISCH_CREDENTIALS_FILE = "nicht_da.json"\n'
        )
        mod, _, _ = _lade(config_local_text=cfg_text)
        s = mod.status()
        self.assertEqual(s['spreadsheet_id'], 'abc')
        self.assertFalse(s['credentials']['existiert'])
        self.assertEqual(s['credentials']['groesse'], 0)

    def test_kiosk_url_mit_env(self):
        # config-Stub liefert KIOSK_PORT=5001, KIOSK_URL=''
        mod, _, _ = _lade(config_local_text='')
        s = mod.status()
        self.assertIn('localhost:5001', s['kiosk_url'])
        self.assertTrue(s['kiosk_mittagstisch_url']
                        .endswith('/mittagstisch'))

    def test_db_gewinnt_ueber_config_local_bei_spreadsheet(self):
        cfg_text = ('MITTAGSTISCH_SPREADSHEET_ID = "alt-aus-file"\n')
        mod, _, _ = _lade(config_local_text=cfg_text,
                          konfig_werte={
                              'mittagstisch.spreadsheet_id':
                                  'neu-aus-db',
                          })
        s = mod.status()
        self.assertEqual(s['spreadsheet_id'], 'neu-aus-db')
        self.assertEqual(s['spreadsheet_id_quelle'], 'db')

    def test_db_credentials_json_wird_sanity_geprueft(self):
        import json as _json
        creds = _json.dumps({
            'type': 'service_account',
            'client_email': 'svc@p.iam.gserviceaccount.com',
            'project_id': 'proj-42',
            'private_key': '...',
        })
        mod, _, _ = _lade(
            config_local_text='',
            konfig_werte={'mittagstisch.credentials_json': creds})
        s = mod.status()
        self.assertEqual(s['credentials']['quelle'], 'db')
        self.assertTrue(s['credentials']['json_set'])
        self.assertEqual(
            s['credentials']['json_sanity']['email'],
            'svc@p.iam.gserviceaccount.com')

    def test_db_credentials_json_kaputt(self):
        mod, _, _ = _lade(
            config_local_text='',
            konfig_werte={'mittagstisch.credentials_json': 'nicht-json'})
        s = mod.status()
        # 'quelle' bleibt 'leer' weil JSON-Parse fehlschlug
        self.assertEqual(s['credentials']['quelle'], 'leer')
        self.assertIsNone(s['credentials']['json_sanity'])


class TestSpeichern(unittest.TestCase):

    def test_spreadsheet_id_speichern(self):
        mod, _, _ = _lade(config_local_text='',
                          konfig_werte={})
        r = mod.speichern(spreadsheet_id='xxxx-yyyy-zzzz')
        self.assertTrue(r['ok'])
        self.assertEqual(r['geaendert'], ['spreadsheet_id'])
        self.assertEqual(mod._konfig_werte['mittagstisch.spreadsheet_id'],
                         'xxxx-yyyy-zzzz')

    def test_credentials_valides_json(self):
        import json as _json
        creds = _json.dumps({
            'type': 'service_account', 'client_email': 'x@y',
            'project_id': 'p', 'private_key': 'k'})
        mod, _, _ = _lade(config_local_text='', konfig_werte={})
        r = mod.speichern(credentials_json=creds)
        self.assertTrue(r['ok'])
        self.assertIn('credentials_json', r['geaendert'])

    def test_credentials_kaputtes_json_wird_abgelehnt(self):
        mod, _, _ = _lade(config_local_text='', konfig_werte={})
        r = mod.speichern(credentials_json='{nicht valide')
        self.assertFalse(r['ok'])
        self.assertIn('ungueltig', r['msg'].lower())
        # nichts gespeichert
        self.assertNotIn('mittagstisch.credentials_json',
                         mod._konfig_werte)

    def test_credentials_kein_service_account_wird_abgelehnt(self):
        import json as _json
        mod, _, _ = _lade(config_local_text='', konfig_werte={})
        r = mod.speichern(credentials_json=_json.dumps({'type': 'user'}))
        self.assertFalse(r['ok'])
        self.assertIn('service_account', r['msg'])

    def test_leerer_credentials_string_ueberschreibt_nicht(self):
        mod, _, _ = _lade(
            config_local_text='',
            konfig_werte={'mittagstisch.credentials_json': 'alt'})
        r = mod.speichern(spreadsheet_id='foo', credentials_json='')
        self.assertTrue(r['ok'])
        self.assertEqual(r['geaendert'], ['spreadsheet_id'])
        # Alt-Wert unveraendert
        self.assertEqual(
            mod._konfig_werte['mittagstisch.credentials_json'], 'alt')


if __name__ == '__main__':
    unittest.main()
