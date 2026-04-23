"""
Unit-Tests fuer admin-app/app/cao_rechte.py – reine Logik ohne DB.

Deckt ab:
- kategorie_fuer: Ableitung des Kategorie-Labels aus MODUL_ID.
- bit_labels: universelle Bit-0-Bedeutung + modul-spezifische Extras.
- rechte_zu_bits: Zerlegung der Bitmaske, inkl. unbekannter Bits.

Die DB-Funktionen (gruppen_laden, modul_baum, ...) werden in
Integrationstests gegen eine Test-DB abgedeckt – hier bleibt alles
offline. Wir stubben ``db.get_db`` daher mit einem No-op.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_CAO_RECHTE_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'cao_rechte.py')

# admin-app/app hat einen Bindestrich – kein regulaerer Paketimport moeglich.
# Wir stubben das erwartete ``db``-Modul und laden cao_rechte.py direkt via
# importlib (dasselbe Muster wird auch von admin-app/app/app.py genutzt,
# weil dort ``from db import get_db`` ohne Paketpfad laeuft).
_fake_db = types.ModuleType('db')
_fake_db.get_db = lambda: None  # noqa: E731
sys.modules['db'] = _fake_db

_spec = importlib.util.spec_from_file_location('cao_rechte_test_modul',
                                               _CAO_RECHTE_PATH)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


class TestKategorieFuer(unittest.TestCase):
    def test_stammdaten_1010(self):
        self.assertEqual(cr.kategorie_fuer(1010), (1000, 'Stammdaten'))

    def test_kasse_10010(self):
        self.assertEqual(cr.kategorie_fuer(10010), (10000, 'Kasse'))

    def test_kasse_grenzfall_10999(self):
        # 10999 faellt in 10000er-Bucket.
        self.assertEqual(cr.kategorie_fuer(10999), (10000, 'Kasse'))

    def test_unbekannter_bereich(self):
        # 15000 ist keine definierte Kategorie.
        kid, name = cr.kategorie_fuer(15000)
        self.assertEqual(kid, 0)
        self.assertEqual(name, 'Sonstige')


class TestBitLabels(unittest.TestCase):
    def test_bit0_universell(self):
        # Beliebiges Modul hat mindestens Bit 0 = "Modul aufrufen".
        labels = cr.bit_labels(1010)
        self.assertEqual(labels[0], 'Modul aufrufen')

    def test_kasse_main_spezial(self):
        # MODUL 10010 hat verifizierte Extra-Bits.
        labels = cr.bit_labels(10010)
        self.assertEqual(labels[0],  'Modul aufrufen')
        self.assertEqual(labels[12], 'Vorgang abschließen')
        self.assertEqual(labels[13], 'Drucken')
        self.assertEqual(labels[14], 'Formulare bearbeiten')


class TestRechteZuBits(unittest.TestCase):
    def test_leere_rechte(self):
        # RECHTE=0 → Bit 0 ungesetzt, keine Unbekannten.
        bits = cr.rechte_zu_bits(0, 1010)
        self.assertEqual(len(bits), 1)
        self.assertEqual(bits[0]['bit'], 0)
        self.assertFalse(bits[0]['gesetzt'])
        self.assertEqual(bits[0]['label'], 'Modul aufrufen')

    def test_nur_bit0(self):
        bits = cr.rechte_zu_bits(1, 1010)
        self.assertTrue(bits[0]['gesetzt'])
        self.assertEqual(bits[0]['label'], 'Modul aufrufen')

    def test_kasse_mitarbeiter_bitmaske(self):
        # Screenshot-verifiziert: GRP=6 Kasse Main RECHTE=12289
        # → Bits 0, 12, 13 aktiv; Bit 14 aus.
        bits = cr.rechte_zu_bits(12289, 10010)
        label_zu_status = {b['label']: b['gesetzt'] for b in bits
                           if b['label'] is not None}
        self.assertTrue(label_zu_status['Modul aufrufen'])
        self.assertTrue(label_zu_status['Vorgang abschließen'])
        self.assertTrue(label_zu_status['Drucken'])
        self.assertFalse(label_zu_status['Formulare bearbeiten'])

    def test_unbekannte_gesetzte_bits_werden_angehangen(self):
        # Modul ohne Spezial-Labels, RECHTE mit Bit 5 gesetzt.
        # → Erwartung: Bit 0 mit Label, dann Bit 5 mit label=None.
        bits = cr.rechte_zu_bits(0b100001, 1010)
        bit_nrs = [b['bit'] for b in bits]
        self.assertIn(0, bit_nrs)
        self.assertIn(5, bit_nrs)
        unbekannt = [b for b in bits if b['label'] is None]
        self.assertEqual(len(unbekannt), 1)
        self.assertTrue(unbekannt[0]['gesetzt'])
        self.assertEqual(unbekannt[0]['bit'], 5)


if __name__ == '__main__':
    unittest.main()
