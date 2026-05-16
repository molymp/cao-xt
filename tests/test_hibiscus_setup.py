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
            # Status-Read der Auto-Sync (Hibiscus-CORE-Service)
            self.assertIn(
                'hibiscus.synchronizescheduler.shared=true', txt)

    def test_sync_scheduler_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = hs.schreibe_sync_scheduler(
                d, interval_min=90, start_hour=7, end_hour=21,
                enabled=True, stop_on_error=True)
            self.assertTrue(p.endswith(
                'de.willuhn.jameica.hbci.'
                'SynchronizeSchedulerSettings.properties'))
            txt = open(p, encoding='iso-8859-1').read()
            self.assertIn('enabled=true', txt)
            self.assertIn('interval.minutes=90', txt)
            self.assertIn('start.hour=7', txt)
            self.assertIn('end.hour=21', txt)
            self.assertIn('stoponerror=true', txt)

    def test_sync_scheduler_konservativer_default(self):
        # PSD2: ≤ ~4 Abrufe/Tag ohne SCA. Default muss konservativ
        # sein (360 min / 07–19 ≈ 3 Läufe/Tag).
        with tempfile.TemporaryDirectory() as d:
            hs.schreibe_sync_scheduler(d)
            txt = open(os.path.join(d, 'cfg', hs._SYNC_SCHED_PROPS),
                       encoding='iso-8859-1').read()
            self.assertIn('interval.minutes=360', txt)
            self.assertIn('start.hour=7', txt)
            self.assertIn('end.hour=19', txt)
            # Default AUS: headless-Auto-Sync ist mit pushTAN bewiesen
            # nicht möglich → bewusst per Admin-UI einzuschalten.
            self.assertIn('enabled=false', txt)
            self.assertIn('stoponerror=false', txt)
            fenster_h = (hs.SYNC_DEFAULT_END_HOUR
                         - hs.SYNC_DEFAULT_START_HOUR)
            laeufe = fenster_h * 60 // hs.SYNC_DEFAULT_INTERVAL_MIN + 1
            self.assertLessEqual(laeufe, 4)

    def test_sync_scheduler_disabled_flag(self):
        with tempfile.TemporaryDirectory() as d:
            hs.schreibe_sync_scheduler(d, enabled=False)
            txt = open(os.path.join(d, 'cfg', hs._SYNC_SCHED_PROPS),
                       encoding='iso-8859-1').read()
            self.assertIn('enabled=false', txt)

    def test_lies_sync_scheduler_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(hs.lies_sync_scheduler(d)['vorhanden'])
            hs.schreibe_sync_scheduler(
                d, interval_min=240, start_hour=8, end_hour=18,
                enabled=True)
            r = hs.lies_sync_scheduler(d)
            self.assertTrue(r['vorhanden'])
            self.assertTrue(r['enabled'])
            self.assertEqual(r['interval_min'], 240)
            self.assertEqual(r['start_hour'], 8)
            self.assertEqual(r['end_hour'], 18)


