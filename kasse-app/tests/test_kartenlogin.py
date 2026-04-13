"""
Tests für Kartenlogin (common.auth.mitarbeiter_login_karte).

Strategie: DB-Zugriffe werden mit unittest.mock gepatcht.
Wir testen die Logik (GUID-Lookup, TYP-Filter, ADR_ID-JOIN, Fehlerfälle).
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# common-Verzeichnis zum Python-Pfad hinzufügen
_repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_repo_root))

# ── Stub-Modul für common.db ─────────────────────────────────
_common_db_mod = types.ModuleType('common.db')
_common_db_mod.get_db = MagicMock()
sys.modules['common.db'] = _common_db_mod

# common als Package registrieren
_common_pkg = types.ModuleType('common')
_common_pkg.__path__ = [str(_repo_root / 'common')]
sys.modules['common'] = _common_pkg

# Flask-Session-Mock (common.auth importiert flask.session)
import flask  # noqa: E402
_test_app = flask.Flask(__name__)
_test_app.config['SECRET_KEY'] = 'testsecret'

from common.auth import mitarbeiter_login_karte  # noqa: E402


class TestMitarbeiterLoginKarte(unittest.TestCase):
    """Tests für common.auth.mitarbeiter_login_karte()."""

    def _mock_db(self, return_value):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = return_value
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_cur)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        return mock_ctx, mock_cur

    @patch('common.db.get_db')
    def test_gueltige_mitarbeiterkarte(self, mock_get_db):
        """Gültige Mitarbeiterkarte → Mitarbeiter-Dict zurück."""
        ma_row = {'MA_ID': 5, 'LOGIN_NAME': 'maria', 'VNAME': 'Maria', 'NAME': 'Huber'}
        ctx, cur = self._mock_db(ma_row)
        mock_get_db.return_value = ctx

        with _test_app.app_context():
            result = mitarbeiter_login_karte('MKCADD6B63')

        self.assertEqual(result, ma_row)
        cur.execute.assert_called_once()
        sql = cur.execute.call_args[0][0]
        self.assertIn('KARTEN', sql)
        self.assertIn('MITARBEITER', sql)
        self.assertIn("TYP = 'M'", sql)
        self.assertIn('ADR_ID', sql)

    @patch('common.db.get_db')
    def test_unbekannte_guid(self, mock_get_db):
        """Unbekannte GUID → None."""
        ctx, cur = self._mock_db(None)
        mock_get_db.return_value = ctx

        with _test_app.app_context():
            result = mitarbeiter_login_karte('UNKNOWN-GUID')

        self.assertIsNone(result)

    def test_leerer_guid(self):
        """Leerer GUID-String → None, kein DB-Aufruf."""
        result = mitarbeiter_login_karte('')
        self.assertIsNone(result)

    def test_none_guid(self):
        """None als GUID → None, kein DB-Aufruf."""
        result = mitarbeiter_login_karte(None)
        self.assertIsNone(result)

    @patch('common.db.get_db')
    def test_kundenkarte_wird_abgelehnt(self, mock_get_db):
        """KARTEN.TYP != 'M' → None (SQL filtert über WHERE TYP='M')."""
        ctx, cur = self._mock_db(None)
        mock_get_db.return_value = ctx

        with _test_app.app_context():
            result = mitarbeiter_login_karte('KUNDEN-GUID')

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
