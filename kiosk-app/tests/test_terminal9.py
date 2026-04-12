"""Tests für Terminal-9-Kundenterminal (HAB-360).

Testet Kundenkarten-Scan, Session-Management und Bestellungs-Filterung.
"""
import sys
import types
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

# ── Stub-Module für DB und Konfiguration ─────────────────────
_db_mod = types.ModuleType('db')

@contextmanager
def _fake_get_db():
    cur = MagicMock()
    yield cur

@contextmanager
def _fake_get_db_transaction():
    cur = MagicMock()
    yield cur

_db_mod.get_db = _fake_get_db
_db_mod.get_db_transaction = _fake_get_db_transaction
_db_mod.cent_zu_euro_str = lambda v: f"{v/100:.2f} €"
_db_mod.test_verbindung = lambda: True
sys.modules.setdefault('db', _db_mod)

_cfg_mod = types.ModuleType('config')
_cfg_mod.TERMINAL_NR = 1
_cfg_mod.SECRET_KEY = 'test-secret'
_cfg_mod.HOST = '127.0.0.1'
_cfg_mod.PORT = 5001
_cfg_mod.DEBUG = False
_cfg_mod.DB_HOST = 'localhost'
_cfg_mod.DB_PORT = 3306
_cfg_mod.DB_NAME = 'test'
_cfg_mod.DB_USER = 'test'
_cfg_mod.DB_PASSWORD = 'test'
_cfg_mod.FIRMA_NAME = 'Testladen'
_cfg_mod.EAN_BEREICH = '21'
_cfg_mod.EAN_SAMMELARTIKEL = '7408'
_cfg_mod.KASSE_PORT = 5002
_cfg_mod.WAWI_PORT = 5003
_cfg_mod.VERWALTUNG_PORT = 5004
_cfg_mod.KASSE_URL = ''
_cfg_mod.WAWI_URL = ''
_cfg_mod.VERWALTUNG_URL = ''
sys.modules.setdefault('config', _cfg_mod)

# Stub für druck-Modul
_druck_mod = types.ModuleType('druck')
_druck_mod.test_drucker = lambda: True
_druck_mod.generiere_bon_bytes = lambda **kw: b'\x00'
_druck_mod._sende_an_drucker = lambda *a, **kw: None
_druck_mod.drucke_pickliste = lambda *a, **kw: None
sys.modules.setdefault('druck', _druck_mod)

# Stub für mittagstisch
_mt_mod = types.ModuleType('mittagstisch')
sys.modules.setdefault('mittagstisch', _mt_mod)

import app as kiosk_app  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def client():
    """Flask Test Client mit Terminal-9-Cookie."""
    kiosk_app.app.config['TESTING'] = True
    with kiosk_app.app.test_client() as c:
        yield c


@pytest.fixture
def client_t9(client):
    """Client mit Terminal-9-Cookie und Mitarbeiter-Session."""
    client.set_cookie('kiosk_terminal', '9')
    with client.session_transaction() as sess:
        sess['ma_id'] = 1
        sess['login_name'] = 'test'
        sess['vname'] = 'Test'
        sess['ma_name'] = 'User'
    return client


@pytest.fixture
def client_t9_kunde(client_t9):
    """Client mit Terminal-9-Cookie, MA-Session UND Kunden-Session."""
    with client_t9.session_transaction() as sess:
        sess['kunden_kontakt_id'] = 42
        sess['kunden_name'] = 'Max Mustermann'
        sess['kunden_adr_id'] = 100
    return client_t9


# ── Hilfsfunktionen-Tests ─────────────────────────────────────

class TestIstKundenterminal:
    def test_terminal_9_ist_kundenterminal(self, client_t9):
        """Terminal 9 wird als Kundenterminal erkannt."""
        with kiosk_app.app.test_request_context(headers={'Cookie': 'kiosk_terminal=9'}):
            assert kiosk_app.ist_kundenterminal() is True

    def test_terminal_1_ist_kein_kundenterminal(self, client):
        """Terminal 1 ist kein Kundenterminal."""
        client.set_cookie('kiosk_terminal', '1')
        with kiosk_app.app.test_request_context(headers={'Cookie': 'kiosk_terminal=1'}):
            assert kiosk_app.ist_kundenterminal() is False


# ── Routing-Tests ─────────────────────────────────────────────

class TestIndexRedirect:
    def test_terminal9_ohne_kunde_redirect_scan(self, client_t9):
        """Terminal 9 ohne Kunden-Session → Redirect auf /kunden-scan."""
        res = client_t9.get('/', follow_redirects=False)
        assert res.status_code == 302
        assert '/kunden-scan' in res.headers['Location']

    def test_terminal9_mit_kunde_redirect_bestellungen(self, client_t9_kunde):
        """Terminal 9 mit Kunden-Session → Redirect auf /meine-bestellungen."""
        res = client_t9_kunde.get('/', follow_redirects=False)
        assert res.status_code == 302
        assert '/meine-bestellungen' in res.headers['Location']


class TestKundenScan:
    def test_kunden_scan_nur_terminal9(self, client):
        """Kunden-Scan-Seite nur auf Terminal 9 erreichbar."""
        client.set_cookie('kiosk_terminal', '1')
        with client.session_transaction() as sess:
            sess['ma_id'] = 1
            sess['login_name'] = 'test'
        res = client.get('/kunden-scan', follow_redirects=False)
        assert res.status_code == 302
        assert '/' == res.headers['Location'] or '/kunden-scan' not in res.headers['Location']

    def test_kunden_scan_terminal9_zeigt_seite(self, client_t9):
        """Terminal 9 zeigt die Scan-Seite an."""
        res = client_t9.get('/kunden-scan')
        assert res.status_code == 200
        assert b'Kundenkarte scannen' in res.data or b'kunden_scan' in res.data


