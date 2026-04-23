"""
Unit-Tests fuer common/terminal_selbstregistrierung.py
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import terminal_selbstregistrierung as _tsr  # noqa: E402


class TestSelbstRegistrieren(unittest.TestCase):
    def test_bekanntes_terminal_aktualisiert_nur_kontakt(self):
        bekannt = {'TERMINAL_ID': 42, 'BEZEICHNUNG': 'Kasse 1'}
        with patch.object(_tsr._terminal, 'hostname',
                          return_value='pos-01'), \
             patch.object(_tsr._terminal, 'mac_adresse',
                          return_value='AA:BB:CC:DD:EE:FF'), \
             patch.object(_tsr._terminal, 'lokale_ip',
                          return_value='10.0.0.7'), \
             patch.object(_tsr._terminal, 'erkenne',
                          return_value=bekannt), \
             patch.object(_tsr._terminal,
                          'setze_letzten_kontakt') as m_kontakt, \
             patch.object(_tsr._terminal, 'anlegen') as m_anlegen:
            tid = _tsr.selbst_registrieren('KASSE')
        self.assertEqual(tid, 42)
        m_kontakt.assert_called_once_with(42, ip='10.0.0.7')
        m_anlegen.assert_not_called()

    def test_unbekannt_wird_neu_angelegt(self):
        with patch.object(_tsr._terminal, 'hostname',
                          return_value='kiosk-3'), \
             patch.object(_tsr._terminal, 'mac_adresse',
                          return_value=''), \
             patch.object(_tsr._terminal, 'lokale_ip',
                          return_value='10.0.0.9'), \
             patch.object(_tsr._terminal, 'erkenne', return_value=None), \
             patch.object(_tsr._terminal, 'anlegen', return_value=77), \
             patch.object(_tsr._terminal,
                          'setze_letzten_kontakt') as m_kontakt:
            tid = _tsr.selbst_registrieren('KIOSK')
        self.assertEqual(tid, 77)
        m_kontakt.assert_called_once_with(77, ip='10.0.0.9')

    def test_default_bezeichnung(self):
        captured = {}

        def _anlegen(**kwargs):
            captured.update(kwargs)
            return 5
        with patch.object(_tsr._terminal, 'hostname',
                          return_value='host-xyz'), \
             patch.object(_tsr._terminal, 'mac_adresse', return_value=''), \
             patch.object(_tsr._terminal, 'lokale_ip', return_value=''), \
             patch.object(_tsr._terminal, 'erkenne', return_value=None), \
             patch.object(_tsr._terminal, 'anlegen', side_effect=_anlegen), \
             patch.object(_tsr._terminal, 'setze_letzten_kontakt'):
            _tsr.selbst_registrieren('ORGA')
        self.assertIn('host-xyz', captured['bezeichnung'])
        self.assertEqual(captured['typ'], 'ORGA')

    def test_fail_soft_bei_exception(self):
        with patch.object(_tsr._terminal, 'hostname',
                          side_effect=RuntimeError('boom')):
            # Muss None zurueckgeben, NICHT exception weiterwerfen
            self.assertIsNone(_tsr.selbst_registrieren('KASSE'))


if __name__ == '__main__':
    unittest.main()
