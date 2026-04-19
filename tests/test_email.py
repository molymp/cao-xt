"""
Unit-Tests fuer common/email.py.

Keine echte SMTP-Verbindung – smtplib.SMTP wird gemockt.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import email as e


def _cfg(**overrides) -> dict:
    base = {
        'smtp_host': 'mail.example.com',
        'smtp_port': 587,
        'smtp_user': 'user',
        'smtp_pass': 'pass',
        'smtp_tls':  True,
        'from_addr': 'noreply@example.com',
        'from_name': 'CAO-XT',
        'dev_mode':  False,
    }
    base.update(overrides)
    return base


class TestEmailSenden(unittest.TestCase):
    def test_ohne_smtp_host_ist_disabled(self):
        with patch.object(e, 'load_email_config',
                          return_value=_cfg(smtp_host='')):
            r = e.email_senden('a@b.de', 'T', 'Body')
        self.assertEqual(r['modus'], 'disabled')
        self.assertEqual(r['versendet'], 0)

    def test_ohne_from_addr_ist_disabled(self):
        with patch.object(e, 'load_email_config',
                          return_value=_cfg(from_addr='')):
            r = e.email_senden('a@b.de', 'T', 'Body')
        self.assertEqual(r['modus'], 'disabled')

    def test_leere_empfaengerliste_ist_disabled(self):
        with patch.object(e, 'load_email_config', return_value=_cfg()):
            r = e.email_senden('', 'T', 'Body')
        self.assertEqual(r['modus'], 'disabled')
        self.assertEqual(r['versendet'], 0)

    def test_ok_ruft_send_message_mit_empfaenger(self):
        smtp_mock = MagicMock()
        smtp_ctx = MagicMock()
        smtp_ctx.__enter__.return_value = smtp_mock
        smtp_ctx.__exit__.return_value = False
        with patch.object(e, 'load_email_config', return_value=_cfg()), \
             patch.object(e.smtplib, 'SMTP', return_value=smtp_ctx):
            r = e.email_senden('ma@example.com', 'Subj', 'Hallo')
        self.assertEqual(r['modus'], 'ok')
        self.assertEqual(r['versendet'], 1)
        self.assertEqual(r['empfaenger'], ['ma@example.com'])
        smtp_mock.starttls.assert_called_once()
        smtp_mock.login.assert_called_once_with('user', 'pass')
        smtp_mock.send_message.assert_called_once()
        kwargs = smtp_mock.send_message.call_args.kwargs
        self.assertEqual(kwargs['to_addrs'], ['ma@example.com'])
        self.assertEqual(kwargs['from_addr'], 'noreply@example.com')

    def test_helper_leitet_nicht_um_im_dev_mode(self):
        """Dev-Umleitung ist Aufrufer-Sache; der Helper bleibt dumm."""
        smtp_mock = MagicMock()
        smtp_ctx = MagicMock()
        smtp_ctx.__enter__.return_value = smtp_mock
        smtp_ctx.__exit__.return_value = False
        cfg = _cfg(dev_mode=True)
        with patch.object(e, 'load_email_config', return_value=cfg), \
             patch.object(e.smtplib, 'SMTP', return_value=smtp_ctx):
            r = e.email_senden(['ma@example.com', 'ma2@example.com'],
                               'Subj', 'Hallo')
        self.assertEqual(r['modus'], 'ok')
        self.assertEqual(r['empfaenger'],
                         ['ma@example.com', 'ma2@example.com'])
        kwargs = smtp_mock.send_message.call_args.kwargs
        self.assertEqual(kwargs['to_addrs'],
                         ['ma@example.com', 'ma2@example.com'])
        msg_arg = smtp_mock.send_message.call_args.args[0]
        self.assertFalse(msg_arg['Subject'].startswith('[DEV]'))

    def test_smtp_fehler_liefert_modus_fehler(self):
        def boom(*a, **kw):
            raise OSError('Verbindung verweigert')
        with patch.object(e, 'load_email_config', return_value=_cfg()), \
             patch.object(e.smtplib, 'SMTP', side_effect=boom):
            r = e.email_senden('ma@example.com', 'T', 'B')
        self.assertEqual(r['modus'], 'fehler')
        self.assertEqual(r['versendet'], 0)
        self.assertIn('Verbindung', r['fehler'])

    def test_ohne_tls_kein_starttls(self):
        smtp_mock = MagicMock()
        smtp_ctx = MagicMock()
        smtp_ctx.__enter__.return_value = smtp_mock
        smtp_ctx.__exit__.return_value = False
        with patch.object(e, 'load_email_config',
                          return_value=_cfg(smtp_tls=False)), \
             patch.object(e.smtplib, 'SMTP', return_value=smtp_ctx):
            e.email_senden('ma@example.com', 'T', 'B')
        smtp_mock.starttls.assert_not_called()

    def test_html_body_erzeugt_multipart(self):
        smtp_mock = MagicMock()
        smtp_ctx = MagicMock()
        smtp_ctx.__enter__.return_value = smtp_mock
        smtp_ctx.__exit__.return_value = False
        with patch.object(e, 'load_email_config', return_value=_cfg()), \
             patch.object(e.smtplib, 'SMTP', return_value=smtp_ctx):
            e.email_senden('ma@example.com', 'T', 'Plain',
                           html='<p>HTML</p>')
        msg = smtp_mock.send_message.call_args.args[0]
        self.assertEqual(msg.get_content_type(), 'multipart/alternative')


if __name__ == '__main__':
    unittest.main()
