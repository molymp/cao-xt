"""
Unit-Tests fuer installer/hibiscus_setup.py und common/hibiscus_client.py.

Keine Netzwerk-/DB-Zugriffe – Downloads + Konfig werden gemockt.
"""
from __future__ import annotations

import configparser
import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from installer import hibiscus_setup as hs  # noqa: E402
from common.hibiscus_client import HibiscusClient, HibiscusError  # noqa: E402


class TestPropertiesMerge(unittest.TestCase):
    def test_merge_erhaelt_unbekannte_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.properties')
            with open(p, 'w', encoding='iso-8859-1') as fh:
                fh.write('# comment\nfoo=alt\nbehalten=ja\n')
            hs._schreibe_properties(p, {'foo': 'neu', 'dazu': '1'})
            gelesen = {}
            with open(p, encoding='iso-8859-1') as fh:
                for z in fh:
                    z = z.strip()
                    if z and not z.startswith('#') and '=' in z:
                        k, _, v = z.partition('=')
                        gelesen[k] = v
            self.assertEqual(gelesen['foo'], 'neu')      # ueberschrieben
            self.assertEqual(gelesen['behalten'], 'ja')  # erhalten
            self.assertEqual(gelesen['dazu'], '1')       # hinzugefuegt

    def test_webadmin_config_setzt_auth_ssl_localhost(self):
        with tempfile.TemporaryDirectory() as d:
            hs.schreibe_webadmin_config(d)
            p = os.path.join(
                d, 'cfg',
                'de.willuhn.jameica.webadmin.Plugin.properties')
            txt = open(p, encoding='iso-8859-1').read()
            self.assertIn('listener.http.auth=true', txt)
            self.assertIn('listener.http.ssl=true', txt)
            self.assertIn('listener.http.address=127.0.0.1', txt)
            self.assertIn(f'listener.http.port={hs.WEBADMIN_PORT}', txt)

    def test_xmlrpc_sharing_setzt_shared_flags(self):
        with tempfile.TemporaryDirectory() as d:
            hs.schreibe_xmlrpc_sharing(d)
            p = os.path.join(
                d, 'cfg', 'de.willuhn.jameica.xmlrpc.Plugin.properties')
            txt = open(p, encoding='iso-8859-1').read()
            self.assertIn('xmlrpc.useinterfacenames=false', txt)
            self.assertIn('hibiscus.xmlrpc.konto.shared=true', txt)
            self.assertIn('hibiscus.xmlrpc.umsatz.shared=true', txt)


class TestDbConfig(unittest.TestCase):
    def test_db_config_setzt_mysql_treiber_und_url(self):
        with tempfile.TemporaryDirectory() as d:
            p = hs.schreibe_db_config(
                d, host='db.local', port=3333, schema='hibiscus',
                user='cao', password='geheim/mit:sonder@zeichen')
            self.assertTrue(p.endswith(
                'de.willuhn.jameica.hbci.rmi.HBCIDBService.properties'))
            txt = open(p, encoding='iso-8859-1').read()
            self.assertIn(
                'database.driver=de.willuhn.jameica.hbci.server.'
                'DBSupportMySqlImpl', txt)
            self.assertIn(
                'database.driver.mysql.jdbcurl=jdbc:mariadb://'
                'db.local:3333/hibiscus', txt)
            self.assertIn('database.driver.mysql.username=cao', txt)
            # Passwort als Plaintext (Hibiscus encrypt=false Default) –
            # Sonderzeichen unverändert (kein URL-Quoting in Properties).
            self.assertIn(
                'database.driver.mysql.password=geheim/mit:sonder@zeichen',
                txt)

    def test_setup_ueberspringt_db_ohne_parameter(self):
        # Ohne db_host/db_user darf keine HBCIDBService.properties
        # entstehen (Hibiscus bleibt auf H2).
        import installer.hibiscus_setup as _hs
        with tempfile.TemporaryDirectory() as d, \
             patch.object(_hs, 'download_und_pruefe'), \
             patch.object(_hs, '_entpacke'):
            res = _hs.setup(basis=os.path.join(d, '.hib'),
                            print_fn=lambda *a: None)
        self.assertFalse(res['db_konfiguriert'])
        self.assertFalse(os.path.exists(os.path.join(
            d, '.hib', 'userdata', 'cfg',
            'de.willuhn.jameica.hbci.rmi.HBCIDBService.properties')))


