"""
Unit-Tests fuer admin-app/app/system_rechte_dorfkern.py.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'system_rechte_dorfkern.py')


class _FakeCursor:
    """Routet SQL-Queries auf fixe Result-Sets.

    Erkennt anhand von Keywords welche Query laeuft und liefert das
    passende Test-Fixture.
    """

    def __init__(self, rollen=None, objekte=None, rechte=None,
                 objekt_unterscheidung=None):
        self._rollen = rollen or []
        self._objekte = objekte or []
        self._rechte = rechte or []
        self._unterscheidung = objekt_unterscheidung or {}
        self._naechste = []
        self._letzter_key = None

    def execute(self, sql, *args, **kwargs):
        u = sql.upper()
        if 'DISTINCT MODUL_NAME' in u and 'BENUTZERRECHTE' in u:
            self._naechste = [{'rolle': r} for r in self._rollen]
        elif 'UNTERSCHEIDUNG' in u and 'WHERE OBJEKT_KEY' in u:
            # args=(('objekt_key',),) dank *args
            key = args[0][0] if args else ''
            self._letzter_key = key
            if key in self._unterscheidung:
                self._naechste = [{'UNTERSCHEIDUNG':
                                   self._unterscheidung[key]}]
            else:
                self._naechste = []
        elif 'FROM DORFKERN_PERMISSION_OBJEKT' in u:
            self._naechste = self._objekte
        elif 'FROM DORFKERN_ROLLE_PERMISSION' in u:
            self._naechste = self._rechte
        else:
            self._naechste = []

    def fetchall(self):
        return self._naechste

    def fetchone(self):
        return self._naechste[0] if self._naechste else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade(fake_cur, perm_calls=None):
    # Fake db
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: fake_cur
    sys.modules['db'] = fake_db

    # Fake common.permission mit zaehlenden set/loesche
    common_pkg = types.ModuleType('common')
    common_pkg.__path__ = []
    sys.modules['common'] = common_pkg
    calls = perm_calls if perm_calls is not None else []
    fake_perm = types.SimpleNamespace(
        ROLLE_ADMIN='Administratoren',
        set_rolle_permission=lambda r, k, recht: calls.append(
            ('set', r, k, recht)),
        loesche_rolle_permission=lambda r, k: calls.append(
            ('loesche', r, k)),
    )
    sys.modules['common.permission'] = fake_perm

    sys.modules.pop('rd_test', None)
    spec = importlib.util.spec_from_file_location('rd_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._perm_calls = calls
    return mod


def _objekt(key, app='KIOSK', unterscheidung='KEINE',
            bezeichnung=None, beschreibung=''):
    return {
        'OBJEKT_KEY':    key,
        'APP':           app,
        'BEZEICHNUNG':   bezeichnung or key,
        'BESCHREIBUNG':  beschreibung,
        'UNTERSCHEIDUNG': unterscheidung,
    }


class TestMatrix(unittest.TestCase):

    def test_leere_db(self):
        mod = _lade(_FakeCursor())
        m = mod.matrix()
        # Nur Admin-Rolle als "immer da"
        self.assertEqual(len(m['rollen']), 1)
        self.assertEqual(m['rollen'][0]['name'], 'Administratoren')
        self.assertTrue(m['rollen'][0]['admin'])
        self.assertEqual(m['objekte'], [])
        self.assertEqual(m['rechte'], {})

    def test_admin_kommt_erst_dann_rest_alphabetisch(self):
        mod = _lade(_FakeCursor(
            rollen=['Mitarbeiter', 'Administratoren',
                    'Geschäftsführung', 'Ladenleitung']))
        m = mod.matrix()
        namen = [r['name'] for r in m['rollen']]
        self.assertEqual(namen[0], 'Administratoren')
        self.assertTrue(m['rollen'][0]['admin'])
        # Rest wie die DB sie geliefert hat (sortiert) ohne Admin
        for r in m['rollen'][1:]:
            self.assertFalse(r['admin'])

    def test_matrix_mit_daten(self):
        mod = _lade(_FakeCursor(
            rollen=['Ladenleitung'],
            objekte=[
                _objekt('kasse.storno', 'KASSE', 'KEINE'),
                _objekt('orga.schichtplan', 'ORGA', 'LESE_PFLEGE'),
            ],
            rechte=[
                {'ROLLE': 'Ladenleitung',
                 'OBJEKT_KEY': 'kasse.storno',
                 'RECHT': 'BEIDES'},
                {'ROLLE': 'Ladenleitung',
                 'OBJEKT_KEY': 'orga.schichtplan',
                 'RECHT': 'PFLEGEN'},
            ],
        ))
        m = mod.matrix()
        # Objekte nach APP+Key sortiert
        keys = [o['key'] for o in m['objekte']]
        self.assertIn('kasse.storno', keys)
        self.assertIn('orga.schichtplan', keys)
        # Matrix-Eintraege fuer Ladenleitung
        self.assertEqual(m['rechte']['Ladenleitung']['kasse.storno'],
                         'BEIDES')
        self.assertEqual(m['rechte']['Ladenleitung']['orga.schichtplan'],
                         'PFLEGEN')
        # Recht-Optionen pro Unterscheidung
        self.assertEqual(m['recht_optionen']['KEINE'], ['', 'BEIDES'])
        self.assertEqual(m['recht_optionen']['LESE_PFLEGE'],
                         ['', 'LESEN', 'PFLEGEN', 'BEIDES'])


class TestZelleSetzen(unittest.TestCase):

    def test_admin_ablehnen(self):
        mod = _lade(_FakeCursor())
        r = mod.zelle_setzen('Administratoren', 'kasse.storno', 'BEIDES')
        self.assertFalse(r['ok'])
        self.assertIn('implizit', r['msg'])

    def test_leerer_recht_loescht(self):
        mod = _lade(_FakeCursor(
            objekt_unterscheidung={'kasse.storno': 'KEINE'}))
        r = mod.zelle_setzen('Ladenleitung', 'kasse.storno', '')
        self.assertTrue(r['ok'])
        self.assertEqual(mod._perm_calls,
                         [('loesche', 'Ladenleitung', 'kasse.storno')])

    def test_beides_auf_keine_objekt(self):
        mod = _lade(_FakeCursor(
            objekt_unterscheidung={'kasse.storno': 'KEINE'}))
        r = mod.zelle_setzen('Ladenleitung', 'kasse.storno', 'BEIDES')
        self.assertTrue(r['ok'])
        self.assertEqual(
            mod._perm_calls,
            [('set', 'Ladenleitung', 'kasse.storno', 'BEIDES')])

    def test_lesen_auf_keine_objekt_wird_abgelehnt(self):
        """KEINE-Objekte akzeptieren nur '' oder BEIDES, kein LESEN/PFLEGEN."""
        mod = _lade(_FakeCursor(
            objekt_unterscheidung={'kasse.storno': 'KEINE'}))
        r = mod.zelle_setzen('Ladenleitung', 'kasse.storno', 'LESEN')
        self.assertFalse(r['ok'])
        self.assertIn('unterscheidet nicht', r['msg'])
        self.assertEqual(mod._perm_calls, [])

    def test_lesen_auf_lese_pflege_erlaubt(self):
        mod = _lade(_FakeCursor(
            objekt_unterscheidung={'orga.schichtplan': 'LESE_PFLEGE'}))
        r = mod.zelle_setzen('Mitarbeiter', 'orga.schichtplan', 'LESEN')
        self.assertTrue(r['ok'])
        self.assertEqual(
            mod._perm_calls,
            [('set', 'Mitarbeiter', 'orga.schichtplan', 'LESEN')])

    def test_unbekanntes_objekt(self):
        mod = _lade(_FakeCursor(objekt_unterscheidung={}))
        r = mod.zelle_setzen('Ladenleitung', 'gibt.es.nicht', 'BEIDES')
        self.assertFalse(r['ok'])
        self.assertIn('Unbekanntes', r['msg'])

    def test_ungueltiges_recht(self):
        mod = _lade(_FakeCursor())
        r = mod.zelle_setzen('Ladenleitung', 'kasse.storno', 'SUPERUSER')
        self.assertFalse(r['ok'])
        self.assertIn('Ungueltiges', r['msg'])

    def test_leere_rolle(self):
        mod = _lade(_FakeCursor())
        r = mod.zelle_setzen('', 'kasse.storno', 'BEIDES')
        self.assertFalse(r['ok'])


if __name__ == '__main__':
    unittest.main()
