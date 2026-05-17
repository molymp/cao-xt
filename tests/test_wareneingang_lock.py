"""Tests: wareneingang Lock MODUL_ID 2065 + CAO-Mimik offener WE.

- _eingang_lock_db/_tx: Lock cao_<db>_MOD_2065_RECID_<id> (Trace).
- storno offener WE (STADIUM=0): harter DELETE (CAO-Mimik), KEIN
  Soft-STADIUM=127. STADIUM=127: idempotenter No-Op.
Keine DB: get_db(_transaction) gemockt.
"""
from __future__ import annotations

import contextlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from modules.orga.bestellwesen import wareneingang as W  # noqa: E402
from common import cao_lock  # noqa: E402


def _ctx(cur):
    @contextlib.contextmanager
    def _g():
        yield cur
    return _g


def _sql(cur):
    return ' '.join(c.args[0] for c in cur.execute.call_args_list
                    if c.args)


class TestEingangLockHelpers(unittest.TestCase):
    def test_lock_db_mod_2065(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{'L': 1}, {'RELEASE_LOCK': 1}]
        with patch.object(W, 'get_db', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'cao_XT_DEV'}):
            with W._eingang_lock_db(51) as c:
                self.assertIs(c, cur)
        gl = [c.args for c in cur.execute.call_args_list
              if c.args and 'GET_LOCK' in c.args[0]][0]
        self.assertEqual(gl[1][0], 'cao_XT_DEV_MOD_2065_RECID_51')

    def test_lock_tx_belegt_wirft(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'L': 0}
        with patch.object(W, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with self.assertRaises(cao_lock.CaoLockBelegt):
                with W._eingang_lock_tx(1):
                    raise AssertionError('Body darf nicht laufen')


class TestStornoOffenerWeHartDelete(unittest.TestCase):
    def _run(self, *, stadium):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {'L': 1},
            {'REC_ID': 51, 'STADIUM': stadium, 'BELEGNUM': 'WE1'},
            {'RELEASE_LOCK': 1},
        ]
        with patch.object(W, 'get_db', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            r = W.storno(51, ma_name='T')
        return r, cur

    def test_offen_hart_delete_kein_soft(self):
        r, cur = self._run(stadium=0)
        self.assertEqual(r, {'ok': 1, 'pos_lager_korrigiert': 0})
        sql = _sql(cur)
        self.assertIn('DELETE FROM REFERENZEN WHERE ZIEL=2065', sql)
        self.assertIn('DELETE FROM EKEINGANG_POS', sql)
        self.assertIn('DELETE FROM EKEINGANG', sql)
        # KEIN Soft-Storno für offene WE.
        self.assertNotIn('SET STADIUM = 127', sql)
        # Unter dem WE-Record-Lock.
        self.assertIn('GET_LOCK', sql)
        self.assertIn('RELEASE_LOCK', sql)

    def test_bereits_storniert_noop(self):
        r, cur = self._run(stadium=127)
        self.assertEqual(r, {'ok': 0, 'pos_lager_korrigiert': 0})
        sql = _sql(cur)
        self.assertNotIn('DELETE FROM EKEINGANG', sql)


if __name__ == '__main__':
    unittest.main()
