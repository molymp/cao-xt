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


def _lade(config_local_text: str | None,
          credentials_inhalt: bytes | None = None,
          credentials_relativ: bool = True):
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

    # Modul mit angepassten Pfaden laden
    sys.modules.pop('mtt_test', None)
    spec = importlib.util.spec_from_file_location('mtt_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Pfade ueberschreiben, sonst zeigen sie auf das echte Repo
    mod._KIOSK_CONFIG_LOCAL = os.path.join(kiosk_app_dir, 'config_local.py')
    mod._KIOSK_APP_DIR = kiosk_app_dir
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


if __name__ == '__main__':
    unittest.main()
