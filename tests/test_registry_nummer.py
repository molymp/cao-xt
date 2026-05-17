"""Tests: REGISTRY-Belegnummern-Ziehung (common.einkauf).

CAO-Semantik (User-verifiziert 2026-05-17): VAL_INT2 = die als
Nächstes zu vergebende Nummer; danach +1. Delphi-Maske VAL_CHAR
(Quoted-Literal + 0-Ziffern), geteilter EDI-Zähler NAME='EDIT'.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from common.einkauf import (_format_nummernkreis,  # noqa: E402
                            _next_registry_nummer)


class TestFormatNummernkreis(unittest.TestCase):
    def test_reine_ziffernmaske(self):
        self.assertEqual(_format_nummernkreis(7418, '000000'), '007418')
        self.assertEqual(_format_nummernkreis(11040, '00000'), '11040')

    def test_laenger_als_maske_keine_kuerzung(self):
        # GoBD: niemals abschneiden.
        self.assertEqual(_format_nummernkreis(253433, '000000'),
                         '253433')

    def test_edi_quoted_literal(self):
        self.assertEqual(_format_nummernkreis(18187, '"EDI-"000000'),
                         'EDI-018187')

    def test_fallback_ohne_ziffern(self):
        self.assertEqual(_format_nummernkreis(42, 'XX'), '000042')

    def test_none_maske(self):
        self.assertEqual(_format_nummernkreis(5, None), '000005')


class TestNextRegistryNummerSemantik(unittest.TestCase):
    def _draw(self, val_int2, mask):
        cur = MagicMock()
        cur.fetchone.return_value = {'VAL_INT2': val_int2,
                                     'VAL_CHAR': mask}
        res = _next_registry_nummer(cur, 'EDIT')
        upd = [c for c in cur.execute.call_args_list
               if 'UPDATE REGISTRY' in c.args[0]][0]
        return res, upd.args[1][0]

    def test_vergibt_val_int2_as_is_nicht_plus_eins(self):
        # KEIN Off-by-one: gezogen wird genau VAL_INT2.
        nummer, gespeichert = self._draw(18187, '"EDI-"000000')
        self.assertEqual(nummer, 'EDI-018187')
        self.assertEqual(gespeichert, 18188)   # danach +1

    def test_plain_counter(self):
        nummer, gespeichert = self._draw(7418, '000000')
        self.assertEqual(nummer, '007418')
        self.assertEqual(gespeichert, 7419)

    def test_fehlender_eintrag_wirft(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        with self.assertRaises(RuntimeError):
            _next_registry_nummer(cur, 'GIBTSNICHT')


if __name__ == '__main__':
    unittest.main()
