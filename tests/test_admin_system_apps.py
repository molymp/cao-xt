"""
Unit-Tests fuer admin-app/app/system_apps.py.

Wir monkeypatchen installer.app_manager, damit keine echten Prozesse
gestartet werden.
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'system_apps.py')


def _lade(fake_manager):
    """Laedt system_apps.py und ersetzt installer.app_manager durch Fake."""
    # Installer-Paket vortaeuschen
    installer_pkg = types.ModuleType('installer')
    installer_pkg.__path__ = []
    sys.modules['installer'] = installer_pkg
    sys.modules['installer.app_manager'] = fake_manager
    sys.modules.pop('sa_test', None)
    spec = importlib.util.spec_from_file_location('sa_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_manager(**overrides) -> types.SimpleNamespace:
    apps = {
        'admin': {'type': 'web', 'port': 5004,
                  'app_dir': '/x', 'log': '/tmp/a.log'},
        'kasse': {'type': 'web', 'port': 5002,
                  'app_dir': '/y', 'log': '/tmp/k.log'},
        'haccp-poller': {'type': 'daemon',
                         'module': 'modules.haccp.poller',
                         'log': '/tmp/h.log'},
    }
    calls = []

    def status_app(name):
        return {'name': name, 'type': apps[name]['type'],
                'port': apps[name].get('port'),
                'running': True, 'pid': 42,
                'log': apps[name]['log']}

    def status_all():
        return [status_app(n) for n in apps]

    def start_app(name, *, print_fn=None):
        calls.append(('start', name))
        return True

    def stop_app(name, *, print_fn=None):
        calls.append(('stop', name))

    def restart_app(name, *, print_fn=None):
        calls.append(('restart', name))
        return True

    ns = types.SimpleNamespace(
        APPS=apps,
        status_app=status_app,
        status_all=status_all,
        start_app=start_app,
        stop_app=stop_app,
        restart_app=restart_app,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    ns._calls = calls
    return ns


class TestSystemApps(unittest.TestCase):

    def test_liste_hat_alle_apps_mit_beschreibung(self):
        fake = _fake_manager()
        mod = _lade(fake)
        res = mod.liste()
        namen = [e['name'] for e in res]
        self.assertIn('admin', namen)
        self.assertIn('haccp-poller', namen)
        # Beschreibung ist gefuellt fuer bekannte Apps
        by = {e['name']: e for e in res}
        self.assertIn('Admin', by['admin']['beschreibung'])
        self.assertIn('HACCP', by['haccp-poller']['beschreibung'])

    def test_start_ruft_manager(self):
        fake = _fake_manager()
        mod = _lade(fake)
        r = mod.start('kasse')
        self.assertTrue(r['ok'])
        self.assertEqual(fake._calls, [('start', 'kasse')])

    def test_start_unbekannte_app(self):
        fake = _fake_manager()
        mod = _lade(fake)
        r = mod.start('nicht-da')
        self.assertFalse(r['ok'])
        self.assertIn('Unbekannte', r['msg'])
        # Manager wurde nicht aufgerufen
        self.assertEqual(fake._calls, [])

    def test_restart_admin_wird_abgelehnt(self):
        """Die Admin-App darf sich nicht selbst restarten (wuerde sich
        tot fallen)."""
        fake = _fake_manager()
        mod = _lade(fake)
        r = mod.restart('admin')
        self.assertFalse(r['ok'])
        self.assertIn('nicht selbst', r['msg'].lower())
        self.assertEqual(fake._calls, [])

    def test_restart_andere_app_laeuft_durch(self):
        fake = _fake_manager()
        mod = _lade(fake)
        r = mod.restart('kasse')
        self.assertTrue(r['ok'])
        self.assertEqual(fake._calls, [('restart', 'kasse')])

    def test_stop(self):
        fake = _fake_manager()
        mod = _lade(fake)
        r = mod.stop('haccp-poller')
        self.assertTrue(r['ok'])
        self.assertEqual(fake._calls, [('stop', 'haccp-poller')])

    def test_log_tail_liest_letzte_zeilen(self):
        # Temp-Log erstellen
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log',
                                         delete=False) as tf:
            for i in range(200):
                tf.write(f'Zeile {i}\n')
            log_pfad = tf.name
        try:
            fake = _fake_manager()
            fake.APPS['kasse']['log'] = log_pfad
            mod = _lade(fake)
            r = mod.log_tail('kasse', zeilen=20)
            self.assertTrue(r['ok'])
            self.assertEqual(len(r['zeilen']), 20)
            # Ergebnis endet mit der letzten Zeile
            self.assertEqual(r['zeilen'][-1], 'Zeile 199')
        finally:
            os.unlink(log_pfad)

    def test_log_tail_datei_fehlt(self):
        fake = _fake_manager()
        fake.APPS['kasse']['log'] = '/tmp/existiert-nicht-xyz.log'
        mod = _lade(fake)
        r = mod.log_tail('kasse')
        self.assertTrue(r['ok'])
        self.assertEqual(r['zeilen'], [])


if __name__ == '__main__':
    unittest.main()
