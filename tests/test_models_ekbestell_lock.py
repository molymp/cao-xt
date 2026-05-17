"""Tests: modules.orga.bestellwesen.models EKBESTELL-Editoren unter
CAO-Record-Lock MODUL_ID 2060 (Trace 17.05.26
cao_<db>_MOD_2060_RECID_<ekbestell_rec_id>). Keine DB: get_db gemockt.
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

from modules.orga.bestellwesen import models as M  # noqa: E402
from common import cao_lock  # noqa: E402


def _ctx(cur):
    @contextlib.contextmanager
    def _g():
        yield cur
    return _g


class TestEkbestellLockDb(unittest.TestCase):
    def test_helper_mod_2060_und_release(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{'L': 1}, {'RELEASE_LOCK': 1}]
        with patch.object(M, 'get_db', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'cao_XT_DEV'}):
            with M._ekbestell_lock_db(467) as c:
                self.assertIs(c, cur)
        calls = [c.args for c in cur.execute.call_args_list if c.args]
        gl = [a for a in calls if 'GET_LOCK' in a[0]][0]
        self.assertEqual(gl[1][0], 'cao_XT_DEV_MOD_2060_RECID_467')
        self.assertTrue(any('RELEASE_LOCK' in a[0] for a in calls))

    def test_belegt_wirft(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'L': 0}
        with patch.object(M, 'get_db', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with self.assertRaises(cao_lock.CaoLockBelegt):
                with M._ekbestell_lock_db(1):
                    raise AssertionError('Body darf nicht laufen')


class TestPosKeyedLockAufEkbestellId(unittest.TestCase):
    """pos_id-keyed Editor: Lock auf der via Pos aufgelösten
    EKBESTELL_ID, nicht auf pos_id."""

    def test_position_status_setzen_lockt_ekbestell_id(self):
        cur = MagicMock()
        # SELECT pos -> GET_LOCK -> RELEASE_LOCK
        cur.fetchone.side_effect = [
            {'REC_ID': 9, 'STADIUM': 2, 'EKBESTELL_ID': 467},
            {'L': 1},
            {'RELEASE_LOCK': 1},
        ]
        with patch.object(M, 'get_db', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'cao_XT_DEV'}):
            M.position_status_setzen(9, 2)
        calls = [c.args for c in cur.execute.call_args_list if c.args]
        gl = [a for a in calls if 'GET_LOCK' in a[0]][0]
        # Lock auf EKBESTELL.REC_ID 467 (aus Pos), NICHT pos_id 9.
        self.assertEqual(gl[1][0], 'cao_XT_DEV_MOD_2060_RECID_467')
        self.assertTrue(any('UPDATE EKBESTELL_POS' in a[0] for a in calls))
        # Pos-SELECT zieht EKBESTELL_ID mit.
        sel = [a for a in calls if 'FROM EKBESTELL_POS' in a[0]
               and 'SELECT' in a[0]][0]
        self.assertIn('EKBESTELL_ID', sel[0])


if __name__ == '__main__':
    unittest.main()