class TestKundenkarteApi:
    def test_leerer_barcode_fehler(self, client_t9):
        """Leerer Barcode gibt Fehlermeldung."""
        res = client_t9.post('/api/kundenkarte/scan',
                             json={'barcode': ''},
                             content_type='application/json')
        data = res.get_json()
        assert data['ok'] is False
        assert 'Barcode' in data.get('fehler', '')

    @patch('app._kunde_per_karte')
    def test_unbekannte_karte_fehler(self, mock_kpk, client_t9):
        """Unbekannte Kundenkarte gibt Fehlermeldung."""
        mock_kpk.return_value = None
        res = client_t9.post('/api/kundenkarte/scan',
                             json={'barcode': 'UNKNOWN123'},
                             content_type='application/json')
        data = res.get_json()
        assert data['ok'] is False
        assert 'nicht erkannt' in data.get('fehler', '')

    @patch('app._kontakt_fuer_kunde')
    @patch('app._kunde_per_karte')
    def test_erfolgreicher_scan(self, mock_kpk, mock_kontakt, client_t9):
        """Erfolgreicher Kartenscan setzt Session und gibt OK zurück."""
        mock_kpk.return_value = {
            'id': 100, 'kunnum': 'K001',
            'name': 'Max Mustermann', 'telefon': '08671 1234'
        }
        mock_kontakt.return_value = 42

        res = client_t9.post('/api/kundenkarte/scan',
                             json={'barcode': 'VALID-GUID'},
                             content_type='application/json')
        data = res.get_json()
        assert data['ok'] is True
        assert data['name'] == 'Max Mustermann'
        assert data['kontakt_id'] == 42

        # Session prüfen
        with client_t9.session_transaction() as sess:
            assert sess['kunden_kontakt_id'] == 42
            assert sess['kunden_name'] == 'Max Mustermann'
            assert sess['kunden_adr_id'] == 100


class TestKundenAbmelden:
    def test_abmelden_loescht_kundensession(self, client_t9_kunde):
        """Kunden-Abmelden löscht nur die Kunden-Session, nicht MA-Session."""
        res = client_t9_kunde.get('/kunden-abmelden', follow_redirects=False)
        assert res.status_code == 302
        assert '/kunden-scan' in res.headers['Location']

        with client_t9_kunde.session_transaction() as sess:
            assert 'kunden_kontakt_id' not in sess
            assert 'kunden_name' not in sess
            # MA-Session bleibt erhalten
            assert sess.get('ma_id') == 1


class TestMeineBestellungen:
    def test_ohne_kunde_redirect(self, client_t9):
        """Ohne Kunden-Session → Redirect auf Scan."""
        res = client_t9.get('/meine-bestellungen', follow_redirects=False)
        assert res.status_code == 302
        assert '/kunden-scan' in res.headers['Location']

    @patch('app.get_db')
    def test_mit_kunde_zeigt_bestellungen(self, mock_db, client_t9_kunde):
        """Mit Kunden-Session werden nur eigene Bestellungen angezeigt."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.return_value.__enter__ = lambda s: mock_cursor
        mock_db.return_value.__exit__ = lambda s, *a: None

        res = client_t9_kunde.get('/meine-bestellungen')
        assert res.status_code == 200

        # Prüfen dass SQL mit kontakt_id=42 gefiltert wird
        call_args = mock_cursor.execute.call_args
        assert 42 in call_args[0][1]  # kontakt_id Parameter


class TestMeineBestellungStornieren:
    def test_ohne_kunde_401(self, client_t9):
        """Storno ohne Kunden-Session gibt 401."""
        res = client_t9.post('/api/meine-bestellungen/1/stornieren')
        assert res.status_code == 401

    @patch('app.get_db')
    def test_fremde_bestellung_404(self, mock_db, client_t9_kunde):
        """Storno einer fremden Bestellung (anderer kontakt_id) gibt 404."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # Nicht gefunden für diesen Kunden
        mock_db.return_value.__enter__ = lambda s: mock_cursor
        mock_db.return_value.__exit__ = lambda s, *a: None

        res = client_t9_kunde.post('/api/meine-bestellungen/999/stornieren')
        assert res.status_code == 404


class TestMeineBestellungNeu:
    def test_ohne_kunde_401(self, client_t9):
        """Neue Bestellung ohne Kunden-Session gibt 401."""
        res = client_t9.post('/api/meine-bestellungen/neu',
                             json={'positionen': []},
                             content_type='application/json')
        assert res.status_code == 401

    def test_ohne_positionen_fehler(self, client_t9_kunde):
        """Neue Bestellung ohne Positionen gibt Fehler."""
        res = client_t9_kunde.post('/api/meine-bestellungen/neu',
                                   json={'positionen': []},
                                   content_type='application/json')
        data = res.get_json()
        assert data['ok'] is False
        assert 'Artikel' in data.get('fehler', '')

    def test_einmalig_ohne_datum_fehler(self, client_t9_kunde):
        """Einmalige Bestellung ohne Datum gibt Fehler."""
        res = client_t9_kunde.post('/api/meine-bestellungen/neu',
                                   json={
                                       'typ': 'einmalig',
                                       'positionen': [{'produkt_id': 1, 'name': 'Brot', 'preis_cent': 350, 'menge': 1}],
                                   },
                                   content_type='application/json')
        data = res.get_json()
        assert data['ok'] is False
        assert 'Abholdatum' in data.get('fehler', '')
