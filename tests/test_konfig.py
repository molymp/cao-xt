"""
Unit-Tests fuer common/konfig.py

Keine echte DB-Verbindung noetig – ``get_db``/``get_db_transaction`` werden
als Context-Manager gemockt. Getestet werden:

  * ``_cast`` – Typ-robustes Lesen (inkl. kaputter Daten)
  * ``_serialize`` – Schreiben als TEXT
  * ``get`` – DB-Lookup, Default-Rueckgabe, TTL-Cache
  * ``set`` – UPSERT + Cache-Invalidierung
  * ``invalidate`` – einzeln und gesamt
  * ``seed_aus_ini`` – Mapping von ini-Sektionen, SECRET-Heuristik
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import konfig  # noqa: E402


def _cur_mock(fetchone_rueckgabe=None, rowcount: int = 1) -> MagicMock:
    """Baut einen MagicMock, der wie ein DB-Cursor funktioniert."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_rueckgabe
    cur.fetchall.return_value = []
    cur.rowcount = rowcount
    return cur


def _ctxmgr_fuer(cur: MagicMock):
    """Wandelt einen Cursor-Mock in einen Context-Manager-Mock."""
    @contextmanager
    def _cm():
        yield cur
    return _cm


class TestCast(unittest.TestCase):
    def test_none_bleibt_none(self):
        self.assertIsNone(konfig._cast(None, 'STRING'))
        self.assertIsNone(konfig._cast(None, 'INT'))

    def test_string(self):
        self.assertEqual(konfig._cast('hallo', 'STRING'), 'hallo')

    def test_int_ok(self):
        self.assertEqual(konfig._cast('42', 'INT'), 42)

    def test_int_kaputt_wird_none(self):
        # Kaputte Daten reissen nicht die App mit.
        self.assertIsNone(konfig._cast('abc', 'INT'))

    def test_bool_wahr(self):
        for v in ('1', 'true', 'yes', 'ja', 'on', 'True'):
            self.assertTrue(konfig._cast(v, 'BOOL'), v)

    def test_bool_falsch(self):
        for v in ('0', 'false', 'no', '', 'nein'):
            self.assertFalse(konfig._cast(v, 'BOOL'), v)

    def test_json_ok(self):
        self.assertEqual(konfig._cast('{"a": 1}', 'JSON'), {'a': 1})

    def test_json_kaputt_wird_none(self):
        self.assertIsNone(konfig._cast('{nicht json}', 'JSON'))

    def test_secret_als_klartext(self):
        self.assertEqual(konfig._cast('geheim', 'SECRET'), 'geheim')


class TestSerialize(unittest.TestCase):
    def test_none_wird_leerstring(self):
        self.assertEqual(konfig._serialize(None, 'STRING'), '')

    def test_bool_echt(self):
        self.assertEqual(konfig._serialize(True, 'BOOL'), '1')
        self.assertEqual(konfig._serialize(False, 'BOOL'), '0')

    def test_bool_stringform(self):
        # '1'/'true' sind als Input akzeptiert und werden normalisiert
        self.assertEqual(konfig._serialize('true', 'BOOL'), '1')
        self.assertEqual(konfig._serialize('nein', 'BOOL'), '0')

    def test_int(self):
        self.assertEqual(konfig._serialize(42, 'INT'), '42')
        self.assertEqual(konfig._serialize('7', 'INT'), '7')

    def test_json(self):
        # JSON-Dump ist UTF-8, Umlaute nicht escaped (ensure_ascii=False)
        self.assertEqual(konfig._serialize({'a': 1}, 'JSON'), '{"a": 1}')
        self.assertEqual(konfig._serialize({'k': 'äöü'}, 'JSON'),
                         '{"k": "äöü"}')


class TestGet(unittest.TestCase):
    def setUp(self):
        konfig.invalidate()  # sicherstellen, dass kein Alt-Cache stoert

    def test_liefert_default_wenn_nicht_gefunden(self):
        cur = _cur_mock(fetchone_rueckgabe=None)
        with patch.object(konfig, 'get_db', _ctxmgr_fuer(cur)):
            self.assertEqual(konfig.get('nichts.da', default='x'), 'x')

    def test_liefert_gecasteten_wert(self):
        cur = _cur_mock(fetchone_rueckgabe={'WERT': '42', 'TYP': 'INT'})
        with patch.object(konfig, 'get_db', _ctxmgr_fuer(cur)):
            self.assertEqual(konfig.get('db.port'), 42)

    def test_cache_trifft_nicht_zweimal_db(self):
        cur = _cur_mock(fetchone_rueckgabe={'WERT': 'host', 'TYP': 'STRING'})
        with patch.object(konfig, 'get_db', _ctxmgr_fuer(cur)):
            konfig.get('db.host')
            konfig.get('db.host')
            konfig.get('db.host')
        # DB-Aufruf nur beim 1. get; spaetere aus Cache
        self.assertEqual(cur.execute.call_count, 1)

    def test_db_fehler_liefert_default(self):
        @contextmanager
        def _broken():
            raise RuntimeError('DB weg')
            yield None  # pragma: no cover
        with patch.object(konfig, 'get_db', _broken):
            self.assertEqual(konfig.get('egal', default='fallback'),
                             'fallback')


