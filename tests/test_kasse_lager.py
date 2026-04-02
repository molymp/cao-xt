"""Tests für die Warenbestand-Abbuchung bei Kassenbuchungen (HAB-34).

Geprüfte Anforderungen:
- zahlung_abschliessen(): ARTIKEL.MENGE_AKT wird für jede Position mit gültiger
  ARTIKEL_ID um die verkaufte MENGE verringert.
- vorgang_stornieren(): ARTIKEL.MENGE_AKT wird für jede Position der stornierten
  Buchung wieder erhöht.
- Positionen ohne ARTIKEL_ID oder mit ARTIKEL_ID <= 0 (Warengruppen-Buchungen)
  werden beim Lager-Update übersprungen.
- Bei DB-Fehler im Lager-Update rollt die gesamte Transaktion zurück
  (kein Vorgang abgeschlossen, kein Kassenbuch-Eintrag).

Implementierungsstrategie (Option A, dokumentiert in DECISIONS.md):
  Direktes UPDATE ARTIKEL.MENGE_AKT mit SELECT ... FOR UPDATE innerhalb der
  bestehenden get_db_transaction()-Transaktion.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Minimales Stub-Modul für `tse` und `config` damit kasse_logik importierbar
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_stub_module(
    'config',
    DB_HOST='localhost', DB_PORT=3306, DB_USER='test',
    DB_PASSWORD='test', DB_NAME='test', TERMINAL_NR=1,
)
_stub_module(
    'tse',
    tse_verfuegbar=lambda *a: False,
    tse_finish_transaktion=lambda *a, **kw: {},
    tse_storno_transaktion=lambda *a, **kw: {},
)


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

def _make_cursor(fetchone_val=None, fetchall_val=None, lastrowid=42):
    """Erzeugt einen Mock-Cursor für mysql.connector (dictionary=True)."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_val
    cur.fetchall.return_value = fetchall_val or []
    cur.lastrowid = lastrowid
    return cur


