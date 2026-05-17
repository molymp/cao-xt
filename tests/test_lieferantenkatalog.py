"""Tests für den festen Kramer-Lieferantenkatalog-Parser."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from modules.orga.lieferantenkatalog.parser_kramer import (  # noqa: E402
    parse_kramer_xlsx, _norm_header)


def _xlsx(rows, sheet='Wurm'):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    wb.save(path)
    return path


# Kramer-Layout: Zeile0 Vor-Header, Zeile1 Header (Zahlen-Präfixe,
# 'EAN' doppelt = Label- + Wertspalte), ab Zeile2 Daten.
_HEADER = ['5- Kategorie', 'Artikel-Nr', '7 Kurzbeschreibung',
           'Artikelname', '2 Name', 'Gebinde', 'EK NETTO',
           '6- Beschreibung', 'Ust-Satz', ' Empfohlener Preis (LVP) ',
           'EAN', 'EAN', 'Liefermenge min.', 'Handelsklasse',
           'Produktbild Link']


class TestKramerParser(unittest.TestCase):
    def _parse(self, datenzeilen):
        path = _xlsx([['vor', None], _HEADER, *datenzeilen])
        try:
            return parse_kramer_xlsx(path)
        finally:
            os.unlink(path)

    def test_norm_header(self):
        self.assertEqual(_norm_header('5- Kategorie'), 'kategorie')
        self.assertEqual(_norm_header(' Empfohlener Preis (LVP) '),
                         'empfohlener preis (lvp)')
        self.assertEqual(_norm_header('EK NETTO'), 'ek netto')

    def test_kernfelder_und_typen(self):
        b = self._parse([
            ['Marke X', 3001, 'Naturseifen', 'Moorseife',
             'Moorseife 100g', 'ca. 100g', 3.95, 'UVP: 7,9 …',
             '19', '7,9', 'EAN: ', 'N/A', 1, 'Saulgrub',
             'http://bild/1.jpg'],
        ])
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]['marke'], 'Wurm')
        p = b[0]['positionen'][0]
        self.assertEqual(p['lief_art_nr'], '3001')
        # „Artikelname"-Spalte (col3 'Moorseife') wird IGNORIERT;
        # primärer Name = „2 Name" (col4).
        self.assertEqual(p['artikelname'], 'Moorseife 100g')
        self.assertNotIn('name_lang', p)
        self.assertEqual(p['ek_netto'], 3.95)
        self.assertEqual(p['ust_satz'], 19.0)
        self.assertEqual(p['vk_empf'], 7.9)        # „7,9" → 7.9
        self.assertEqual(p['ean'], 'N/A')          # letzte EAN-Spalte
        self.assertEqual(p['menge_min'], 1.0)
        self.assertEqual(p['bild_url'], 'http://bild/1.jpg')

    def test_unzuverlaessige_header_nicht_gemappt(self):
        # 'Handelsklasse' (Kramer-Label/Wert-Müll) darf NICHT als
        # Strukturfeld auftauchen.
        p = self._parse([['K', 1, 'a', 'b', 'c', 'd', 1.0, 'x',
                          '7', '1,0', 'EAN:', '123', 2, 'Saulgrub',
                          '']])[0]['positionen'][0]
        self.assertNotIn('handelsklasse', p)
        self.assertNotIn('einheit', p)

    def test_zeile_ohne_artikelnr_wird_aufgenommen(self):
        # Ohne Art-Nr aber mit Name → aufnehmen, stabiler ~Key.
        # Ohne Art-Nr UND ohne Name → echte Leerzeile, überspringen.
        b = self._parse([
            ['K', '', 'a', 'b', 'Sonderposten 1', 'd', 1.0, 'x', '7',
             '1', 'E', '1', 1, 's', ''],
            ['K', '', '', '', '', '', None, '', '', '', '', '', None,
             '', ''],
            ['K', 4002, 'a', 'Reg', 'Reg lang', 'd', 2.0, 'x', '7',
             '1', 'E', '2', 1, 's', ''],
        ])
        ps = b[0]['positionen']
        self.assertEqual(len(ps), 2)               # Leerzeile raus
        ohne = next(p for p in ps if p.get('ohne_liefnr'))
        self.assertTrue(ohne['lief_art_nr'].startswith('~'))
        self.assertEqual(ohne['artikelname'], 'Sonderposten 1')
        mit = next(p for p in ps if p['lief_art_nr'] == '4002')
        self.assertFalse(mit.get('ohne_liefnr'))

    def test_synthetik_key_stabil(self):
        a = self._parse([['K', '', 'a', 'b', 'Same', 'Stk', 1.0, 'x',
                           '7', '1', 'E', '1', 1, 's', '']])
        b = self._parse([['K', '', 'a', 'b', 'Same', 'Stk', 9.9, 'x',
                           '7', '2', 'E', '1', 1, 's', '']])
        # gleicher Name+Gebinde+Marke → gleicher Key (Preis egal).
        self.assertEqual(a[0]['positionen'][0]['lief_art_nr'],
                         b[0]['positionen'][0]['lief_art_nr'])

    def test_leeres_blatt_ignoriert(self):
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.title = 'Leer'
        fd, path = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        wb.save(path)
        try:
            self.assertEqual(parse_kramer_xlsx(path), [])
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
