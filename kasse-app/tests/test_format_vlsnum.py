"""
Tests für _format_vlsnum() in kasse_logik.

Die Funktion muss ein reines Zahlenformat (keine "LS"-Präfix) als Fallback
erzeugen, damit das CAO VRENUM-Feld (VARCHAR ≤ 7) nicht überläuft.
"""
import sys
import types
import unittest

# ── Stub-Module für DB und Konfiguration ─────────────────────
_db_mod = types.ModuleType('db')
_db_mod.get_db = lambda: None
_db_mod.get_db_transaction = lambda: None
_db_mod.euro_zu_cent = lambda v: int(round(float(v) * 100))
_db_mod.cent_zu_euro_str = lambda v: f"{v/100:.2f} €"
sys.modules.setdefault('db', _db_mod)

_cfg_mod = types.ModuleType('config')
_cfg_mod.TERMINAL_NR = 1
_cfg_mod.DB_HOST = 'localhost'
_cfg_mod.DB_PORT = 3306
_cfg_mod.DB_NAME = 'test'
_cfg_mod.DB_USER = 'test'
_cfg_mod.DB_PASSWORD = 'test'
sys.modules.setdefault('config', _cfg_mod)

from kasse_logik import _format_vlsnum  # noqa: E402


class TestFormatVlsnum(unittest.TestCase):
    """_format_vlsnum: korrektes VLSNUM-Format für alle Eingaben."""

    # ── Fallback (leeres Pattern) ────────────────────────────────
    def test_leeres_pattern_erzeugt_reines_zahlenformat(self):
        """Kein Pattern → 6-stellige Zahl, kein LS-Präfix."""
        self.assertEqual(_format_vlsnum('', 1), '000001')

    def test_none_pattern_erzeugt_reines_zahlenformat(self):
        self.assertEqual(_format_vlsnum(None, 1), '000001')

    def test_fallback_laenge_6_stellen(self):
        self.assertEqual(len(_format_vlsnum('', 1)), 6)

    def test_fallback_kein_ls_praefix(self):
        ergebnis = _format_vlsnum('', 42)
        self.assertFalse(ergebnis.startswith('LS'),
                         f"Fallback enthält unerwartetes LS-Präfix: {ergebnis!r}")

    def test_fallback_grosse_nummer(self):
        self.assertEqual(_format_vlsnum('', 123456), '123456')

    # ── Pattern mit quoted Präfix und Nullen ───────────────────
    def test_cao_pattern_ohne_praefix(self):
        """'000000' → reine 6-stellige Zahl."""
        self.assertEqual(_format_vlsnum('000000', 18165), '018165')

    def test_cao_pattern_mit_praefix(self):
        """'"EDI-"000000' → 'EDI-018165'."""
        self.assertEqual(_format_vlsnum('"EDI-"000000', 18165), 'EDI-018165')

    def test_cao_pattern_mit_praefix_fuehrende_nullen(self):
        self.assertEqual(_format_vlsnum('"LS"000000', 1), 'LS000001')

    def test_cao_pattern_8_stellen(self):
        self.assertEqual(_format_vlsnum('00000000', 1), '00000001')

    # ── Pattern ohne Nullen (Sonderfall) ───────────────────────
    def test_pattern_praefix_ohne_nullen_kein_ls_fallback(self):
        """Präfix vorhanden, aber keine Nullen → Präfix + 6-stellige Zahl, kein LS."""
        ergebnis = _format_vlsnum('"RG"', 5)
        self.assertFalse(ergebnis.startswith('LS'),
                         f"Unerwartetes LS-Präfix: {ergebnis!r}")

    def test_pattern_ohne_praefix_ohne_nullen_kein_ls_fallback(self):
        """Weder Präfix noch Nullen → reine 6-stellige Zahl."""
        ergebnis = _format_vlsnum('XYZ', 5)
        self.assertFalse(ergebnis.startswith('LS'),
                         f"Unerwartetes LS-Präfix: {ergebnis!r}")


if __name__ == '__main__':
    unittest.main()
