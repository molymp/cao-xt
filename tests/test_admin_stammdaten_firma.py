"""
Unit-Tests fuer admin-app/app/stammdaten_firma.py.

Tests decken ab:
- Leere Tabelle -> None (statt Fehler)
- Gruppierung der Felder nach Bereich
- Memo-Felder (KOPFTEXT/FUSSTEXT) als Bytes werden dekodiert
- Bank-Dict nur bei gesetzten Feldern (None sonst)
- Logo-BLOBs werden nur als 'vorhanden + Groesse' gemeldet
- Spalten, die in dieser DB fehlen (alte CAO-Version), fuehren nicht
  zum Fehler
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_firma.py')


class _FakeCursor:
    """Fake-Cursor, der je nach SQL unterschiedliche Rows liefert.

    - INFORMATION_SCHEMA -> schema_spalten (als COLUMN_NAME-Dicts)
    - OCTET_LENGTH       -> bild_laengen (als 1-Row-Dict)
    - sonst              -> daten_rows
    """

    def __init__(self, schema_spalten, daten_rows, bild_laengen=None):
        self._schema = [{'COLUMN_NAME': s} for s in schema_spalten]
        self._daten = daten_rows
        self._bilder = [bild_laengen] if bild_laengen else []
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
        u = sql.upper()
        if 'INFORMATION_SCHEMA' in u:
            self._naechste = self._schema
        elif 'OCTET_LENGTH' in u:
            self._naechste = self._bilder
        else:
            self._naechste = self._daten

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
    sys.modules.pop('firma_test', None)
    spec = importlib.util.spec_from_file_location('firma_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_VOLLES_SCHEMA = [
    'REC_ID',
    'ANREDE', 'NAME1', 'NAME2', 'NAME3',
    'GESCHAEFTSFUEHRER', 'GERICHT',
    'HRANUMMER', 'HRBNUMMER', 'WID', 'EORI', 'UID',
    'STRASSE', 'HAUSNR', 'ADRESSZUSATZ', 'LAND', 'PLZ', 'ORT',
    'VORWAHL', 'TELEFON1', 'TELEFON2', 'MOBILFUNK', 'FAX',
    'EMAIL', 'WEBSEITE',
    'STEUERNUMMER', 'UST_ID', 'SEPA_GID',
    'BANK1_BLZ', 'BANK1_KONTONR', 'BANK1_NAME', 'BANK1_IBAN',
    'BANK1_SWIFT', 'BANK1_KONTOINHABER',
    'BANK2_BLZ', 'BANK2_KONTONR', 'BANK2_NAME', 'BANK2_IBAN',
    'BANK2_SWIFT', 'BANK2_KONTOINHABER',
    'KOPFTEXT', 'FUSSTEXT', 'ABSENDER',
    'FREITEXT1', 'FREITEXT2',
    'IMAGE1', 'IMAGE2', 'IMAGE3',
]


class TestFirma(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor(_VOLLES_SCHEMA, []))
        self.assertIsNone(mod.firma())

    def test_komplettes_mapping(self):
        daten = [{
            'REC_ID': 1,
            'ANREDE': 'Firma',
            'NAME1': 'Muster GmbH',
            'NAME2': 'Zusatz',
            'NAME3': '',
            'GESCHAEFTSFUEHRER': 'Erika Mustermann',
            'GERICHT': 'AG Musterstadt',
            'HRANUMMER': '',
            'HRBNUMMER': 'HRB 12345',
            'WID': '',
            'EORI': 'DE12345',
            'UID': '',
            'STRASSE': 'Hauptstr.',
            'HAUSNR': '1',
            'ADRESSZUSATZ': 'c/o Verwaltung',
            'LAND': 'DE',
            'PLZ': '12345',
            'ORT': 'Musterstadt',
            'VORWAHL': '+49',
            'TELEFON1': '30 1234567',
            'TELEFON2': '',
            'MOBILFUNK': '',
            'FAX': '',
            'EMAIL': 'info@muster.de',
            'WEBSEITE': 'https://muster.de',
            'STEUERNUMMER': '12/345/67890',
            'UST_ID': 'DE123456789',
            'SEPA_GID': 'DE98ZZZ09999999999',
            'BANK1_BLZ': '', 'BANK1_KONTONR': '',
            'BANK1_NAME': 'Sparkasse', 'BANK1_IBAN': 'DE12500105170648489890',
            'BANK1_SWIFT': 'INGDDEFF',
            'BANK1_KONTOINHABER': 'Muster GmbH',
            'BANK2_BLZ': '', 'BANK2_KONTONR': '',
            'BANK2_NAME': '', 'BANK2_IBAN': '', 'BANK2_SWIFT': '',
            'BANK2_KONTOINHABER': '',
            'KOPFTEXT': 'Ihr Fachhaendler',
            'FUSSTEXT': 'Mit freundlichen Gruessen',
            'ABSENDER': 'Muster GmbH · 12345 Musterstadt',
            'FREITEXT1': 'Frei 1',
            'FREITEXT2': '',
        }]
        mod = _lade_modul(_FakeCursor(
            _VOLLES_SCHEMA, daten,
            bild_laengen={'IMAGE1_LEN': 12345,
                          'IMAGE2_LEN': 0, 'IMAGE3_LEN': None}))
        f = mod.firma()
        self.assertEqual(f['id'], 1)
        self.assertEqual(f['basis']['name1'], 'Muster GmbH')
        self.assertEqual(f['basis']['geschaeftsfuehrer'], 'Erika Mustermann')
        self.assertEqual(f['basis']['hrbnummer'], 'HRB 12345')
        self.assertEqual(f['adresse']['strasse'], 'Hauptstr.')
        self.assertEqual(f['adresse']['hausnr'], '1')
        self.assertEqual(f['adresse']['land'], 'DE')
        self.assertEqual(f['kontakt']['email'], 'info@muster.de')
        self.assertEqual(f['steuern']['ust_id'], 'DE123456789')
        self.assertEqual(f['steuern']['sepa_gid'], 'DE98ZZZ09999999999')
        # Bank1 gesetzt, Bank2 leer -> None
        self.assertIsNotNone(f['banken'][0])
        self.assertEqual(f['banken'][0]['iban'], 'DE12500105170648489890')
        self.assertEqual(f['banken'][0]['name'], 'Sparkasse')
        self.assertIsNone(f['banken'][1])
        # Formular-Texte
        self.assertEqual(f['formular']['kopftext'], 'Ihr Fachhaendler')
        self.assertEqual(f['formular']['fusstext'],
                         'Mit freundlichen Gruessen')
        # Freitexte (Liste)
        self.assertEqual(f['freitexte'], ['Frei 1', ''])
        # Logos
        by_name = {l['name']: l for l in f['logos']}
        self.assertTrue(by_name['IMAGE1']['vorhanden'])
        self.assertEqual(by_name['IMAGE1']['bytes'], 12345)
        self.assertFalse(by_name['IMAGE2']['vorhanden'])
        self.assertEqual(by_name['IMAGE2']['bytes'], 0)
        self.assertFalse(by_name['IMAGE3']['vorhanden'])

    def test_memos_als_bytes(self):
        mod = _lade_modul(_FakeCursor(
            _VOLLES_SCHEMA,
            [{'REC_ID': 1,
              'KOPFTEXT': 'Bytestext'.encode('utf-8'),
              'FUSSTEXT': None}],
            bild_laengen={'IMAGE1_LEN': 0,
                          'IMAGE2_LEN': 0, 'IMAGE3_LEN': 0}))
        f = mod.firma()
        self.assertEqual(f['formular']['kopftext'], 'Bytestext')
        self.assertEqual(f['formular']['fusstext'], '')

    def test_fehlende_spalten_werden_ignoriert(self):
        """Alte CAO-DB: EORI und WID fehlen komplett."""
        schema = [s for s in _VOLLES_SCHEMA if s not in ('EORI', 'WID')]
        mod = _lade_modul(_FakeCursor(
            schema,
            [{'REC_ID': 1, 'NAME1': 'Alt-DB GmbH'}],
            bild_laengen={'IMAGE1_LEN': 0,
                          'IMAGE2_LEN': 0, 'IMAGE3_LEN': 0}))
        f = mod.firma()
        self.assertEqual(f['basis']['name1'], 'Alt-DB GmbH')
        # Nicht vorhandene Spalten -> leerer String
        self.assertEqual(f['basis']['eori'], '')
        self.assertEqual(f['basis']['wid'], '')

    def test_bank2_teilweise_befuellt(self):
        """Bank2 hat nur einen IBAN -> Dict wird zurueckgegeben."""
        mod = _lade_modul(_FakeCursor(
            _VOLLES_SCHEMA,
            [{'REC_ID': 1,
              'BANK2_IBAN': 'DE22222222222222222222'}],
            bild_laengen={'IMAGE1_LEN': 0,
                          'IMAGE2_LEN': 0, 'IMAGE3_LEN': 0}))
        f = mod.firma()
        self.assertIsNone(f['banken'][0])
        self.assertIsNotNone(f['banken'][1])
        self.assertEqual(f['banken'][1]['iban'],
                         'DE22222222222222222222')

    def test_kein_image_spalten_in_db(self):
        """Sehr alte DB ohne IMAGE-Spalten -> Logos alle vorhanden=False."""
        schema = [s for s in _VOLLES_SCHEMA if not s.startswith('IMAGE')]
        mod = _lade_modul(_FakeCursor(schema, [{'REC_ID': 1}]))
        f = mod.firma()
        self.assertEqual(len(f['logos']), 3)
        for l in f['logos']:
            self.assertFalse(l['vorhanden'])
            self.assertEqual(l['bytes'], 0)


if __name__ == '__main__':
    unittest.main()
