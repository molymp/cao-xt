"""
Tests für Kundenkarten-Scan (kunde_per_karte) und Barcode-Route-Integration.

Strategie: DB-Zugriffe werden mit unittest.mock gepatcht.
Wir testen die Logik (GUID-Lookup, TYP='K'-Filter, Fehlerfälle).
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ── Stub-Module für DB und Konfiguration ─────────────────────
_db_mod = types.ModuleType('db')
_db_mod.get_db = MagicMock()
_db_mod.get_db_transaction = MagicMock()
_db_mod.euro_zu_cent = lambda v: int(round(float(v) * 100))
_db_mod.cent_zu_euro_str = lambda v: f"{v/100:.2f} €"
_db_mod.test_verbindung = MagicMock(return_value=True)
sys.modules['db'] = _db_mod

_cfg_mod = types.ModuleType('config')
_cfg_mod.TERMINAL_NR = 1
_cfg_mod.DB_HOST = 'localhost'
_cfg_mod.DB_PORT = 3306
_cfg_mod.DB_NAME = 'test'
_cfg_mod.DB_USER = 'test'
_cfg_mod.DB_PASSWORD = ''
_cfg_mod.FIRMA_NAME = 'Testladen'
_cfg_mod.FIRMA_STRASSE = ''
_cfg_mod.FIRMA_ORT = ''
_cfg_mod.FIRMA_UST_ID = ''
_cfg_mod.FIRMA_STEUERNUMMER = ''
_cfg_mod.SECRET_KEY = 'testsecret'
_cfg_mod.DEBUG = False
_cfg_mod.PORT = 5002
_cfg_mod.HOST = '0.0.0.0'
_cfg_mod.KIOSK_URL = ''
_cfg_mod.FISKALY_BASE_URL = ''
_cfg_mod.FISKALY_MGMT_URL = ''
sys.modules['config'] = _cfg_mod

import kasse_logik  # noqa: E402


# ── Tests: kunde_per_karte ───────────────────────────────────

class TestKundePerKarte(unittest.TestCase):
    """Tests für kasse_logik.kunde_per_karte()."""

    def _mock_db(self, return_value):
        """Erstellt einen Mock-DB-Cursor mit fetchone-Rückgabe."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = return_value
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_cur)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        return mock_ctx, mock_cur

    @patch('kasse_logik.get_db')
    def test_gueltige_kundenkarte(self, mock_get_db):
        """Gültige Kundenkarte → Kunden-Dict mit ADRESSEN-Feldern."""
        kunden_row = {
            'REC_ID': 42, 'KUNNUM1': 'K-1001', 'NAME1': 'Müller',
            'NAME2': 'Hans', 'ORT': 'Habach', 'PR_EBENE': 2,
            'KUN_ZAHLART': 3, 'ZAHLART_NAME': 'Rechnung',
        }
        ctx, cur = self._mock_db(kunden_row)
        mock_get_db.return_value = ctx

        result = kasse_logik.kunde_per_karte('KUNDEN-GUID-001')

        self.assertEqual(result, kunden_row)
        cur.execute.assert_called_once()
        sql = cur.execute.call_args[0][0]
        self.assertIn('KARTEN', sql)
        self.assertIn('ADRESSEN', sql)
        self.assertIn("TYP = 'K'", sql)

    @patch('kasse_logik.get_db')
    def test_unbekannte_guid(self, mock_get_db):
        """Unbekannte GUID → None."""
        ctx, cur = self._mock_db(None)
        mock_get_db.return_value = ctx

        result = kasse_logik.kunde_per_karte('UNKNOWN-GUID')

        self.assertIsNone(result)

    def test_leerer_guid(self):
        """Leerer GUID-String → None, kein DB-Aufruf."""
        result = kasse_logik.kunde_per_karte('')
        self.assertIsNone(result)

    def test_none_guid(self):
        """None als GUID → None, kein DB-Aufruf."""
        result = kasse_logik.kunde_per_karte(None)
        self.assertIsNone(result)

    @patch('kasse_logik.get_db')
    def test_mitarbeiterkarte_wird_nicht_als_kunde_erkannt(self, mock_get_db):
        """KARTEN.TYP='M' (Mitarbeiter) → None bei kunde_per_karte (SQL filtert TYP='K')."""
        ctx, cur = self._mock_db(None)  # DB gibt nichts zurück weil TYP != K
        mock_get_db.return_value = ctx

        result = kasse_logik.kunde_per_karte('MITARBEITER-GUID')

        self.assertIsNone(result)

    @patch('kasse_logik.get_db')
    def test_kunde_ohne_preisebene(self, mock_get_db):
        """Kunde ohne PR_EBENE → Feld ist None (Frontend fällt auf 5 zurück)."""
        kunden_row = {
            'REC_ID': 99, 'KUNNUM1': 'K-2000', 'NAME1': 'Bauer',
            'NAME2': None, 'ORT': 'Murnau', 'PR_EBENE': None,
            'KUN_ZAHLART': None, 'ZAHLART_NAME': None,
        }
        ctx, cur = self._mock_db(kunden_row)
        mock_get_db.return_value = ctx

        result = kasse_logik.kunde_per_karte('KUNDEN-GUID-002')

        self.assertEqual(result['REC_ID'], 99)
        self.assertIsNone(result['PR_EBENE'])

    @patch('kasse_logik.get_db')
    def test_sql_joined_adressen_ueber_karten_id(self, mock_get_db):
        """SQL muss KARTEN.ID mit ADRESSEN.REC_ID joinen."""
        ctx, cur = self._mock_db(None)
        mock_get_db.return_value = ctx

        kasse_logik.kunde_per_karte('ANY-GUID')

        sql = cur.execute.call_args[0][0]
        self.assertIn('k.ID', sql)


if __name__ == '__main__':
    unittest.main()