class TestPlattform(unittest.TestCase):
    def test_linux_x86_kein_jre_serverlauncher(self):
        p = hs.aktuelle_plattform('Linux', 'x86_64')
        self.assertEqual(p.key, 'linux64')
        self.assertEqual(p.zip_name, 'jameica-linux64.zip')
        self.assertEqual(p.root_dir, 'jameica')
        self.assertFalse(p.jre_bundled)
        cmd = hs.jameica_start_cmd('/b', headless=True,
                                   passwordfile='/b/pw', plat=p)
        self.assertEqual(cmd, ['/b/jameica/jameicaserver.sh',
                               '-f', '/b/userdata', '-w', '/b/pw'])
        # Server-Launcher ist schon Server-Mode → KEIN -d -n
        self.assertNotIn('-d', cmd)

    def test_linux_arm64(self):
        p = hs.aktuelle_plattform('Linux', 'aarch64')
        self.assertEqual(p.zip_name, 'jameica-linuxarm64.zip')

    def test_macos_headless_java_direkt_kein_o(self):
        # macOS headless MUSS java direkt starten (GUI-.sh erzwingt -o,
        # das -P/-w aushebelt). Wrapper: sh -c 'cd <app> && exec java …'
        p = hs.aktuelle_plattform('Darwin', 'arm64')
        self.assertEqual(p.key, 'macos-aarch64')
        self.assertTrue(p.jre_bundled)
        cmd = hs.jameica_start_cmd('/b', headless=True,
                                   passwordcommand='PW', plat=p)
        self.assertEqual(cmd[0], 'sh')
        self.assertEqual(cmd[1], '-c')
        s = cmd[2]
        self.assertIn('cd /b/jameica.app &&', s)
        self.assertIn('jre-macosaarch64/Contents/Home/bin/java', s)
        self.assertIn('-jar /b/jameica.app/jameica-macos-aarch64.jar', s)
        self.assertIn('-d -n', s)
        self.assertIn('-P PW', s)
        self.assertNotIn(' -o ', s)               # NICHT das GUI-.sh
        self.assertNotIn('jameica-macos-aarch64.sh', s)

    def test_macos_gui_nutzt_sh(self):
        p = hs.aktuelle_plattform('Darwin', 'arm64')
        cmd = hs.jameica_start_cmd('/b', plat=p)
        self.assertEqual(
            cmd, ['/b/jameica.app/jameica-macos-aarch64.sh',
                  '-f', '/b/userdata'])

    def test_amd64_alias(self):
        # 'amd64' (z.B. manche Linux/Docker) → x86_64
        self.assertEqual(
            hs.aktuelle_plattform('Linux', 'amd64').key, 'linux64')

    def test_unbekannte_plattform_wirft(self):
        with self.assertRaises(RuntimeError):
            hs.aktuelle_plattform('Windows', 'x86_64')

    def test_jameica_artefakt_url_pro_plattform(self):
        a = hs.jameica_artefakt(hs.aktuelle_plattform('Linux', 'x86_64'))
        self.assertTrue(a.url.endswith('jameica-linux64.zip'))
        self.assertIsNone(a.sha256_sidecar)


class TestJava(unittest.TestCase):
    def _run(self, stderr):
        class R:
            def __init__(s): s.stderr = stderr; s.stdout = ''
        return R()

    def test_java_major_parst_21_und_legacy_8(self):
        with patch('shutil.which', return_value='/usr/bin/java'):
            with patch('subprocess.run',
                       return_value=self._run('openjdk version "21.0.9"')):
                self.assertEqual(hs.java_major(), 21)
            with patch('subprocess.run',
                       return_value=self._run('java version "1.8.0_392"')):
                self.assertEqual(hs.java_major(), 8)

    def test_java_major_kein_java(self):
        with patch('shutil.which', return_value=None):
            self.assertIsNone(hs.java_major())

    def test_ensure_java_vorhanden_ok(self):
        with patch.object(hs, 'java_major', return_value=21):
            r = hs.ensure_java(print_fn=lambda *a: None)
        self.assertEqual(r['status'], 'ok')

    def test_ensure_java_no_autoinstall_manuell(self):
        with patch.object(hs, 'java_major', return_value=None):
            r = hs.ensure_java(auto_install=False, print_fn=lambda *a: None)
        self.assertEqual(r['status'], 'manuell')

    def test_ensure_java_apt_install_erfolg(self):
        # 1. java_major None (fehlt) → nach Install 21.
        seq = [None, 21]
        with patch.object(hs, 'java_major', side_effect=lambda *a: seq.pop(0)), \
             patch('shutil.which', side_effect=lambda x: '/usr/bin/'+x
                   if x in ('apt-get', 'sudo') else None), \
             patch.object(hs.os, 'geteuid', create=True, return_value=0), \
             patch('subprocess.run') as srun:
            r = hs.ensure_java(print_fn=lambda *a: None)
        self.assertEqual(r['status'], 'installiert')
        self.assertTrue(srun.called)

    def test_ensure_java_kein_pkgmanager(self):
        with patch.object(hs, 'java_major', return_value=None), \
             patch('shutil.which', return_value=None):
            r = hs.ensure_java(print_fn=lambda *a: None)
        self.assertEqual(r['status'], 'manuell')
        self.assertIn('Paketmanager', r['msg'])