class TestCaoxtIniBlock(unittest.TestCase):
    def test_block_wird_ergaenzt_ohne_andere_zu_loeschen(self):
        with tempfile.TemporaryDirectory() as d:
            ini = os.path.join(d, 'caoxt.ini')
            cfg = configparser.ConfigParser()
            cfg['Datenbank'] = {'db_loc': 'x'}
            with open(ini, 'w', encoding='utf-8') as fh:
                cfg.write(fh)
            hs.schreibe_caoxt_ini_block(ini, user='dorfkern')
            neu = configparser.ConfigParser()
            neu.read(ini, encoding='utf-8')
            self.assertEqual(neu['Datenbank']['db_loc'], 'x')   # erhalten
            self.assertEqual(neu['Hibiscus']['aktiv'], '1')
            self.assertIn('xmlrpc_url', neu['Hibiscus'])
            self.assertEqual(
                neu['Hibiscus']['pw_quelle'],
                'DORFKERN_KONFIG:hibiscus.master_passwort')


class TestDownloadVerify(unittest.TestCase):
    def test_hash_mismatch_loescht_datei_und_wirft(self):
        art = hs._Artefakt(name='x', url='http://example/x.zip',
                            sha256='0' * 64, ziel='plugin')
        with tempfile.TemporaryDirectory() as d:
            ziel = os.path.join(d, 'x.zip')

            class _Resp(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *a): return False
            with patch('urllib.request.urlopen',
                       return_value=_Resp(b'inhalt')):
                with self.assertRaises(RuntimeError) as ctx:
                    hs.download_und_pruefe(art, ziel, print_fn=lambda *a: None)
            self.assertIn('SHA-256-Mismatch', str(ctx.exception))
            self.assertFalse(os.path.exists(ziel))  # geloescht

    def test_hash_match_behaelt_datei(self):
        daten = b'genau-diese-bytes'
        h = hashlib.sha256(daten).hexdigest()
        art = hs._Artefakt(name='x', url='http://example/x.zip',
                            sha256=h, ziel='plugin')
        with tempfile.TemporaryDirectory() as d:
            ziel = os.path.join(d, 'x.zip')

            class _Resp(io.BytesIO):
                def __enter__(self): return self
                def __exit__(self, *a): return False
            with patch('urllib.request.urlopen',
                       return_value=_Resp(daten)):
                hs.download_und_pruefe(art, ziel, print_fn=lambda *a: None)
            self.assertTrue(os.path.exists(ziel))


class TestZipSlipSchutz(unittest.TestCase):
    def test_entpacke_lehnt_pfad_traversal_ab(self):
        with tempfile.TemporaryDirectory() as d:
            boese = os.path.join(d, 'boese.zip')
            with zipfile.ZipFile(boese, 'w') as zf:
                zf.writestr('../../etc/pwn', 'x')
            with self.assertRaises(RuntimeError):
                hs._entpacke(boese, os.path.join(d, 'out'))


class TestMasterPasswortSpeichern(unittest.TestCase):
    def test_leeres_pw_false(self):
        self.assertFalse(hs.speichere_master_passwort(''))

    def test_speichert_via_konfig_set(self):
        with patch('common.konfig.run_migration'), \
             patch('common.konfig.set') as mset:
            ok = hs.speichere_master_passwort('geheim123', ma_id=7)
        self.assertTrue(ok)
        args, kwargs = mset.call_args
        self.assertEqual(args[0], 'hibiscus.master_passwort')
        self.assertEqual(args[1], 'geheim123')
        self.assertEqual(kwargs['typ'], 'SECRET')
        self.assertEqual(kwargs['kategorie'], 'HIBISCUS')


class TestHibiscusClientGuard(unittest.TestCase):
    def test_fehlende_konfig_wirft(self):
        with self.assertRaises(HibiscusError):
            HibiscusClient('', 'u', '')
        with self.assertRaises(HibiscusError):
            HibiscusClient('https://x/xmlrpc', 'u', '')  # kein pw

    def test_url_bekommt_basic_auth_eingebettet(self):
        c = HibiscusClient('https://127.0.0.1:8080/xmlrpc',
                           'ignored', 'p@ss/wort')
        # ServerProxy haelt die URL intern; Passwort muss URL-codiert sein
        uri = c._proxy.__dict__['_ServerProxy__host']
        self.assertIn('p%40ss%2Fwort', uri)


if __name__ == '__main__':
    unittest.main()
