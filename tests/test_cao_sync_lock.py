"""Tests für den Dorfkern-internen Sync-Create-Lock
(common.einkauf._xt_ekbestell_sync_lock_tx).

Schützt cao_sync_ekbestell gegen Doppel-Anlage bei zwei
gleichzeitigen Syncs derselben XT-Bestellung (Check-then-Act).
Kein CAO-Lock: MODUL_ID 92050 ist XT-intern (>=90000).
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

from common import einkauf as CE  # noqa: E402
from common import cao_lock  # noqa: E402


def _ctx(cur):
    @contextlib.contextmanager
    def _g():
        yield cur
    return _g


class TestXtEkbestellSyncLockTx(unittest.TestCase):
    def test_xt_internes_modul_92050_und_release(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{'L': 1}, {'RELEASE_LOCK': 1}]
        with patch.object(CE, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with CE._xt_ekbestell_sync_lock_tx(4711) as c:
                self.assertIs(c, cur)
        calls = [c.args for c in cur.execute.call_args_list if c.args]
        get_lock = [a for a in calls if 'GET_LOCK' in a[0]][0]
        # XT-interner Namespace (NICHT CAO-MOD-2060), Quelle = XT-
        # Bestellung.REC_ID.
        self.assertEqual(get_lock[1][0], 'd_MOD_92050_RECID_4711')
        self.assertTrue(any('RELEASE_LOCK' in a[0] for a in calls))

    def test_belegt_wirft_vor_body(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'L': 0}
        with patch.object(CE, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with self.assertRaises(cao_lock.CaoLockBelegt):
                with CE._xt_ekbestell_sync_lock_tx(1):
                    raise AssertionError('Body darf nicht laufen')

    def test_konstante_ist_xt_intern(self):
        # >=90000 = bewusst NICHT CAO-kompatibel.
        self.assertGreaterEqual(cao_lock.LOCK_MOD_XT_EK_SYNC, 90000)


if __name__ == '__main__':
    unittest.main()
