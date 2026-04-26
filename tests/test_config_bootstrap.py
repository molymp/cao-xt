"""
Tests fuer common.config._bootstrap_ini – Erstinstallations-Bootstrap.

caoxt.ini ist nicht im Repo getrackt (siehe .gitignore). Das Modul
kopiert beim ersten Import die mitgelieferte caoxt.ini.example, falls
caoxt.ini lokal noch fehlt.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import config as c


class TestBootstrap(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='caoxt-bootstrap-')
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._ini      = os.path.join(self._tmp, 'caoxt.ini')
        self._example  = os.path.join(self._tmp, 'caoxt.ini.example')

    def _run(self):
        # _bootstrap_ini liest die Modul-Pfad-Konstanten beim Aufruf.
        with patch.object(c, '_INI_PATH',    self._ini), \
             patch.object(c, '_INI_EXAMPLE', self._example):
            c._bootstrap_ini()

    def test_kopiert_example_wenn_ini_fehlt(self):
        with open(self._example, 'w', encoding='utf-8') as f:
            f.write('[Datenbank]\ndb_loc=[server-URL]\n')
        self._run()
        self.assertTrue(os.path.exists(self._ini))
        with open(self._ini, encoding='utf-8') as f:
            self.assertIn('[server-URL]', f.read())

    def test_idempotent_wenn_ini_existiert(self):
        with open(self._example, 'w', encoding='utf-8') as f:
            f.write('[Datenbank]\ndb_loc=[server-URL]\n')
        with open(self._ini, 'w', encoding='utf-8') as f:
            f.write('[Datenbank]\ndb_loc=meine-echte-db.example\n')
        self._run()
        # echte caoxt.ini bleibt UNVERAENDERT
        with open(self._ini, encoding='utf-8') as f:
            self.assertIn('meine-echte-db.example', f.read())

    def test_tut_nichts_wenn_example_fehlt(self):
        # Weder caoxt.ini noch caoxt.ini.example existieren – Bootstrap
        # darf nicht werfen und legt nichts an.
        self._run()
        self.assertFalse(os.path.exists(self._ini))


if __name__ == '__main__':
    unittest.main()
