"""Tests für modules.orga.bestellwesen.einkauf.einkauf_storno.

CAO-Mimik: Soft-Delete (QUELLE→-15, DEL_FLAG='Y') unter Record-Lock
MODUL_ID 2050, KEIN harter DELETE. Keine DB: get_db_transaction +
cao_record_lock-Connection gemockt.
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

from modules.orga.bestellwesen import einkauf as E  # noqa: E402
from common import cao_lock  # noqa: E402


def _ctx(cur):
    @contextlib.contextmanager
    def _g():
        yield cur
    return _g


def _run(cur):
    with patch.object(E, 'get_db_transaction', _ctx(cur)), \
         patch.object(cao_lock, 'effektive_db_config',
                      return_value={'name': 'd'}):
        return E.einkauf_storno(7)


class TestEinkaufStorno(unittest.TestCase):
    def _cur(self, *, lock_ok=1, quelle=15, stadium=0, del_flag='N'):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {'L': lock_ok},                                  # GET_LOCK
            {'QUELLE': quelle, 'STADIUM': stadium,           # JOURNAL-Check
             'DEL_FLAG': del_flag},
            {'RELEASE_LOCK': 1},                             # RELEASE_LOCK
        ]
        return cur

    def _sql(self, cur):
        return ' '.join(c.args[0] for c in cur.execute.call_args_list
                        if c.args)

    def test_soft_delete_statt_hard_delete(self):
        cur = self._cur()
        r = _run(cur)
        self.assertEqual(r, {'ok': 1})
        sql = self._sql(cur)
        # CAO-Mimik: Soft-Delete + Cleanup, kein harter DELETE.
        self.assertIn("UPDATE JOURNAL SET QUELLE=-15, DEL_FLAG='Y'", sql)
        self.assertIn('DELETE FROM REFERENZEN WHERE ZIEL=2050', sql)
        self.assertIn('ARTIKEL_BDATEN', sql)
        self.assertNotIn('DELETE FROM JOURNAL ', sql)
        self.assertNotIn('DELETE FROM JOURNALPOS', sql)

    def test_record_lock_modul_2050(self):
        cur = self._cur()
        _run(cur)
        # Lockname = CAO-kompatibel, MODUL_ID 2050, RECID=JOURNAL.REC_ID.
        get_lock = [c.args for c in cur.execute.call_args_list
                    if c.args and 'GET_LOCK' in c.args[0]][0]
        self.assertEqual(get_lock[1][0], 'd_MOD_2050_RECID_7')
        self.assertIn('RELEASE_LOCK', self._sql(cur))

    def test_idempotent_noop_wenn_schon_storniert(self):
        cur = self._cur(quelle=-15, del_flag='Y')
        r = _run(cur)
        self.assertEqual(r, {'ok': 1})
        sql = self._sql(cur)
        # Re-Run: kein zweiter Soft-Delete / kein Cleanup.
        self.assertNotIn('UPDATE JOURNAL', sql)
        self.assertNotIn('DELETE FROM REFERENZEN', sql)

    def test_gebucht_wirft_permission(self):
        cur = self._cur(quelle=5, stadium=2)
        with self.assertRaises(PermissionError):
            _run(cur)

    def test_lock_belegt_wirft(self):
        cur = self._cur(lock_ok=0)
        with self.assertRaises(cao_lock.CaoLockBelegt):
            _run(cur)


class TestJournalLockTx(unittest.TestCase):
    """Zentraler Wrapper für alle JOURNAL/2050-Schreibpfade
    (einkauf_buchen, _zahlung_erfassen, vormerken/-zuruecknehmen,
    bankumsatz_uebernehmen, storno_gebucht)."""

    def test_nimmt_lock_mod_2050_und_gibt_frei(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{'L': 1}, {'RELEASE_LOCK': 1}]
        with patch.object(E, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with E._journal_lock_tx(556509) as c:
                self.assertIs(c, cur)
        calls = [c.args for c in cur.execute.call_args_list if c.args]
        get_lock = [a for a in calls if 'GET_LOCK' in a[0]][0]
        self.assertEqual(get_lock[1][0], 'd_MOD_2050_RECID_556509')
        self.assertTrue(any('RELEASE_LOCK' in a[0] for a in calls))

    def test_belegt_wirft_vor_dem_body(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'L': 0}
        with patch.object(E, 'get_db_transaction', _ctx(cur)), \
             patch.object(cao_lock, 'effektive_db_config',
                          return_value={'name': 'd'}):
            with self.assertRaises(cao_lock.CaoLockBelegt):
                with E._journal_lock_tx(1):
                    raise AssertionError('Body darf nicht laufen')


if __name__ == '__main__':
    unittest.main()
