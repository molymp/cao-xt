"""
Unit-Tests fuer common/config.py::load_email_config.

Prueft Prioritaet REGISTRY > ENV > INI und das dev_mode-Bool.
"""
import os
import sys
import unittest
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import config as c


class TestLoadEmailConfig(unittest.TestCase):
    def setUp(self):
        # ENV-Vars aus dem Prozess herausfiltern, die den Test stoeren wuerden.
        self._env_keys = [k for k in list(os.environ)
                          if k.startswith('XT_EMAIL_')]
        self._saved = {k: os.environ.pop(k) for k in self._env_keys}

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ[k] = v

    def test_registry_hat_vorrang_vor_ini(self):
        reg = {
            'SMTPSERVER': 'reg.example.com',
            'SMTPPORT':   '465',
            'SMTPUSER':   'reguser',
            'SMTPPASS':   'regpass',
            'TLS':        '1',
            'FROMADDR':   'reg@example.com',
            'FROMNAME':   'Reg Absender',
            'DEVMODE':    '0',
        }
        with patch.object(c, '_registry_email_lesen', return_value=reg):
            cfg = c.load_email_config()
        self.assertEqual(cfg['smtp_host'], 'reg.example.com')
        self.assertEqual(cfg['smtp_port'], 465)
        self.assertEqual(cfg['smtp_user'], 'reguser')
        self.assertEqual(cfg['smtp_pass'], 'regpass')
        self.assertEqual(cfg['from_addr'], 'reg@example.com')
        self.assertEqual(cfg['from_name'], 'Reg Absender')
        self.assertTrue(cfg['smtp_tls'])
        self.assertFalse(cfg['dev_mode'])

    def test_env_override_wenn_registry_leer(self):
        with patch.object(c, '_registry_email_lesen', return_value={}), \
             patch.dict(os.environ, {
                 'XT_EMAIL_SMTP_HOST': 'env.example.com',
                 'XT_EMAIL_FROM_ADDR': 'env@example.com',
                 'XT_EMAIL_DEV_MODE':  '1',
             }):
            cfg = c.load_email_config()
        self.assertEqual(cfg['smtp_host'], 'env.example.com')
        self.assertEqual(cfg['from_addr'], 'env@example.com')
        self.assertTrue(cfg['dev_mode'])

    def test_registry_fallback_val_int_wenn_val_char_leer(self):
        # _registry_email_lesen liefert bereits Strings – hier simulieren wir
        # den Fall, dass der Port als VAL_INT2 kam und schon als '587' zurueck-
        # kommt. (Die interne Fallback-Logik wird in
        # test_registry_lesen_fallback separat geprueft.)
        reg = {'SMTPSERVER': 'x', 'SMTPPORT': '2525'}
        with patch.object(c, '_registry_email_lesen', return_value=reg):
            cfg = c.load_email_config()
        self.assertEqual(cfg['smtp_port'], 2525)

    def test_dev_mode_bool_parsing(self):
        for val, erwartet in [('1', True), ('true', True), ('ja', True),
                              ('yes', True), ('0', False), ('false', False),
                              ('', False), ('nein', False)]:
            with self.subTest(val=val):
                with patch.object(c, '_registry_email_lesen',
                                  return_value={'DEVMODE': val,
                                                'SMTPSERVER': 'x',
                                                'FROMADDR': 'x@y'}):
                    cfg = c.load_email_config()
                self.assertEqual(cfg['dev_mode'], erwartet)


