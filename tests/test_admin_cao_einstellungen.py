"""
Unit-Tests fuer admin-app/app/cao_einstellungen.py – reine Logik ohne DB.

Deckt ab:
- kategorie_fuer: Mapping MAINKEY → (Label, Icon, Sortier-Index).
- wert_extrahieren: Prioritaet VAL_CHAR > VAL_INT > ... und Blob-Handling.

Die DB-Funktionen (registry_laden / gruppiert_nach_kategorie) werden in
Integrationstests gegen eine Test-DB abgedeckt – hier bleibt alles
offline. Wir stubben ``db.get_db`` daher mit einem No-op.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'cao_einstellungen.py')

# admin-app/app hat einen Bindestrich – kein regulaerer Paketimport moeglich.
_fake_db = types.ModuleType('db')
_fake_db.get_db = lambda: None  # noqa: E731
sys.modules['db'] = _fake_db

_spec = importlib.util.spec_from_file_location('cao_einstellungen_test_modul',
                                               _MODUL_PATH)
ce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ce)


class TestKategorieFuer(unittest.TestCase):
    def test_main_ist_erste_kategorie(self):
        label, icon, idx = ce.kategorie_fuer('MAIN')
        self.assertEqual(label, 'Allgemein')
        self.assertEqual(idx, 0)

    def test_email_hat_eigene_kategorie(self):
        label, icon, idx = ce.kategorie_fuer('MAIN\\EMAIL')
        self.assertEqual(label, 'EMail-Einstellungen')
        self.assertGreater(idx, 0)

    def test_adressen_userfelder_unterscheiden_sich_von_adressen(self):
        a = ce.kategorie_fuer('MAIN\\ADRESSEN')
        b = ce.kategorie_fuer('MAIN\\ADRESSEN\\USERFELDER')
        self.assertNotEqual(a[0], b[0])
        self.assertNotEqual(a[2], b[2])

    def test_unbekannter_mainkey_landet_am_ende(self):
        label, icon, idx = ce.kategorie_fuer('MAIN\\VOELLIG_UNBEKANNT')
        # Unbekannte bekommen den groessten Sortier-Index.
        self.assertEqual(idx, len(ce._KATEGORIEN))
        # Label ist der MAINKEY selbst (so bleibt er sichtbar).
        self.assertEqual(label, 'MAIN\\VOELLIG_UNBEKANNT')

    def test_leerer_mainkey_bekommt_fallback_label(self):
        label, icon, idx = ce.kategorie_fuer('')
        self.assertEqual(label, '(ohne Kategorie)')


class TestWertExtrahieren(unittest.TestCase):
    def test_val_char_gewinnt(self):
        wert, typ = ce.wert_extrahieren({'VAL_CHAR': 'hallo', 'VAL_INT': 42})
        self.assertEqual(wert, 'hallo')
        self.assertEqual(typ, 'char')

    def test_val_int_wenn_char_null(self):
        wert, typ = ce.wert_extrahieren({'VAL_CHAR': None, 'VAL_INT': 42})
        self.assertEqual(wert, '42')
        self.assertEqual(typ, 'int')

    def test_val_double_mit_null_int(self):
        wert, typ = ce.wert_extrahieren({'VAL_INT': None, 'VAL_DOUBLE': 19.0})
        self.assertEqual(wert, '19.0')
        self.assertEqual(typ, 'double')

    def test_alle_leer_liefert_none(self):
        wert, typ = ce.wert_extrahieren({'VAL_CHAR': None, 'VAL_INT': None,
                                         'VAL_DOUBLE': None, 'VAL_BLOB': None})
        self.assertIsNone(wert)
        self.assertEqual(typ, '(leer)')

    def test_val_int_gleich_null_wird_angezeigt(self):
        # "0" ist ein gueltiger Wert, nicht NULL.
        wert, typ = ce.wert_extrahieren({'VAL_INT': 0})
        self.assertEqual(wert, '0')
        self.assertEqual(typ, 'int')

    def test_blob_liefert_laengen_hinweis(self):
        blob = b'Signatur-Text mit etwas mehr Inhalt'
        wert, typ = ce.wert_extrahieren({'VAL_BLOB': blob})
        self.assertIn('Signatur-Text', wert)
        # Typ nennt die Byte-Laenge.
        self.assertTrue(typ.startswith('blob ('))
        self.assertIn(str(len(blob)), typ)

    def test_blob_wird_gekuerzt(self):
        blob = b'x' * 10000
        wert, typ = ce.wert_extrahieren({'VAL_BLOB': blob})
        self.assertLessEqual(len(wert or ''), 4001 + 1)  # 4000 + ellipsis
        self.assertTrue((wert or '').endswith('…'))


if __name__ == '__main__':
    unittest.main()
