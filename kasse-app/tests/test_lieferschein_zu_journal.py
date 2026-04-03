"""Tests für lieferschein_zu_journal().

Strategie: DB-Zugriffe werden mit unittest.mock gepatcht.
Wir testen die Logik (Validierung, Kundendaten, Summenberechnung,
HASHSUM-Aufruf, Vorgang-Abschluss), nicht die echte DB-Anbindung.
"""
import hashlib
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── Stub-Module für DB und Konfiguration ─────────────────────

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

import kasse_logik  # noqa: E402


# ── Hilfsfunktionen ───────────────────────────────────────────

def _vorgang(status='OFFEN', betrag_brutto=1190, betrag_netto=1000,
             vorgangsnummer='01-20260403-000042'):
    return {
        'ID': 42,
        'TERMINAL_NR': 1,
        'BON_NR': 42,
        'VORGANGSNUMMER': vorgangsnummer,
        'STATUS': status,
        'BETRAG_BRUTTO': betrag_brutto,
        'BETRAG_NETTO': betrag_netto,
        'IST_TRAINING': 0,
        'STORNO_VON_ID': None,
    }


def _adresse(kun_num='K001', name1='Max Mustermann', name2='', deb_num=10000):
    return {
        'KUNNUM1': kun_num,
        'NAME1': name1,
        'NAME2': name2,
        'DEB_NUM': deb_num,
        'PR_EBENE': 5,
    }


def _position(pos=1, artikel_id=100, menge=1.0, brutto=1190, netto=1000,
              mwst=190, steuer_code=1, artnum='TEST001', barcode='4001234'):
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


def _make_cursor(journal_id=77):
    """Cursor-Mock für get_db_transaction."""
    cur = MagicMock()
    cur.lastrowid = journal_id
    cur.fetchall.return_value = [{'HASHSTRING': 'testdata123'}]
    return cur


def _make_db_side_effects(adresse=None, with_ta=True, with_firma=True,
                           with_zahlart=True, with_artikel=True):
    """Erzeugt die fetchone-Reihenfolge für mehrere get_db()-Aufrufe."""
    results = []
    results.append({'ID': 5} if with_ta else None)   # XT_KASSE_TAGESABSCHLUSS
    results.append({'REC_ID': 8} if with_firma else None)  # FIRMA
    results.append({'REC_ID': 3} if with_zahlart else None)  # ZAHLUNGSARTEN
    if adresse is not None:
        results.insert(0, adresse)  # ADRESSEN (erster get_db-Aufruf)
    return results


# ── Validierungs-Tests ────────────────────────────────────────

class TestLieferscheinZuJournalValidierung(unittest.TestCase):
    """Fehlerbehandlung und Eingabevalidierung."""

    @patch('kasse_logik.vorgang_laden')
    def test_vorgang_nicht_gefunden_wirft_valueerror(self, mock_laden):
        mock_laden.return_value = None
        with self.assertRaises(ValueError, msg="Vorgang nicht gefunden"):
            kasse_logik.lieferschein_zu_journal(999, 1, 'Test')

    @patch('kasse_logik.vorgang_laden')
    def test_abgeschlossener_vorgang_wirft_valueerror(self, mock_laden):
        mock_laden.return_value = _vorgang(status='ABGESCHLOSSEN')
        with self.assertRaises(ValueError):
            kasse_logik.lieferschein_zu_journal(42, 1, 'Test')

    @patch('kasse_logik.vorgang_laden')
    def test_stornierter_vorgang_wirft_valueerror(self, mock_laden):
        mock_laden.return_value = _vorgang(status='STORNIERT')
        with self.assertRaises(ValueError):
            kasse_logik.lieferschein_zu_journal(42, 1, 'Test')

    @patch('kasse_logik.vorgang_laden')
    @patch('kasse_logik.get_db')
    def test_adresse_nicht_gefunden_wirft_valueerror(self, mock_db, mock_laden):
        mock_laden.return_value = _vorgang()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.fetchone.return_value = None  # Adresse nicht vorhanden
        mock_db.return_value = ctx
        with self.assertRaises(ValueError, msg="Adresse nicht gefunden"):
            kasse_logik.lieferschein_zu_journal(42, 999, 'Test')

    @patch('kasse_logik.vorgang_laden')
    def test_geparkter_vorgang_ist_gueltig(self, mock_laden):
        """STATUS='GEPARKT' darf keinen 'Vorgang ist nicht offen'-Fehler auslösen."""
        mock_laden.return_value = _vorgang(status='GEPARKT')
        try:
            kasse_logik.lieferschein_zu_journal(42, 1, 'Test')
        except ValueError as e:
            self.assertNotIn('nicht offen', str(e),
                             "GEPARKT-Vorgänge sollen die Statusprüfung passieren")


