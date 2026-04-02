"""GoBD-Exporttest für datevexport (CAO-Faktura → DATEV-CSV).

Geprüfte GoBD-Anforderungen (BMF-Schreiben 28.11.2019 / § 147 AO):
- Vollständigkeit aller 15 DATEV-Pflichtfelder
- Korrekte Dateistruktur (Encoding UTF-8 BOM, Delimiter Tab)
- SollHabenKennzeichen nur 'S' oder 'H'
- Waehrungskennung immer 'EUR'
- Umsatz in deutscher Dezimalnotation (Komma statt Punkt)
- Datum im Format DDMM (vierstellig)
- Belegfeld1 nicht leer (Belegnummer als Grundlage Buchungsbeleg)
- Buchungstext nicht leer (nachvollziehbare Buchungsbeschreibung)
- UNION-Abfrage enthält alle 19 Buchungsteile
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from datevexport.config import Kontenplan
from datevexport.export import DELIMITER, ENCODING, generate_filename, write_csv
from datevexport.queries import (
    DATEV_COLUMNS,
    build_full_query,
    execute_query,
)


# ---------------------------------------------------------------------------
# Testdaten
# ---------------------------------------------------------------------------

# Minimaler, aber vollständiger Datensatz – alle Pflichtfelder gesetzt
_BUCHUNG_VOLLSTAENDIG = {
    'Waehrungskennung': 'EUR',
    'SollHabenKennzeichen': 'S',
    'Umsatz': '119,00',
    'BUSchluessel': '',
    'Gegenkonto': '3400',
    'Belegfeld1': 'RE-2026-001',
    'Belegfeld2': '',
    'Datum': '1503',
    'Konto': '1600',
    'Kostfeld1': '1600',
    'Kostfeld2': '',
    'Kostmenge': '',
    'Skonto': '',
    'Buchungstext': 'Muster Lieferant 19%',
    'Festschreibung': '0',
}


def _make_rows(n: int = 3) -> list[dict]:
    """Erzeugt n identische Buchungszeilen für Strukturtests."""
    return [dict(_BUCHUNG_VOLLSTAENDIG) for _ in range(n)]


# ---------------------------------------------------------------------------
# 1 – Spalten-Vollständigkeit
# ---------------------------------------------------------------------------

class TestDatevSpalten:
    """DATEV_COLUMNS enthält alle GoBD-relevanten Felder."""

    def test_spaltenanzahl(self):
        """Genau 15 Spalten gemäß DATEV-Buchungsstapel-Format."""
        assert len(DATEV_COLUMNS) == 15

    def test_pflichtfelder_vorhanden(self):
        """Kernpflichtfelder des DATEV-Buchungsstapels sind enthalten."""
        pflichtfelder = {
            'Waehrungskennung', 'SollHabenKennzeichen', 'Umsatz',
            'Gegenkonto', 'Belegfeld1', 'Datum', 'Konto', 'Buchungstext',
        }
        assert pflichtfelder <= set(DATEV_COLUMNS)

    def test_gobd_archivierungsfelder_vorhanden(self):
        """GoBD-Unveränderbarkeitskennzeichen ist im Schema enthalten."""
        assert 'Festschreibung' in DATEV_COLUMNS


# ---------------------------------------------------------------------------
# 2 – SQL-Abfragestruktur
# ---------------------------------------------------------------------------

class TestQueryStruktur:
    """build_full_query() erzeugt eine vollständige UNION-Abfrage."""

    _EXPECTED_PARTS = 19  # 1a–1e, 2, 3a–3c, 4, 5a–5c, 6, 7a–7c, 8, 9

    def test_union_anzahl(self):
        """Alle 19 Buchungsteile sind per UNION verknüpft."""
        sql = build_full_query(2026, 3)
        # 19 Teile → 18 UNION-Verbindungen
        assert sql.upper().count('UNION') == self._EXPECTED_PARTS - 1

    def test_year_month_in_query(self):
        """Jahr und Monat werden korrekt in die Abfrage eingesetzt."""
        sql = build_full_query(2025, 12)
        assert '2025' in sql
        assert '12' in sql

    def test_alle_spalten_in_select(self):
        """Jede DATEV-Spalte kommt als AS-Alias in der Abfrage vor."""
        sql = build_full_query(2026, 1)
        for col in DATEV_COLUMNS:
            assert col in sql, f"Spalte '{col}' fehlt im SELECT"

    def test_kontenplan_werte_in_query(self):
        """Standard-Kontenplan (SKR03) wird korrekt eingesetzt."""
        k = Kontenplan()
        sql = build_full_query(2026, 3, k)
        assert str(k.WE19) in sql    # 3400 – Wareneingangskonto 19 %
        assert str(k.Kasse) in sql   # 1000
        assert str(k.Bank) in sql    # 1200

    def test_custom_kontenplan(self):
        """Angepasster Kontenplan wird korrekt übernommen."""
        k = Kontenplan(WE19=9999, Kasse=8888)
        sql = build_full_query(2026, 3, k)
        assert '9999' in sql
        assert '8888' in sql

    def test_festschreibungskennzeichen_default(self):
        """Festschreibungskennzeichen ist per Default 0 (nicht festgeschrieben)."""
        k = Kontenplan()
        assert k.Festschreibungskennzeichen == 0
        sql = build_full_query(2026, 3, k)
        assert 'AS Festschreibung' in sql


# ---------------------------------------------------------------------------
# 3 – CSV-Dateistruktur und Encoding
# ---------------------------------------------------------------------------

class TestCsvStruktur:
    """write_csv() erzeugt eine GoBD-konforme CSV-Datei."""

    def test_datei_wird_erstellt(self, tmp_path):
        """CSV-Datei wird im angegebenen Verzeichnis angelegt."""
        rows = _make_rows(2)
        path = write_csv(rows, 2026, 3, str(tmp_path))
        assert path.exists()

    def test_encoding_utf8_bom(self, tmp_path):
        """Datei beginnt mit UTF-8 BOM (für Excel/DATEV-Kompatibilität)."""
        rows = _make_rows(1)
        path = write_csv(rows, 2026, 3, str(tmp_path))
        raw = path.read_bytes()
        assert raw[:3] == b'\xef\xbb\xbf', "UTF-8 BOM fehlt"

    def test_delimiter_tab(self, tmp_path):
        """Feldtrennzeichen ist Tab (DATEV-Konvention)."""
        rows = _make_rows(1)
        path = write_csv(rows, 2026, 3, str(tmp_path))
        content = path.read_text(encoding=ENCODING)
        assert '\t' in content

    def test_kopfzeile_enthaelt_alle_spalten(self, tmp_path):
        """Kopfzeile enthält alle 15 DATEV-Spalten."""
        rows = _make_rows(1)
        path = write_csv(rows, 2026, 3, str(tmp_path))
        content = path.read_text(encoding=ENCODING)
        reader = csv.DictReader(io.StringIO(content), delimiter=DELIMITER)
        assert set(reader.fieldnames or []) == set(DATEV_COLUMNS)

    def test_zeilenanzahl(self, tmp_path):
        """Anzahl Datenzeilen stimmt mit Eingabe überein."""
        rows = _make_rows(5)
        path = write_csv(rows, 2026, 3, str(tmp_path))
        content = path.read_text(encoding=ENCODING)
        reader = csv.DictReader(io.StringIO(content), delimiter=DELIMITER)
        data_rows = list(reader)
        assert len(data_rows) == 5

    def test_dateiname_format(self, tmp_path):
        """Dateiname enthält Jahr, Monat und Zeitstempel."""
        rows = _make_rows(1)
        path = write_csv(rows, 2026, 3, str(tmp_path))
        assert '2026-3' in path.name
        assert path.suffix == '.csv'

    def test_unterverzeichnis_wird_angelegt(self, tmp_path):
        """Ausgabeverzeichnis wird automatisch erstellt."""
        nested = tmp_path / 'a' / 'b' / 'export'
        rows = _make_rows(1)
        path = write_csv(rows, 2026, 3, str(nested))
        assert path.exists()

    def test_generate_filename_format(self):
        """Dateiname folgt dem erwarteten Muster."""
        name = generate_filename(2026, 3)
        assert name.startswith('habadola2datev_2026-3_as-of_')
        assert name.endswith('.csv')


# ---------------------------------------------------------------------------
# 4 – GoBD-Pflichtfelder in Buchungszeilen
# ---------------------------------------------------------------------------

class TestGobdPflichtfelder:
    """Jede Buchungszeile erfüllt die GoBD-Mindestanforderungen."""

    def _lese_csv(self, tmp_path, rows) -> list[dict]:
        path = write_csv(rows, 2026, 3, str(tmp_path))
        content = path.read_text(encoding=ENCODING)
        return list(csv.DictReader(io.StringIO(content), delimiter=DELIMITER))

    def test_waehrungskennung_immer_eur(self, tmp_path):
        """Waehrungskennung ist in jeder Zeile 'EUR' (§ 253 HGB)."""
        data = self._lese_csv(tmp_path, _make_rows(3))
        for row in data:
            assert row['Waehrungskennung'] == 'EUR'

    def test_sollhaben_nur_s_oder_h(self, tmp_path):
        """SollHabenKennzeichen ist ausschließlich 'S' oder 'H'."""
        rows = [
            {**_BUCHUNG_VOLLSTAENDIG, 'SollHabenKennzeichen': 'S'},
            {**_BUCHUNG_VOLLSTAENDIG, 'SollHabenKennzeichen': 'H'},
        ]
        data = self._lese_csv(tmp_path, rows)
        for row in data:
            assert row['SollHabenKennzeichen'] in ('S', 'H')

    def test_umsatz_deutsches_dezimalformat(self, tmp_path):
        """Umsatz verwendet Komma als Dezimaltrennzeichen (GoBD: Originaldatenformat)."""
        rows = [{**_BUCHUNG_VOLLSTAENDIG, 'Umsatz': '1234,56'}]
        data = self._lese_csv(tmp_path, rows)
        assert ',' in data[0]['Umsatz']
        assert '.' not in data[0]['Umsatz']

    def test_datum_vierstellig_ddmm(self, tmp_path):
        """Datum ist vierstellig im Format DDMM."""
        rows = [{**_BUCHUNG_VOLLSTAENDIG, 'Datum': '1503'}]
        data = self._lese_csv(tmp_path, rows)
        datum = data[0]['Datum']
        assert re.fullmatch(r'\d{4}', datum), f"Ungültiges Datumsformat: '{datum}'"

    def test_belegfeld1_nicht_leer(self, tmp_path):
        """Belegfeld1 (Belegnummer) darf nicht leer sein (GoBD Rn. 82: Belegprinzip)."""
        data = self._lese_csv(tmp_path, _make_rows(3))
        for i, row in enumerate(data):
            assert row['Belegfeld1'].strip(), f"Belegfeld1 leer in Zeile {i + 1}"

    def test_buchungstext_nicht_leer(self, tmp_path):
        """Buchungstext ist nicht leer (GoBD: nachvollziehbare Buchungsbeschreibung)."""
        data = self._lese_csv(tmp_path, _make_rows(3))
        for i, row in enumerate(data):
            assert row['Buchungstext'].strip(), f"Buchungstext leer in Zeile {i + 1}"

    def test_konto_nicht_leer(self, tmp_path):
        """Konto (Sachkonto) ist in jeder Buchungszeile gesetzt."""
        data = self._lese_csv(tmp_path, _make_rows(3))
        for i, row in enumerate(data):
            assert row['Konto'].strip(), f"Konto leer in Zeile {i + 1}"

    def test_gegenkonto_nicht_leer(self, tmp_path):
        """Gegenkonto ist in jeder Buchungszeile gesetzt."""
        data = self._lese_csv(tmp_path, _make_rows(3))
        for i, row in enumerate(data):
            assert row['Gegenkonto'].strip(), f"Gegenkonto leer in Zeile {i + 1}"


# ---------------------------------------------------------------------------
# 5 – execute_query (mit gemockter DB-Verbindung)
# ---------------------------------------------------------------------------

class TestExecuteQuery:
    """execute_query() führt die Abfrage korrekt aus und gibt Dicts zurück."""

    def _mock_connection(self, return_rows: list[dict]) -> MagicMock:
        """Erzeugt eine pymysql-Connection-Attrappe mit vorkonfigurierten Ergebnissen."""
        cursor = MagicMock()
        cursor.fetchall.return_value = return_rows
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cursor

    def test_gibt_liste_zurueck(self):
        """execute_query gibt eine Liste zurück."""
        conn, _ = self._mock_connection(_make_rows(2))
        result = execute_query(conn, 2026, 3)
        assert isinstance(result, list)

    def test_anzahl_ergebnisse(self):
        """Anzahl zurückgegebener Zeilen entspricht DB-Ergebnis."""
        conn, _ = self._mock_connection(_make_rows(7))
        result = execute_query(conn, 2026, 3)
        assert len(result) == 7

    def test_sql_wird_ausgefuehrt(self):
        """cursor.execute() wird genau einmal aufgerufen."""
        conn, cursor = self._mock_connection(_make_rows(1))
        execute_query(conn, 2026, 3)
        cursor.execute.assert_called_once()

    def test_sql_enthaelt_jahr_und_monat(self):
        """Die ausgeführte SQL-Abfrage enthält das angegebene Jahr und den Monat."""
        conn, cursor = self._mock_connection([])
        execute_query(conn, 2025, 11)
        sql_arg = cursor.execute.call_args[0][0]
        assert '2025' in sql_arg
        assert '11' in sql_arg

    def test_leere_datenbank_gibt_leere_liste(self):
        """Kein Absturz bei leerem DB-Ergebnis – leere Liste wird zurückgegeben."""
        conn, _ = self._mock_connection([])
        result = execute_query(conn, 2026, 3)
        assert result == []

    def test_custom_kontenplan_wird_verwendet(self):
        """Ein angepasster Kontenplan wird an die Abfrage weitergegeben."""
        conn, cursor = self._mock_connection([])
        k = Kontenplan(WE19=9999)
        execute_query(conn, 2026, 3, k)
        sql_arg = cursor.execute.call_args[0][0]
        assert '9999' in sql_arg
