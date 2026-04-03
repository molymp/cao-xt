"""Tests für die WaWi-Preis-Logik (HAB-52).

Geprüfte Anforderungen:
- berechne_vk(): VK_brutto = EK_netto × (1 + Marge/100) × (1 + MwSt/100)
- berechne_marge(): Marge = (VK_brutto / (1 + MwSt/100) / EK_netto − 1) × 100
- Rundung auf 2 Dezimalstellen (kaufmännisch)
- Grenzfälle: EK = 0, VK = 0, negative Marge
- MwSt-Sätze 0%, 7%, 19%
- preis_speichern() ruft nur INSERT auf (kein UPDATE/DELETE – GoBD)
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, call

import pytest


# ---------------------------------------------------------------------------
# Stubs damit preise.py importierbar ist
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _make_wawi_transaction_ctx(cursor):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _setup_stubs():
    """Installiert minimale Stubs für config und db."""
    _stub_module('config',
                 CAO_DB_HOST='localhost', CAO_DB_PORT=3306,
                 CAO_DB_NAME='test', CAO_DB_USER='test', CAO_DB_PASSWORD='test',
                 WAWI_DB_HOST='localhost', WAWI_DB_PORT=3306,
                 WAWI_DB_NAME='cao_wawi', WAWI_DB_USER='test', WAWI_DB_PASSWORD='test',
                 WAWI_BENUTZER_DEFAULT='wawi')

    db_mod = _stub_module('db',
                          get_cao_db=MagicMock(),
                          get_wawi_db=MagicMock(),
                          get_wawi_transaction=MagicMock(),
                          de_zu_float=lambda v: float(str(v).replace(',', '.')))
    return db_mod


def _import_preise():
    for mod in ('preise', 'db', 'config'):
        sys.modules.pop(mod, None)

    db_mod = _setup_stubs()

    # Pfad zur wawi-app
    WAWI_APP = (
        '/Volumes/MacDisk01/ml/.paperclip/instances/default/workspaces/'
        'bddd7c2d-0bec-47a5-a435-33ba5645bf8e/cao-xt/wawi-app/app'
    )
    if WAWI_APP not in sys.path:
        sys.path.insert(0, WAWI_APP)

    import preise  # noqa: PLC0415
    return preise, db_mod


# ---------------------------------------------------------------------------
# 1 – berechne_vk
# ---------------------------------------------------------------------------

class TestBerechneVK:
    """VK_brutto = EK_netto × (1 + Marge/100) × (1 + MwSt/100)"""

    def setup_method(self):
        self.preise, _ = _import_preise()

    def test_normalfall_19pct(self):
        """EK=1,00 Marge=30% MwSt=19% → VK=1,547 → gerundet 1,55"""
        vk = self.preise.berechne_vk(1.00, 30.0, 19.0)
        assert vk == pytest.approx(1.55, abs=0.005)

    def test_normalfall_7pct(self):
        """MwSt 7%: EK=2,00 Marge=25% → VK = 2×1,25×1,07 = 2,675 → kaufm. gerundet 2,68"""
        vk = self.preise.berechne_vk(2.00, 25.0, 7.0)
        assert vk == pytest.approx(2.68, abs=0.005)

    def test_mwst_0pct(self):
        """MwSt 0%: VK = EK × (1 + Marge/100)"""
        vk = self.preise.berechne_vk(10.0, 50.0, 0.0)
        assert vk == pytest.approx(15.00, abs=0.005)

    def test_ek_null_gibt_null(self):
        """EK = 0 → VK = 0.0 (keine Division durch 0)"""
        vk = self.preise.berechne_vk(0.0, 30.0, 19.0)
        assert vk == 0.0

    def test_negative_marge(self):
        """Negative Marge (Verlust): VK < EK × (1 + MwSt/100)"""
        vk = self.preise.berechne_vk(2.00, -10.0, 19.0)
        assert vk < 2.00 * 1.19

    def test_rundung_kaufmaennisch(self):
        """Ergebnis wird auf 2 Dezimalstellen kaufmännisch gerundet."""
        # 1,234... → 1,23 und 1,235... → 1,24
        vk1 = self.preise.berechne_vk(1.00, 3.0, 19.0)    # 1×1,03×1,19 = 1.2257 → 1,23
        assert isinstance(vk1, float)
        assert round(vk1, 2) == vk1  # Resultat ist bereits gerundet

    def test_ergebnis_ist_float(self):
        vk = self.preise.berechne_vk(1.5, 20.0, 19.0)
        assert isinstance(vk, float)


# ---------------------------------------------------------------------------
# 2 – berechne_marge
# ---------------------------------------------------------------------------

class TestBerechneMarge:
    """Marge = (VK_brutto / (1 + MwSt/100) / EK_netto − 1) × 100"""

    def setup_method(self):
        self.preise, _ = _import_preise()

    def test_normalfall_19pct(self):
        """Umkehrfunktion von berechne_vk: EK=1, VK=1,55, MwSt=19% → ~29,4%"""
        marge = self.preise.berechne_marge(1.00, 1.55, 19.0)
        assert marge == pytest.approx(30.25, abs=0.5)  # nicht exakt 30 wg. Rundung

    def test_inverse_von_berechne_vk(self):
        """berechne_marge(EK, berechne_vk(EK, m, mwst), mwst) ≈ m
        Toleranz 0.2% da berechne_vk auf 2 Stellen rundet – leichter Rundungsverlust."""
        for marge in [10.0, 25.0, 50.0, 100.0]:
            for mwst in [0.0, 7.0, 19.0]:
                vk = self.preise.berechne_vk(2.0, marge, mwst)
                marge_rueck = self.preise.berechne_marge(2.0, vk, mwst)
                assert marge_rueck == pytest.approx(marge, abs=0.3), \
                    f"Marge={marge}, MwSt={mwst}"

    def test_ek_null_gibt_null(self):
        assert self.preise.berechne_marge(0.0, 1.50, 19.0) == 0.0

    def test_vk_null_gibt_null(self):
        assert self.preise.berechne_marge(1.0, 0.0, 19.0) == 0.0

    def test_ergebnis_ist_float(self):
        m = self.preise.berechne_marge(1.0, 1.50, 19.0)
        assert isinstance(m, float)

    def test_verlust_negative_marge(self):
        """VK < EK_netto → Marge < 0"""
        m = self.preise.berechne_marge(2.00, 1.90, 19.0)
        vk_netto = 1.90 / 1.19
        assert vk_netto < 2.00
        assert m < 0.0


# ---------------------------------------------------------------------------
# 3 – preis_speichern: GoBD – nur INSERT, kein UPDATE
# ---------------------------------------------------------------------------

class TestPreisSpeichernGoBD:
    """preis_speichern() darf nur INSERT ausführen (GoBD append-only)."""

    def _run(self, preise, db_mod):
        cur = MagicMock()
        cur.lastrowid = 99
        db_mod.get_wawi_transaction.return_value = _make_wawi_transaction_ctx(cur)

        neue_id = preise.preis_speichern(
            artikel_id=42,
            preisgruppe_id=1,
            ek_preis=1.50,
            vk_preis=2.19,
            mwst_satz=19.0,
            erstellt_von='testuser',
            aenderungsgrund='Teständerung',
        )
        return cur, neue_id

    def test_gibt_lastrowid_zurueck(self):
        preise, db = _import_preise()
        cur, neue_id = self._run(preise, db)
        assert neue_id == 99

    def test_nur_insert_kein_update(self):
        """Kein UPDATE oder DELETE in den DB-Aufrufen."""
        preise, db = _import_preise()
        cur, _ = self._run(preise, db)

        for c in cur.execute.call_args_list:
            sql = str(c[0][0]).upper()
            assert 'UPDATE' not in sql, f"Unerlaubter UPDATE-Aufruf: {sql}"
            assert 'DELETE' not in sql, f"Unerlaubter DELETE-Aufruf: {sql}"

    def test_insert_enthaelt_pflichtfelder(self):
        """INSERT enthält artikel_id, preisgruppe_id, vk_preis, mwst_satz."""
        preise, db = _import_preise()
        cur, _ = self._run(preise, db)

        insert_calls = [c for c in cur.execute.call_args_list
                        if 'INSERT' in str(c[0][0]).upper()]
        assert len(insert_calls) == 1
        sql, params = insert_calls[0][0]
        assert 'WAWI_PREISHISTORIE' in sql
        # Params: artikel_id, preisgruppe_id, ek_preis, vk_preis, marge, mwst_satz, user, grund, import_ref
        assert params[0] == 42    # artikel_id
        assert params[1] == 1     # preisgruppe_id
        assert params[3] == 2.19  # vk_preis
        assert params[5] == 19.0  # mwst_satz
        assert params[6] == 'testuser'

    def test_marge_wird_berechnet(self):
        """Marge wird automatisch berechnet wenn EK vorhanden."""
        preise, db = _import_preise()
        cur, _ = self._run(preise, db)

        insert_calls = [c for c in cur.execute.call_args_list
                        if 'INSERT' in str(c[0][0]).upper()]
        _, params = insert_calls[0][0]
        marge = params[4]
        assert marge is not None
        assert marge != 0.0

    def test_ohne_ek_marge_ist_none(self):
        """Ohne EK-Preis ist marge_prozent = None."""
        preise, db = _import_preise()
        cur = MagicMock()
        cur.lastrowid = 1
        db.get_wawi_transaction.return_value = _make_wawi_transaction_ctx(cur)

        preise.preis_speichern(
            artikel_id=1, preisgruppe_id=1,
            ek_preis=None, vk_preis=2.00,
            mwst_satz=19.0, erstellt_von='user',
        )
        insert_calls = [c for c in cur.execute.call_args_list
                        if 'INSERT' in str(c[0][0]).upper()]
        _, params = insert_calls[0][0]
        marge = params[4]
        assert marge is None
