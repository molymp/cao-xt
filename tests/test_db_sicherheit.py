"""
Unit-Tests fuer common/db.py::_pruefe_db_whitelist und
common/config.py::load_security_config.

Stellt sicher, dass eine Dev-/Worktree-Instanz NICHT versehentlich
gegen eine in der Blacklist aufgefuehrte Produktions-DB schreiben kann.
"""
import os
import sys
import unittest
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import config as c
from common import db as dbmod


class TestLoadSecurityConfig(unittest.TestCase):
    def setUp(self):
        self._saved_env = os.environ.pop('XT_FORBIDDEN_DB_NAMES', None)

    def tearDown(self):
        if self._saved_env is not None:
            os.environ['XT_FORBIDDEN_DB_NAMES'] = self._saved_env
        else:
            os.environ.pop('XT_FORBIDDEN_DB_NAMES', None)

    def test_env_ueberschreibt_ini(self):
        os.environ['XT_FORBIDDEN_DB_NAMES'] = 'cao_prod_a, cao_prod_b'
        sec = c.load_security_config()
        self.assertEqual(sec['verbotene_db_namen'],
                         ['cao_prod_a', 'cao_prod_b'])

    def test_env_wird_lower_case_normalisiert(self):
        os.environ['XT_FORBIDDEN_DB_NAMES'] = 'CAO_Prod'
        sec = c.load_security_config()
        self.assertEqual(sec['verbotene_db_namen'], ['cao_prod'])

    def test_leere_env_liefert_leere_liste(self):
        os.environ['XT_FORBIDDEN_DB_NAMES'] = ''
        sec = c.load_security_config()
        # Fallback greift auf ini → je nach Umgebung u.U. nicht leer.
        # Wichtig: Rueckgabe ist Liste, nicht None/str.
        self.assertIsInstance(sec['verbotene_db_namen'], list)


class TestPruefeDbWhitelist(unittest.TestCase):
    def test_wirft_bei_match(self):
        with patch.object(c, 'load_security_config',
                          return_value={'verbotene_db_namen':
                                        ['cao_2018_001']}):
            with self.assertRaises(RuntimeError) as ctx:
                dbmod._pruefe_db_whitelist('cao_2018_001')
            self.assertIn('cao_2018_001', str(ctx.exception))

    def test_match_ist_case_insensitiv(self):
        with patch.object(c, 'load_security_config',
                          return_value={'verbotene_db_namen':
                                        ['cao_2018_001']}):
            with self.assertRaises(RuntimeError):
                dbmod._pruefe_db_whitelist('CAO_2018_001')

    def test_kein_wurf_bei_abweichendem_namen(self):
        with patch.object(c, 'load_security_config',
                          return_value={'verbotene_db_namen':
                                        ['cao_2018_001']}):
            # Darf nicht werfen.
            dbmod._pruefe_db_whitelist('cao_xt_dev')

    def test_leere_blacklist_laesst_alles_durch(self):
        with patch.object(c, 'load_security_config',
                          return_value={'verbotene_db_namen': []}):
            dbmod._pruefe_db_whitelist('cao_2018_001')
            dbmod._pruefe_db_whitelist('cao_xt_dev')

    def test_leerer_db_name_wirft_nicht(self):
        # Kein DB-Name konfiguriert -> Pool-Erstellung scheitert ohnehin
        # an anderer Stelle; der Sicherheits-Check soll hier nicht greifen.
        with patch.object(c, 'load_security_config',
                          return_value={'verbotene_db_namen':
                                        ['cao_2018_001']}):
            dbmod._pruefe_db_whitelist('')


if __name__ == '__main__':
    unittest.main()
