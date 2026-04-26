"""
Tests fuer common/rfid.py – Format-Validierung + Tag-Lookup.

Die DB-Logik (run_migration / set_for_ma / get_for_ma / finde_ma_per_rfid)
testen wir mit gemockten ``common.db``-Helfern, damit der Test ohne echte
DB laeuft.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import rfid


class TestRfidFormat(unittest.TestCase):

    def test_normalisierung_uppercase_und_trim(self):
        self.assertEqual(rfid._rfid_normalisieren('  04:a2:b5:91 '),
                         '04:A2:B5:91')

    def test_gueltige_formate(self):
        for tag in ['04A2B591', '04:A2:B5:91', '04-A2-B5-91',
                    '1234', 'A' * 64]:
            self.assertTrue(rfid.is_gueltig(tag), f'sollte gueltig: {tag}')

    def test_ungueltige_formate(self):
        for tag in ['', '   ', 'ABC', 'A' * 65, 'tag mit space',
                    '04:A2:B5:91/', None]:
            self.assertFalse(rfid.is_gueltig(tag or ''),
                             f'sollte ungueltig: {tag}')


class TestRfidLookup(unittest.TestCase):
    """Pruefe ``finde_ma_per_rfid`` mit gemocktem DB-Cursor."""

    def _mit_treffer(self, treffer):
        cur = MagicMock()
        cur.fetchone.return_value = treffer
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        return ctx, cur

    def test_findet_aktiven_mitarbeiter(self):
        treffer = {'MA_ID': 5, 'LOGIN_NAME': 'mledermann',
                   'VNAME': 'Marc', 'NAME': 'Ledermann'}
        ctx, cur = self._mit_treffer(treffer)
        with patch('common.db.get_db', return_value=ctx):
            row = rfid.finde_ma_per_rfid('04:A2:B5:91')
        self.assertEqual(row, treffer)
        # Normalisierung wirkt: Pattern wurde uppercase eingesetzt.
        sql_args = cur.execute.call_args[0][1]
        self.assertEqual(sql_args, ('04:A2:B5:91',))

    def test_keine_db_anfrage_bei_ungueltigem_tag(self):
        # Tag mit Leerzeichen ist ungueltig -> kurzschluss vor DB.
        with patch('common.db.get_db') as mock_get_db:
            self.assertIsNone(rfid.finde_ma_per_rfid('not valid tag'))
            mock_get_db.assert_not_called()

    def test_leerer_tag_liefert_none(self):
        self.assertIsNone(rfid.finde_ma_per_rfid(''))
        self.assertIsNone(rfid.finde_ma_per_rfid(None))

    def test_kein_treffer_in_db(self):
        ctx, _ = self._mit_treffer(None)
        with patch('common.db.get_db', return_value=ctx):
            self.assertIsNone(rfid.finde_ma_per_rfid('04A2B591'))


class TestRfidSet(unittest.TestCase):
    """``set_for_ma``: UPSERT, Loeschen, Format-Validierung, Kollision."""

    def _tx_ctx(self, fetch_result=None):
        cur = MagicMock()
        cur.fetchone.return_value = fetch_result
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        return ctx, cur

    def test_loescht_bei_leerem_tag(self):
        ctx, cur = self._tx_ctx()
        with patch('common.db.get_db_transaction', return_value=ctx):
            rfid.set_for_ma(5, '')
        # Nur DELETE wurde abgesetzt
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn('DELETE FROM XT_MITARBEITER_RFID', sql)

    def test_wirft_bei_ungueltigem_format(self):
        with self.assertRaises(ValueError):
            rfid.set_for_ma(5, 'tag mit space')

    def test_wirft_bei_kollision_mit_anderem_ma(self):
        # fetch findet den Tag bei einem ANDEREN MA_ID
        ctx, _ = self._tx_ctx(fetch_result={'MA_ID': 99})
        with patch('common.db.get_db_transaction', return_value=ctx):
            with self.assertRaisesRegex(ValueError, 'bereits einem anderen'):
                rfid.set_for_ma(5, '04:A2:B5:91')

    def test_upsert_normalisiert_lowercase(self):
        ctx, cur = self._tx_ctx(fetch_result=None)
        with patch('common.db.get_db_transaction', return_value=ctx):
            rfid.set_for_ma(5, '04:a2:b5:91', geaendert_von_ma_id=2)
        # Letzter execute-Call ist der INSERT/UPSERT mit dem normalisierten Tag
        upsert_args = cur.execute.call_args_list[-1][0][1]
        self.assertEqual(upsert_args, (5, '04:A2:B5:91', 2))


if __name__ == '__main__':
    unittest.main()