class TestDaemon(unittest.TestCase):
    def test_passwordcommand_vor_passwordfile(self):
        p = hs.aktuelle_plattform('Linux', 'x86_64')
        cmd = hs.jameica_start_cmd('/b', headless=True,
                                   passwordfile='/b/pw',
                                   passwordcommand='PWCMD', plat=p)
        self.assertIn('-P', cmd)
        self.assertIn('PWCMD', cmd)
        self.assertNotIn('-w', cmd)            # -P hat Vorrang
        self.assertNotIn('-d', cmd)            # Linux server.sh

    def test_macos_daemon_java_direkt(self):
        # macOS Daemon = sh -c java-direkt (siehe
        # test_macos_headless_java_direkt_kein_o). Hier nur: kein -o.
        p = hs.aktuelle_plattform('Darwin', 'arm64')
        cmd = hs.jameica_start_cmd('/b', headless=True,
                                   passwordcommand='X', plat=p)
        self.assertEqual(cmd[:2], ['sh', '-c'])
        self.assertIn('-P X', cmd[2])
        self.assertNotIn(' -o ', cmd[2])

    def test_ist_installiert(self):
        with tempfile.TemporaryDirectory() as d:
            p = hs.aktuelle_plattform('Darwin', 'arm64')
            self.assertFalse(hs.ist_installiert(d, plat=p))
            launcher = os.path.join(d, 'jameica.app',
                                    'jameica-macos-aarch64.sh')
            os.makedirs(os.path.dirname(launcher))
            open(launcher, 'w').close()
            self.assertTrue(hs.ist_installiert(d, plat=p))

    def test_jameica_daemon_env_aus_db_config(self):
        from installer import app_manager as am
        with patch('common.db.effektive_db_config',
                   return_value={'host': 'h', 'port': 3333,
                                 'name': 'cao_XT_DEV', 'user': 'cao',
                                 'password': 'p'}):
            e = am._jameica_daemon_env()
        self.assertEqual(e['DB_LOC'], 'h')
        self.assertEqual(e['DB_PORT'], '3333')
        self.assertEqual(e['DB_NAME'], 'cao_XT_DEV')
        self.assertEqual(e['DB_USER'], 'cao')
        self.assertEqual(e['DB_PASS'], 'p')

    def test_pw_cmd_ohne_quotes(self):
        # Jameica führt -P via Runtime.exec(String) aus (Whitespace-
        # Split, kein Shell-Quoting) → KEINE Anführungszeichen.
        from installer import app_manager as am
        with patch('installer.hibiscus_setup.ist_installiert',
                   return_value=True), \
             patch('installer.hibiscus_setup.jameica_start_cmd') as jsc:
            am._jameica_daemon_argv()
        pw = jsc.call_args.kwargs['passwordcommand']
        self.assertNotIn('"', pw)
        self.assertIn('hibiscus_pw.py', pw)

    def test_app_manager_jameica_skip_ohne_install(self):
        from installer import app_manager as am
        self.assertIn('jameica', am.APPS)
        self.assertIn('jameica', am.START_ORDER)
        with patch('installer.hibiscus_setup.ist_installiert',
                   return_value=False):
            self.assertIsNone(am._jameica_daemon_argv())

    def test_hibiscus_pw_stdout(self):
        import importlib
        m = importlib.import_module('installer.hibiscus_pw')
        with patch('common.konfig.get', return_value='S3cret'):
            buf = io.StringIO()
            with patch('sys.stdout', buf):
                rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), 'S3cret')   # kein \n

    def test_hibiscus_pw_fehlt(self):
        import importlib
        m = importlib.import_module('installer.hibiscus_pw')
        with patch('common.konfig.get', return_value=''):
            buf = io.StringIO()
            with patch('sys.stdout', buf), patch('sys.stderr',
                                                 io.StringIO()):
                rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(buf.getvalue(), '')


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


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


