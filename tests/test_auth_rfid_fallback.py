"""
Test: ``common.auth.mitarbeiter_login_karte`` faellt nach KARTEN-Lookup
auf XT_MITARBEITER_RFID zurueck. So koennen Mitarbeiter sowohl mit ihrer
klassischen Mitarbeiterkarte als auch mit ihrem Alarm-RFID-Tag in alle
Apps einloggen oder am Stempelterminal einchecken.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import auth


def _db_ctx(treffer):
    cur = MagicMock()
    cur.fetchone.return_value = treffer
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    return ctx


class TestRfidFallback(unittest.TestCase):

    def test_klassische_mitarbeiterkarte_hat_vorrang(self):
        karten_treffer = {'MA_ID': 5, 'LOGIN_NAME': 'mledermann',
                          'VNAME': 'Marc', 'NAME': 'Ledermann'}
        with patch('common.db.get_db',
                   return_value=_db_ctx(karten_treffer)) as mock_db, \
             patch('common.rfid.finde_ma_per_rfid') as mock_rfid:
            row = auth.mitarbeiter_login_karte('SOME-GUID')
        self.assertEqual(row, karten_treffer)
        mock_db.assert_called_once()        # Nur KARTEN abgefragt
        mock_rfid.assert_not_called()       # RFID-Fallback NICHT genutzt

    def test_rfid_fallback_wenn_keine_karte(self):
        rfid_treffer = {'MA_ID': 7, 'LOGIN_NAME': 'jdoe',
                        'VNAME': 'Jane', 'NAME': 'Doe'}
        with patch('common.db.get_db', return_value=_db_ctx(None)), \
             patch('common.rfid.finde_ma_per_rfid',
                   return_value=rfid_treffer) as mock_rfid:
            row = auth.mitarbeiter_login_karte('04:A2:B5:91')
        self.assertEqual(row, rfid_treffer)
        mock_rfid.assert_called_once_with('04:A2:B5:91')

    def test_keine_karte_kein_rfid_liefert_none(self):
        with patch('common.db.get_db', return_value=_db_ctx(None)), \
             patch('common.rfid.finde_ma_per_rfid', return_value=None):
            self.assertIsNone(auth.mitarbeiter_login_karte('UNBEKANNT'))

    def test_leere_eingabe_liefert_none_ohne_db(self):
        with patch('common.db.get_db') as mock_db, \
             patch('common.rfid.finde_ma_per_rfid') as mock_rfid:
            self.assertIsNone(auth.mitarbeiter_login_karte(''))
            self.assertIsNone(auth.mitarbeiter_login_karte(None))
            mock_db.assert_not_called()
            mock_rfid.assert_not_called()


if __name__ == '__main__':
    unittest.main()
