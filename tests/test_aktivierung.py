"""
Unit-Tests fuer common/aktivierung.py

Keine echte DB – alle DB-Zugriffe werden gemockt.
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import aktivierung  # noqa: E402


def _cur(fetchone=None, fetchall=None, rowcount=1):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall if fetchall is not None else []
    cur.rowcount = rowcount
    return cur


def _ctxmgr(cur):
    @contextmanager
    def _cm():
        yield cur
    return _cm


class _Base(unittest.TestCase):
    def setUp(self):
        aktivierung.invalidate()


class TestIstAktiv(_Base):
    def test_leere_app(self):
        self.assertFalse(aktivierung.ist_aktiv(''))
        self.assertFalse(aktivierung.ist_aktiv(None))

    def test_admin_immer_aktiv_ohne_db(self):
        # Sollte nicht einmal die DB anfragen
        with patch.object(aktivierung, 'get_db') as g:
            self.assertTrue(aktivierung.ist_aktiv('ADMIN'))
            self.assertTrue(aktivierung.ist_aktiv('admin'))
            g.assert_not_called()

    def test_unbekannte_app_false(self):
        self.assertFalse(aktivierung.ist_aktiv('UNBEKANNT'))

    def test_aktiv_true(self):
        cur = _cur(fetchone={'AKTIV': 1, 'LIZENZ_BIS': None})
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            self.assertTrue(aktivierung.ist_aktiv('KASSE'))

    def test_aktiv_false(self):
        cur = _cur(fetchone={'AKTIV': 0, 'LIZENZ_BIS': None})
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            self.assertFalse(aktivierung.ist_aktiv('KASSE'))

    def test_kein_eintrag_fail_closed(self):
        cur = _cur(fetchone=None)
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            self.assertFalse(aktivierung.ist_aktiv('KIOSK'))

    def test_lizenz_abgelaufen(self):
        gestern = date.today() - timedelta(days=1)
        cur = _cur(fetchone={'AKTIV': 1, 'LIZENZ_BIS': gestern})
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            self.assertFalse(aktivierung.ist_aktiv('ORGA'))

    def test_lizenz_heute_noch_gueltig(self):
        heute = date.today()
        cur = _cur(fetchone={'AKTIV': 1, 'LIZENZ_BIS': heute})
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            self.assertTrue(aktivierung.ist_aktiv('ORGA'))

    def test_cache_verhindert_zweite_query(self):
        cur = _cur(fetchone={'AKTIV': 1, 'LIZENZ_BIS': None})
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            self.assertTrue(aktivierung.ist_aktiv('KASSE'))
            self.assertTrue(aktivierung.ist_aktiv('KASSE'))  # aus cache
        self.assertEqual(cur.execute.call_count, 1)

    def test_db_fehler_fail_closed(self):
        @contextmanager
        def boom():
            raise RuntimeError('db weg')
            yield  # pragma: no cover
        with patch.object(aktivierung, 'get_db', boom):
            self.assertFalse(aktivierung.ist_aktiv('KASSE'))


class TestSetAktiv(_Base):
    def test_ungueltige_app(self):
        with self.assertRaises(ValueError):
            aktivierung.set_aktiv('UNBEKANNT', True)

    def test_admin_nicht_deaktivierbar(self):
        with self.assertRaises(ValueError):
            aktivierung.set_aktiv('ADMIN', False)

    def test_admin_kann_reaktiviert_werden(self):
        # Aktivierung (idempotent) ist erlaubt
        cur = _cur()
        with patch.object(aktivierung, 'get_db_transaction', _ctxmgr(cur)):
            aktivierung.set_aktiv('ADMIN', True, hinweis='ok')
        cur.execute.assert_called_once()

    def test_upsert(self):
        cur = _cur()
        with patch.object(aktivierung, 'get_db_transaction', _ctxmgr(cur)):
            aktivierung.set_aktiv('KIOSK', False, hinweis='Wartung')
        sql, params = cur.execute.call_args.args
        self.assertIn('ON DUPLICATE KEY UPDATE', sql)
        self.assertEqual(params, ('KIOSK', 0, None, 'Wartung'))

    def test_cache_invalidierung(self):
        cur_read = _cur(fetchone={'AKTIV': 1, 'LIZENZ_BIS': None})
        # 1. Lesen → True, in Cache
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur_read)):
            self.assertTrue(aktivierung.ist_aktiv('KASSE'))
        # 2. Schreibend deaktivieren → Cache muss weg sein
        cur_write = _cur()
        with patch.object(aktivierung, 'get_db_transaction',
                          _ctxmgr(cur_write)):
            aktivierung.set_aktiv('KASSE', False)
        # 3. Naechstes Lesen muss wieder die DB treffen
        cur_read2 = _cur(fetchone={'AKTIV': 0, 'LIZENZ_BIS': None})
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur_read2)):
            self.assertFalse(aktivierung.ist_aktiv('KASSE'))


class TestSeedDefaults(_Base):
    def test_zaehlt_rowcount(self):
        cur = _cur(rowcount=1)
        with patch.object(aktivierung, 'get_db_transaction', _ctxmgr(cur)):
            n = aktivierung.seed_defaults()
        self.assertEqual(n, 4)  # KIOSK, KASSE, ORGA, ADMIN

    def test_bereits_vorhanden(self):
        cur = _cur(rowcount=0)
        with patch.object(aktivierung, 'get_db_transaction', _ctxmgr(cur)):
            n = aktivierung.seed_defaults()
        self.assertEqual(n, 0)


class TestAlle(_Base):
    def test_ordering_mit_field(self):
        cur = _cur(fetchall=[])
        with patch.object(aktivierung, 'get_db', _ctxmgr(cur)):
            aktivierung.alle()
        sql = cur.execute.call_args.args[0]
        self.assertIn('ORDER BY FIELD', sql)
        self.assertIn("'KIOSK'", sql)


class TestInvalidate(_Base):
    def test_einzeln(self):
        aktivierung._cache_put('KASSE', True)
        aktivierung._cache_put('KIOSK', True)
        aktivierung.invalidate('KASSE')
        self.assertIsNone(aktivierung._cache_get('KASSE'))
        self.assertTrue(aktivierung._cache_get('KIOSK'))

    def test_gesamt(self):
        aktivierung._cache_put('KASSE', True)
        aktivierung._cache_put('KIOSK', True)
        aktivierung.invalidate()
        self.assertIsNone(aktivierung._cache_get('KASSE'))
        self.assertIsNone(aktivierung._cache_get('KIOSK'))


if __name__ == '__main__':
    unittest.main()
