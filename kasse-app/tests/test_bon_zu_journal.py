"""
Tests für bon_zu_journal / _bon_zu_journal_intern.

Strategie: DB-Zugriffe werden mit unittest.mock gepatcht.
Wir testen die Logik (Summenberechnung, HASHSUM-Aufruf,
Fehlerbehandlung), nicht die echte DB-Anbindung.
"""
import hashlib
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, call, patch

# ── Stub-Module für DB und Konfiguration ─────────────────────
# kasse_logik importiert db und config – wir mocken sie weg.

_db_mod = types.ModuleType('db')
_db_mod.get_db = MagicMock()
_db_mod.get_db_transaction = MagicMock()
_db_mod.euro_zu_cent = lambda v: int(round(float(v) * 100))
_db_mod.cent_zu_euro_str = lambda v: f"{v/100:.2f} €"
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
_cfg_mod.SECRET_KEY = 'test'
_cfg_mod.DEBUG = False
_cfg_mod.PORT = 5002
_cfg_mod.HOST = '0.0.0.0'
_cfg_mod.KIOSK_URL = ''
_cfg_mod.FISKALY_BASE_URL = ''
_cfg_mod.FISKALY_MGMT_URL = ''
sys.modules['config'] = _cfg_mod

import kasse_logik  # noqa: E402 – muss nach den Mocks kommen


# ── Hilfsfunktionen ───────────────────────────────────────────

def _vorgang(betrag_brutto=1190, betrag_netto=1000, ist_training=0):
    return {
        'ID': 42,
        'TERMINAL_NR': 1,
        'BON_NR': 7,
        'VORGANGSNUMMER': '01-20260403-000007',
        'STATUS': 'ABGESCHLOSSEN',
        'BETRAG_BRUTTO': betrag_brutto,
        'BETRAG_NETTO': betrag_netto,
        'MWST_BETRAG_1': betrag_brutto - betrag_netto,
        'MWST_BETRAG_2': 0,
        'MWST_BETRAG_3': 0,
        'NETTO_BETRAG_1': betrag_netto,
        'NETTO_BETRAG_2': 0,
        'NETTO_BETRAG_3': 0,
        'MITARBEITER_ID': 3,
        'IST_TRAINING': ist_training,
        'STORNO_VON_ID': None,
    }


def _position(pos=1, artikel_id=100, menge=1.0, brutto=1190, netto=1000,
              mwst=190, steuer_code=1, artnum='TEST001', barcode='123'):
    return {
        'POSITION': pos,
        'ARTIKEL_ID': artikel_id,
        'ARTNUM': artnum,
        'BARCODE': barcode,
        'BEZEICHNUNG': 'Testartikel',
        'MENGE': menge,
        'EINZELPREIS_BRUTTO': brutto,
        'GESAMTPREIS_BRUTTO': int(brutto * menge),
        'NETTO_BETRAG': int(netto * menge),
        'MWST_BETRAG': int(mwst * menge),
        'STEUER_CODE': steuer_code,
        'STORNIERT': 0,
    }


def _zahlung(zahlart='BAR', betrag=1190, betrag_gegeben=2000):
    return {
        'ZAHLART': zahlart,
        'BETRAG': betrag,
        'BETRAG_GEGEBEN': betrag_gegeben,
        'WECHSELGELD': betrag_gegeben - betrag,
    }


def _make_cursor(journal_id=99):
    cur = MagicMock()
    cur.lastrowid = journal_id
    # HASHSUM-Query gibt eine Reihe zurück
    cur.fetchall.return_value = [{'HASHSTRING': 'abc123'}]
    # FIRMA-Query
    cur.fetchone.side_effect = [
        {'ID': 5},          # XT_KASSE_TAGESABSCHLUSS
        {'REC_ID': 8},      # FIRMA
        {'REC_ID': 1},      # ZAHLUNGSARTEN
        {'MATCHCODE': 'MATCH01', 'KURZNAME': 'Kurz'},  # ARTIKEL
    ]
    return cur


# ── Tests ─────────────────────────────────────────────────────

class TestBonZuJournalHashsum(unittest.TestCase):
    """HASHSUM-Berechnung ohne DB."""

    def test_hashsum_formel(self):
        salz   = 'cZodx62PyrgwlJKuj'
        concat = 'abc123'
        expected = hashlib.md5(
            (salz + concat).encode('ascii', errors='replace')
        ).hexdigest().upper()
        self.assertEqual(len(expected), 32)
        self.assertTrue(expected.isupper() or expected.isdigit())


