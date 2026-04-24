"""
Unit-Tests fuer common/terminal.py

Keine echte DB – alle DB-Zugriffe werden gemockt.
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import terminal  # noqa: E402


def _cur(fetchone=None, rowcount=1, lastrowid=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = []
    cur.rowcount = rowcount
    cur.lastrowid = lastrowid
    return cur


def _ctxmgr(cur):
    @contextmanager
    def _cm():
        yield cur
    return _cm


class TestMacAdresse(unittest.TestCase):
    def test_stabile_mac_wird_formatiert(self):
        # Bit 40 NICHT gesetzt → echte MAC
        with patch('common.terminal.uuid.getnode', return_value=0x001122334455):
            self.assertEqual(terminal.mac_adresse(), '00:11:22:33:44:55')

    def test_synthetische_mac_wird_leer(self):
        # Bit 40 gesetzt → Python hat geraten, keine echte NIC.
        # 0x010000000000 hat Bit 40 gesetzt.
        with patch('common.terminal.uuid.getnode', return_value=0x010011223344):
            self.assertEqual(terminal.mac_adresse(), '')


class TestAnlegen(unittest.TestCase):
    def test_ungueltiger_typ(self):
        with self.assertRaises(ValueError):
            terminal.anlegen('Kasse 1', 'UNBEKANNT')

    def test_leere_bezeichnung(self):
        with self.assertRaises(ValueError):
            terminal.anlegen('   ', 'KASSE')

    def test_insert_und_lastrowid(self):
        cur = _cur(lastrowid=77)
        with patch.object(terminal, 'get_db_transaction', _ctxmgr(cur)):
            self.assertEqual(
                terminal.anlegen('Kasse 1', 'KASSE',
                                 hostname_='pos-01',
                                 mac='AA:BB:CC:DD:EE:FF'),
                77)
        # Geprueft: INSERT-Parameter
        args = cur.execute.call_args.args
        self.assertIn('INSERT INTO TERMINAL', args[0])
        self.assertEqual(args[1],
                         ('Kasse 1', 'KASSE', 'pos-01', 'AA:BB:CC:DD:EE:FF'))


class TestAktualisieren(unittest.TestCase):
    def test_ignoriert_unbekannte_felder(self):
        cur = _cur()
        with patch.object(terminal, 'get_db_transaction', _ctxmgr(cur)):
            terminal.aktualisieren(5, foo='x', bar=42)
        cur.execute.assert_not_called()

    def test_setzt_erlaubte_felder(self):
        cur = _cur()
        with patch.object(terminal, 'get_db_transaction', _ctxmgr(cur)):
            terminal.aktualisieren(5, bezeichnung='Neu', aktiv=0)
        args = cur.execute.call_args.args
        self.assertIn('UPDATE TERMINAL SET', args[0])
        # Erlaubte Felder (Reihenfolge laut dict-Iteration)
        self.assertEqual(args[1][-1], 5)  # letzte Param = WHERE-Wert


class TestSetzeLetztenKontakt(unittest.TestCase):
    def test_ohne_ip(self):
        cur = _cur()
        with patch.object(terminal, 'get_db_transaction', _ctxmgr(cur)):
            terminal.setze_letzten_kontakt(3)
        args = cur.execute.call_args.args
        self.assertIn('LETZTER_KONTAKT = NOW()', args[0])
        self.assertEqual(args[1], (3,))

    def test_mit_ip(self):
        cur = _cur()
        with patch.object(terminal, 'get_db_transaction', _ctxmgr(cur)):
            terminal.setze_letzten_kontakt(3, ip='192.168.1.7')
        args = cur.execute.call_args.args
        self.assertEqual(args[1], ('192.168.1.7', 3))


class TestErkenne(unittest.TestCase):
    def test_ungueltiger_typ(self):
        with self.assertRaises(ValueError):
            terminal.erkenne('UNBEKANNT')

    def test_match_per_mac(self):
        row_mac = {'TERMINAL_ID': 1, 'BEZEICHNUNG': 'Kasse 1',
                   'TYP': 'KASSE', 'HOSTNAME': 'pos-01',
                   'MAC_ADRESSE': 'AA:BB:CC:DD:EE:FF', 'IP_LETZTE': None,
                   'AKTIV': 1, 'LETZTER_KONTAKT': None}
        cur = _cur(fetchone=row_mac)
        with patch.object(terminal, 'get_db', _ctxmgr(cur)):
            got = terminal.erkenne('KASSE', host='pos-01',
                                   mac='AA:BB:CC:DD:EE:FF')
        self.assertEqual(got, row_mac)
        # MAC wird zuerst versucht → 1 Query
        self.assertEqual(cur.execute.call_count, 1)

    def test_fallback_auf_hostname(self):
        # 1. Query (MAC): None, 2. Query (HOSTNAME): Row
        row_host = {'TERMINAL_ID': 2, 'BEZEICHNUNG': 'Kasse 2',
                    'TYP': 'KASSE', 'HOSTNAME': 'pos-02',
                    'MAC_ADRESSE': None, 'IP_LETZTE': None,
                    'AKTIV': 1, 'LETZTER_KONTAKT': None}
        cur = MagicMock()
        cur.fetchone.side_effect = [None, row_host]
        with patch.object(terminal, 'get_db', _ctxmgr(cur)):
            got = terminal.erkenne('KASSE', host='pos-02', mac='X')
        self.assertEqual(got, row_host)
        self.assertEqual(cur.execute.call_count, 2)

    def test_kein_match(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [None, None]
        with patch.object(terminal, 'get_db', _ctxmgr(cur)):
            got = terminal.erkenne('KIOSK', host='h', mac='m')
        self.assertIsNone(got)

    def test_leere_mac_ueberspringt_mac_query(self):
        row = {'TERMINAL_ID': 3, 'BEZEICHNUNG': 'Kiosk 1', 'TYP': 'KIOSK',
               'HOSTNAME': 'kiosk-1', 'MAC_ADRESSE': None, 'IP_LETZTE': None,
               'AKTIV': 1, 'LETZTER_KONTAKT': None}
        cur = _cur(fetchone=row)
        with patch.object(terminal, 'get_db', _ctxmgr(cur)):
            got = terminal.erkenne('KIOSK', host='kiosk-1', mac='')
        self.assertEqual(got, row)
        # Nur der Hostname-Query lief
        self.assertEqual(cur.execute.call_count, 1)


class TestAlle(unittest.TestCase):
    def test_filter_nach_typ(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        with patch.object(terminal, 'get_db', _ctxmgr(cur)):
            terminal.alle(typ='KASSE')
        args = cur.execute.call_args.args
        self.assertIn('WHERE TYP = %s', args[0])
        self.assertEqual(args[1], ('KASSE',))

    def test_nur_aktiv(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        with patch.object(terminal, 'get_db', _ctxmgr(cur)):
            terminal.alle(nur_aktiv=True)
        args = cur.execute.call_args.args
        self.assertIn('AKTIV = 1', args[0])


if __name__ == '__main__':
    unittest.main()
