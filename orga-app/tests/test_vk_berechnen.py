"""
Tests für vk_berechnen – VK-Preis-Ermittlung im Orga-Modul.

Strategie: DB-Zugriffe werden mit unittest.mock gepatcht (analog kasse-app).
Getestet wird die Geschäftslogik der 3-stufigen Preisermittlung:
  1. Orga-Preishistorie (XT_WAWI_PREISHISTORIE) hat höchste Priorität
  2. CAO-Aktionspreis (ARTIKEL_PREIS PT2='AP') hat zweithöchste Priorität
  3. CAO-Standardpreis (VKxB-Felder) ist der Fallback

Referenz: HAB-201
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ── Stub-Module für DB-Verbindung ─────────────────────────────────────────────
# models.py initialisiert beim Import einen DB-Connection-Pool.
# Wir mocken mysql.connector und configparser weg, damit kein echter
# DB-Server benötigt wird.

_connector_mod = types.ModuleType('mysql.connector')
_pooling_mod = types.ModuleType('mysql.connector.pooling')


class _FakePool:
    def get_connection(self):
        raise Exception('not connected')


_pooling_mod.MySQLConnectionPool = MagicMock(return_value=_FakePool())
_connector_mod.pooling = _pooling_mod
_connector_mod.connect = MagicMock()
sys.modules['mysql'] = types.ModuleType('mysql')
sys.modules['mysql.connector'] = _connector_mod
sys.modules['mysql.connector.pooling'] = _pooling_mod

# configparser liest caoxt.ini – wir geben leere Werte zurück
import configparser as _cp_real
_cfg_stub = _cp_real.ConfigParser()
# kein [Datenbank]-Abschnitt → get() liefert fallback-Wert

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'modules', 'orga'))

# Jetzt können wir models importieren (Pool-Erstellung wird durch Mock abgefangen)
import models as m  # noqa: E402


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _artikel(artnum='A001', vk5b=2.99, mwst_code='2'):
    """Minimaler Artikel-Dict wie von artikel_by_artnum() zurückgegeben."""
    return {
        'ARTNUM': artnum,
        'BEZEICHNUNG': 'Testartikel',
        'BARCODE': '4000000000001',
        'VK1B': 2.99, 'VK2B': 2.99, 'VK3B': 2.99, 'VK4B': 2.99, 'VK5B': vk5b,
        'EK_PREIS': 1.50,
        'MWST_CODE': mwst_code,
        'MENGE_AKT': 10.0,
        'ARTIKELTYP': '0',
        'WG_NAME': 'Testwarengruppe',
    }


def _orga_preis(artnum='A001', preis_ct=350, preisebene=5):
    """Minimaler Orga-Preis-Dict wie von aktuellen_preis_holen() zurückgegeben."""
    return {
        'REC_ID': 1,
        'ARTNUM': artnum,
        'PREISEBENE': preisebene,
        'PREIS_BRUTTO_CT': preis_ct,
        'GUELTIG_AB': '2026-01-01',
        'GUELTIG_BIS': None,
        'KOMMENTAR': '',
        'CREATED_AT': '2026-01-01T10:00:00',
        'CREATED_BY': 'test',
    }


def _aktionspreis(preis=2.49):
    """Minimaler Aktionspreis-Dict wie von preisgruppen_fuer_artikel() zurückgegeben."""
    return {
        'REC_ID': 10,
        'PT2': 'AP',
        'PREIS': preis,
        'MENGE_AB': None,
        'MENGE_BIS': None,
        'DATUM_AB': '2026-01-01',
        'DATUM_BIS': None,
        'KUNDEN_NR': None,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestVkBerechnenPrioritaeten(unittest.TestCase):
    """Testet die 3-stufige Preis-Priorität von vk_berechnen()."""

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_orga_preis_hat_hoechste_prioritaet(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """Orga-Preishistorie überschreibt Aktions- und CAO-Preis."""
        mock_artikel.return_value = _artikel(vk5b=2.99)
        mock_orga.return_value = _orga_preis(preis_ct=350)
        mock_aktionen.return_value = [_aktionspreis(preis=2.49)]

        result = m.vk_berechnen('A001', preisebene=5)

        self.assertEqual(result['preis_ct'], 350)
        self.assertEqual(result['quelle'], 'orga')
        self.assertEqual(result['artnum'], 'A001')

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_aktionspreis_wenn_kein_orga_preis(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """Aktionspreis wird verwendet, wenn kein Orga-Preis vorhanden."""
        mock_artikel.return_value = _artikel(vk5b=2.99)
        mock_orga.return_value = None  # kein Orga-Preis
        mock_aktionen.return_value = [_aktionspreis(preis=2.49)]

        result = m.vk_berechnen('A001', preisebene=5)

        self.assertEqual(result['preis_ct'], 249)
        self.assertEqual(result['quelle'], 'aktion')

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_cao_fallback_wenn_kein_orga_und_keine_aktion(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """CAO-Standardpreis (VKxB) ist letzter Fallback."""
        mock_artikel.return_value = _artikel(vk5b=2.99)
        mock_orga.return_value = None
        mock_aktionen.return_value = []

        result = m.vk_berechnen('A001', preisebene=5)

        self.assertEqual(result['preis_ct'], 299)
        self.assertEqual(result['quelle'], 'cao')

    @patch.object(m, 'artikel_by_artnum')
    def test_artikel_nicht_gefunden_wirft_valueerror(self, mock_artikel):
        """ValueError wenn Artikel nicht in DB."""
        mock_artikel.return_value = None

        with self.assertRaises(ValueError) as ctx:
            m.vk_berechnen('UNBEKANNT', preisebene=5)

        self.assertIn('UNBEKANNT', str(ctx.exception))

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_mwst_code_wird_weitergegeben(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """mwst_code aus ARTIKEL wird immer im Ergebnis zurückgegeben."""
        mock_artikel.return_value = _artikel(mwst_code='1')
        mock_orga.return_value = _orga_preis(preis_ct=100)
        mock_aktionen.return_value = []

        result = m.vk_berechnen('A001', preisebene=5)

        self.assertEqual(result['mwst_code'], '1')

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_preisebene_wird_an_orga_abfrage_weitergegeben(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """aktuellen_preis_holen() wird mit der korrekten Preisebene aufgerufen."""
        mock_artikel.return_value = _artikel()
        mock_orga.return_value = None
        mock_aktionen.return_value = []

        m.vk_berechnen('A001', preisebene=3)

        mock_orga.assert_called_once_with('A001', 3)


class TestVkBerechnenCaoFallback(unittest.TestCase):
    """Tests für den CAO-Standardpreis-Fallback (VKxB-Felder)."""

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_vk5b_ist_fallback_bei_fehlender_preisebene(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """Wenn VKxB für die gesuchte Ebene fehlt, wird VK5B als Fallback verwendet."""
        artikel = _artikel(vk5b=1.99)
        artikel['VK3B'] = None  # Ebene 3 fehlt
        mock_artikel.return_value = artikel
        mock_orga.return_value = None
        mock_aktionen.return_value = []

        result = m.vk_berechnen('A001', preisebene=3)

        # Kein VK3B → Fallback auf VK5B = 1.99 → 199 Cent
        self.assertEqual(result['preis_ct'], 199)
        self.assertEqual(result['quelle'], 'cao')

    @patch.object(m, 'artikel_by_artnum')
    @patch.object(m, 'aktuellen_preis_holen')
    @patch.object(m, 'preisgruppen_fuer_artikel')
    def test_preis_null_wenn_vk5b_fehlt(
        self, mock_aktionen, mock_orga, mock_artikel
    ):
        """0 Cent wenn weder VKxB noch VK5B gesetzt ist."""
        artikel = _artikel(vk5b=None)
        mock_artikel.return_value = artikel
        mock_orga.return_value = None
        mock_aktionen.return_value = []

        result = m.vk_berechnen('A001', preisebene=5)

        self.assertEqual(result['preis_ct'], 0)
        self.assertEqual(result['quelle'], 'cao')


class TestPreisSetzenValidierung(unittest.TestCase):
    """Tests für die Eingabevalidierung von preis_setzen()."""

    def test_negativer_preis_wirft_valueerror(self):
        """Negativer Preis wird abgelehnt (GoBD)."""
        with self.assertRaises(ValueError) as ctx:
            m.preis_setzen(
                artnum='A001',
                preisebene=5,
                preis_brutto_ct=-1,
                gueltig_ab='2026-01-01',
                gueltig_bis=None,
                benutzer='test',
            )
        self.assertIn('negativ', str(ctx.exception).lower())

    @patch.object(m, 'get_db_transaction')
    def test_preis_null_ist_erlaubt(self, mock_tx):
        """Preis von 0 Cent ist valid (Gratisartikel)."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'id': 42}
        mock_tx.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_tx.return_value.__exit__ = MagicMock(return_value=False)

        result = m.preis_setzen(
            artnum='A001',
            preisebene=5,
            preis_brutto_ct=0,
            gueltig_ab='2026-01-01',
            gueltig_bis=None,
            benutzer='test',
        )

        self.assertEqual(result, 42)


if __name__ == '__main__':
    unittest.main()
