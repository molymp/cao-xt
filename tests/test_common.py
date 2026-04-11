"""
Unit-Tests fuer common/db.py, common/auth.py und common/druck/escpos.py

Keine echte DB-Verbindung erforderlich – alle DB-abhaengigen Funktionen
werden gemockt.
"""
import os
import sys
import socket
import unittest
from unittest.mock import MagicMock, patch, call

# Repo-Root in sys.path aufnehmen damit 'common' importierbar ist
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import flask
from common.db   import cent_zu_euro_str, euro_zu_cent
from common.auth import login_required, get_current_user, login_user, logout_user
from common.druck.escpos import tcp_send, ESC_INIT, ALIGN_CENTER, BOLD_ON, CUT


# ── Hilfsfunktionen common/db.py ──────────────────────────────

class TestCentZuEuroStr(unittest.TestCase):
    def test_ganzer_euro(self):
        self.assertEqual(cent_zu_euro_str(100), "1,00 €")

    def test_null(self):
        self.assertEqual(cent_zu_euro_str(0), "0,00 €")

    def test_dezimalstellen(self):
        self.assertEqual(cent_zu_euro_str(199), "1,99 €")

    def test_grosse_zahl(self):
        self.assertEqual(cent_zu_euro_str(12345), "123,45 €")


class TestEuroZuCent(unittest.TestCase):
    def test_none(self):
        self.assertEqual(euro_zu_cent(None), 0)

    def test_int(self):
        self.assertEqual(euro_zu_cent(5), 500)

    def test_float(self):
        self.assertEqual(euro_zu_cent(1.99), 199)

    def test_string_punkt(self):
        self.assertEqual(euro_zu_cent("2.50"), 250)

    def test_string_komma(self):
        self.assertEqual(euro_zu_cent("2,50"), 250)

    def test_ungueltig(self):
        self.assertEqual(euro_zu_cent("abc"), 0)

    def test_rundung(self):
        # Gleitkomma-Arithmetik: 0.1 + 0.2 = 0.30000...004 → soll 30 ergeben
        self.assertEqual(euro_zu_cent(0.30), 30)


# ── Session-Helpers common/auth.py ────────────────────────────

def _make_app():
    """Minimale Flask-App fuer Session-Tests."""
    app = flask.Flask(__name__)
    app.secret_key = 'test-secret'
    app.config['TESTING'] = True
    return app


class TestLoginUser(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def test_setzt_session_keys(self):
        ma = {'MA_ID': 42, 'LOGIN_NAME': 'max', 'VNAME': 'Max', 'NAME': 'Muster'}
        with self.app.test_request_context('/'):
            flask.session  # sicherstellen, dass Session-Objekt vorhanden
            login_user(ma)
            self.assertEqual(flask.session['ma_id'],      42)
            self.assertEqual(flask.session['login_name'], 'max')
            self.assertEqual(flask.session['vname'],      'Max')
            self.assertEqual(flask.session['ma_name'],    'Muster')


class TestLogoutUser(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def test_loescht_session(self):
        with self.app.test_request_context('/'):
            flask.session['ma_id']      = 42
            flask.session['login_name'] = 'max'
            logout_user()
            self.assertIsNone(flask.session.get('ma_id'))
            self.assertIsNone(flask.session.get('login_name'))


class TestGetCurrentUser(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

    def test_eingeloggt(self):
        with self.app.test_request_context('/'):
            flask.session['ma_id']      = 7
            flask.session['login_name'] = 'anna'
            flask.session['vname']      = 'Anna'
            flask.session['ma_name']    = 'Beispiel'
            user = get_current_user()
            self.assertIsNotNone(user)
            self.assertEqual(user['MA_ID'], 7)
            self.assertEqual(user['LOGIN_NAME'], 'anna')

    def test_nicht_eingeloggt(self):
        with self.app.test_request_context('/'):
            self.assertIsNone(get_current_user())


class TestLoginRequired(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()

        @self.app.get('/login')
        def login():
            return 'login page', 200

        @self.app.get('/geschuetzt')
        @login_required
        def geschuetzt():
            return 'geheime Seite', 200

    def test_leitet_um_wenn_nicht_eingeloggt(self):
        client = self.app.test_client()
        resp   = client.get('/geschuetzt')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_erlaubt_zugriff_wenn_eingeloggt(self):
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['ma_id'] = 1
            resp = client.get('/geschuetzt')
            self.assertEqual(resp.status_code, 200)


# ── TCP-Sendehilfe common/druck/escpos.py ─────────────────────

class TestTcpSend(unittest.TestCase):
    @patch('common.druck.escpos.socket.socket')
    def test_verbindung_und_sendall(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_socket_class.return_value = mock_sock

        daten = ESC_INIT + ALIGN_CENTER + BOLD_ON + b'Test\n' + CUT
        tcp_send('192.168.1.50', 9100, daten, timeout=2.0)

        mock_sock.settimeout.assert_called_once_with(2.0)
        mock_sock.connect.assert_called_once_with(('192.168.1.50', 9100))
        mock_sock.sendall.assert_called_once_with(daten)
        mock_sock.close.assert_called_once()

    @patch('common.druck.escpos.socket.socket')
    def test_close_auch_bei_fehler(self, mock_socket_class):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("Verbindung abgelehnt")
        mock_socket_class.return_value = mock_sock

        with self.assertRaises(OSError):
            tcp_send('10.0.0.1', 9100, b'\x00')

        mock_sock.close.assert_called_once()


class TestEscposKonstanten(unittest.TestCase):
    def test_esc_init_korrekt(self):
        self.assertEqual(ESC_INIT, b'\x1b\x40')

    def test_align_center_korrekt(self):
        self.assertEqual(ALIGN_CENTER, b'\x1b\x61\x01')

    def test_cut_korrekt(self):
        self.assertEqual(CUT, b'\x1d\x56\x01')


if __name__ == '__main__':
    unittest.main()
