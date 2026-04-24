"""
Unit-Tests fuer common/backwaren/*

Interface-Contract, CSV-Parsing, Factory-Lookup, Stubs.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.backwaren import (  # noqa: E402
    ADAPTER_TYPEN,
    Artikel,
    BackwarenDatenquelle,
    CaoMysqlQuelle,
    CsvQuelle,
    ExcelQuelle,
    GoogleSheetQuelle,
    get_quelle,
)
from common.backwaren import cao_mysql as _cao_mysql_mod  # noqa: E402
from common.backwaren import factory as _factory_mod  # noqa: E402


def _ctxmgr(cur):
    @contextmanager
    def _cm():
        yield cur
    return _cm


class TestArtikel(unittest.TestCase):
    def test_als_dict_roundtrip(self):
        a = Artikel(artikel_id=7, artnum='A7', name='Brezn',
                    preis_cent=120, bestand=4.5, einheit='Stk')
        d = a.als_dict()
        self.assertEqual(d['artikel_id'], 7)
        self.assertEqual(d['preis_cent'], 120)
        self.assertEqual(d['bestand'], 4.5)

    def test_frozen(self):
        a = Artikel(1, 'X', 'n', 100)
        with self.assertRaises(Exception):
            a.preis_cent = 200  # type: ignore[misc]


class TestInterface(unittest.TestCase):
    def test_default_bestand_sucht_in_liste(self):
        class Dummy(BackwarenDatenquelle):
            TYP = 'DUMMY'

            def artikel_liste(self):
                return [Artikel(1, 'A', 'a', 100, bestand=3.0),
                        Artikel(2, 'B', 'b', 200)]
        d = Dummy()
        self.assertEqual(d.bestand(1), 3.0)
        self.assertIsNone(d.bestand(2))
        self.assertIsNone(d.bestand(99))

    def test_schreiben_nicht_erlaubt(self):
        class Dummy(BackwarenDatenquelle):
            TYP = 'DUMMY'

            def artikel_liste(self):
                return []
        with self.assertRaises(NotImplementedError):
            Dummy().schreibe_verkauf()


class TestCaoMysqlQuelle(unittest.TestCase):
    def test_artikel_liste_mapping(self):
        rows = [{
            'artikel_id': 10, 'artnum': 'AR10', 'name': 'Brot',
            'preis_cent': 250, 'bestand': 12.5, 'einheit': 'Stk',
            'gesperrt': 0,
        }]
        cur = MagicMock()
        cur.fetchall.return_value = rows
        with patch.object(_cao_mysql_mod, 'get_db', _ctxmgr(cur)):
            arts = CaoMysqlQuelle().artikel_liste()
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].artikel_id, 10)
        self.assertEqual(arts[0].preis_cent, 250)
        self.assertEqual(arts[0].bestand, 12.5)
        self.assertTrue(arts[0].aktiv)
        # Warengruppe als Parameter
        args = cur.execute.call_args.args
        self.assertEqual(args[1], ('101',))

    def test_gesperrt_mapped_auf_aktiv_false(self):
        rows = [{
            'artikel_id': 11, 'artnum': 'AR11', 'name': 'x',
            'preis_cent': 100, 'bestand': None, 'einheit': None,
            'gesperrt': 1,
        }]
        cur = MagicMock()
        cur.fetchall.return_value = rows
        with patch.object(_cao_mysql_mod, 'get_db', _ctxmgr(cur)):
            arts = CaoMysqlQuelle().artikel_liste()
        self.assertFalse(arts[0].aktiv)
        self.assertEqual(arts[0].einheit, 'Stk')  # Default

    def test_db_fehler_leerliste(self):
        @contextmanager
        def boom():
            raise RuntimeError('db')
            yield  # pragma: no cover
        with patch.object(_cao_mysql_mod, 'get_db', boom):
            arts = CaoMysqlQuelle().artikel_liste()
        self.assertEqual(arts, [])

    def test_bestand_direkt_lookup(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'MENGE_LAGER': 7.5}
        with patch.object(_cao_mysql_mod, 'get_db', _ctxmgr(cur)):
            self.assertEqual(CaoMysqlQuelle().bestand(42), 7.5)
        cur.fetchone.return_value = None
        with patch.object(_cao_mysql_mod, 'get_db', _ctxmgr(cur)):
            self.assertIsNone(CaoMysqlQuelle().bestand(99))


class TestCsvQuelle(unittest.TestCase):
    def _schreibe_csv(self, inhalt: str) -> str:
        fd, pfad = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write(inhalt)
        self.addCleanup(os.unlink, pfad)
        return pfad

    def test_vollstaendige_zeile(self):
        pfad = self._schreibe_csv(
            'artikel_id,artnum,name,preis_cent,bestand,einheit,aktiv\n'
            '1,A001,Brot,250,5.0,Stk,1\n'
            '2,A002,Brezn,90,,,1\n')
        arts = CsvQuelle(pfad).artikel_liste()
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0].name, 'Brot')
        self.assertEqual(arts[0].bestand, 5.0)
        self.assertIsNone(arts[1].bestand)
        self.assertEqual(arts[1].einheit, 'Stk')  # Default

    def test_ungueltige_zeile_uebersprungen(self):
        pfad = self._schreibe_csv(
            'artikel_id,artnum,name,preis_cent\n'
            'abc,x,y,100\n'         # artikel_id kein int
            '5,A5,Brotchen,200\n')
        arts = CsvQuelle(pfad).artikel_liste()
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].artikel_id, 5)

    def test_datei_fehlt(self):
        self.assertEqual(CsvQuelle('/nicht/da.csv').artikel_liste(), [])

    def test_aktiv_null_wird_false(self):
        pfad = self._schreibe_csv(
            'artikel_id,artnum,name,preis_cent,aktiv\n'
            '1,A,x,50,0\n')
        self.assertFalse(CsvQuelle(pfad).artikel_liste()[0].aktiv)

    def test_delimiter_semikolon(self):
        pfad = self._schreibe_csv(
            'artikel_id;artnum;name;preis_cent\n'
            '1;A1;x;100\n')
        arts = CsvQuelle(pfad, delimiter=';').artikel_liste()
        self.assertEqual(len(arts), 1)


class TestStubs(unittest.TestCase):
    def test_excel_nicht_impl(self):
        with self.assertRaises(NotImplementedError):
            ExcelQuelle('/tmp/x.xlsx').artikel_liste()

    def test_google_sheet_nicht_impl(self):
        with self.assertRaises(NotImplementedError):
            GoogleSheetQuelle('abc').artikel_liste()


class TestFactory(unittest.TestCase):
    def setUp(self):
        self._konfig_werte: dict = {}

        def _get(key, default=None):
            return self._konfig_werte.get(key, default)
        self._patch = patch.object(_factory_mod, '_konfig_get',
                                   side_effect=_get)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_default_cao(self):
        q = get_quelle()
        self.assertIsInstance(q, CaoMysqlQuelle)
        self.assertEqual(q.warengruppe, '101')

    def test_explizit_csv(self):
        self._konfig_werte['backwaren.csv.pfad'] = '/tmp/x.csv'
        self._konfig_werte['backwaren.csv.delimiter'] = ';'
        q = get_quelle('CSV')
        self.assertIsInstance(q, CsvQuelle)
        self.assertEqual(q.delimiter, ';')

    def test_konfig_steuert_typ(self):
        self._konfig_werte['backwaren.quelle.typ'] = 'EXCEL'
        self._konfig_werte['backwaren.excel.pfad'] = '/tmp/b.xlsx'
        q = get_quelle()
        self.assertIsInstance(q, ExcelQuelle)

    def test_google_sheet(self):
        self._konfig_werte['backwaren.quelle.typ'] = 'GOOGLE_SHEET'
        self._konfig_werte['backwaren.google_sheet.id'] = 'sheet42'
        q = get_quelle()
        self.assertIsInstance(q, GoogleSheetQuelle)
        self.assertEqual(q.sheet_id, 'sheet42')

    def test_unbekannter_typ_fallback_cao(self):
        q = get_quelle('UNKNOWN')
        self.assertIsInstance(q, CaoMysqlQuelle)

    def test_adapter_typen_konstante(self):
        self.assertEqual(
            set(ADAPTER_TYPEN),
            {'CAO', 'CSV', 'EXCEL', 'GOOGLE_SHEET'})


if __name__ == '__main__':
    unittest.main()