# ── Kundendaten-Tests ─────────────────────────────────────────

class TestLieferscheinZuJournalKundendaten(unittest.TestCase):
    """JOURNAL-Eintrag muss korrekte Kundendaten enthalten."""

    @patch('kasse_logik.vorgang_laden')
    @patch('kasse_logik.vorgang_positionen')
    @patch('kasse_logik.mwst_saetze_laden')
    @patch('kasse_logik.get_db')
    @patch('kasse_logik.get_db_transaction')
    def test_journal_insert_enthaelt_kundendaten(
        self, mock_txn, mock_db, mock_mwst, mock_pos, mock_laden
    ):
        mock_laden.return_value = _vorgang()
        mock_pos.return_value = [_position()]
        mock_mwst.return_value = {1: 19.0, 2: 7.0, 3: 0.0}

        # get_db: ADRESSEN → TA → FIRMA → ZAHLUNGSARTEN → ARTIKEL
        adresse = _adresse()
        db_calls = [adresse,       # ADRESSEN
                    {'ID': 5},     # XT_KASSE_TAGESABSCHLUSS
                    {'REC_ID': 8}, # FIRMA
                    {'REC_ID': 3}, # ZAHLUNGSARTEN
                    {'MATCHCODE': 'MATCH1', 'KURZNAME': 'Kurz'}]  # ARTIKEL
        db_ctx = MagicMock()
        db_ctx.__enter__ = MagicMock(return_value=db_ctx)
        db_ctx.__exit__ = MagicMock(return_value=False)
        db_ctx.fetchone.side_effect = db_calls
        mock_db.return_value = db_ctx

        cur = _make_cursor()
        txn_ctx = MagicMock()
        txn_ctx.__enter__ = MagicMock(return_value=cur)
        txn_ctx.__exit__ = MagicMock(return_value=False)
        mock_txn.return_value = txn_ctx

        result = kasse_logik.lieferschein_zu_journal(42, 1, 'Kassierer Test',
                                                      terminal_nr=1, ma_id=3)

        self.assertIn('journal_id', result)
        self.assertEqual(result['journal_id'], 77)

        # JOURNAL-INSERT muss stattgefunden haben
        insert_calls = [str(c) for c in cur.execute.call_args_list]
        journal_call = next((c for c in insert_calls if 'INSERT INTO JOURNAL' in c), None)
        self.assertIsNotNone(journal_call, "INSERT INTO JOURNAL muss aufgerufen werden")

        # Kundennamen-Werte im INSERT
        all_args = str(cur.execute.call_args_list)
        self.assertIn('Max Mustermann', all_args)
        self.assertIn('K001', all_args)     # KUN_NUM
        self.assertIn('10000', all_args)    # DEB_NUM als GEGENKONTO


# ── Summen-Tests ──────────────────────────────────────────────

