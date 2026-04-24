"""
Unit-Tests fuer admin-app/app/stammdaten_lieferart.py.

DB wird gestubbt; geprueft werden:
- Schema-Introspektion (LIEFERARTEN hat nur REC_ID/NAME vs. mit TEXT-Spalte)
- Trimmen, leeres/ungepflegtes TEXT
- BLOB-Decodierung und has_text-Flag
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_lieferart.py')


class _FakeCursor:
    """Faker, der auf jede execute-Folge die naechste vorbereitete Zeile
    ausliefert. ``schema_spalten`` sind die von INFORMATION_SCHEMA
    erwarteten Spalten."""

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
    # Modul frisch laden, damit _spalten_cache zurueckgesetzt ist
    sys.modules.pop('sla_test', None)
    spec = importlib.util.spec_from_file_location('sla_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle_ohne_text_spalte(self):
        mod = _lade_modul(_FakeCursor(['REC_ID', 'NAME'], []))
        self.assertEqual(mod.liste(), [])

    def test_ohne_text_spalte_liefert_leere_texte(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME'],
            [{'REC_ID': 1, 'NAME': 'DHL'}],
        ))
        res = mod.liste()
        self.assertEqual(res[0]['name'], 'DHL')
        self.assertEqual(res[0]['text'], '')
        self.assertFalse(res[0]['has_text'])

    def test_mit_text_spalte(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'TEXT'],
            [{'REC_ID': 1, 'NAME': 'Selbstabholung',
              'TEXT': 'Bitte abholen.'}],
        ))
        res = mod.liste()
        self.assertEqual(res[0]['text'], 'Bitte abholen.')
        self.assertTrue(res[0]['has_text'])

    def test_leerer_text_hat_has_text_false(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'TEXT'],
            [
                {'REC_ID': 2, 'NAME': 'DHL', 'TEXT': None},
                {'REC_ID': 3, 'NAME': 'UPS', 'TEXT': '   '},
                {'REC_ID': 4, 'NAME': 'Spedition', 'TEXT': ''},
            ],
        ))
        res = mod.liste()
        for e in res:
            self.assertEqual(e['text'], '')
            self.assertFalse(e['has_text'])

    def test_blob_text_wird_decodiert(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'TEXT'],
            [{'REC_ID': 5, 'NAME': 'Versand',
              'TEXT': 'Versand mit DHL – Lieferzeit 1–2 Tage.'.encode(
                  'utf-8')}],
        ))
        res = mod.liste()
        self.assertIn('Lieferzeit', res[0]['text'])
        self.assertTrue(res[0]['has_text'])

    def test_alternative_text_spalte_langtext(self):
        """Falls CAO-Variante 'LANGTEXT' statt 'TEXT' hat."""
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'LANGTEXT'],
            [{'REC_ID': 7, 'NAME': 'Abholung', 'LANGTEXT': 'Hier abholen'}],
        ))
        res = mod.liste()
        self.assertEqual(res[0]['text'], 'Hier abholen')

    def test_name_wird_getrimmt(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'TEXT'],
            [{'REC_ID': 6, 'NAME': '  Abholung  ', 'TEXT': '  rand  '}],
        ))
        res = mod.liste()
        self.assertEqual(res[0]['name'], 'Abholung')
        self.assertEqual(res[0]['text'], 'rand')


if __name__ == '__main__':
    unittest.main()