class TestDownloadVerify(unittest.TestCase):
    def test_sidecar_mismatch_loescht_datei_und_wirft(self):
        daten = b'inhalt'
        art = hs._Artefakt(name='x', url='http://example/x.zip',
                            sha256_sidecar='http://example/x.zip.SHA-256',
                            ziel='plugin')
        with tempfile.TemporaryDirectory() as d:
            ziel = os.path.join(d, 'x.zip')
            # 1. Call: ZIP-Bytes, 2. Call: Sidecar mit falschem Hash
            seite = [_Resp(daten),
                     _Resp(('0' * 64 + '  x.zip').encode())]
            with patch('urllib.request.urlopen', side_effect=seite):
                with self.assertRaises(RuntimeError) as ctx:
                    hs.download_und_pruefe(art, ziel, print_fn=lambda *a: None)
            self.assertIn('SHA-256-Mismatch', str(ctx.exception))
            self.assertFalse(os.path.exists(ziel))  # geloescht

    def test_sidecar_match_behaelt_datei(self):
        daten = b'genau-diese-bytes'
        h = hashlib.sha256(daten).hexdigest()
        art = hs._Artefakt(name='x', url='http://example/x.zip',
                            sha256_sidecar='http://example/x.zip.SHA-256',
                            ziel='plugin')
        with tempfile.TemporaryDirectory() as d:
            ziel = os.path.join(d, 'x.zip')
            seite = [_Resp(daten),
                     _Resp(f'{h} *x.zip'.encode())]
            with patch('urllib.request.urlopen', side_effect=seite):
                ret = hs.download_und_pruefe(art, ziel,
                                             print_fn=lambda *a: None)
            self.assertTrue(os.path.exists(ziel))
            self.assertEqual(ret, h)

    def test_ohne_sidecar_kein_hardfail(self):
        # Bewegliche Nightly/current-URL: kein Sidecar → kein Mismatch,
        # Datei bleibt, beobachteter Hash wird zurückgegeben.
        daten = b'irgendein-nightly-build'
        art = hs._Artefakt(name='nightly', url='http://example/n.zip',
                            sha256_sidecar=None, ziel='plugin')
        with tempfile.TemporaryDirectory() as d:
            ziel = os.path.join(d, 'n.zip')
            with patch('urllib.request.urlopen',
                       return_value=_Resp(daten)):
                ret = hs.download_und_pruefe(art, ziel,
                                             print_fn=lambda *a: None)
            self.assertTrue(os.path.exists(ziel))
            self.assertEqual(ret, hashlib.sha256(daten).hexdigest())


class TestZipSlipSchutz(unittest.TestCase):
    def test_entpacke_lehnt_pfad_traversal_ab(self):
        with tempfile.TemporaryDirectory() as d:
            boese = os.path.join(d, 'boese.zip')
            with zipfile.ZipFile(boese, 'w') as zf:
                zf.writestr('../../etc/pwn', 'x')
            with self.assertRaises(RuntimeError):
                hs._entpacke(boese, os.path.join(d, 'out'))

    def test_entpacke_erhaelt_exec_bit(self):
        # Jameica-JRE-Binaries müssen ausführbar bleiben.
        with tempfile.TemporaryDirectory() as d:
            z = os.path.join(d, 'a.zip')
            with zipfile.ZipFile(z, 'w') as zf:
                zi = zipfile.ZipInfo('bin/java')
                zi.external_attr = 0o755 << 16
                zf.writestr(zi, '#!/bin/sh\n')
            out = os.path.join(d, 'out')
            hs._entpacke(z, out)
            st = os.stat(os.path.join(out, 'bin', 'java'))
            self.assertTrue(st.st_mode & 0o111, 'exec-Bit fehlt')


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

    def test_sync_status_mappt_scheduler_antworten(self):
        c = HibiscusClient('https://127.0.0.1:8080/xmlrpc', 'u', 'pw')
        antworten = {
            'hibiscus.synchronizescheduler.getLastExecution':
                '2026-05-16 09:00:00',
            'hibiscus.synchronizescheduler.getNextExecution':
                '2026-05-16 12:00:00',
            'hibiscus.synchronizescheduler.getStatus': 2,
        }
        c._proxy = type('P', (), {
            '__getattr__': staticmethod(
                lambda name: (lambda *a: antworten[name]))
        })()
        st = c.sync_status()
        self.assertEqual(st['letzter'], '2026-05-16 09:00:00')
        self.assertEqual(st['naechster'], '2026-05-16 12:00:00')
        self.assertEqual(st['status'], 2)
        self.assertEqual(st['status_text'], 'OK')


