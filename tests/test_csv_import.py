"""Tests für den CSV-Import der WaWi-App (HAB-52).

Geprüfte Anforderungen:
- csv_import_vorschau(): Parst gültige und ungültige CSV-Zeilen
- Semikolon-Trennzeichen, DE-Zahlenformat (Komma als Dezimal)
- Validierung: Artikelnummer muss in CAO-DB vorhanden sein
- Ungültige EK-Preise werden als Fehler gemeldet
- Leerzeilen werden übersprungen
- Encoding: UTF-8 und Latin-1 werden erkannt
- csv_import_ausfuehren(): INSERTs in WAWI_PREISHISTORIE, Import-Log-Eintrag
- GoBD: kein UPDATE/DELETE
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Simulierte CAO-Artikeldaten (Art.-Nr. → Row)
_CAO_ARTIKEL = {
    '4711': {'artikel_id': 100, 'art_nr': '4711', 'bezeichnung': 'Testbrot', 'mwst_satz': 7.0},
    '8899': {'artikel_id': 200, 'art_nr': '8899', 'bezeichnung': 'Butter',   'mwst_satz': 7.0},
    'WEIN': {'artikel_id': 300, 'art_nr': 'WEIN', 'bezeichnung': 'Rotwein',  'mwst_satz': 19.0},
}


def _setup_stubs_csv():
    _stub_module('config',
                 CAO_DB_HOST='localhost', CAO_DB_PORT=3306,
                 CAO_DB_NAME='test', CAO_DB_USER='test', CAO_DB_PASSWORD='test',
                 WAWI_DB_HOST='localhost', WAWI_DB_PORT=3306,
                 WAWI_DB_NAME='cao_wawi', WAWI_DB_USER='test', WAWI_DB_PASSWORD='test',
                 WAWI_BENUTZER_DEFAULT='wawi')

    db_mod = _stub_module(
        'db',
        get_cao_db=MagicMock(),
        get_wawi_db=MagicMock(),
        get_wawi_transaction=MagicMock(),
        de_zu_float=lambda v: float(str(v).strip().replace(',', '.')),
    )
    return db_mod


def _make_ctx(cursor):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _import_preise_csv():
    for mod in ('preise', 'db', 'config'):
        sys.modules.pop(mod, None)

    db_mod = _setup_stubs_csv()

    WAWI_APP = (
        '/Volumes/MacDisk01/ml/.paperclip/instances/default/workspaces/'
        'bddd7c2d-0bec-47a5-a435-33ba5645bf8e/cao-xt/wawi-app/app'
    )
    if WAWI_APP not in sys.path:
        sys.path.insert(0, WAWI_APP)

    import preise  # noqa: PLC0415

    # _artikel_by_artnr() patchen: gibt unsere Testdaten zurück
    preise._artikel_by_artnr = lambda: _CAO_ARTIKEL.copy()

    return preise, db_mod


# ---------------------------------------------------------------------------
# 1 – csv_import_vorschau: Parsing
# ---------------------------------------------------------------------------

class TestCsvVorschauParsing:

    def _vorschau(self, inhalt: str, encoding='utf-8'):
        preise, db = _import_preise_csv()
        return preise.csv_import_vorschau(inhalt.encode(encoding), preisgruppe_id=1)

    def test_gueltige_zeile_wird_erkannt(self):
        result = self._vorschau('4711;1,50\n')
        assert result['ok_count'] == 1
        assert result['err_count'] == 0
        assert result['zeilen'][0]['art_nr'] == '4711'
        assert result['zeilen'][0]['ek_neu'] == pytest.approx(1.50)
        assert result['zeilen'][0]['mwst_satz'] == 7.0

    def test_bezeichnung_optional(self):
        """Dritte Spalte (Bezeichnung) ist optional."""
        result = self._vorschau('4711;2,00;Neuer Testname\n')
        assert result['ok_count'] == 1
        assert result['zeilen'][0]['bezeichnung'] == 'Neuer Testname'

    def test_bezeichnung_fehlt_nutzt_cao_name(self):
        """Ohne Bezeichnung: CAO-DB-Bezeichnung wird verwendet."""
        result = self._vorschau('4711;2,00\n')
        assert result['zeilen'][0]['bezeichnung'] == 'Testbrot'

    def test_mehrere_zeilen(self):
        csv_text = '4711;1,50\n8899;0,75\nWEIN;3,20\n'
        result = self._vorschau(csv_text)
        assert result['ok_count'] == 3
        assert result['err_count'] == 0

    def test_unbekannte_artikelnummer_ist_fehler(self):
        result = self._vorschau('UNBEKANNT;1,50\n')
        assert result['ok_count'] == 0
        assert result['err_count'] == 1
        assert 'UNBEKANNT' in result['fehler'][0]['grund']

    def test_ungültiger_ek_preis_ist_fehler(self):
        result = self._vorschau('4711;KEIN_PREIS\n')
        assert result['err_count'] == 1

    def test_ek_null_ist_fehler(self):
        result = self._vorschau('4711;0\n')
        assert result['err_count'] == 1

    def test_ek_negativ_ist_fehler(self):
        result = self._vorschau('4711;-1,50\n')
        assert result['err_count'] == 1

    def test_leerzeile_wird_uebersprungen(self):
        result = self._vorschau('4711;1,50\n\n8899;0,75\n')
        assert result['ok_count'] == 2

    def test_gemischt_ok_und_fehler(self):
        csv_text = '4711;1,50\nUNBEKANNT;2,00\n8899;0,75\n'
        result = self._vorschau(csv_text)
        assert result['ok_count'] == 2
        assert result['err_count'] == 1

    def test_en_dezimalformat_wird_auch_akzeptiert(self):
        """Punkt als Dezimaltrennzeichen (EN-Format) wird toleriert."""
        result = self._vorschau('4711;1.50\n')
        assert result['ok_count'] == 1
        assert result['zeilen'][0]['ek_neu'] == pytest.approx(1.50)


# ---------------------------------------------------------------------------
# 2 – csv_import_vorschau: Encoding
# ---------------------------------------------------------------------------

class TestCsvEncoding:

    def _vorschau_bytes(self, inhalt: bytes):
        preise, db = _import_preise_csv()
        return preise.csv_import_vorschau(inhalt, preisgruppe_id=1)

    def test_utf8_mit_bom(self):
        inhalt = b'\xef\xbb\xbf4711;1,50\n'  # UTF-8 BOM
        result = self._vorschau_bytes(inhalt)
        assert result['ok_count'] == 1

    def test_latin1_umlaute(self):
        """Latin-1 kodierte Umlaute in der Bezeichnung."""
        bezeichnung = 'Bröt'.encode('latin-1')
        inhalt = b'4711;1,50;' + bezeichnung + b'\n'
        result = self._vorschau_bytes(inhalt)
        assert result['ok_count'] == 1

    def test_leere_datei(self):
        result = self._vorschau_bytes(b'')
        assert result['ok_count'] == 0
        assert result['err_count'] == 0


# ---------------------------------------------------------------------------
# 3 – csv_import_ausfuehren: GoBD + Import-Log
# ---------------------------------------------------------------------------

class TestCsvImportAusfuehren:

    def _run_import(self, preise, db_mod, zeilen):
        cur = MagicMock()
        cur.lastrowid = 1
        db_mod.get_wawi_transaction.return_value = _make_ctx(cur)

        # Keine aktuellen Preise (neue Artikel)
        db_mod.get_wawi_db.return_value = _make_ctx(
            MagicMock(**{'fetchall.return_value': []})
        )

        # Patch _aktuelle_preise_batch → leere Map
        preise._aktuelle_preise_batch = lambda ids, pg: {}

        return preise.csv_import_ausfuehren(
            vorschau_zeilen=zeilen,
            preisgruppe_id=1,
            dateiname='test.csv',
            erstellt_von='testuser',
            marge_standard=30.0,
        ), cur

    def _make_zeilen(self):
        return [
            {'zeile': 1, 'art_nr': '4711', 'artikel_id': 100,
             'bezeichnung': 'Testbrot', 'ek_neu': 1.50, 'mwst_satz': 7.0},
            {'zeile': 2, 'art_nr': '8899', 'artikel_id': 200,
             'bezeichnung': 'Butter', 'ek_neu': 0.75, 'mwst_satz': 7.0},
        ]

    def test_gibt_batch_id_zurueck(self):
        preise, db = _import_preise_csv()
        ergebnis, _ = self._run_import(preise, db, self._make_zeilen())
        assert ergebnis['batch_id'] is not None
        assert len(ergebnis['batch_id']) == 36  # UUID-Format

    def test_zeilen_ok_count(self):
        preise, db = _import_preise_csv()
        ergebnis, _ = self._run_import(preise, db, self._make_zeilen())
        assert ergebnis['zeilen_ok'] == 2

    def test_kein_update_kein_delete(self):
        """GoBD: Kein UPDATE oder DELETE in der Transaktion."""
        preise, db = _import_preise_csv()
        _, cur = self._run_import(preise, db, self._make_zeilen())

        for c in cur.execute.call_args_list:
            sql = str(c[0][0]).upper()
            assert 'UPDATE' not in sql, f"Unerlaubter UPDATE: {sql}"
            assert 'DELETE' not in sql, f"Unerlaubter DELETE: {sql}"

    def test_import_log_wird_geschrieben(self):
        """Ein Eintrag in WAWI_IMPORT_LOG wird angelegt."""
        preise, db = _import_preise_csv()
        _, cur = self._run_import(preise, db, self._make_zeilen())

        log_calls = [c for c in cur.execute.call_args_list
                     if 'WAWI_IMPORT_LOG' in str(c[0][0])]
        assert len(log_calls) == 1

    def test_vk_wird_berechnet(self):
        """VK_brutto wird aus EK + Standardmarge berechnet."""
        preise, db = _import_preise_csv()
        _, cur = self._run_import(preise, db, [self._make_zeilen()[0]])

        insert_preise = [c for c in cur.execute.call_args_list
                         if 'WAWI_PREISHISTORIE' in str(c[0][0])
                         and 'INSERT' in str(c[0][0]).upper()]
        assert len(insert_preise) >= 1
        # VK = 1,50 × 1,30 × 1,07 = 2,0865 → 2,09
        _, params = insert_preise[0][0]
        vk = params[3]  # vk_preis ist 4. Parameter
        assert vk == pytest.approx(2.0865, abs=0.02)

    def test_leere_zeilen_gibt_none_batch_id(self):
        """Kein Import bei leerer Liste."""
        preise, db = _import_preise_csv()
        db.get_wawi_transaction.return_value = _make_ctx(MagicMock())
        ergebnis = preise.csv_import_ausfuehren(
            vorschau_zeilen=[], preisgruppe_id=1,
            dateiname='leer.csv', erstellt_von='user',
        )
        assert ergebnis['batch_id'] is None
        assert ergebnis['zeilen_ok'] == 0

    def test_import_ref_ist_batch_id(self):
        """Alle Preishistorie-Einträge tragen die Batch-UUID als import_ref."""
        preise, db = _import_preise_csv()
        ergebnis, cur = self._run_import(preise, db, self._make_zeilen())
        batch_id = ergebnis['batch_id']

        insert_preise = [c for c in cur.execute.call_args_list
                         if 'WAWI_PREISHISTORIE' in str(c[0][0])
                         and 'INSERT' in str(c[0][0]).upper()]
        for c in insert_preise:
            _, params = c[0]
            assert params[-1] == batch_id, "import_ref muss batch_id sein"