class TestEmailConfigDiagnose(unittest.TestCase):
    """Liefert effektiven Wert + Herkunft pro Key."""

    def setUp(self):
        self._env_keys = [k for k in list(os.environ)
                          if k.startswith('XT_EMAIL_')]
        self._saved = {k: os.environ.pop(k) for k in self._env_keys}

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ[k] = v

    @staticmethod
    def _debug(daten, **rest):
        base = {'daten': daten, 'mainkeys': ['MAIN\\EMAIL'],
                'rows': len(daten), 'fehler': None,
                'sql': 'SELECT ...'}
        base.update(rest)
        return base

    def test_registry_quelle_wird_erkannt(self):
        reg = {'DEVMODE': '1', 'SMTPSERVER': 'reg.example.com',
               'FROMADDR': 'reg@example.com'}
        with patch.object(c, '_registry_email_lesen_debug',
                          return_value=self._debug(reg)), \
             patch.object(c, '_registry_email_lesen', return_value=reg):
            d = c.email_config_diagnose()
        self.assertEqual(d['sources']['dev_mode']['quelle'], 'registry')
        self.assertIn('DEVMODE', d['sources']['dev_mode']['detail'])
        self.assertEqual(d['sources']['dev_mode']['roh'], '1')
        self.assertTrue(d['config']['dev_mode'])
        self.assertEqual(d['sources']['smtp_host']['quelle'], 'registry')
        # Debug-Block muss durchgereicht werden
        self.assertEqual(d['registry_debug']['rows'], 3)
        self.assertIn('MAIN\\EMAIL', d['registry_debug']['mainkeys'])

    def test_env_quelle_wird_erkannt_wenn_registry_leer(self):
        with patch.object(c, '_registry_email_lesen_debug',
                          return_value=self._debug({})), \
             patch.object(c, '_registry_email_lesen', return_value={}), \
             patch.dict(os.environ,
                        {'XT_EMAIL_DEV_MODE': '1',
                         'XT_EMAIL_SMTP_HOST': 'env.example.com'}):
            d = c.email_config_diagnose()
        self.assertEqual(d['sources']['dev_mode']['quelle'], 'env')
        self.assertEqual(d['sources']['dev_mode']['detail'],
                         'XT_EMAIL_DEV_MODE')
        self.assertTrue(d['config']['dev_mode'])

    def test_ini_quelle_wenn_registry_und_env_leer(self):
        with patch.object(c, '_registry_email_lesen_debug',
                          return_value=self._debug({})), \
             patch.object(c, '_registry_email_lesen', return_value={}):
            d = c.email_config_diagnose()
        # dev_mode ist in INI als 0 gepflegt
        self.assertIn(d['sources']['dev_mode']['quelle'], ('ini', 'fallback'))

    def test_db_fehler_wird_durchgereicht(self):
        debug = self._debug({}, fehler='OperationalError: Pool missing',
                            rows=0, mainkeys=[])
        with patch.object(c, '_registry_email_lesen_debug',
                          return_value=debug), \
             patch.object(c, '_registry_email_lesen', return_value={}):
            d = c.email_config_diagnose()
        self.assertIn('OperationalError', d['registry_debug']['fehler'])

    def test_passwort_wird_maskiert(self):
        reg = {'SMTPPASS': 'SuperGeheim123', 'SMTPSERVER': 'x',
               'FROMADDR': 'x@y'}
        with patch.object(c, '_registry_email_lesen_debug',
                          return_value=self._debug(reg)), \
             patch.object(c, '_registry_email_lesen', return_value=reg):
            d = c.email_config_diagnose()
        # weder in sources.roh noch in config
        self.assertNotIn('SuperGeheim123', d['sources']['smtp_pass']['roh'])
        self.assertNotIn('SuperGeheim123', d['config']['smtp_pass'])


class TestRegistryLesenFallback(unittest.TestCase):
    """VAL_CHAR-Fallback auf VAL_INT2/INT/DOUBLE."""

    def test_val_int2_wird_genommen_wenn_val_char_leer(self):
        # Mock get_db mit Context-Manager + fetchall.
        class _Cur:
            def execute(self, *a, **kw): pass
            def fetchall(self):
                return [
                    {'MAINKEY': 'MAIN\\EMAIL',
                     'NAME': 'SMTPSERVER', 'VAL_CHAR': 'x',
                     'VAL_INT': None, 'VAL_INT2': None, 'VAL_DOUBLE': None},
                    {'MAINKEY': 'MAIN\\EMAIL',
                     'NAME': 'SMTPPORT', 'VAL_CHAR': '',
                     'VAL_INT': None, 'VAL_INT2': 465, 'VAL_DOUBLE': None},
                ]
        class _Ctx:
            def __enter__(self_): return _Cur()
            def __exit__(self_, *a): return False

        # common.db wird lazy importiert – wir patchen die Import-Quelle.
        import common.db
        with patch.object(common.db, 'get_db', return_value=_Ctx()):
            reg = c._registry_email_lesen()
        self.assertEqual(reg['SMTPSERVER'], 'x')
        self.assertEqual(reg['SMTPPORT'], '465')

    def test_debug_liefert_mainkey_varianten(self):
        """LIKE 'MAIN%EMAIL' matcht beide Schreibweisen – Debug muss beide sehen."""
        class _Cur:
            def execute(self, *a, **kw): pass
            def fetchall(self):
                return [
                    {'MAINKEY': 'MAIN\\EMAIL', 'NAME': 'SMTPSERVER',
                     'VAL_CHAR': 'a', 'VAL_INT': None,
                     'VAL_INT2': None, 'VAL_DOUBLE': None},
                    {'MAINKEY': 'MAIN/EMAIL', 'NAME': 'FROMADDR',
                     'VAL_CHAR': 'x@y', 'VAL_INT': None,
                     'VAL_INT2': None, 'VAL_DOUBLE': None},
                ]
        class _Ctx:
            def __enter__(self_): return _Cur()
            def __exit__(self_, *a): return False

        import common.db
        with patch.object(common.db, 'get_db', return_value=_Ctx()):
            info = c._registry_email_lesen_debug()
        self.assertEqual(info['rows'], 2)
        self.assertIn('MAIN\\EMAIL', info['mainkeys'])
        self.assertIn('MAIN/EMAIL', info['mainkeys'])
        self.assertIsNone(info['fehler'])

    def test_debug_traegt_fehler_ein(self):
        import common.db
        def boom(*a, **kw):
            raise RuntimeError('DB-Pool nicht initialisiert')
        with patch.object(common.db, 'get_db', side_effect=boom):
            info = c._registry_email_lesen_debug()
        self.assertIn('DB-Pool', info['fehler'])
        self.assertEqual(info['rows'], 0)
        self.assertEqual(info['daten'], {})

    def test_fail_safe_wenn_db_nicht_verfuegbar(self):
        import common.db
        def boom(*a, **kw):
            raise RuntimeError('DB-Pool nicht initialisiert')
        with patch.object(common.db, 'get_db', side_effect=boom):
            reg = c._registry_email_lesen()
        self.assertEqual(reg, {})


if __name__ == '__main__':
    unittest.main()
