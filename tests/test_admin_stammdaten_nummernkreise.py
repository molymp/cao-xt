"""
Unit-Tests fuer admin-app/app/stammdaten_nummernkreise.py.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_nummernkreise.py')


class _FakeCursor:

    def __init__(self, schemas, registry_rows, log_count=0):
        self._schemas = schemas   # {tabelle: [spalten]}
        self._reg = registry_rows
        self._log = log_count
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
        u = sql.upper()
        if 'INFORMATION_SCHEMA' in u:
            tab = args[0][0] if args else ''
            self._naechste = [
                {'COLUMN_NAME': s}
                for s in self._schemas.get(tab.upper(), [])
            ]
        elif 'COUNT(*)' in u and 'NUMMERN_LOG' in u:
            self._naechste = [{'ANZ': self._log}]
        elif 'FROM REGISTRY' in u:
            self._naechste = self._reg
        else:
            self._naechste = []

    def fetchall(self):
        return self._naechste

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade_modul(cursor):
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: cursor
    sys.modules['db'] = fake_db
    sys.modules.pop('nk_test', None)
    spec = importlib.util.spec_from_file_location('nk_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_keine_registry(self):
        mod = _lade_modul(_FakeCursor(schemas={}, registry_rows=[]))
        res = mod.liste()
        self.assertEqual(res['eintraege'], [])
        self.assertEqual(res['log_total'], 0)

    def test_typische_nummernkreise(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'REGISTRY': ['MAINKEY', 'NAME', 'VAL_CHAR', 'VAL_INT',
                             'VAL_INT2', 'VAL_INT3', 'READONLY'],
                'NUMMERN_LOG': ['REC_ID'],
            },
            registry_rows=[
                {'NAME': 'VK-AGB',  'VAL_CHAR': '000000',
                 'VAL_INT': 1, 'VAL_INT2': 240000, 'VAL_INT3': 6,
                 'READONLY': 'N'},
                {'NAME': 'VK-RECH', 'VAL_CHAR': '000000',
                 'VAL_INT': 3, 'VAL_INT2': 240000, 'VAL_INT3': 6,
                 'READONLY': 'N'},
                {'NAME': 'EDIT',    'VAL_CHAR': '"EDI-"000000',
                 'VAL_INT': 10, 'VAL_INT2': 1000, 'VAL_INT3': 6,
                 'READONLY': 'Y'},
            ],
            log_count=42,
        ))
        res = mod.liste()
        self.assertEqual(len(res['eintraege']), 3)
        # Sortierung nach VAL_INT
        self.assertEqual(res['eintraege'][0]['key'], 'VK-AGB')
        self.assertEqual(res['eintraege'][1]['key'], 'VK-RECH')
        self.assertEqual(res['eintraege'][2]['key'], 'EDIT')
        # Attribute
        edit = res['eintraege'][2]
        self.assertEqual(edit['maske'], '"EDI-"000000')
        self.assertEqual(edit['naechste'], 1000)
        self.assertEqual(edit['laenge'], 6)
        self.assertTrue(edit['readonly'])
        # Log
        self.assertEqual(res['log_total'], 42)

    def test_keine_log_tabelle(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'REGISTRY': ['MAINKEY', 'NAME', 'VAL_CHAR', 'VAL_INT',
                             'VAL_INT2', 'VAL_INT3', 'READONLY'],
            },
            registry_rows=[
                {'NAME': 'X', 'VAL_CHAR': '0000',
                 'VAL_INT': 1, 'VAL_INT2': 100, 'VAL_INT3': 4,
                 'READONLY': 'N'},
            ],
            log_count=999,  # wird nicht angefragt, weil Tabelle fehlt
        ))
        res = mod.liste()
        self.assertEqual(len(res['eintraege']), 1)
        self.assertEqual(res['log_total'], 0)

    def test_readonly_flag_varianten(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'REGISTRY': ['NAME', 'VAL_CHAR', 'VAL_INT',
                             'VAL_INT2', 'VAL_INT3', 'READONLY'],
            },
            registry_rows=[
                {'NAME': 'A', 'READONLY': 'Y'},
                {'NAME': 'B', 'READONLY': 'N'},
                {'NAME': 'C', 'READONLY': None},
            ],
        ))
        res = mod.liste()
        self.assertTrue(res['eintraege'][0]['readonly'])
        self.assertFalse(res['eintraege'][1]['readonly'])
        self.assertFalse(res['eintraege'][2]['readonly'])


if __name__ == '__main__':
    unittest.main()