class TestCertPinLoopback(unittest.TestCase):
    def test_ist_loopback(self):
        from common.hibiscus_client import _ist_loopback
        for u in ('https://127.0.0.1:8080/xmlrpc',
                  'https://localhost:8080/x', 'https://[::1]:8080/x'):
            self.assertTrue(_ist_loopback(u), u)
        for u in ('https://bank.example.com/xmlrpc',
                  'https://192.168.1.5:8080/x'):
            self.assertFalse(_ist_loopback(u), u)

    def test_loopback_auto_repin_kein_hardfail(self):
        # Loopback + geänderter Cert → kein HibiscusError, Pin wird
        # automatisch neu geschrieben (Audit/auto-heal).
        import common.hibiscus_client as hc
        kset = {}

        def _get(k, d=None):
            return {'hibiscus.master_passwort': 'pw',
                    'hibiscus.cert_sha256': 'a' * 64}.get(k, d)

        def _set(k, v, **kw):
            kset[k] = v

        with patch.object(hc, '_ini_hibiscus',
                          return_value={'aktiv': '1',
                                        'xmlrpc_url':
                                        'https://127.0.0.1:8080/xmlrpc',
                                        'xmlrpc_user': 'u'}), \
             patch('common.konfig.get', side_effect=_get), \
             patch('common.konfig.set', side_effect=_set), \
             patch('common.konfig.invalidate'), \
             patch.object(hc.HibiscusClient, 'konto_list',
                          return_value=[]), \
             patch.object(hc.HibiscusClient, 'gesehener_cert_sha256',
                          new_callable=lambda: property(
                              lambda self: 'b' * 64)):
            c = hc.aus_konfig(timeout=5)   # darf NICHT werfen
        self.assertEqual(kset.get('hibiscus.cert_sha256'), 'b' * 64)


class TestBankingSyncStatusAusProtokoll(unittest.TestCase):
    """hibiscus_sync_status liest aus DB-protokoll (nicht XML-RPC)."""

    def _db(self, cur):
        import contextlib

        @contextlib.contextmanager
        def _g():
            yield cur
        return _g

    def test_verfuegbar_aus_protokoll(self):
        import datetime
        import modules.orga.banking.models as M
        from unittest.mock import MagicMock
        cur = MagicMock()
        d = datetime.datetime(2026, 5, 16, 15, 30)
        cur.fetchone.side_effect = [{'m': d, 'n': 7},
                                    {'kommentar': 'Saldo abgerufen'}]
        cur.fetchall.return_value = [{'konto_id': 48, 'letzter': d}]
        with patch.object(M, 'get_db', self._db(cur)):
            r = M.hibiscus_sync_status()
        self.assertTrue(r['verfuegbar'])
        self.assertEqual(r['letzter'], '16.05.2026 15:30')
        self.assertEqual(r['status_text'], 'Saldo abgerufen')
        self.assertEqual(r['eintraege'], 7)
        self.assertEqual(r['pro_konto'], {48: '16.05.2026 15:30'})

    def test_leer_degradiert(self):
        import modules.orga.banking.models as M
        from unittest.mock import MagicMock
        cur = MagicMock()
        cur.fetchone.return_value = {'m': None, 'n': 0}
        cur.fetchall.return_value = []
        with patch.object(M, 'get_db', self._db(cur)):
            r = M.hibiscus_sync_status()
        self.assertFalse(r['verfuegbar'])
        self.assertIn('protokoll', r['hinweis'].lower())


