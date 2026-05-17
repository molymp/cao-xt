"""Tests für common.cao_lock (CAO-kompatibler Record-Lock)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from common import cao_lock  # noqa: E402


class TestCaoLock(unittest.TestCase):
    def test_lock_name_matcht_cao_trace(self):
        with patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'cao_XT_DEV'}):
            self.assertEqual(cao_lock.lock_name(1010, 432),
                             'cao_XT_DEV_MOD_1010_RECID_432')

    def test_acquire_release_gleiche_connection(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{'L': 1}, {'RELEASE_LOCK': 1}]
        with patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with cao_lock.cao_record_lock(cur, 2050, 7) as n:
                self.assertEqual(n, 'd_MOD_2050_RECID_7')
        sql = ' '.join(c.args[0] for c in cur.execute.call_args_list)
        self.assertIn('GET_LOCK', sql)
        self.assertIn('RELEASE_LOCK', sql)

    def test_belegt_wirft(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'L': 0}
        with patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with self.assertRaises(cao_lock.CaoLockBelegt):
                with cao_lock.cao_record_lock(cur, 1, 1):
                    pass


if __name__ == '__main__':
    unittest.main()