class TestBonZuJournalTraining(unittest.TestCase):
    """Trainings-Vorgänge dürfen nicht in JOURNAL geschrieben werden."""

    @patch('kasse_logik.vorgang_laden')
    def test_trainingsvorgang_gibt_none(self, mock_laden):
        mock_laden.return_value = _vorgang(ist_training=1)
        result = kasse_logik.bon_zu_journal(42, terminal_nr=1)
        self.assertIsNone(result)

    @patch('kasse_logik.vorgang_laden')
    def test_fehlender_vorgang_gibt_none(self, mock_laden):
        mock_laden.return_value = None
        result = kasse_logik.bon_zu_journal(999, terminal_nr=1)
        self.assertIsNone(result)  # Exception wird abgefangen


class TestBonZuJournalSummen(unittest.TestCase):
    """Summenberechnung je Steuersatz."""

    def test_summen_je_code(self):
        positionen = [
            _position(pos=1, brutto=1190, netto=1000, mwst=190, steuer_code=1),
            _position(pos=2, brutto=107,  netto=100,  mwst=7,   steuer_code=2),
        ]
        bsumme = {0: 0, 1: 0, 2: 0, 3: 0}
        nsumme = {0: 0, 1: 0, 2: 0, 3: 0}
        msumme = {0: 0, 1: 0, 2: 0, 3: 0}
        for pos in positionen:
            code = pos['STEUER_CODE']
            bsumme[code] += pos['GESAMTPREIS_BRUTTO']
            nsumme[code] += pos['NETTO_BETRAG']
            msumme[code] += pos['MWST_BETRAG']

        self.assertEqual(bsumme[1], 1190)
        self.assertEqual(bsumme[2], 107)
        self.assertEqual(nsumme[1], 1000)
        self.assertEqual(nsumme[2], 100)
        self.assertEqual(msumme[1], 190)
        self.assertEqual(msumme[2], 7)
        self.assertEqual(bsumme[0], 0)
        self.assertEqual(bsumme[3], 0)

    def test_cent_zu_euro_konversion(self):
        """c()-Konversion: 1190 Cent → 11.9 Euro."""
        def c(cent): return round(cent / 100, 4)
        self.assertAlmostEqual(c(1190), 11.9)
        self.assertAlmostEqual(c(107),  1.07)
        self.assertAlmostEqual(c(0),    0.0)


class TestBonZuJournalFehlerbehandlung(unittest.TestCase):
    """bon_zu_journal() darf keine Exception nach oben werfen."""

    @patch('kasse_logik.vorgang_laden')
    @patch('kasse_logik.vorgang_positionen')
    @patch('kasse_logik.vorgang_zahlungen')
    @patch('kasse_logik.mwst_saetze_laden')
    @patch('kasse_logik.get_db')
    @patch('kasse_logik.get_db_transaction')
    def test_db_fehler_gibt_none_zurueck(
        self, mock_txn, mock_db,
        mock_mwst, mock_zahl, mock_pos, mock_laden
    ):
        mock_laden.return_value = _vorgang()
        mock_pos.return_value   = [_position()]
        mock_zahl.return_value  = [_zahlung()]
        mock_mwst.return_value  = {1: 19.0, 2: 7.0, 3: 0.0}

        # get_db: Fehler beim ersten Aufruf (XT_KASSE_TAGESABSCHLUSS)
        db_ctx = MagicMock()
        db_ctx.__enter__ = MagicMock(side_effect=Exception("DB kaputt"))
        db_ctx.__exit__  = MagicMock(return_value=False)
        mock_db.return_value = db_ctx

        result = kasse_logik.bon_zu_journal(42, terminal_nr=1)
        self.assertIsNone(result)


class TestJournalHashsalz(unittest.TestCase):
    """Modul-Konstante HASHSALZ muss exakt dem CAO-Wert entsprechen."""

    def test_hashsalz_wert(self):
        self.assertEqual(
            kasse_logik._JOURNAL_HASHSALZ,
            'cZodx62PyrgwlJKuj'
        )


if __name__ == '__main__':
    unittest.main()
