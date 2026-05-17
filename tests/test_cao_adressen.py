"""Tests für common.cao_adressen (CAO-Mimik Adress-Anlage/-Änderung).

Keine DB: get_db(_transaction) + Hashsum gemockt.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from common import cao_adressen as A  # noqa: E402


def _ctx(cur):
    @contextlib.contextmanager
    def _g():
        yield cur
    return _g


class TestWerte(unittest.TestCase):
    def test_defaults_und_whitelist(self):
        # Schlüssel case-insensitiv (lowercase wird akzeptiert).
        w = A._werte({'name1': 'Wurms', 'KUNDENGRUPPE': 5,
                      'STRASSE': 'Am Mühlbach 7'})
        self.assertEqual(w['NAME1'], 'Wurms')
        self.assertEqual(w['STRASSE'], 'Am Mühlbach 7')
        self.assertEqual(w['LAND'], 'DE')           # Default
        self.assertEqual(w['WAEHRUNG'], '€')        # Default
        # KUNDENGRUPPE ist NICHT in EDITIERBAR → Default 999 bleibt.
        self.assertEqual(w['KUNDENGRUPPE'], 999)
        self.assertEqual(w['PR_EBENE'], 5)

    def test_unbekanntes_feld_ignoriert(self):
        w = A._werte({'GIBTSNICHT': 'x'})
        self.assertNotIn('GIBTSNICHT', w)


class TestLockName(unittest.TestCase):
    def test_format_matcht_cao_trace(self):
        # CAO-Trace: GET_LOCK('cao_XT_DEV_MOD_1010_RECID_432')
        from common import cao_lock
        with patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'cao_XT_DEV'}):
            self.assertEqual(
                cao_lock.lock_name(1010, 432),
                'cao_XT_DEV_MOD_1010_RECID_432')
            self.assertEqual(A.MODUL_ID_ADRESSEN, 1010)


class TestHashstring(unittest.TestCase):
    def test_v1_prefix_alle_spalten_kein_splitliteral(self):
        sql = A._log_hashstring_sql()
        self.assertIn("'V1'", sql)
        for c in A._LOG_COLS:
            self.assertIn(c, sql)
        # Regressionsschutz COMMENT-Outage-Klasse:
        self.assertFalse(re.findall(r"'\s*\n\s*'", sql))
        # Quell-SQL des Moduls ebenfalls split-literal-frei
        src = open(A.__file__).read()
        self.assertFalse(re.findall(r"'\s*\n\s*'", src))


class TestAnlegen(unittest.TestCase):
    def _run(self):
        cur = MagicMock()
        cur.lastrowid = 432
        # fetchone(): hashstring-row, prev-hashsum-row
        cur.fetchone.side_effect = [{'HASHSTRING': 'V1|432|…'},
                                    {'HASHSUM': b'prev'}]
        with patch.object(A, 'get_db_transaction', _ctx(cur)), \
             patch.object(A._cao_hashsum, 'get_salt',
                          return_value='salt'), \
             patch.object(A._cao_log_hashsum, 'compute',
                          return_value=b'XT-HMAC') as comp:
            rid = A.adresse_anlegen({'NAME1': 'Wurms Seife Tee Fass',
                                     'PLZ': '82442', 'ORT': 'Saulgrub',
                                     'STRASSE': 'Am Mühlbach 7'},
                                    ma_name='Marc')
        return rid, cur, comp

    def test_happy(self):
        rid, cur, comp = self._run()
        self.assertEqual(rid, 432)
        sql = ' '.join(c.args[0] for c in cur.execute.call_args_list
                       if c.args)
        self.assertIn('INSERT INTO ADRESSEN (', sql)
        self.assertIn('INSERT INTO ADRESSEN_LOG', sql)
        self.assertIn('UPDATE ADRESSEN_LOG SET HASHSUM', sql)
        comp.assert_called_once()
        self.assertEqual(comp.call_args.kwargs['table_name'],
                         'ADRESSEN_LOG')
        self.assertEqual(comp.call_args.kwargs['previous_hashsum'],
                         b'prev')

    def test_salt_fehlt_bricht_ab(self):
        from common.cao_hashsum import SaltFehlt
        with patch.object(A._cao_hashsum, 'get_salt',
                          side_effect=SaltFehlt('x')):
            with self.assertRaises(SaltFehlt):
                A.adresse_anlegen({'NAME1': 'X'})


class TestAendern(unittest.TestCase):
    def _cur(self, lock_ok=1, exists=True):
        cur = MagicMock()
        cur.lastrowid = 99
        cur.fetchone.side_effect = [
            {'L': lock_ok},                       # GET_LOCK
            {'REC_ID': 432} if exists else None,  # Existenz-Check
            {'HASHSTRING': 'V1|…'},               # Hashstring
            {'HASHSUM': None},                    # prev-Hashsum
            {'RELEASE_LOCK': 1},                  # RELEASE_LOCK
        ]
        return cur

    def test_lock_acquire_release_und_log(self):
        cur = self._cur()
        from common import cao_lock
        with patch.object(A, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}), \
             patch.object(A._cao_hashsum, 'get_salt',
                          return_value='s'), \
             patch.object(A._cao_log_hashsum, 'compute',
                          return_value=b'h'):
            r = A.adresse_aendern(432, {'NAME1': 'Neu'}, ma_name='M')
        self.assertTrue(r['ok'])
        sql = ' '.join(c.args[0] for c in cur.execute.call_args_list
                       if c.args)
        self.assertIn('GET_LOCK', sql)
        self.assertIn('RELEASE_LOCK', sql)
        self.assertIn('UPDATE ADRESSEN SET', sql)
        self.assertIn('INSERT INTO ADRESSEN_LOG', sql)

    def test_lock_belegt_wirft(self):
        cur = self._cur(lock_ok=0)
        from common import cao_lock
        with patch.object(A, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}), \
             patch.object(A._cao_hashsum, 'get_salt',
                          return_value='s'):
            with self.assertRaises(RuntimeError):
                A.adresse_aendern(432, {'NAME1': 'Neu'})

    def test_keine_felder_wirft(self):
        with patch.object(A._cao_hashsum, 'get_salt',
                          return_value='s'):
            with self.assertRaises(ValueError):
                A.adresse_aendern(1, {'GIBTSNICHT': 'x'})


if __name__ == '__main__':
    unittest.main()