class TestSepaUeberweisungAnlegen(unittest.TestCase):
    """HibiscusClient.sepa_ueberweisung_anlegen → sepaueberweisung.create."""

    def _client_mit_capture(self):
        c = HibiscusClient('https://127.0.0.1:8080/xmlrpc', 'u', 'pw')
        calls = []

        def _getattr(name):
            def _m(*a):
                calls.append((name, a))
                return 'HIB-4711'
            return _m

        c._proxy = type('P', (), {
            '__getattr__': staticmethod(_getattr)})()
        return c, calls

    def test_create_map_keys_und_normalisierung(self):
        c, calls = self._client_mit_capture()
        rid = c.sepa_ueberweisung_anlegen(
            debit_konto_id=48,
            iban='de89 3704 0044 0532 0130 00',
            bic='cobadeffxxx',
            name='Großhandel Müller GmbH',
            betrag=123.456, zweck='Rechnung 4711',
            endtoendid='EDI-000123')
        self.assertEqual(rid, 'HIB-4711')
        self.assertEqual(len(calls), 1)
        name, args = calls[0]
        self.assertEqual(name, 'hibiscus.xmlrpc.sepaueberweisung.create')
        p = args[0]
        self.assertEqual(p['konto'], 48)
        # IBAN: ohne Leerzeichen, Großbuchstaben
        self.assertEqual(p['kontonummer'], 'DE89370400440532013000')
        self.assertEqual(p['blz'], 'COBADEFFXXX')
        self.assertEqual(p['betrag'], 123.46)          # 2 NK gerundet
        self.assertEqual(p['verwendungszweck'], 'Rechnung 4711')
        self.assertEqual(p['endtoendid'], 'EDI-000123')

    def test_kein_termin_kein_key(self):
        c, calls = self._client_mit_capture()
        c.sepa_ueberweisung_anlegen(
            debit_konto_id=1, iban='DE12', bic='X', name='N',
            betrag=1.0, zweck='z')
        p = calls[0][1][0]
        self.assertNotIn('termin', p)
        self.assertNotIn('endtoendid', p)


