"""
Unit-Tests fuer admin-app/app/stammdaten_kontenrahmen.py.

Tests decken ab:
- Leere Tabelle
- Mehrere Kontenrahmen werden zusammengefasst
- 0 -> None fuer nebenkonto/steuersatz/ustva_zeile/bwa_gruppe
- Bank-Dict nur bei gesetzten Bank-Feldern
- Y/N-Flags fuer BILANZKONTO, NK_AUSWAHL, STANDARD
- INFO-Memo als Bytes
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_kontenrahmen.py')


class _FakeCursor:

    def __init__(self, schema_spalten, daten_rows):
        self._schema = [{'COLUMN_NAME': s} for s in schema_spalten]
        self._daten = daten_rows
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
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
    sys.modules.pop('kr_test', None)
    spec = importlib.util.spec_from_file_location('kr_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME'], []))
        res = mod.liste()
        self.assertEqual(res['rahmen'], [])
        self.assertEqual(res['eintraege'], [])

    def test_mehrere_rahmen(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1000,
                 'KONTONAME': 'Kasse'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1200,
                 'KONTONAME': 'Bank'},
                {'KONTORAHMEN': 'SKR04', 'KONTO': 1600,
                 'KONTONAME': 'Kasse (SKR04)'},
            ],
        ))
        res = mod.liste()
        self.assertEqual(res['rahmen'], ['SKR03', 'SKR04'])
        self.assertEqual(len(res['eintraege']), 3)

    def test_nullen_werden_none(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME',
             'NEBENKONTO', 'STEUERSATZ', 'USTVA_ZEILE', 'BWA_GRUPPE'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1000,
                 'KONTONAME': 'Kasse', 'NEBENKONTO': 0,
                 'STEUERSATZ': 0, 'USTVA_ZEILE': 0, 'BWA_GRUPPE': 0},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 3400,
                 'KONTONAME': 'Wareneingang 19%', 'NEBENKONTO': 1576,
                 'STEUERSATZ': 19.0, 'USTVA_ZEILE': 81, 'BWA_GRUPPE': 12},
            ],
        ))
        eintraege = mod.liste()['eintraege']
        self.assertIsNone(eintraege[0]['nebenkonto'])
        self.assertIsNone(eintraege[0]['steuersatz'])
        self.assertIsNone(eintraege[0]['ustva_zeile'])
        self.assertIsNone(eintraege[0]['bwa_gruppe'])
        self.assertEqual(eintraege[1]['nebenkonto'], 1576)
        self.assertEqual(eintraege[1]['steuersatz'], 19.0)
        self.assertEqual(eintraege[1]['ustva_zeile'], 81)
        self.assertEqual(eintraege[1]['bwa_gruppe'], 12)

    def test_y_n_flags(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME',
             'BILANZKONTO', 'NK_AUSWAHL', 'STANDARD'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1,
                 'KONTONAME': 'alle Y', 'BILANZKONTO': 'Y',
                 'NK_AUSWAHL': 'Y', 'STANDARD': 'Y'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 2,
                 'KONTONAME': 'alle N', 'BILANZKONTO': 'N',
                 'NK_AUSWAHL': 'N', 'STANDARD': 'N'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 3,
                 'KONTONAME': 'null', 'BILANZKONTO': None,
                 'NK_AUSWAHL': None, 'STANDARD': None},
            ],
        ))
        eintraege = mod.liste()['eintraege']
        self.assertTrue(eintraege[0]['bilanzkonto'])
        self.assertTrue(eintraege[0]['nk_auswahl'])
        self.assertTrue(eintraege[0]['standard'])
        self.assertFalse(eintraege[1]['bilanzkonto'])
        self.assertFalse(eintraege[2]['bilanzkonto'])

    def test_bank_dict_nur_bei_bankkonto(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME',
             'IBAN', 'SWIFT', 'BANK_NAME', 'BANK_BLZ',
             'BANK_KONTO', 'KONTO_INHABER'],
            [
                # Kein Bankkonto: keines der Bank-Felder gesetzt
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1000,
                 'KONTONAME': 'Kasse',
                 'IBAN': None, 'SWIFT': None, 'BANK_NAME': None,
                 'BANK_BLZ': None, 'BANK_KONTO': None,
                 'KONTO_INHABER': None},
                # Bankkonto: IBAN + Bankname gesetzt
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1200,
                 'KONTONAME': 'Bank',
                 'IBAN': 'DE12500105170648489890',
                 'SWIFT': 'INGDDEFF', 'BANK_NAME': 'ING',
                 'BANK_BLZ': '', 'BANK_KONTO': '',
                 'KONTO_INHABER': 'Firma GmbH'},
            ],
        ))
        eintraege = mod.liste()['eintraege']
        self.assertIsNone(eintraege[0]['bank'])
        self.assertIsNotNone(eintraege[1]['bank'])
        self.assertEqual(eintraege[1]['bank']['iban'],
                         'DE12500105170648489890')
        self.assertEqual(eintraege[1]['bank']['swift'], 'INGDDEFF')
        self.assertEqual(eintraege[1]['bank']['inhaber'], 'Firma GmbH')

    def test_info_bytes(self):
        mod = _lade_modul(_FakeCursor(
            ['KONTORAHMEN', 'KONTO', 'KONTONAME', 'INFO'],
            [
                {'KONTORAHMEN': 'SKR03', 'KONTO': 1,
                 'KONTONAME': 't', 'INFO': 'Hinweis'},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 2,
                 'KONTONAME': 'b', 'INFO': 'BLOB'.encode('utf-8')},
                {'KONTORAHMEN': 'SKR03', 'KONTO': 3,
                 'KONTONAME': 'n', 'INFO': None},
            ],
        ))
        eintraege = mod.liste()['eintraege']
        self.assertEqual(eintraege[0]['info'], 'Hinweis')
        self.assertEqual(eintraege[1]['info'], 'BLOB')
        self.assertEqual(eintraege[2]['info'], '')


if __name__ == '__main__':
    unittest.main()
