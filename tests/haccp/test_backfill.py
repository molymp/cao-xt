"""Unit-Tests fuer modules/haccp/backfill.py und poller._auto_backfill.

Kein DB- und kein HTTP-Zugriff — alles gemockt.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from modules.haccp import backfill as bf
from modules.haccp.tfa_client import Messwert, TFAError


def _mw(device_id='AA', idx=0, minute=0, temp=5.0):
    return Messwert(
        device_id=device_id, sensor_index=idx,
        zeitpunkt_utc=datetime(2026, 4, 19, 12, minute, 0),
        temp_c=temp, feuchte_pct=None,
        battery_low=False, no_connection=False,
        transmission_counter=None,
        internal_id=None, device_name=None, mess_intervall_s=None,
    )


class TestNachholen(unittest.TestCase):
    """``bf.nachholen`` orchestriert API-Call + Persistenz."""

    def setUp(self):
        self.client = MagicMock()
        # historie() gibt per default zwei Messwerte zurueck
        self.client.historie.return_value = [
            _mw(device_id='AA', minute=1),
            _mw(device_id='BB', minute=2),
        ]

    def test_leere_device_liste_macht_keinen_api_call(self):
        gefunden, neu, fehler = bf.nachholen(
            self.client, [],
            datetime(2026, 4, 19, 12, 0), datetime(2026, 4, 19, 13, 0))
        self.assertEqual((gefunden, neu, fehler), (0, 0, []))
        self.client.historie.assert_not_called()

    def test_bis_vor_von_macht_keinen_api_call(self):
        gefunden, neu, fehler = bf.nachholen(
            self.client, ['AA'],
            datetime(2026, 4, 19, 13, 0), datetime(2026, 4, 19, 12, 0))
        self.assertEqual((gefunden, neu, fehler), (0, 0, []))
        self.client.historie.assert_not_called()

    @patch('modules.haccp.backfill.m')
    def test_happy_path_persistiert_und_zaehlt_neu(self, models):
        models.geraet_by_tfa.return_value = {'GERAET_ID': 42}
        # erster Messwert neu, zweiter dupliziert
        models.messwert_insert.side_effect = [True, False]
        gefunden, neu, fehler = bf.nachholen(
            self.client, ['AA', 'BB'],
            datetime(2026, 4, 19, 12, 0), datetime(2026, 4, 19, 13, 0))
        self.assertEqual((gefunden, neu, fehler), (2, 1, []))
        self.assertEqual(self.client.historie.call_count, 1)

    @patch('modules.haccp.backfill.m')
    def test_unbekanntes_geraet_wird_angelegt(self, models):
        models.geraet_by_tfa.return_value = None
        models.geraet_anlegen.return_value = 99
        models.messwert_insert.return_value = True
        self.client.historie.return_value = [_mw(device_id='NEU', minute=0)]
        _, _, fehler = bf.nachholen(
            self.client, ['NEU'],
            datetime(2026, 4, 19, 12, 0), datetime(2026, 4, 19, 13, 0))
        self.assertEqual(fehler, [])
        models.geraet_anlegen.assert_called_once()

    @patch('modules.haccp.backfill.m')
    def test_chunked_in_sieben_tage_bloecke(self, models):
        """Fuer 15-Tage-Zeitraum muessen 3 API-Calls fallen (7+7+1)."""
        models.geraet_by_tfa.return_value = {'GERAET_ID': 42}
        models.messwert_insert.return_value = True
        self.client.historie.return_value = []
        von = datetime(2026, 4, 1, 0, 0)
        bis = datetime(2026, 4, 16, 0, 0)   # 15 Tage
        bf.nachholen(self.client, ['AA'], von, bis)
        self.assertEqual(self.client.historie.call_count, 3)
        # Chunks duerfen sich nicht ueberlappen und muessen die Grenze respektieren
        calls = self.client.historie.call_args_list
        chunk_von_1, chunk_bis_1 = calls[0].args[1], calls[0].args[2]
        chunk_von_2, chunk_bis_2 = calls[1].args[1], calls[1].args[2]
        chunk_von_3, chunk_bis_3 = calls[2].args[1], calls[2].args[2]
        self.assertEqual(chunk_bis_1 - chunk_von_1, timedelta(days=7))
        self.assertEqual(chunk_bis_2 - chunk_von_2, timedelta(days=7))
        self.assertEqual(chunk_bis_3 - chunk_von_3, timedelta(days=1))
        self.assertEqual(chunk_bis_1, chunk_von_2)
        self.assertEqual(chunk_bis_2, chunk_von_3)
        self.assertEqual(chunk_bis_3, bis)

    @patch('modules.haccp.backfill.m')
    def test_tfa_fehler_im_chunk_blockiert_nicht_den_rest(self, models):
        models.geraet_by_tfa.return_value = {'GERAET_ID': 42}
        models.messwert_insert.return_value = True
        self.client.historie.side_effect = [
            TFAError('429 Too Many'),
            [_mw(device_id='AA', minute=0)],
        ]
        von = datetime(2026, 4, 1, 0, 0)
        bis = datetime(2026, 4, 10, 0, 0)   # 9 Tage -> 2 Chunks
        gefunden, neu, fehler = bf.nachholen(self.client, ['AA'], von, bis)
        self.assertEqual(gefunden, 1)   # nur aus dem zweiten Chunk
        self.assertEqual(neu, 1)
        self.assertEqual(len(fehler), 1)
        self.assertIn('429', fehler[0])


class TestNachholenAb(unittest.TestCase):

    @patch('modules.haccp.backfill.datetime')
    @patch('modules.haccp.backfill.m')
    def test_mini_luecke_ueberspringt(self, models, dt):
        """Wenn die Luecke < 60 s ist, soll kein API-Call fallen."""
        dt.now.return_value.replace.return_value = datetime(2026, 4, 19, 12, 0, 30)
        client = MagicMock()
        gefunden, neu, fehler = bf.nachholen_ab(
            client, ['AA'], datetime(2026, 4, 19, 12, 0, 0))
        self.assertEqual((gefunden, neu, fehler), (0, 0, []))
        client.historie.assert_not_called()

    @patch('modules.haccp.backfill.datetime')
    @patch('modules.haccp.backfill.m')
    def test_max_tage_kappt_zu_alten_startpunkt(self, models, dt):
        """Wenn von_utc > max_tage zurueck ist, auf Grenze klemmen."""
        dt.now.return_value.replace.return_value = datetime(2026, 4, 19, 12, 0)
        models.geraet_by_tfa.return_value = {'GERAET_ID': 42}
        models.messwert_insert.return_value = False
        client = MagicMock()
        client.historie.return_value = []
        # von 30 Tage zurueck, max 7 Tage -> Chunk darf bei -7 Tagen starten
        bf.nachholen_ab(client, ['AA'],
                        datetime(2026, 3, 20, 12, 0), max_tage=7)
        self.assertEqual(client.historie.call_count, 1)
        call = client.historie.call_args_list[0]
        von_arg = call.args[1]
        self.assertEqual(von_arg, datetime(2026, 4, 12, 12, 0))


class TestPollerAutoBackfill(unittest.TestCase):
    """``poller._auto_backfill`` entscheidet, OB Backfill faellt."""

    def setUp(self):
        # Poller laedt wawi-app/app/config; wir stubben vor dem Import.
        import types
        fake_config = types.ModuleType('config')
        fake_config.TFA_API_KEY = 'x'
        fake_config.TFA_BASE_URL = 'http://example'
        fake_config.DB_HOST = 'h'
        fake_config.DB_PORT = 3306
        fake_config.DB_NAME = 'n'
        fake_config.DB_USER = 'u'
        fake_config.DB_PASSWORD = 'p'
        fake_config.HACCP_POLL_INTERVALL_S = 60
        sys.modules.setdefault('config', fake_config)
        from modules.haccp import poller as p
        self.p = p

    @patch('modules.haccp.poller.bf')
    @patch('modules.haccp.poller.m')
    def test_kein_heartbeat_macht_nichts(self, models, bfmod):
        models.poller_status_lesen.return_value = None
        self.p._auto_backfill(MagicMock())
        bfmod.nachholen_ab.assert_not_called()

    @patch('modules.haccp.poller.bf')
    @patch('modules.haccp.poller.m')
    def test_frischer_heartbeat_macht_nichts(self, models, bfmod):
        models.poller_status_lesen.return_value = {
            'LAST_SUCCESS_AT': datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
        }
        self.p._auto_backfill(MagicMock())
        bfmod.nachholen_ab.assert_not_called()

    @patch('modules.haccp.poller.bf')
    @patch('modules.haccp.poller.m')
    def test_alter_heartbeat_triggert_backfill(self, models, bfmod):
        last_ok = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        models.poller_status_lesen.return_value = {'LAST_SUCCESS_AT': last_ok}
        models.geraete_liste.return_value = [
            {'TFA_DEVICE_ID': 'AA'}, {'TFA_DEVICE_ID': 'BB'},
            {'TFA_DEVICE_ID': None},  # ohne ID wird uebersprungen
        ]
        bfmod.MAX_TAGE_PRO_CALL = 7
        bfmod.nachholen_ab.return_value = (123, 42, [])
        client = MagicMock()
        self.p._auto_backfill(client)
        bfmod.nachholen_ab.assert_called_once()
        args, kwargs = bfmod.nachholen_ab.call_args
        self.assertIs(args[0], client)
        self.assertEqual(sorted(args[1]), ['AA', 'BB'])
        self.assertEqual(args[2], last_ok)
        self.assertEqual(kwargs['max_tage'], 7)

    @patch('modules.haccp.poller.bf')
    @patch('modules.haccp.poller.m')
    def test_alter_heartbeat_ohne_sensoren_macht_nichts(self, models, bfmod):
        models.poller_status_lesen.return_value = {
            'LAST_SUCCESS_AT': datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
        }
        models.geraete_liste.return_value = []
        self.p._auto_backfill(MagicMock())
        bfmod.nachholen_ab.assert_not_called()


if __name__ == '__main__':
    unittest.main()