class TestVormerkenViaHibiscus(unittest.TestCase):
    """einkauf.vormerken_via_hibiscus: Guards + Happy-Path."""

    def _ctx(self, cur):
        import contextlib

        @contextlib.contextmanager
        def _g():
            yield cur
        return _g

    def _run(self, *, kopf, sums=(0.0, 0.0), debit='48',
             client_exc=None, aktive_vormerkung=None):
        import modules.orga.bestellwesen.einkauf as E
        import common.hibiscus_client as hc
        from unittest.mock import MagicMock

        cur = MagicMock()
        cur.lastrowid = 99
        # Reihenfolge der fetchone(): Header → aktive-Vormerkung-Guard
        # → Zahlungssumme.
        cur.fetchone.side_effect = [
            kopf,
            aktive_vormerkung,
            {'s_betrag': sums[0], 's_skonto': sums[1]},
        ]
        fake_client = MagicMock()
        if client_exc:
            fake_client.sepa_ueberweisung_anlegen.side_effect = client_exc
        else:
            fake_client.sepa_ueberweisung_anlegen.return_value = 'HIB-9'

        with patch.object(E, 'get_db', self._ctx(cur)), \
             patch.object(E, 'get_db_transaction', self._ctx(cur)), \
             patch('common.konfig.get',
                   side_effect=lambda k, d=None:
                       debit if k == 'hibiscus.debit_konto_id' else d), \
             patch.object(hc, 'aus_konfig', return_value=fake_client):
            return E.vormerken_via_hibiscus(123, ma_name='Tester'), \
                cur, fake_client

    def _kopf(self, **kw):
        base = {'QUELLE': 5, 'STADIUM': 2, 'BSUMME': 100.0,
                'VRENUM': 'EDI-000123', 'ORGNUM': 'RE-77',
                'lief_name': 'Müller GmbH',
                'lief_iban': 'DE89 3704 0044 0532 0130 00',
                'lief_bic': 'cobadeffxxx'}
        base.update(kw)
        return base

    def test_happy_path_setzt_stadium_11(self):
        res, cur, client = self._run(kopf=self._kopf())
        self.assertTrue(res['ok'])
        self.assertEqual(res['stadium'], 11)
        self.assertEqual(res['betrag'], 100.0)
        self.assertEqual(res['hibiscus_id'], 'HIB-9')
        # SEPA mit normalisierter IBAN + offenem Betrag
        kw = client.sepa_ueberweisung_anlegen.call_args.kwargs
        self.assertEqual(kw['iban'], 'DE89370400440532013000')
        self.assertEqual(kw['betrag'], 100.0)
        self.assertEqual(kw['debit_konto_id'], 48)
        # STADIUM-Update idempotent (STADIUM<>11)
        sql = ' '.join(c.args[0] for c in cur.execute.call_args_list
                       if c.args)
        self.assertIn('STADIUM=11', sql)
        self.assertIn('STADIUM<>11', sql)

    def test_offener_betrag_minus_zahlungen(self):
        res, _, client = self._run(kopf=self._kopf(BSUMME=100.0),
                                    sums=(30.0, 0.0))
        self.assertEqual(res['betrag'], 70.0)
        self.assertEqual(
            client.sepa_ueberweisung_anlegen.call_args.kwargs['betrag'],
            70.0)

    def test_bereits_stadium_11_wirft(self):
        with self.assertRaises(PermissionError):
            self._run(kopf=self._kopf(STADIUM=11))

    def test_storniert_wirft(self):
        with self.assertRaises(PermissionError):
            self._run(kopf=self._kopf(STADIUM=127))

    def test_voll_bezahlt_wirft(self):
        with self.assertRaises(PermissionError):
            self._run(kopf=self._kopf(STADIUM=9))

    def test_ohne_iban_wirft_valueerror(self):
        with self.assertRaises(ValueError):
            self._run(kopf=self._kopf(lief_iban=''))

    def test_ohne_debit_konto_wirft_valueerror(self):
        with self.assertRaises(ValueError):
            self._run(kopf=self._kopf(), debit='')

    def test_nichts_offen_wirft(self):
        with self.assertRaises(PermissionError):
            self._run(kopf=self._kopf(BSUMME=100.0), sums=(100.0, 0.0))

    def test_hibiscus_fehler_wird_runtimeerror(self):
        from common.hibiscus_client import HibiscusError
        with self.assertRaises(RuntimeError):
            self._run(kopf=self._kopf(),
                      client_exc=HibiscusError('boom'))

    def test_aktive_vormerkung_wirft(self):
        # Generischer Doppel-Schutz: existiert bereits eine aktive
        # XT_HIBISCUS_VORMERKUNG-Zeile → PermissionError.
        with self.assertRaises(PermissionError):
            self._run(kopf=self._kopf(),
                      aktive_vormerkung={'REC_ID': 7})

    def test_persistiert_vormerkung_und_endtoendid(self):
        res, cur, client = self._run(kopf=self._kopf())
        # EndToEndId Dorfkern-genamespact + im Ergebnis + an Client
        e2e = res['endtoendid']
        self.assertTrue(e2e.startswith('DK-EK123-'), e2e)
        self.assertLessEqual(len(e2e), 35)
        self.assertEqual(
            client.sepa_ueberweisung_anlegen.call_args.kwargs['endtoendid'],
            e2e)
        self.assertEqual(res['vormerkung_id'], 99)
        # INSERT in die generische Verknüpfungstabelle (Status
        # 'vorgemerkt', modulübergreifend keyed).
        sql = ' '.join(c.args[0] for c in cur.execute.call_args_list
                       if c.args)
        self.assertIn('XT_HIBISCUS_VORMERKUNG', sql)
        self.assertIn("'vorgemerkt'", sql)
        self.assertIn("'einkauf'", sql)

    def test_endtoendid_format_und_eindeutig(self):
        import modules.orga.bestellwesen.einkauf as E
        a = E._dorfkern_endtoendid('einkauf', 555811)
        b = E._dorfkern_endtoendid('einkauf', 555811)
        for x in (a, b):
            self.assertTrue(x.startswith('DK-EK555811-'), x)
            self.assertLessEqual(len(x), 35)
            self.assertRegex(x, r'^[A-Z0-9-]+$')
        self.assertNotEqual(a, b)   # Zufallsanteil → kollisionsarm


if __name__ == '__main__':
    unittest.main()
