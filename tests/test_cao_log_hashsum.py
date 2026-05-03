"""
Unit-Tests fuer common/cao_log_hashsum.py.

Patcht ``common.konfig.get`` per monkey-patch in der Setup-Phase
(robust gegen Test-Reihenfolge, kein sys.modules-Reload noetig).
Decken ab:

- Format des Outputs (Base64, 48 chars, XT-Magic-Prefix)
- Determinismus: gleiche Eingabe -> gleicher Output
- Salz-Sensitivitaet: anderer Salt -> anderer Hash
- Kette: previous_hashsum aendert das Ergebnis
- ``is_xt_hashsum`` / ``verify`` Roundtrip
- Fehlerfaelle: leerer Tabellenname, leerer hashstring, fehlender Salt
"""
import base64
import os
import sys
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _REPO_ROOT)

# Konfig-Modul existiert in echt; wir importieren und patchen seine
# get-Funktion punktuell. cao_hashsum / cao_log_hashsum holen sich den
# Salt aus konfig.get() — dieser eine Patch reicht aus, kein Reload
# der Module noetig.
from common import konfig as _konfig          # noqa: E402
from common import cao_log_hashsum            # noqa: E402
from common.cao_hashsum import SaltFehlt      # noqa: E402


class CaoLogHashsumTests(unittest.TestCase):

    def setUp(self):
        # Pro-Test eigene Salts; jede Modifikation ist auf den
        # aktuellen Test beschraenkt.
        self.salts = {
            'cao.hash_salt.artikel_log':       'salt-artikel-test',
            'cao.hash_salt.nummern_log':       'salt-nummern-test',
            'cao.hash_salt.warengruppen_log':  'salt-wg-test',
        }
        # Original-get speichern, dann monkey-patchen.
        self._orig_get = _konfig.get
        _konfig.get = (
            lambda key, default=None: self.salts.get(key, default)
        )

    def tearDown(self):
        # Konfig-Modul auf Original zuruecksetzen — keine Spuren in
        # spaeteren Test-Modulen.
        _konfig.get = self._orig_get

    # ── Format ─────────────────────────────────────────────────

    def test_output_ist_base64_text_48_zeichen(self):
        h = cao_log_hashsum.compute(
            table_name='ARTIKEL_LOG',
            hashstring="V1|123|007409|2.59",
        )
        self.assertIsInstance(h, bytes)
        self.assertEqual(len(h), 48)
        # Sauberer Base64 - decodierbar, ergibt 36 Bytes
        raw = base64.b64decode(h)
        self.assertEqual(len(raw), 36)

    def test_xt_magic_prefix(self):
        """Erste 4 Bytes sind 'XTL' + Versions-Byte 0x01."""
        h = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|test")
        raw = base64.b64decode(h)
        self.assertEqual(raw[:4], b'XTL\x01')

    def test_base64_anfang_ist_WFRMA(self):
        """Damit jeder XT-HASHSUM auf den ersten Blick erkennbar ist."""
        h = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|test")
        self.assertTrue(h.startswith(b'WFRMA'))

    # ── Determinismus + Salt ───────────────────────────────────

    def test_determinismus_gleiche_eingabe_gleicher_hash(self):
        h1 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123")
        h2 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123")
        self.assertEqual(h1, h2)

    def test_unterschiedlicher_hashstring_unterschiedlicher_hash(self):
        h1 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123")
        h2 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|124")
        self.assertNotEqual(h1, h2)

    def test_unterschiedliche_tabelle_unterschiedlicher_hash(self):
        # Gleicher hashstring, anderer Salt-Schluessel -> anderes
        # Ergebnis. Das verhindert Hash-Replay zwischen Tabellen.
        h1 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|test")
        h2 = cao_log_hashsum.compute('NUMMERN_LOG', "V1|test")
        self.assertNotEqual(h1, h2)

    def test_aenderung_am_salt_aendert_den_hash(self):
        h1 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|test")
        # Salt aendern - patched konfig.get sieht das sofort
        self.salts['cao.hash_salt.artikel_log'] = 'anderer-salt'
        h2 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|test")
        self.assertNotEqual(h1, h2)

    # ── Chain ──────────────────────────────────────────────────

    def test_previous_hashsum_aendert_ergebnis(self):
        h_first = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123")
        h_chain = cao_log_hashsum.compute(
            'ARTIKEL_LOG', "V1|124", previous_hashsum=h_first)
        h_no_chain = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|124")
        self.assertNotEqual(h_chain, h_no_chain)

    def test_chain_separator_ist_at2at(self):
        """Der Plaintext fuer Chain-Eintraege ist
        ``hashstring + '|@#2@|' + prev_hashsum`` – das stellen wir
        durch direkten Vergleich mit erwartetem HMAC sicher.
        """
        import hmac
        from hashlib import sha256
        salt = 'salt-artikel-test'
        prev = b'WFRMAprevprev_dummy_value_for_chain'
        plain = 'V1|123|@#2@|' + prev.decode('ascii')
        erwartet_hmac = hmac.new(
            salt.encode('utf-8'),
            plain.encode('utf-8'),
            sha256,
        ).digest()
        erwartet = base64.b64encode(b'XTL\x01' + erwartet_hmac)

        ist = cao_log_hashsum.compute(
            'ARTIKEL_LOG', "V1|123", previous_hashsum=prev)
        self.assertEqual(ist, erwartet)

    def test_previous_als_bytes_und_str_sind_gleichwertig(self):
        prev_bytes = b'WFRMAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx==='
        prev_str   = prev_bytes.decode('ascii')
        h_b = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123",
                                      previous_hashsum=prev_bytes)
        h_s = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123",
                                      previous_hashsum=prev_str)
        self.assertEqual(h_b, h_s)

    # ── is_xt_hashsum + verify ─────────────────────────────────

    def test_is_xt_hashsum_eigener_eintrag_true(self):
        h = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|test")
        self.assertTrue(cao_log_hashsum.is_xt_hashsum(h))

    def test_is_xt_hashsum_cao_eintrag_false(self):
        # Echter CAO-Eintrag aus DB-Empirie (NUMMERN_LOG)
        cao_eintrag = (b'8p4KQsGQmRVlxmbtJTsTw7+qRGhl6v5GN3TkPI4CBlojdQDx'
                       b'qUt6Akem6c1/CS87/JkyFYvCjfi8kEFjutNKqF8JkPtkhVev')
        self.assertFalse(cao_log_hashsum.is_xt_hashsum(cao_eintrag))

    def test_is_xt_hashsum_leer_false(self):
        self.assertFalse(cao_log_hashsum.is_xt_hashsum(b''))
        self.assertFalse(cao_log_hashsum.is_xt_hashsum(None))

    def test_verify_roundtrip_match(self):
        h = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123|007409|2.59")
        self.assertTrue(cao_log_hashsum.verify(
            'ARTIKEL_LOG', "V1|123|007409|2.59", h))

    def test_verify_roundtrip_mismatch_anderer_hashstring(self):
        h = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123|007409|2.59")
        self.assertFalse(cao_log_hashsum.verify(
            'ARTIKEL_LOG', "V1|999|007409|2.59", h))

    def test_verify_roundtrip_mismatch_falscher_salt(self):
        h = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|123")
        # Salt aendern und nochmal verify -> mismatch
        self.salts['cao.hash_salt.artikel_log'] = 'anderer-salt'
        self.assertFalse(cao_log_hashsum.verify(
            'ARTIKEL_LOG', "V1|123", h))

    def test_verify_mit_chain(self):
        # Erster Eintrag
        h1 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|001")
        # Zweiter Eintrag mit Chain
        h2 = cao_log_hashsum.compute('ARTIKEL_LOG', "V1|002",
                                      previous_hashsum=h1)
        # Verify beide
        self.assertTrue(cao_log_hashsum.verify(
            'ARTIKEL_LOG', "V1|001", h1))
        self.assertTrue(cao_log_hashsum.verify(
            'ARTIKEL_LOG', "V1|002", h2, previous_hashsum=h1))
        # Mismatch wenn falsche prev-Kette
        self.assertFalse(cao_log_hashsum.verify(
            'ARTIKEL_LOG', "V1|002", h2, previous_hashsum=None))

    # ── Fehlerfaelle ───────────────────────────────────────────

    def test_leerer_table_name_wirft_value_error(self):
        with self.assertRaises(ValueError):
            cao_log_hashsum.compute('', "V1|test")

    def test_leerer_hashstring_wirft_value_error(self):
        with self.assertRaises(ValueError):
            cao_log_hashsum.compute('ARTIKEL_LOG', '')
        with self.assertRaises(ValueError):
            cao_log_hashsum.compute('ARTIKEL_LOG', None)

    def test_unbekannte_tabelle_wirft_salt_fehlt(self):
        with self.assertRaises(SaltFehlt):
            cao_log_hashsum.compute('IRGENDEINE_TABELLE_LOG', "V1|test")


if __name__ == '__main__':
    unittest.main()
