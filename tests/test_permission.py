"""
Unit-Tests fuer common/permission.py

Keine echte DB – alle DB-Zugriffe werden gemockt.
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import permission  # noqa: E402


def _cur(fetchone=None, fetchall=None, rowcount=1):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall if fetchall is not None else []
    cur.rowcount = rowcount
    return cur


def _ctxmgr(cur):
    @contextmanager
    def _cm():
        yield cur
    return _cm


class TestDecktAb(unittest.TestCase):
    """Die Matrix aus _DECKT_AB ist der Kern des Rechtemodells."""

    def test_lesen_deckt_nur_lesen(self):
        self.assertEqual(permission._DECKT_AB['LESEN'],
                         frozenset({'LESEN'}))

    def test_pflegen_deckt_nur_pflegen_strikt(self):
        # Strikt: PFLEGEN deckt NICHT LESEN ab.
        self.assertNotIn('LESEN', permission._DECKT_AB['PFLEGEN'])
        self.assertIn('PFLEGEN', permission._DECKT_AB['PFLEGEN'])

    def test_beides_deckt_alles(self):
        self.assertEqual(
            permission._DECKT_AB['BEIDES'],
            frozenset({'LESEN', 'PFLEGEN', 'BEIDES'}))


class TestRolleVon(unittest.TestCase):
    def test_leere_ma_id(self):
        self.assertIsNone(permission.rolle_von(0))
        self.assertIsNone(permission.rolle_von(None))

    def test_treffer(self):
        cur = _cur(fetchone={'rolle': 'Administratoren'})
        with patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertEqual(permission.rolle_von(42), 'Administratoren')
        # Geprueft: Query nutzt BENUTZERRECHTE-Self-Join-Muster
        sql = cur.execute.call_args.args[0]
        self.assertIn('BENUTZERRECHTE', sql)
        self.assertIn('USER_ID     = -1', sql)
        self.assertEqual(cur.execute.call_args.args[1], (42,))

    def test_kein_treffer(self):
        cur = _cur(fetchone=None)
        with patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertIsNone(permission.rolle_von(99))

    def test_db_fehler_fail_closed(self):
        @contextmanager
        def boom():
            raise RuntimeError('kein DB')
            yield  # pragma: no cover
        with patch.object(permission, 'get_db', boom):
            self.assertIsNone(permission.rolle_von(1))


class TestHatRecht(unittest.TestCase):
    def test_ungueltiges_recht(self):
        self.assertFalse(permission.hat_recht(1, 'x', recht='MAYBE'))

    def test_admin_wildcard(self):
        with patch.object(permission, 'rolle_von',
                          return_value='Administratoren'):
            # Kein DB-Lookup benoetigt
            self.assertTrue(permission.hat_recht(1, 'kiosk.backwaren'))
            self.assertTrue(
                permission.hat_recht(1, 'orga.schichtplan', recht='PFLEGEN'))

    def test_unbekannte_rolle(self):
        with patch.object(permission, 'rolle_von', return_value=None):
            self.assertFalse(permission.hat_recht(1, 'kiosk.backwaren'))

    def test_kein_eintrag(self):
        cur = _cur(fetchone=None)
        with patch.object(permission, 'rolle_von',
                          return_value='Mitarbeiter'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertFalse(permission.hat_recht(1, 'kiosk.backwaren'))

    def test_beides_deckt_lesen_und_pflegen(self):
        cur = _cur(fetchone={'RECHT': 'BEIDES'})
        with patch.object(permission, 'rolle_von',
                          return_value='Ladenleitung'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertTrue(permission.hat_recht(1, 'orga.schichtplan',
                                                 recht='LESEN'))
        cur = _cur(fetchone={'RECHT': 'BEIDES'})
        with patch.object(permission, 'rolle_von',
                          return_value='Ladenleitung'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertTrue(permission.hat_recht(1, 'orga.schichtplan',
                                                 recht='PFLEGEN'))

    def test_pflegen_impliziert_nicht_lesen(self):
        cur = _cur(fetchone={'RECHT': 'PFLEGEN'})
        with patch.object(permission, 'rolle_von',
                          return_value='Ladenleitung'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertFalse(permission.hat_recht(1, 'orga.schichtplan',
                                                  recht='LESEN'))

    def test_lesen_gewaehrt_nur_lesen(self):
        cur = _cur(fetchone={'RECHT': 'LESEN'})
        with patch.object(permission, 'rolle_von',
                          return_value='Mitarbeiter'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertTrue(permission.hat_recht(1, 'orga.schichtplan',
                                                 recht='LESEN'))
            self.assertFalse(permission.hat_recht(1, 'orga.schichtplan',
                                                  recht='PFLEGEN'))

    def test_db_fehler_fail_closed(self):
        @contextmanager
        def boom():
            raise RuntimeError('db weg')
            yield  # pragma: no cover
        with patch.object(permission, 'rolle_von',
                          return_value='Mitarbeiter'), \
             patch.object(permission, 'get_db', boom):
            self.assertFalse(permission.hat_recht(1, 'kiosk.zugriff'))


class TestErlaubteObjekte(unittest.TestCase):
    def test_keine_rolle(self):
        with patch.object(permission, 'rolle_von', return_value=None):
            self.assertEqual(permission.erlaubte_objekte(1), [])

    def test_admin_bekommt_alle(self):
        cur = _cur(fetchall=[{'OBJEKT_KEY': 'kiosk.zugriff'},
                             {'OBJEKT_KEY': 'kasse.zugriff'}])
        with patch.object(permission, 'rolle_von',
                          return_value='Administratoren'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            self.assertEqual(
                permission.erlaubte_objekte(1),
                ['kiosk.zugriff', 'kasse.zugriff'])
        sql = cur.execute.call_args.args[0]
        self.assertIn('DORFKERN_PERMISSION_OBJEKT', sql)
        self.assertNotIn('DORFKERN_ROLLE_PERMISSION', sql)

    def test_admin_mit_app_filter(self):
        cur = _cur(fetchall=[{'OBJEKT_KEY': 'kiosk.zugriff'}])
        with patch.object(permission, 'rolle_von',
                          return_value='Administratoren'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            permission.erlaubte_objekte(1, app='KIOSK')
        sql, params = cur.execute.call_args.args
        self.assertIn('WHERE APP = %s', sql)
        self.assertEqual(params, ('KIOSK',))

    def test_nicht_admin_join_auf_rolle_permission(self):
        cur = _cur(fetchall=[{'OBJEKT_KEY': 'kiosk.backwaren'}])
        with patch.object(permission, 'rolle_von',
                          return_value='Mitarbeiter'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            permission.erlaubte_objekte(1)
        sql, params = cur.execute.call_args.args
        self.assertIn('DORFKERN_ROLLE_PERMISSION', sql)
        self.assertEqual(params, ('Mitarbeiter',))

    def test_nicht_admin_mit_app_filter(self):
        cur = _cur(fetchall=[])
        with patch.object(permission, 'rolle_von',
                          return_value='Mitarbeiter'), \
             patch.object(permission, 'get_db', _ctxmgr(cur)):
            permission.erlaubte_objekte(1, app='ORGA')
        sql, params = cur.execute.call_args.args
        self.assertIn('po.APP = %s', sql)
        self.assertEqual(params, ('Mitarbeiter', 'ORGA'))


class TestSeedObjekte(unittest.TestCase):
    def test_zaehlt_rowcount(self):
        # 10 Seeds → 10 INSERT IGNORE-Aufrufe.
        cur = _cur(rowcount=1)
        with patch.object(permission, 'get_db_transaction', _ctxmgr(cur)):
            n = permission.seed_objekte()
        self.assertEqual(n, len(permission._SEED_OBJEKTE))
        self.assertEqual(cur.execute.call_count,
                         len(permission._SEED_OBJEKTE))

    def test_bereits_vorhanden(self):
        # rowcount=0 → nichts neu
        cur = _cur(rowcount=0)
        with patch.object(permission, 'get_db_transaction', _ctxmgr(cur)):
            n = permission.seed_objekte()
        self.assertEqual(n, 0)

    def test_katalog_enthaelt_pflichtkeys(self):
        keys = {row[0] for row in permission._SEED_OBJEKTE}
        for must in ('kiosk.zugriff', 'kasse.zugriff',
                     'orga.zugriff', 'orga.schichtplan'):
            self.assertIn(must, keys)

    def test_schichtplan_hat_lese_pflege_trennung(self):
        for key, _app, _bez, _beschr, unt in permission._SEED_OBJEKTE:
            if key == 'orga.schichtplan':
                self.assertEqual(unt, 'LESE_PFLEGE')
                return
        self.fail('orga.schichtplan fehlt im Seed-Katalog')


class TestSetRollePermission(unittest.TestCase):
    def test_ungueltiges_recht_raises(self):
        with self.assertRaises(ValueError):
            permission.set_rolle_permission(
                'Mitarbeiter', 'kiosk.zugriff', 'MAYBE')

    def test_admin_wird_ignoriert(self):
        cur = _cur()
        with patch.object(permission, 'get_db_transaction', _ctxmgr(cur)):
            permission.set_rolle_permission(
                'Administratoren', 'kiosk.zugriff', 'BEIDES')
        cur.execute.assert_not_called()

    def test_upsert(self):
        cur = _cur()
        with patch.object(permission, 'get_db_transaction', _ctxmgr(cur)):
            permission.set_rolle_permission(
                'Ladenleitung', 'orga.schichtplan', 'BEIDES')
        sql, params = cur.execute.call_args.args
        self.assertIn('ON DUPLICATE KEY UPDATE', sql)
        self.assertEqual(
            params, ('Ladenleitung', 'orga.schichtplan', 'BEIDES'))


class TestLoescheRollePermission(unittest.TestCase):
    def test_delete(self):
        cur = _cur()
        with patch.object(permission, 'get_db_transaction', _ctxmgr(cur)):
            permission.loesche_rolle_permission(
                'Mitarbeiter', 'kasse.storno')
        sql, params = cur.execute.call_args.args
        self.assertIn('DELETE FROM DORFKERN_ROLLE_PERMISSION', sql)
        self.assertEqual(params, ('Mitarbeiter', 'kasse.storno'))


class TestObjekteAlle(unittest.TestCase):
    def test_ohne_filter(self):
        cur = _cur(fetchall=[{'OBJEKT_KEY': 'x', 'APP': 'KIOSK'}])
        with patch.object(permission, 'get_db', _ctxmgr(cur)):
            rows = permission.objekte_alle()
        self.assertEqual(len(rows), 1)
        sql = cur.execute.call_args.args[0]
        self.assertNotIn('WHERE', sql)

    def test_mit_app_filter(self):
        cur = _cur(fetchall=[])
        with patch.object(permission, 'get_db', _ctxmgr(cur)):
            permission.objekte_alle(app='KIOSK')
        sql, params = cur.execute.call_args.args
        self.assertIn('WHERE APP = %s', sql)
        self.assertEqual(params, ('KIOSK',))


class TestRollePermissions(unittest.TestCase):
    def test_admin_liefert_leer(self):
        # Kein DB-Lookup noetig
        self.assertEqual(
            permission.rolle_permissions('Administratoren'), {})

    def test_mapping(self):
        cur = _cur(fetchall=[
            {'OBJEKT_KEY': 'kiosk.zugriff',   'RECHT': 'BEIDES'},
            {'OBJEKT_KEY': 'orga.schichtplan', 'RECHT': 'LESEN'},
        ])
        with patch.object(permission, 'get_db', _ctxmgr(cur)):
            got = permission.rolle_permissions('Mitarbeiter')
        self.assertEqual(got, {'kiosk.zugriff': 'BEIDES',
                               'orga.schichtplan': 'LESEN'})


if __name__ == '__main__':
    unittest.main()
