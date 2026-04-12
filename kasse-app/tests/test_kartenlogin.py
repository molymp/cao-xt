"""
Tests für Kartenlogin (mitarbeiter_login_karte) und /login/karte Route.

Strategie: DB-Zugriffe werden mit unittest.mock gepatcht.
Wir testen die Logik (GUID-Lookup, TYP-Filter, Fehlerfälle).
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


# ── Tests: mitarbeiter_login_karte ───────────────────────────

class TestMitarbeiterLoginKarte(unittest.TestCase):
    """Tests für kasse_logik.mitarbeiter_login_karte()."""

    def _mock_db(self, return_value):
        """Erstellt einen Mock-DB-Cursor mit fetchone-Rückgabe."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = return_value
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_cur)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        return mock_ctx, mock_cur

    @patch('kasse_logik.get_db')
    def test_gueltige_mitarbeiterkarte(self, mock_get_db):
        """Gültige Mitarbeiterkarte → Mitarbeiter-Dict zurück."""
        ma_row = {'MA_ID': 5, 'LOGIN_NAME': 'maria', 'VNAME': 'Maria', 'NAME': 'Huber'}
        ctx, cur = self._mock_db(ma_row)
        mock_get_db.return_value = ctx

        result = kasse_logik.mitarbeiter_login_karte('ABC-123-GUID')

        self.assertEqual(result, ma_row)
        cur.execute.assert_called_once()
        sql = cur.execute.call_args[0][0]
        self.assertIn('KARTEN', sql)
        self.assertIn('MITARBEITER', sql)
        self.assertIn("TYP = 'M'", sql)

    @patch('kasse_logik.get_db')
    def test_unbekannte_guid(self, mock_get_db):
        """Unbekannte GUID → None."""
        ctx, cur = self._mock_db(None)
        mock_get_db.return_value = ctx

        result = kasse_logik.mitarbeiter_login_karte('UNKNOWN-GUID')

        self.assertIsNone(result)

    def test_leerer_guid(self):
        """Leerer GUID-String → None, kein DB-Aufruf."""
        result = kasse_logik.mitarbeiter_login_karte('')
        self.assertIsNone(result)

    def test_none_guid(self):
        """None als GUID → None, kein DB-Aufruf."""
        result = kasse_logik.mitarbeiter_login_karte(None)
        self.assertIsNone(result)

    @patch('kasse_logik.get_db')
    def test_kundenkarte_wird_abgelehnt(self, mock_get_db):
        """KARTEN.TYP != 'M' → None (SQL filtert über WHERE TYP='M')."""
        ctx, cur = self._mock_db(None)  # DB gibt nichts zurück weil TYP != M
        mock_get_db.return_value = ctx

        result = kasse_logik.mitarbeiter_login_karte('KUNDEN-GUID')

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
