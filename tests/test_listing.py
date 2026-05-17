"""Tests fuer common.listing (Sort-Whitelist, Paginierung)."""
from __future__ import annotations

import os
import sys
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import listing  # noqa: E402


class _Args(dict):
    """Mini-Ersatz fuer request.args (mit get(..., type=int))."""
    def get(self, key, default=None, type=None):  # noqa: A002
        if key not in self or self[key] in (None, ''):
            return default
        v = self[key]
        if type is int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default
        return v


_ALLOWED = {'datum': 'j.RDATUM', 'name': 'a.NAME1'}
_DEFAULT = 'j.RDATUM DESC, j.REC_ID DESC'


class TestParseSort(unittest.TestCase):
    def test_gueltig_asc(self):
        o, k, d = listing.parse_sort(_Args(sort='datum', dir='asc'),
                                     _ALLOWED, _DEFAULT)
        self.assertTrue(o.startswith('j.RDATUM ASC'))
        self.assertIn(_DEFAULT, o)        # Tie-Breaker angehaengt
        self.assertEqual((k, d), ('datum', 'asc'))

    def test_nicht_whitelisted_faellt_auf_default(self):
        o, k, d = listing.parse_sort(
            _Args(sort='DROP TABLE', dir='asc'), _ALLOWED, _DEFAULT)
        self.assertEqual(o, _DEFAULT)
        self.assertEqual((k, d), ('', ''))

    def test_ungueltige_richtung(self):
        o, k, d = listing.parse_sort(_Args(sort='datum', dir='hoch'),
                                     _ALLOWED, _DEFAULT)
        self.assertEqual(o, _DEFAULT)

    def test_aufgehoben_ohne_param(self):
        o, k, d = listing.parse_sort(_Args(), _ALLOWED, _DEFAULT)
        self.assertEqual((o, k, d), (_DEFAULT, '', ''))


class TestParsePaging(unittest.TestCase):
    def test_default(self):
        self.assertEqual(listing.parse_paging(_Args()), (1, 100))

    def test_clamp(self):
        self.assertEqual(
            listing.parse_paging(_Args(page='-3', per_page='9999'),
                                 max_per_page=500), (1, 500))
        self.assertEqual(
            listing.parse_paging(_Args(per_page='1'))[1], 10)  # min 10


class TestPager(unittest.TestCase):
    def test_mitte(self):
        p = listing.pager(total=250, page=2, per_page=100)
        self.assertEqual((p['seiten'], p['offset'], p['von'], p['bis']),
                         (3, 100, 101, 200))
        self.assertTrue(p['hat_vor'] and p['hat_zurueck'])

    def test_clamp_ueber_ende(self):
        p = listing.pager(total=5, page=99, per_page=100)
        self.assertEqual(p['page'], 1)
        self.assertEqual((p['von'], p['bis']), (1, 5))
        self.assertFalse(p['hat_vor'])

    def test_leer(self):
        p = listing.pager(total=0, page=1, per_page=100)
        self.assertEqual((p['total'], p['von'], p['bis'], p['seiten']),
                         (0, 0, 0, 1))


class TestPeriode(unittest.TestCase):
    from datetime import date as _d
    H = _d(2026, 5, 16)

    def test_monat_default_und_grenzen(self):
        p = listing.periode('monat', None, self.H)
        self.assertEqual(p['label'], 'Mai 2026')
        self.assertEqual((p['von'].isoformat(), p['bis'].isoformat()),
                         ('2026-05-01', '2026-05-31'))
        self.assertEqual((p['prev'], p['next']), ('2026-04', '2026-06'))

    def test_monat_jahreswechsel(self):
        self.assertEqual(
            listing.periode('monat', '2026-01', self.H)['prev'],
            '2025-12')
        self.assertEqual(
            listing.periode('monat', '2026-12', self.H)['next'],
            '2027-01')

    def test_quartal(self):
        p = listing.periode('quartal', '2026-Q2', self.H)
        self.assertEqual((p['von'].isoformat(), p['bis'].isoformat()),
                         ('2026-04-01', '2026-06-30'))
        self.assertEqual((p['prev'], p['next']),
                         ('2026-Q1', '2026-Q3'))

    def test_jahr(self):
        p = listing.periode('jahr', '2024', self.H)
        self.assertEqual((p['von'].isoformat(), p['bis'].isoformat()),
                         ('2024-01-01', '2024-12-31'))

    def test_ungueltig_faellt_auf_aktuell(self):
        p = listing.periode('quatsch', 'xx', self.H)
        self.assertEqual(p['gran'], 'monat')
        self.assertEqual(p['label'], 'Mai 2026')
        self.assertEqual(
            listing.periode('quartal', 'kaputt', self.H)['label'],
            'Q2 2026')


class TestPeriodeFromRequest(unittest.TestCase):
    from datetime import date as _d
    H = _d(2026, 5, 16)

    def test_default_aktueller_monat_und_merkt(self):
        sess = {}
        pz, jahre = listing.periode_from_request(
            _Args(), sess, 'ek', self.H)
        self.assertEqual(pz['label'], 'Mai 2026')
        self.assertEqual(sess['ek_gran'], 'monat')
        self.assertEqual(sess['ek_periode'], '2026-05')
        self.assertIn(2026, jahre)

    def test_session_fallback(self):
        sess = {'we_gran': 'quartal', 'we_periode': '2025-Q4'}
        pz, _ = listing.periode_from_request(
            _Args(), sess, 'we', self.H)
        self.assertEqual(pz['label'], 'Q4 2025')

    def test_dropdown_args_schlagen_session(self):
        sess = {'ek_gran': 'jahr', 'ek_periode': '2020'}
        pz, _ = listing.periode_from_request(
            _Args(gran='monat', jahr='2024', monat='3'),
            sess, 'ek', self.H)
        self.assertEqual(pz['label'], 'März 2024')
        self.assertEqual(sess['ek_periode'], '2024-03')

    def test_prefix_isoliert(self):
        sess = {'ek_periode': '2026-01', 'ek_gran': 'monat'}
        pz, _ = listing.periode_from_request(
            _Args(), sess, 'best', self.H)   # anderer Prefix
        self.assertEqual(pz['label'], 'Mai 2026')  # nicht ek-Stand


if __name__ == '__main__':
    unittest.main()
