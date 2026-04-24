"""
Unit-Tests fuer admin-app/app/stammdaten_firmenbank.py.

Tests decken ab:
- Leere Tabelle
- Mehrere Kontenrahmen werden zusammengefasst
- Delphi-Alias-Mapping (kurzbez/inhaber/blz/ktonr)
- Y/N-Flag fuer STANDARD
- INFO-Memo als Bytes
- Ohne KONTOART-Spalte: leere Ausgabe (kein Fehler)
- WHERE-Filter auf KONTOART=20 wird wirklich uebergeben
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_firmenbank.py')


class _FakeCursor:

    def __init__(self, schema_spalten, daten_rows):
        self._schema = [{'COLUMN_NAME': s} for s in schema_spalten]
        self._daten = daten_rows
        self._naechste = None
        self.letzter_sql = None
        self.letzte_args = None

    def execute(self, sql, *args, **kwargs):
        self.letzter_sql = sql
        self.letzte_args = args
        if 'INFORMATION_SCHEMA' in sql.upper():
            self._naechste = self._schema
        else:
            self._naechste = self._daten

    def fetchall(self):
        return self._naechste

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade_modul(cursor):
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: cursor
    sys.modules['db'] = fake_db
    sys.modules.pop('fb_test', None)
    spec = importlib.util.spec_from_file_location('fb_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'KONTOART'], []))
        res = mod.liste()
        self.assertEqual(res['rahmen'], [])
        self.assertEqual(res['eintraege'], [])

    def test_ohne_kontoart_spalte_leer(self):
        """Alte CAO-DBs ohne KONTOART-Spalte -> leere Ausgabe,
        kein Fehler."""
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME'], []))
        res = mod.liste()
        self.assertEqual(res['rahmen'], [])
        self.assertEqual(res['eintraege'], [])

    def test_where_filter_auf_kontoart_20(self):
        cur = _FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'KONTOART'], [])
        mod = _lade_modul(cur)
        mod.liste()
        # Die Daten-Query muss den KONTOART-Filter verwenden
        self.assertIn('KONTOART', cur.letzter_sql)
        self.assertIn('%s', cur.letzter_sql)
        # args ist ((20,),) weil *args
        self.assertEqual(cur.letzte_args[0], (20,))

    def test_delphi_aliase_werden_aufgeloest(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'KONTOART',
             'KONTO_INHABER', 'BANK_NAME', 'BANK_BLZ', 'BANK_KONTO',
             'IBAN', 'SWIFT', 'STANDARD', 'INFO'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1200,
                 'KONTONAME': 'Hausbank',
                 'KONTO_INHABER': 'Firma GmbH',
                 'BANK_NAME': 'Sparkasse',
                 'BANK_BLZ': '50010517',
                 'BANK_KONTO': '12345678',
                 'IBAN': 'DE12500105170648489890',
                 'SWIFT': 'INGDDEFF',
                 'STANDARD': 'Y',
                 'INFO': 'Hauptgeschaeftskonto'},
            ],
        ))
        e = mod.liste()['eintraege'][0]
        self.assertEqual(e['konto'], 1200)
        self.assertEqual(e['kurzbez'], 'Hausbank')
        self.assertEqual(e['inhaber'], 'Firma GmbH')
        self.assertEqual(e['bank'], 'Sparkasse')
        self.assertEqual(e['blz'], '50010517')
        self.assertEqual(e['ktonr'], '12345678')
        self.assertEqual(e['iban'], 'DE12500105170648489890')
        self.assertEqual(e['swift'], 'INGDDEFF')
        self.assertTrue(e['standard'])
        self.assertEqual(e['info'], 'Hauptgeschaeftskonto')

    def test_mehrere_rahmen_aufgesammelt(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'KONTOART'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1200,
                 'KONTONAME': 'Bank A'},
                {'KONTORAHMEN': 'SKR04', 'KONTO': 1800,
                 'KONTONAME': 'Bank B'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1210,
                 'KONTONAME': 'Bank C'},
            ],
        ))
        res = mod.liste()
        self.assertEqual(res['rahmen'], ['SKR03', 'SKR04'])
        self.assertEqual(len(res['eintraege']), 3)

    def test_standard_y_n(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'KONTOART', 'STANDARD'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1,
                 'KONTONAME': 'a', 'STANDARD': 'Y'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 2,
                 'KONTONAME': 'b', 'STANDARD': 'N'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 3,
                 'KONTONAME': 'c', 'STANDARD': None},
            ],
        ))
        eintraege = mod.liste()['eintraege']
        self.assertTrue(eintraege[0]['standard'])
        self.assertFalse(eintraege[1]['standard'])
        self.assertFalse(eintraege[2]['standard'])

    def test_info_bytes(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'KONTOART', 'INFO'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1,
                 'KONTONAME': 't', 'INFO': 'Notiz'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 2,
                 'KONTONAME': 'b', 'INFO': 'Binaer'.encode('utf-8')},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 3,
                 'KONTONAME': 'n', 'INFO': None},
            ],
        ))
        eintraege = mod.liste()['eintraege']
        self.assertEqual(eintraege[0]['info'], 'Notiz')
        self.assertEqual(eintraege[1]['info'], 'Binaer')
        self.assertEqual(eintraege[2]['info'], '')


if __name__ == '__main__':
    unittest.main()