class TestSet(unittest.TestCase):
    def setUp(self):
        konfig.invalidate()

    def test_upsert_und_cache_invalidiert(self):
        # Erst Cache via get() fuellen
        cur_lesen = _cur_mock(
            fetchone_rueckgabe={'WERT': 'alt', 'TYP': 'STRING'})
        with patch.object(konfig, 'get_db', _ctxmgr_fuer(cur_lesen)):
            self.assertEqual(konfig.get('x.y'), 'alt')

        # set() darf den Cache invalidieren
        cur_schreiben = _cur_mock()
        with patch.object(konfig, 'get_db_transaction',
                          _ctxmgr_fuer(cur_schreiben)):
            konfig.set('x.y', 'neu', typ='STRING',
                       kategorie='TEST', ma_id=7)

        # Cache ist leer → naechster get() trifft DB wieder
        cur_lesen2 = _cur_mock(
            fetchone_rueckgabe={'WERT': 'neu', 'TYP': 'STRING'})
        with patch.object(konfig, 'get_db', _ctxmgr_fuer(cur_lesen2)):
            self.assertEqual(konfig.get('x.y'), 'neu')

    def test_ungueltiger_typ_wirft(self):
        with self.assertRaises(ValueError):
            konfig.set('k', 'v', typ='UNBEKANNT')


class TestInvalidate(unittest.TestCase):
    def test_einzel(self):
        konfig._cache['a'] = ('x', 9e12)
        konfig._cache['b'] = ('y', 9e12)
        konfig.invalidate('a')
        self.assertNotIn('a', konfig._cache)
        self.assertIn('b', konfig._cache)

    def test_gesamt(self):
        konfig._cache['a'] = ('x', 9e12)
        konfig._cache['b'] = ('y', 9e12)
        konfig.invalidate()
        self.assertEqual(konfig._cache, {})


class TestSeedAusIni(unittest.TestCase):
    INI = """[Datenbank]
db_loc = host1
db_port = 3306
db_name = cao
db_user = cao
db_pass = geheim
db_pref = XT_

[Umgebung]
xt_environment = produktion

[Email]
smtp_host = smtp.example
smtp_port = 587
smtp_tls = 1
dev_mode = 0
"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', delete=False)
        self.tmp.write(self.INI)
        self.tmp.close()
        self.addCleanup(os.unlink, self.tmp.name)

    def test_ruft_insert_ignore_mit_richtigen_argumenten(self):
        cur = _cur_mock(rowcount=1)
        with patch.object(konfig, 'get_db_transaction', _ctxmgr_fuer(cur)):
            n = konfig.seed_aus_ini(self.tmp.name)

        # 11 Werte in der Test-INI (6 DB, 1 Umgebung, 4 Email)
        self.assertEqual(n, 11)
        # Extrahiere die uebergebenen (schluessel, wert, typ, kategorie, besch)
        anrufe = [c.args[1] for c in cur.execute.call_args_list]
        per_schluessel = {a[0]: a for a in anrufe}

        # DB-Mapping: db_loc → db.host (rename), db_pass → SECRET
        self.assertEqual(per_schluessel['db.host'][1], 'host1')
        self.assertEqual(per_schluessel['db.host'][2], 'STRING')
        self.assertEqual(per_schluessel['db.port'][1], '3306')
        self.assertEqual(per_schluessel['db.port'][2], 'INT')
        self.assertEqual(per_schluessel['db.password'][1], 'geheim')
        self.assertEqual(per_schluessel['db.password'][2], 'SECRET')
        # Email-Mapping: generische <kategorie>.<key>-Namen
        self.assertEqual(per_schluessel['email.smtp_port'][2], 'INT')
        self.assertEqual(per_schluessel['email.smtp_tls'][2], 'BOOL')
        # Umgebung: expliziter Rename
        self.assertEqual(per_schluessel['umgebung.modus'][1], 'produktion')

    def test_fehlende_ini_liefert_0(self):
        self.assertEqual(konfig.seed_aus_ini('/nicht/vorhanden.ini'), 0)


if __name__ == '__main__':
    unittest.main()
