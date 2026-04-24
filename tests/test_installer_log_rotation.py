"""
Tests fuer installer/app_manager.py – Log-Rotation.
"""
import importlib
import os
import sys
import tempfile
import unittest

# app_manager hat Seiteneffekte beim Import (PID_FILE etc.), aber sie
# sind harmlos – wir laden einfach das echte Modul.
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _REPO_ROOT)

from installer import app_manager   # noqa: E402


def _schreibe(pfad: str, bytes_n: int) -> None:
    with open(pfad, 'wb') as f:
        f.write(b'X' * bytes_n)


class TestLogRotation(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='caoxt_rot_')
        self.log = os.path.join(self.tempdir, 'test.log')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_datei_fehlt_keine_rotation(self):
        self.assertFalse(app_manager._rotate_log(
            self.log, max_bytes=1024, backups=3))
        # Immer noch keine Datei
        self.assertFalse(os.path.isfile(self.log))

    def test_unter_schwelle_keine_rotation(self):
        _schreibe(self.log, 100)
        self.assertFalse(app_manager._rotate_log(
            self.log, max_bytes=1024, backups=3))
        self.assertEqual(os.path.getsize(self.log), 100)

    def test_rotation_erste_runde(self):
        _schreibe(self.log, 2000)
        self.assertTrue(app_manager._rotate_log(
            self.log, max_bytes=1024, backups=3))
        # Aktuelles Log ist weg (App erstellt neues)
        self.assertFalse(os.path.isfile(self.log))
        # Backup .1 hat jetzt die alten 2000 Bytes
        self.assertTrue(os.path.isfile(self.log + '.1'))
        self.assertEqual(os.path.getsize(self.log + '.1'), 2000)

    def test_rotation_shiftet_bestehende_backups(self):
        _schreibe(self.log,          2000)  # wird zu .1
        _schreibe(self.log + '.1',    500)  # wird zu .2
        _schreibe(self.log + '.2',    200)  # wird zu .3
        _schreibe(self.log + '.3',    100)  # wird geloescht

        app_manager._rotate_log(self.log, max_bytes=1024, backups=3)

        self.assertFalse(os.path.isfile(self.log))
        self.assertEqual(os.path.getsize(self.log + '.1'), 2000)
        self.assertEqual(os.path.getsize(self.log + '.2'),  500)
        self.assertEqual(os.path.getsize(self.log + '.3'),  200)
        # Ehemaliges .3 ist weg
        self.assertFalse(os.path.isfile(self.log + '.4'))

    def test_rotation_mit_luecken(self):
        """Wenn .2 fehlt, .1 aber da ist: .1 -> .2 ist OK, .log -> .1."""
        _schreibe(self.log,         2000)
        _schreibe(self.log + '.1',   500)
        # .2, .3 fehlen

        app_manager._rotate_log(self.log, max_bytes=1024, backups=3)

        self.assertEqual(os.path.getsize(self.log + '.1'), 2000)
        self.assertEqual(os.path.getsize(self.log + '.2'),  500)
        self.assertFalse(os.path.isfile(self.log + '.3'))

    def test_backups_null_loescht_nur(self):
        """backups=0: bei Schwellen-Ueberschreitung einfach weg."""
        _schreibe(self.log, 2000)
        app_manager._rotate_log(self.log, max_bytes=1024, backups=0)
        self.assertFalse(os.path.isfile(self.log))
        self.assertFalse(os.path.isfile(self.log + '.1'))

    def test_log_info_struktur(self):
        _schreibe(self.log,         3000)
        _schreibe(self.log + '.1',   500)
        _schreibe(self.log + '.2',   200)
        info = app_manager.log_info(self.log)
        self.assertTrue(info['existiert'])
        self.assertEqual(info['groesse'], 3000)
        self.assertEqual(len(info['backups']), 2)
        self.assertEqual(info['backups'][0]['groesse'], 500)
        self.assertEqual(info['backups'][1]['groesse'], 200)
        self.assertEqual(info['gesamt_bytes'], 3000 + 500 + 200)

    def test_log_info_datei_fehlt(self):
        info = app_manager.log_info(self.log)
        self.assertFalse(info['existiert'])
        self.assertEqual(info['groesse'], 0)
        self.assertEqual(info['backups'], [])
        self.assertEqual(info['gesamt_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