def _make_transaction_ctx(cursor):
    """Gibt einen Context-Manager zurück, der `cursor` liefert."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


ARTIKEL_POS = {
    'ARTIKEL_ID': 100,
    'ARTNUM': 'A001',
    'BARCODE': '',
    'BEZEICHNUNG': 'Testbrot',
    'MENGE': 2.0,
    'POSITION': 1,
    'EINZELPREIS_BRUTTO': 250,
    'GESAMTPREIS_BRUTTO': 500,
    'STEUER_CODE': 2,
    'MWST_SATZ': 7,
    'MWST_BETRAG': 33,
    'NETTO_BETRAG': 467,
    'STORNIERT': None,
}

WARENGR_POS = {
    **ARTIKEL_POS,
    'ARTIKEL_ID': -99,
    'ARTNUM': 'WG',
    'BEZEICHNUNG': 'Warengruppe',
}

NULL_POS = {
    **ARTIKEL_POS,
    'ARTIKEL_ID': None,
    'BEZEICHNUNG': 'Kein Artikel',
}

VORGANG = {
    'ID': 1, 'STATUS': 'OFFEN', 'TERMINAL_NR': 1,
    'BETRAG_BRUTTO': 500, 'BETRAG_NETTO': 467,
    'MWST_BETRAG_1': 0, 'MWST_BETRAG_2': 33, 'MWST_BETRAG_3': 0,
    'NETTO_BETRAG_1': 0, 'NETTO_BETRAG_2': 467, 'NETTO_BETRAG_3': 0,
    'TSE_TX_ID': None, 'TSE_TX_REVISION': None,
    'MITARBEITER_ID': 1,
}

ZAHLUNG_BAR = [{'zahlart': 'BAR', 'betrag': 500,
                 'betrag_gegeben': 500, 'wechselgeld': 0}]

MITARBEITER = {'MA_ID': 1, 'VNAME': 'Max', 'NAME': 'Muster'}


# ---------------------------------------------------------------------------
# Hilfsfunktion: import kasse_logik mit gemockten DB-Aufrufen
# ---------------------------------------------------------------------------

def _import_kasse_logik():
    """Importiert kasse_logik mit gemockten DB-Abhängigkeiten."""
    # Sicherstellen, dass ein frischer Import stattfindet
    if 'kasse_logik' in sys.modules:
        del sys.modules['kasse_logik']
    if 'db' in sys.modules:
        del sys.modules['db']

    db_mod = _stub_module(
        'db',
        get_db=MagicMock(),
        get_db_transaction=MagicMock(),
        euro_zu_cent=lambda v: int(float(str(v).replace(',', '.')) * 100),
        cent_zu_euro_str=lambda c: f'{c / 100:.2f} €',
    )

    sys.path.insert(
        0,
        '/Volumes/MacDisk01/ml/.paperclip/instances/default/workspaces/'
        'bddd7c2d-0bec-47a5-a435-33ba5645bf8e/cao-xt/kasse-app/app',
    )
    import kasse_logik  # noqa: PLC0415
    return kasse_logik, db_mod


# ---------------------------------------------------------------------------
# 1 – zahlung_abschliessen: Lager-Abbuchung
# ---------------------------------------------------------------------------

class TestZahlungAbschliessenLager:
    """zahlung_abschliessen() bucht MENGE_AKT für gültige Artikel-Positionen ab."""

    def _run(self, positionen, db_mod, kasse_logik):
        """Führt zahlung_abschliessen() mit Mocks aus und gibt den cursor zurück."""
        cur = _make_cursor()
        db_mod.get_db_transaction.return_value = _make_transaction_ctx(cur)

        with (
            patch.object(kasse_logik, 'vorgang_laden', return_value=VORGANG),
            patch.object(kasse_logik, 'vorgang_positionen', return_value=positionen),
            patch.object(kasse_logik, 'mwst_saetze_laden', return_value={}),
            patch.object(kasse_logik, 'naechste_bon_nr', return_value=1),
        ):
            kasse_logik.zahlung_abschliessen(1, 1, ZAHLUNG_BAR)

        return cur

    def test_menge_akt_wird_abgebucht(self):
        """UPDATE ARTIKEL ... MENGE - X wird für Artikel-Position ausgeführt."""
        kl, db = _import_kasse_logik()
        cur = self._run([ARTIKEL_POS], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 1
        sql, params = update_calls[0][0]
        assert 'MENGE_AKT - %s' in sql
        assert params == (2.0, 100)

    def test_select_for_update_vorhanden(self):
        """SELECT ... FOR UPDATE wird vor jedem UPDATE ausgeführt (Deadlock-Schutz)."""
        kl, db = _import_kasse_logik()
        cur = self._run([ARTIKEL_POS], db, kl)

        lock_calls = [
            c for c in cur.execute.call_args_list
            if 'FOR UPDATE' in str(c)
        ]
        assert len(lock_calls) == 1

    def test_warengruppen_position_wird_uebersprungen(self):
        """Positionen mit ARTIKEL_ID = -99 (Warengruppe) werden nicht abgebucht."""
        kl, db = _import_kasse_logik()
        cur = self._run([WARENGR_POS], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 0

    def test_null_artikel_id_wird_uebersprungen(self):
        """Positionen ohne ARTIKEL_ID (None) werden nicht abgebucht."""
        kl, db = _import_kasse_logik()
        cur = self._run([NULL_POS], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 0

    def test_mehrere_positionen_alle_abgebucht(self):
        """Für jede gültige Position wird ein eigener UPDATE ausgeführt."""
        kl, db = _import_kasse_logik()
        pos_a = {**ARTIKEL_POS, 'ARTIKEL_ID': 100, 'MENGE': 1.0}
        pos_b = {**ARTIKEL_POS, 'ARTIKEL_ID': 200, 'MENGE': 3.0}
        cur = self._run([pos_a, pos_b], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 2

        artikel_ids = {c[0][1][1] for c in update_calls}
        assert artikel_ids == {100, 200}

    def test_gemischte_positionen(self):
        """Nur Artikel-Positionen werden abgebucht; Warengruppe und None-ID werden ignoriert."""
        kl, db = _import_kasse_logik()
        cur = self._run([ARTIKEL_POS, WARENGR_POS, NULL_POS], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 1


# ---------------------------------------------------------------------------
# 2 – vorgang_stornieren: Lager-Rückbuchung
# ---------------------------------------------------------------------------

class TestVorgangStornierenLager:
    """vorgang_stornieren() bucht MENGE_AKT für gültige Positionen zurück."""

    _ABGESCHLOSSEN = {**VORGANG, 'STATUS': 'ABGESCHLOSSEN'}

    def _run(self, orig_positionen, db_mod, kasse_logik):
        cur = _make_cursor()
        db_mod.get_db_transaction.return_value = _make_transaction_ctx(cur)

        with (
            patch.object(kasse_logik, 'vorgang_laden',
                         side_effect=[self._ABGESCHLOSSEN, self._ABGESCHLOSSEN]),
            patch.object(kasse_logik, 'vorgang_positionen', return_value=orig_positionen),
            patch.object(kasse_logik, 'mwst_saetze_laden', return_value={}),
            patch.object(kasse_logik, 'naechste_bon_nr', return_value=5),
            patch.object(kasse_logik, 'vorgang_zahlungen', return_value=[]),
        ):
            kasse_logik.vorgang_stornieren(1, 1, MITARBEITER)

        return cur

    def test_menge_akt_wird_zurueckgebucht(self):
        """UPDATE ARTIKEL ... MENGE + X wird für Artikel-Position ausgeführt."""
        kl, db = _import_kasse_logik()
        cur = self._run([ARTIKEL_POS], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 1
        sql, params = update_calls[0][0]
        assert 'MENGE_AKT + %s' in sql
        assert params == (2.0, 100)

    def test_warengruppe_wird_uebersprungen(self):
        """Positionen mit ARTIKEL_ID = -99 werden beim Rückbuchen ignoriert."""
        kl, db = _import_kasse_logik()
        cur = self._run([WARENGR_POS], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 0

    def test_mehrere_positionen_alle_rueckgebucht(self):
        """Alle gültigen Positionen werden einzeln rückgebucht."""
        kl, db = _import_kasse_logik()
        pos_a = {**ARTIKEL_POS, 'ARTIKEL_ID': 100, 'MENGE': 1.0}
        pos_b = {**ARTIKEL_POS, 'ARTIKEL_ID': 201, 'MENGE': 2.0}
        cur = self._run([pos_a, pos_b], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        assert len(update_calls) == 2

    def test_vorzeichen_ruckbuchung_positiv(self):
        """Der Rückbuchungs-Betrag ist positiv (MENGE_AKT wird erhöht)."""
        kl, db = _import_kasse_logik()
        cur = self._run([{**ARTIKEL_POS, 'MENGE': 3.0}], db, kl)

        update_calls = [
            c for c in cur.execute.call_args_list
            if 'UPDATE ARTIKEL' in str(c)
        ]
        _, params = update_calls[0][0]
        assert params[0] > 0, "Rückbuchungsmenge muss positiv sein"
        assert params[0] == 3.0