class TestLieferscheinZuJournalSummen(unittest.TestCase):
    """Summenberechnung je Steuersatz, analog bon_zu_journal."""

    def test_summen_je_steuercode(self):
        positionen = [
            _position(pos=1, brutto=1190, netto=1000, mwst=190, steuer_code=1),
            _position(pos=2, brutto=214,  netto=200,  mwst=14,  steuer_code=2,
                      artikel_id=200, artnum='ART002', barcode='9999'),
        ]
        bsumme = {0: 0, 1: 0, 2: 0, 3: 0}
        nsumme = {0: 0, 1: 0, 2: 0, 3: 0}
        for pos in [p for p in positionen if not p.get('STORNIERT')]:
            code = int(pos.get('STEUER_CODE') or 0)
            if code in bsumme:
                bsumme[code] += int(pos.get('GESAMTPREIS_BRUTTO') or 0)
                nsumme[code] += int(pos.get('NETTO_BETRAG') or 0)

        self.assertEqual(bsumme[1], 1190)
        self.assertEqual(bsumme[2], 214)
        self.assertEqual(nsumme[1], 1000)
        self.assertEqual(nsumme[2], 200)
        self.assertEqual(bsumme[0], 0)
        self.assertEqual(bsumme[3], 0)

    def test_stornierte_positionen_werden_ignoriert(self):
        """Stornierte Positionen (STORNIERT=1) dürfen nicht in Summen eingehen."""
        positionen = [
            _position(pos=1, brutto=1190, netto=1000, steuer_code=1),
            {**_position(pos=2, brutto=500, netto=420, steuer_code=1,
                         artikel_id=200, artnum='ART002', barcode='0000'),
             'STORNIERT': 1},
        ]
        aktive = [p for p in positionen if not p.get('STORNIERT')]
        self.assertEqual(len(aktive), 1)
        self.assertEqual(aktive[0]['POSITION'], 1)

    def test_cent_zu_euro_konversion(self):
        def c(cent): return round(cent / 100, 4)
        self.assertAlmostEqual(c(1190), 11.9)
        self.assertAlmostEqual(c(214),  2.14)
        self.assertAlmostEqual(c(0),    0.0)


# ── HASHSUM-Tests ─────────────────────────────────────────────

class TestLieferscheinZuJournalHashsum(unittest.TestCase):
    """HASHSUM-Berechnung muss identisch zu bon_zu_journal sein."""

    def test_hashsalz_identisch_zu_bon_zu_journal(self):
        self.assertEqual(
            kasse_logik._JOURNAL_HASHSALZ,
            'cZodx62PyrgwlJKuj',
        )

    def test_hashsum_formel(self):
        salz   = kasse_logik._JOURNAL_HASHSALZ
        concat = 'Testdaten123'
        expected = hashlib.md5(
            (salz + concat).encode('ascii', errors='replace')
        ).hexdigest().upper()
        self.assertEqual(len(expected), 32)

    @patch('kasse_logik.vorgang_laden')
    @patch('kasse_logik.vorgang_positionen')
    @patch('kasse_logik.mwst_saetze_laden')
    @patch('kasse_logik.get_db')
    @patch('kasse_logik.get_db_transaction')
    def test_hashsum_update_wird_aufgerufen(
        self, mock_txn, mock_db, mock_mwst, mock_pos, mock_laden
    ):
        mock_laden.return_value = _vorgang()
        mock_pos.return_value = [_position()]
        mock_mwst.return_value = {1: 19.0, 2: 7.0, 3: 0.0}

        db_ctx = MagicMock()
        db_ctx.__enter__ = MagicMock(return_value=db_ctx)
        db_ctx.__exit__ = MagicMock(return_value=False)
        db_ctx.fetchone.side_effect = [
            _adresse(), {'ID': 5}, {'REC_ID': 8}, {'REC_ID': 3},
            {'MATCHCODE': 'M', 'KURZNAME': 'K'},
        ]
        mock_db.return_value = db_ctx

        cur = _make_cursor(journal_id=55)
        txn_ctx = MagicMock()
        txn_ctx.__enter__ = MagicMock(return_value=cur)
        txn_ctx.__exit__ = MagicMock(return_value=False)
        mock_txn.return_value = txn_ctx

        kasse_logik.lieferschein_zu_journal(42, 1, 'Kassierer', terminal_nr=1)

        calls = str(cur.execute.call_args_list)
        self.assertIn('UPDATE JOURNAL SET HASHSUM', calls)


