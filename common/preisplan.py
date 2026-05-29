"""Preisplanung (Dorfkern-Erweiterung, unabhängig von CAO).

Mehrere geplante Aktionen (befristet) und dauerhafte Preisänderungen
(ab Stichtag) je Artikel — Tabelle XT_ARTIKEL_PREISPLAN. Anwenden
schreibt zum Stichtag in CAO:
  - art='aktion' → ARTIKEL_PREIS PREIS_TYP=6 (cao_artikel.aktionspreis_speichern)
  - art='preis'  → ARTIKEL.VK1..5 (netto) + VK1B..5B (brutto), Record-Lock

Anwenden geschieht automatisch (faellige_anwenden, via Timer/Poller) ODER
manuell (Übersicht). VK-Werte sind NETTO (wie CAO-Aktionspreis); Brutto
wird beim dauerhaften Anwenden aus dem Steuersatz berechnet.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from common.db import get_db, get_db_transaction
from common.cao_lock import cao_record_lock
from common.binaerdaten import MODUL_ID_ARTIKEL
from common import cao_artikel as art

log = logging.getLogger(__name__)

# STEUER_CODE → MwSt-Satz (CAO-Default; Code 2=7% per Trace bestätigt).
_STEUER_RATE = {0: 0.0, 1: 0.19, 2: 0.07, 3: 0.0}
VK_FELDER = ('vk1', 'vk2', 'vk3', 'vk4', 'vk5')


def _rate(steuer_code) -> float:
    try:
        return _STEUER_RATE.get(int(steuer_code), 0.0)
    except (TypeError, ValueError):
        return 0.0


# ── Lesen ──────────────────────────────────────────────────────────────

def je_artikel(artikel_id: int) -> list[dict[str, Any]]:
    sql = """SELECT * FROM XT_ARTIKEL_PREISPLAN
              WHERE artikel_id=%s AND status<>'storniert'
              ORDER BY gueltig_ab DESC, rec_id DESC"""
    with get_db() as cur:
        cur.execute(sql, (int(artikel_id),))
        return list(cur.fetchall() or [])


def uebersicht(*, nur_offen_schild: bool = False, ab: date | None = None,
               status: str | None = None) -> list[dict[str, Any]]:
    """Geplante/aktive Änderungen artikelübergreifend (für Schilddruck)."""
    where = ["p.status IN ('geplant','aktiv')"]
    params: list[Any] = []
    if nur_offen_schild:
        where.append("p.schild_gedruckt=0")
    if ab:
        where.append("p.gueltig_ab>=%s")
        params.append(ab)
    if status:
        where[0] = "p.status=%s"
        params.insert(0, status)
    sql = f"""SELECT p.*, a.ARTNUM, a.STEUER_CODE,
                     COALESCE(NULLIF(a.KAS_NAME,''),a.KURZNAME,a.MATCHCODE) AS BEZ,
                     a.WARENGRUPPE AS WGR_ID, wg.NAME AS WGR_NAME,
                     a.VK5B AS AKTUELL_VK5B
                FROM XT_ARTIKEL_PREISPLAN p
                JOIN ARTIKEL a ON a.REC_ID=p.artikel_id
                LEFT JOIN WARENGRUPPEN wg ON wg.ID=a.WARENGRUPPE
               WHERE {' AND '.join(where)}
               ORDER BY p.gueltig_ab ASC, BEZ ASC"""
    with get_db() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def _holen(cur, rec_id: int) -> dict[str, Any] | None:
    cur.execute("SELECT * FROM XT_ARTIKEL_PREISPLAN WHERE rec_id=%s",
                (int(rec_id),))
    return cur.fetchone()


# ── Schreiben (Planung) ────────────────────────────────────────────────

def anlegen(artikel_id: int, art_typ: str, vks: list, gueltig_ab,
            gueltig_bis=None, *, notiz: str = '', ma_name: str = 'CAO-XT') -> int:
    art_typ = 'preis' if art_typ == 'preis' else 'aktion'
    vk = [(float(str(x).replace(',', '.')) if x not in (None, '') else None)
          for x in (list(vks) + [None] * 5)[:5]]
    with get_db_transaction() as cur:
        cur.execute(
            """INSERT INTO XT_ARTIKEL_PREISPLAN
               (artikel_id, art, vk1, vk2, vk3, vk4, vk5,
                gueltig_ab, gueltig_bis, status, notiz, erst_name)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'geplant',%s,%s)""",
            (int(artikel_id), art_typ, vk[0], vk[1], vk[2], vk[3], vk[4],
             gueltig_ab, gueltig_bis or None, notiz[:255],
             (ma_name or 'CAO-XT')[:50]))
        return int(cur.lastrowid)


def aendern(rec_id: int, felder: dict[str, Any], *,
            ma_name: str = 'CAO-XT') -> None:
    erlaubt = {'vk1', 'vk2', 'vk3', 'vk4', 'vk5', 'gueltig_ab',
               'gueltig_bis', 'art', 'notiz'}
    sets, params = [], []
    for k, v in (felder or {}).items():
        if k in erlaubt:
            sets.append(f"{k}=%s")
            params.append(v if v not in ('',) else None)
    if not sets:
        return
    sets.append("geaend=NOW()")
    sets.append("geaend_name=%s")
    params.append((ma_name or 'CAO-XT')[:50])
    params.append(int(rec_id))
    with get_db_transaction() as cur:
        cur.execute(f"UPDATE XT_ARTIKEL_PREISPLAN SET {', '.join(sets)} "
                    f"WHERE rec_id=%s AND status IN ('geplant','aktiv')",
                    params)


def loeschen(rec_id: int) -> None:
    with get_db_transaction() as cur:
        cur.execute("DELETE FROM XT_ARTIKEL_PREISPLAN WHERE rec_id=%s",
                    (int(rec_id),))


def schild_setzen(rec_id: int, gedruckt: bool = True) -> None:
    with get_db_transaction() as cur:
        cur.execute("UPDATE XT_ARTIKEL_PREISPLAN SET schild_gedruckt=%s "
                    "WHERE rec_id=%s", (1 if gedruckt else 0, int(rec_id)))


# ── Anwenden / Rückgängig (schreibt in CAO) ────────────────────────────

def _vk_setzen(cur, artikel_id: int, vk_netto: list, rate: float,
               ma: str) -> None:
    """ARTIKEL.VK1..5 (netto) + VK1B..5B (brutto) setzen, Record-Lock."""
    with cao_record_lock(cur, MODUL_ID_ARTIKEL, int(artikel_id)):
        sets = []
        params: list[Any] = []
        for i, v in enumerate(vk_netto, start=1):
            if v is None:
                continue
            brutto = round(float(v) * (1.0 + rate), 4)
            sets.append(f"VK{i}=%s")
            sets.append(f"VK{i}B=%s")
            params += [float(v), brutto]
        if sets:
            sets.append("GEAEND=NOW()")
            sets.append("GEAEND_NAME=%s")
            params.append(ma)
            params.append(int(artikel_id))
            cur.execute(f"UPDATE ARTIKEL SET {', '.join(sets)} "
                        f"WHERE REC_ID=%s", params)


def anwenden(rec_id: int, *, ma_name: str = 'CAO-XT') -> dict[str, Any]:
    """Geplante Änderung jetzt in CAO schreiben."""
    ma = (ma_name or 'CAO-XT')[:50]
    with get_db_transaction() as cur:
        p = _holen(cur, rec_id)
        if not p:
            raise LookupError('Planeintrag nicht gefunden')
        aid = int(p['artikel_id'])
        vk = [p[f] for f in VK_FELDER]
        cur.execute("SELECT VK1,VK2,VK3,VK4,VK5,VK1B,VK2B,VK3B,VK4B,VK5B,"
                    "STEUER_CODE FROM ARTIKEL WHERE REC_ID=%s", (aid,))
        a = cur.fetchone() or {}
    if p['art'] == 'aktion':
        art.aktionspreis_speichern(aid, vk, p['gueltig_ab'],
                                   p.get('gueltig_bis'), ma_name=ma)
    else:  # dauerhafte Preisänderung
        vorher = {k: (float(a[k]) if a.get(k) is not None else None)
                  for k in ('VK1', 'VK2', 'VK3', 'VK4', 'VK5',
                            'VK1B', 'VK2B', 'VK3B', 'VK4B', 'VK5B')}
        with get_db_transaction() as cur:
            _vk_setzen(cur, aid, vk, _rate(a.get('STEUER_CODE')), ma)
            cur.execute("UPDATE XT_ARTIKEL_PREISPLAN SET vorher_json=%s "
                        "WHERE rec_id=%s", (json.dumps(vorher), int(rec_id)))
    with get_db_transaction() as cur:
        cur.execute("UPDATE XT_ARTIKEL_PREISPLAN SET status='aktiv', "
                    "angewendet_am=NOW(), geaend=NOW(), geaend_name=%s "
                    "WHERE rec_id=%s", (ma, int(rec_id)))
    return {'rec_id': int(rec_id), 'artikel_id': aid, 'art': p['art']}


def zuruecksetzen(rec_id: int, *, ma_name: str = 'CAO-XT') -> None:
    """Angewendete Änderung rückgängig machen (Aktion entfernen bzw.
    dauerhaften Preis aus vorher_json wiederherstellen)."""
    ma = (ma_name or 'CAO-XT')[:50]
    with get_db_transaction() as cur:
        p = _holen(cur, rec_id)
    if not p:
        raise LookupError('Planeintrag nicht gefunden')
    aid = int(p['artikel_id'])
    if p['art'] == 'aktion':
        art.aktionspreis_speichern(aid, [0] * 5, None, None, ma_name=ma)
    elif p.get('vorher_json'):
        vor = json.loads(p['vorher_json'])
        with get_db_transaction() as cur:
            with cao_record_lock(cur, MODUL_ID_ARTIKEL, aid):
                cur.execute(
                    "UPDATE ARTIKEL SET VK1=%s,VK2=%s,VK3=%s,VK4=%s,VK5=%s,"
                    "VK1B=%s,VK2B=%s,VK3B=%s,VK4B=%s,VK5B=%s,GEAEND=NOW(),"
                    "GEAEND_NAME=%s WHERE REC_ID=%s",
                    (vor.get('VK1'), vor.get('VK2'), vor.get('VK3'),
                     vor.get('VK4'), vor.get('VK5'), vor.get('VK1B'),
                     vor.get('VK2B'), vor.get('VK3B'), vor.get('VK4B'),
                     vor.get('VK5B'), ma, aid))
    with get_db_transaction() as cur:
        cur.execute("UPDATE XT_ARTIKEL_PREISPLAN SET status='storniert', "
                    "geaend=NOW(), geaend_name=%s WHERE rec_id=%s",
                    (ma, int(rec_id)))


def faellige_anwenden(stichtag: date | None = None, *,
                      ma_name: str = 'Preisplan-Auto') -> dict[str, int]:
    """Engine für Auto-Anwendung (Timer/Poller): fällige geplante
    Änderungen anwenden, abgelaufene Aktionen beenden."""
    stichtag = stichtag or date.today()
    angewendet = beendet = 0
    with get_db() as cur:
        cur.execute("SELECT rec_id FROM XT_ARTIKEL_PREISPLAN "
                    "WHERE status='geplant' AND gueltig_ab<=%s", (stichtag,))
        faellig = [r['rec_id'] for r in cur.fetchall()]
    for rid in faellig:
        try:
            anwenden(rid, ma_name=ma_name)
            angewendet += 1
        except Exception:  # noqa: BLE001
            log.exception("Preisplan #%s anwenden fehlgeschlagen", rid)
    # Abgelaufene Aktionen beenden (CAO-Aktionspreis entfernen)
    with get_db() as cur:
        cur.execute("SELECT rec_id FROM XT_ARTIKEL_PREISPLAN "
                    "WHERE status='aktiv' AND art='aktion' "
                    "AND gueltig_bis IS NOT NULL AND gueltig_bis<%s",
                    (stichtag,))
        ablauf = [r['rec_id'] for r in cur.fetchall()]
    for rid in ablauf:
        try:
            p = None
            with get_db() as cur:
                p = _holen(cur, rid)
            if p:
                art.aktionspreis_speichern(int(p['artikel_id']), [0] * 5,
                                           None, None, ma_name=ma_name)
            with get_db_transaction() as cur:
                cur.execute("UPDATE XT_ARTIKEL_PREISPLAN SET status='beendet',"
                            " geaend=NOW(), geaend_name=%s WHERE rec_id=%s",
                            (ma_name, rid))
            beendet += 1
        except Exception:  # noqa: BLE001
            log.exception("Preisplan #%s beenden fehlgeschlagen", rid)
    if angewendet or beendet:
        log.info("Preisplan: %s angewendet, %s beendet (Stichtag %s)",
                 angewendet, beendet, stichtag)
    return {'angewendet': angewendet, 'beendet': beendet}
