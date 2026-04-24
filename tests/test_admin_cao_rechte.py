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
        labels = cr.bit_labels(9999)          # unbekanntes Modul
        self.assertEqual(labels[0], 'Modul aufrufen')

    def test_kasse_main_spezial(self):
        # MODUL 10010 hat verifizierte Extra-Bits.
        labels = cr.bit_labels(10010)
        self.assertEqual(labels[0],  'Modul aufrufen')
        self.assertEqual(labels[12], 'Vorgang abschließen')
        self.assertEqual(labels[13], 'Drucken')
        self.assertEqual(labels[14], 'Formulare bearbeiten')

    def test_adressen_hat_crud_und_drucken(self):
        # MODUL 1010 Adressen: aus cao_admin.exe Default-Maske 27663
        # → Bits {0,1,2,3,10,11,13,14}. Labels aus Array-Standard.
        labels = cr.bit_labels(1010)
        self.assertEqual(labels[1], 'Datensatz ändern')
        self.assertEqual(labels[2], 'Datensatz neu')
        self.assertEqual(labels[3], 'Datensatz löschen bzw. Storno')
        self.assertEqual(labels[10], 'Import')
        self.assertEqual(labels[11], 'Export')
        self.assertEqual(labels[13], 'Drucken')
        self.assertEqual(labels[14], 'Formulare bearbeiten')

    def test_artikel_lieferantenpreise_ist_pur_crud(self):
        # SUBMODUL 1020/4 Lieferantenpreise: Default-Maske 15 = CRUD only.
        labels = cr.bit_labels(1020, 4)
        self.assertEqual(set(labels.keys()), {0, 1, 2, 3})
        self.assertNotIn(13, labels)
        self.assertNotIn(14, labels)


class TestRechteZuBits(unittest.TestCase):
    def test_leere_rechte_unbekanntes_modul(self):
        # Unbekanntes Modul, RECHTE=0 → nur Bit 0 (universell), ungesetzt.
        bits = cr.rechte_zu_bits(0, 9999)
        self.assertEqual(len(bits), 1)
        self.assertEqual(bits[0]['bit'], 0)
        self.assertFalse(bits[0]['gesetzt'])
        self.assertEqual(bits[0]['label'], 'Modul aufrufen')

    def test_leere_rechte_bekanntes_modul_zeigt_alle_labels(self):
        # MODUL 1010 (Adressen) — Default-Maske aus cao_admin.exe 27663
        # → Bits {0,1,2,3,10,11,13,14}. RECHTE=0 → alle acht ungesetzt.
        bits = cr.rechte_zu_bits(0, 1010)
        self.assertEqual({b['bit'] for b in bits}, {0, 1, 2, 3, 10, 11, 13, 14})
        self.assertTrue(all(not b['gesetzt'] for b in bits))
        self.assertTrue(all(b['label'] is not None for b in bits))

    def test_nur_bit0(self):
        bits = cr.rechte_zu_bits(1, 9999)
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

    def test_adressen_bitmaske_aus_screenshot(self):
        # GRP=7 Ladenleitung Adressen RECHTE=8207
        # → bits {0,1,2,3,13} aktiv; 10/11/14 aus.
        bits = cr.rechte_zu_bits(8207, 1010)
        status = {b['label']: b['gesetzt'] for b in bits
                  if b['label'] is not None}
        self.assertTrue(status['Modul aufrufen'])
        self.assertTrue(status['Datensatz ändern'])
        self.assertTrue(status['Datensatz neu'])
        self.assertTrue(status['Datensatz löschen bzw. Storno'])
        self.assertTrue(status['Drucken'])
        self.assertFalse(status['Import'])
        self.assertFalse(status['Export'])
        self.assertFalse(status['Formulare bearbeiten'])

    def test_artikel_bitmaske_mit_ek_preise(self):
        # GRP=7 Ladenleitung Artikel RECHTE=25359
        # → bits {0,1,2,3,8,9,13,14} — alles an.
        bits = cr.rechte_zu_bits(25359, 1020)
        status = {b['label']: b['gesetzt'] for b in bits
                  if b['label'] is not None}
        self.assertTrue(status['EK-Preise anzeigen'])
        self.assertTrue(status['EK-Preise ändern'])
        self.assertTrue(status['Formulare bearbeiten'])

    def test_unbekannte_gesetzte_bits_werden_angehangen(self):
        # Unbekanntes Modul, RECHTE mit Bit 5 gesetzt.
        # → Erwartung: Bit 0 mit Label, dann Bit 5 mit label=None.
        bits = cr.rechte_zu_bits(0b100001, 9999)
        bit_nrs = [b['bit'] for b in bits]
        self.assertIn(0, bit_nrs)
        self.assertIn(5, bit_nrs)
        unbekannt = [b for b in bits if b['label'] is None]
        self.assertEqual(len(unbekannt), 1)
        self.assertTrue(unbekannt[0]['gesetzt'])
        self.assertEqual(unbekannt[0]['bit'], 5)


if __name__ == '__main__':
    unittest.main()