# ── Vorgang-Abschluss-Tests ───────────────────────────────────

class TestLieferscheinZuJournalAbschluss(unittest.TestCase):
    """Vorgang muss nach Journal-Erstellung auf ABGESCHLOSSEN gesetzt werden."""

    @patch('kasse_logik.vorgang_laden')
    @patch('kasse_logik.vorgang_positionen')
    @patch('kasse_logik.mwst_saetze_laden')
    @patch('kasse_logik.get_db')
    @patch('kasse_logik.get_db_transaction')
    def test_vorgang_wird_abgeschlossen(
        self, mock_txn, mock_db, mock_mwst, mock_pos, mock_laden
    ):
        mock_laden.return_value = _vorgang()
        mock_pos.return_value = [_position()]
        mock_mwst.return_value = {1: 19.0, 2: 7.0, 3: 0.0}

        db_ctx = MagicMock()
        db_ctx.__enter__ = MagicMock(return_value=db_ctx)
        db_ctx.__exit__ = MagicMock(return_value=False)
        db_ctx.fetchone.side_effect = [
            _adresse(), {'ID': 5}, {'REC_ID': 8}, {'REC_ID': 3},
            {'MATCHCODE': 'M', 'KURZNAME': 'K'},
        ]
        mock_db.return_value = db_ctx

        cur = _make_cursor()
        txn_ctx = MagicMock()
        txn_ctx.__enter__ = MagicMock(return_value=cur)
        txn_ctx.__exit__ = MagicMock(return_value=False)
        mock_txn.return_value = txn_ctx

        kasse_logik.lieferschein_zu_journal(42, 1, 'Kassierer', terminal_nr=1)

        calls = str(cur.execute.call_args_list)
        self.assertIn('ABGESCHLOSSEN', calls)
        self.assertIn('Lieferschein', calls)


# ── Rückgabewert-Tests ────────────────────────────────────────

class TestLieferscheinZuJournalRueckgabe(unittest.TestCase):
    """Rückgabedict muss journal_id und vrenum enthalten."""

    @patch('kasse_logik.vorgang_laden')
    @patch('kasse_logik.vorgang_positionen')
    @patch('kasse_logik.mwst_saetze_laden')
    @patch('kasse_logik.get_db')
    @patch('kasse_logik.get_db_transaction')
    def test_rueckgabe_enthaelt_journal_id_und_vrenum(
        self, mock_txn, mock_db, mock_mwst, mock_pos, mock_laden
    ):
        vrenum = '01-20260403-000042'
        mock_laden.return_value = _vorgang(vorgangsnummer=vrenum)
        mock_pos.return_value = [_position()]
        mock_mwst.return_value = {1: 19.0, 2: 7.0, 3: 0.0}

        db_ctx = MagicMock()
        db_ctx.__enter__ = MagicMock(return_value=db_ctx)
        db_ctx.__exit__ = MagicMock(return_value=False)
        db_ctx.fetchone.side_effect = [
            _adresse(), {'ID': 5}, {'REC_ID': 8}, {'REC_ID': 3},
            {'MATCHCODE': 'M', 'KURZNAME': 'K'},
        ]
        mock_db.return_value = db_ctx

        cur = _make_cursor(journal_id=123)
        txn_ctx = MagicMock()
        txn_ctx.__enter__ = MagicMock(return_value=cur)
        txn_ctx.__exit__ = MagicMock(return_value=False)
        mock_txn.return_value = txn_ctx

        result = kasse_logik.lieferschein_zu_journal(42, 1, 'Kassierer', terminal_nr=1)

        self.assertEqual(result['journal_id'], 123)
        self.assertEqual(result['vrenum'], vrenum)


if __name__ == '__main__':
    unittest.main()
