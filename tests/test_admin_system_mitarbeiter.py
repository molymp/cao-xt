"""
Unit-Tests fuer admin-app/app/system_mitarbeiter.py.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'system_mitarbeiter.py')


class _FakeCursor:

    def __init__(self, objekte=None, rechte=None):
        self._objekte = objekte or []
        self._rechte = rechte or []
        self._naechste = []

    def execute(self, sql, *args, **kwargs):
        u = sql.upper()
        if 'FROM DORFKERN_PERMISSION_OBJEKT' in u:
            self._naechste = self._objekte
        elif 'FROM DORFKERN_ROLLE_PERMISSION' in u:
            self._naechste = self._rechte
        else:
            self._naechste = []

    def fetchall(self):
        return self._naechste

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade(fake_cur, ma_liste=None):
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: fake_cur
    sys.modules['db'] = fake_db

    # cao_rechte stubben – wir interessieren uns nur fuer die
    # mitarbeiter_mit_gruppen-Funktion in system_mitarbeiter.liste()
    fake_cr = types.ModuleType('cao_rechte')
    fake_cr.mitarbeiter_mit_gruppen = lambda: ma_liste or []
    sys.modules['cao_rechte'] = fake_cr

    # common.permission stubben
    common_pkg = types.ModuleType('common')
    common_pkg.__path__ = []
    sys.modules['common'] = common_pkg
    fake_perm = types.SimpleNamespace(
        ROLLE_ADMIN='Administratoren',
    )
    sys.modules['common.permission'] = fake_perm

    sys.modules.pop('sm_test', None)
    spec = importlib.util.spec_from_file_location('sm_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ma(ma_id, login, anzeige, gruppe_name='Mitarbeiter',
        gruppe_id=5, aktiv=True):
    return {
        'MA_ID': ma_id, 'LOGIN_NAME': login,
        'ANZEIGE_NAME': anzeige,
        'GRUPPEN_ID': gruppe_id, 'GRUPPEN_NAME': gruppe_name,
        'AKTIV': aktiv,
    }


class TestMitarbeiterListe(unittest.TestCase):

    def test_keine_mitarbeiter(self):
        mod = _lade(_FakeCursor(), ma_liste=[])
        self.assertEqual(mod.liste(), [])

    def test_admin_hat_alle_rechte(self):
        objekte = [
            {'OBJEKT_KEY': 'kasse.storno', 'APP': 'KASSE'},
            {'OBJEKT_KEY': 'orga.schichtplan', 'APP': 'ORGA'},
        ]
        rechte = []   # niemand hat explizite Eintraege – Admin darf
                      # trotzdem alles (Wildcard)
        mod = _lade(_FakeCursor(objekte=objekte, rechte=rechte),
                    ma_liste=[_ma(1, 'admin', 'Admin User',
                                  gruppe_name='Administratoren')])
        liste = mod.liste()
        self.assertEqual(len(liste), 1)
        e = liste[0]
        self.assertTrue(e['ist_admin'])
        self.assertEqual(e['rechte_pro_app']['KASSE']['erlaubt'], 1)
        self.assertEqual(e['rechte_pro_app']['KASSE']['gesamt'], 1)
        self.assertEqual(e['rechte_pro_app']['ORGA']['erlaubt'], 1)
        self.assertEqual(e['rechte_pro_app']['ORGA']['gesamt'], 1)

    def test_mitarbeiter_ohne_eintrag_keine_rechte(self):
        objekte = [
            {'OBJEKT_KEY': 'kasse.storno', 'APP': 'KASSE'},
        ]
        rechte = []
        mod = _lade(_FakeCursor(objekte=objekte, rechte=rechte),
                    ma_liste=[_ma(2, 'anna', 'Anna Arbeit',
                                  gruppe_name='Mitarbeiter')])
        e = mod.liste()[0]
        self.assertFalse(e['ist_admin'])
        self.assertEqual(e['rechte_pro_app']['KASSE']['erlaubt'], 0)
        self.assertEqual(e['rechte_pro_app']['KASSE']['gesamt'], 1)

    def test_mitarbeiter_mit_teilrechten(self):
        objekte = [
            {'OBJEKT_KEY': 'kasse.zugriff', 'APP': 'KASSE'},
            {'OBJEKT_KEY': 'kasse.storno', 'APP': 'KASSE'},
            {'OBJEKT_KEY': 'kasse.einstellungen', 'APP': 'KASSE'},
        ]
        rechte = [
            {'ROLLE': 'Ladenleitung', 'OBJEKT_KEY': 'kasse.zugriff',
             'RECHT': 'BEIDES'},
            {'ROLLE': 'Ladenleitung', 'OBJEKT_KEY': 'kasse.storno',
             'RECHT': 'BEIDES'},
        ]
        mod = _lade(_FakeCursor(objekte=objekte, rechte=rechte),
                    ma_liste=[_ma(3, 'leo', 'Leo Leiter',
                                  gruppe_name='Ladenleitung')])
        e = mod.liste()[0]
        self.assertEqual(e['rechte_pro_app']['KASSE']['erlaubt'], 2)
        self.assertEqual(e['rechte_pro_app']['KASSE']['gesamt'], 3)
        detail = set(e['rechte_pro_app']['KASSE']['detail'])
        self.assertEqual(detail, {'kasse.zugriff', 'kasse.storno'})

    def test_sortierung_aktive_zuerst(self):
        mod = _lade(_FakeCursor(), ma_liste=[
            _ma(1, 'zora', 'Zora Zuletzt', aktiv=False),
            _ma(2, 'bert', 'Bert Baum',    aktiv=True),
            _ma(3, 'anna', 'Anna Apfel',   aktiv=True),
        ])
        namen = [e['anzeige_name'] for e in mod.liste()]
        # Aktive zuerst alphabetisch, dann inaktive
        self.assertEqual(namen, ['Anna Apfel', 'Bert Baum', 'Zora Zuletzt'])


if __name__ == '__main__':
    unittest.main()
