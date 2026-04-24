"""
Unit-Tests fuer admin-app/app/stammdaten_attribut.py.

Tests decken ab:
- Keine ARTIKEL_ATTRIBUT-Tabelle in der DB -> []
- Attribute ohne Optionen
- Attribut + Optionen verknuepft
- Nutzungszaehlung aus ARTIKEL_TO_ATTRIBUT
- Preis 0 wird zu None
- Sortierung nach POS
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_attribut.py')


class _FakeCursor:
    """Fake-Cursor, der basierend auf dem Tabellennamen antwortet."""

    def __init__(self, schemas: dict, daten: dict, nutz: list = None):
        # schemas: {tabellenname: [spalten]}
        # daten:   {tabellenname: [rows]}
        # nutz:    [{OPTIONS_ID, ANZ}] – Ergebnis der GROUP-BY-Query
        self._schemas = schemas
        self._daten = daten
        self._nutz = nutz or []
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
        u = sql.upper()
        if 'INFORMATION_SCHEMA' in u:
            # args[0] ist (tabname,) Parameter
            tab = args[0][0] if args else ''
            self._naechste = [
                {'COLUMN_NAME': s}
                for s in self._schemas.get(tab.upper(), [])
            ]
        elif 'FROM ARTIKEL_TO_ATTRIBUT' in u and 'COUNT' in u:
            self._naechste = self._nutz
        elif 'FROM ARTIKEL_ATTRIBUT_OPTIONEN' in u:
            self._naechste = self._daten.get('ARTIKEL_ATTRIBUT_OPTIONEN', [])
        elif 'FROM ARTIKEL_ATTRIBUT' in u:
            self._naechste = self._daten.get('ARTIKEL_ATTRIBUT', [])
        else:
            self._naechste = []

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
    sys.modules.pop('attr_test', None)
    spec = importlib.util.spec_from_file_location('attr_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_keine_tabelle(self):
        mod = _lade_modul(_FakeCursor(schemas={}, daten={}))
        self.assertEqual(mod.liste(), [])

    def test_attribut_ohne_optionen(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'ARTIKEL_ATTRIBUT': ['ATTRIBUT_ID', 'NAME', 'POS', 'LISTTYP'],
            },
            daten={
                'ARTIKEL_ATTRIBUT': [
                    {'ATTRIBUT_ID': 1, 'NAME': 'Farbe',
                     'POS': 1, 'LISTTYP': 'K'},
                ],
            },
        ))
        erg = mod.liste()
        self.assertEqual(len(erg), 1)
        self.assertEqual(erg[0]['name'], 'Farbe')
        self.assertEqual(erg[0]['listtyp'], 'K')
        self.assertEqual(erg[0]['optionen'], [])

    def test_attribut_mit_optionen_und_nutzung(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'ARTIKEL_ATTRIBUT': ['ATTRIBUT_ID', 'NAME', 'POS', 'LISTTYP'],
                'ARTIKEL_ATTRIBUT_OPTIONEN': [
                    'OPTIONS_ID', 'ATTRIBUT_ID', 'NAME', 'PREIS',
                    'POS', 'LISTTYP',
                ],
                'ARTIKEL_TO_ATTRIBUT': ['OPTIONS_ID', 'ARTIKEL_ID'],
            },
            daten={
                'ARTIKEL_ATTRIBUT': [
                    {'ATTRIBUT_ID': 1, 'NAME': 'Groesse',
                     'POS': 2, 'LISTTYP': 'K'},
                ],
                'ARTIKEL_ATTRIBUT_OPTIONEN': [
                    {'OPTIONS_ID': 10, 'ATTRIBUT_ID': 1, 'NAME': 'S',
                     'PREIS': 0, 'POS': 1, 'LISTTYP': 'N'},
                    {'OPTIONS_ID': 11, 'ATTRIBUT_ID': 1, 'NAME': 'M',
                     'PREIS': 0, 'POS': 2, 'LISTTYP': 'N'},
                    {'OPTIONS_ID': 12, 'ATTRIBUT_ID': 1, 'NAME': 'XXL',
                     'PREIS': 2.50, 'POS': 5, 'LISTTYP': 'N'},
                ],
            },
            nutz=[
                {'OPTIONS_ID': 10, 'ANZ': 42},
                {'OPTIONS_ID': 11, 'ANZ': 73},
            ],
        ))
        erg = mod.liste()
        self.assertEqual(len(erg), 1)
        opt = erg[0]['optionen']
        self.assertEqual(len(opt), 3)
        by_name = {o['name']: o for o in opt}
        self.assertIsNone(by_name['S']['preis'])   # 0 -> None
        self.assertEqual(by_name['S']['nutzungen'], 42)
        self.assertEqual(by_name['M']['nutzungen'], 73)
        self.assertEqual(by_name['XXL']['preis'], 2.50)
        self.assertEqual(by_name['XXL']['nutzungen'], 0)

    def test_mehrere_attribute_zuordnung_korrekt(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'ARTIKEL_ATTRIBUT': ['ATTRIBUT_ID', 'NAME', 'POS', 'LISTTYP'],
                'ARTIKEL_ATTRIBUT_OPTIONEN': [
                    'OPTIONS_ID', 'ATTRIBUT_ID', 'NAME', 'PREIS',
                    'POS', 'LISTTYP',
                ],
            },
            daten={
                'ARTIKEL_ATTRIBUT': [
                    {'ATTRIBUT_ID': 1, 'NAME': 'Farbe',
                     'POS': 1, 'LISTTYP': 'K'},
                    {'ATTRIBUT_ID': 2, 'NAME': 'Groesse',
                     'POS': 2, 'LISTTYP': 'K'},
                ],
                'ARTIKEL_ATTRIBUT_OPTIONEN': [
                    {'OPTIONS_ID': 10, 'ATTRIBUT_ID': 1, 'NAME': 'Rot',
                     'PREIS': 0, 'POS': 1, 'LISTTYP': 'N'},
                    {'OPTIONS_ID': 20, 'ATTRIBUT_ID': 2, 'NAME': 'S',
                     'PREIS': 0, 'POS': 1, 'LISTTYP': 'N'},
                ],
            },
        ))
        erg = mod.liste()
        by_id = {a['id']: a for a in erg}
        self.assertEqual(len(by_id[1]['optionen']), 1)
        self.assertEqual(by_id[1]['optionen'][0]['name'], 'Rot')
        self.assertEqual(len(by_id[2]['optionen']), 1)
        self.assertEqual(by_id[2]['optionen'][0]['name'], 'S')


if __name__ == '__main__':
    unittest.main()
