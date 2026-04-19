"""HACCP-Flask-Blueprint (UI im WaWi-App-Host).

URL-Praefix: ``/wawi/haccp``.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, jsonify, Response)

from . import models as m
from . import backfill as bf
from .tfa_client import TFAClient
from modules.wawi.personal.auth import backoffice_required


bp = Blueprint('haccp', __name__, template_folder=None)


def create_blueprint() -> Blueprint:
    return bp


def _tfa_client() -> TFAClient | None:
    """Baut einen Client anhand des globalen App-Configs (selber Weg wie
    der Poller). None wenn kein Key konfiguriert."""
    try:
        import config as wc  # wawi-app/app/config.py
    except ImportError:
        return None
    key = getattr(wc, 'TFA_API_KEY', '') or ''
    if not key:
        return None
    base = getattr(wc, 'TFA_BASE_URL', 'https://go.tfa.me')
    return TFAClient(key, base_url=base)


def _parse_datum(s: str) -> date | None:
    """Akzeptiert ISO (YYYY-MM-DD) UND deutsch (TT.MM.JJJJ). Leer -> None."""
    s = (s or '').strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    try:
        return datetime.strptime(s, '%d.%m.%Y').date()
    except ValueError:
        return None


def _parse_datetime(s: str) -> datetime | None:
    """Akzeptiert ISO (YYYY-MM-DD[THH:MM[:SS]]) UND deutsch (TT.MM.JJJJ [HH:MM])."""
    s = (s or '').strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ('%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M', '%d.%m.%Y'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── Dashboard ────────────────────────────────────────────────────────

def _status_fuer_temp(temp: float | None, grenz: dict | None) -> str:
    """Liefert 'ok' | 'warn' | 'alarm' je nach Distanz zu den Grenzen.
    'warn' = innerhalb 20%-Puffer zu einer der Grenzen (gelber Korridor)."""
    if temp is None or not grenz:
        return 'ok'
    t_min = float(grenz['TEMP_MIN_C'])
    t_max = float(grenz['TEMP_MAX_C'])
    if temp > t_max or temp < t_min:
        return 'alarm'
    puffer = (t_max - t_min) * 0.15
    if temp > t_max - puffer or temp < t_min + puffer:
        return 'warn'
    return 'ok'


def _dashboard_kacheln(jetzt):
    geraete = m.geraete_liste(nur_aktive=True)
    kacheln = []
    heute_alle = m.sichtkontrolle_heute_alle()
    for g in geraete:
        letzte = m.messwerte_letzte(int(g['GERAET_ID']), 1)
        grenz  = m.grenzwerte_aktuell(int(g['GERAET_ID']))
        letzter = letzte[0] if letzte else None
        status = 'ok'
        alter_min = None
        if letzter:
            alter_min = int((jetzt - letzter['ZEITPUNKT_UTC']).total_seconds() / 60)
            if grenz:
                stale_min = int(grenz['STALE_MIN'])
                if alter_min >= stale_min:
                    status = 'offline'
                elif letzter['TEMP_C'] is not None:
                    t = float(letzter['TEMP_C'])
                    if t > float(grenz['TEMP_MAX_C']) or t < float(grenz['TEMP_MIN_C']):
                        status = 'warn'
            elif alter_min >= 60:
                status = 'offline'
        else:
            status = 'offline'
        kacheln.append({
            'geraet': g, 'letzter': letzter, 'grenz': grenz,
            'status': status, 'alter_min': alter_min,
            'heute_quittiert': int(g['GERAET_ID']) in heute_alle,
        })
    return kacheln


@bp.get('/')
@backoffice_required
def dashboard():
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    return render_template('haccp/dashboard.html',
                           kacheln=_dashboard_kacheln(jetzt),
                           offene_alarme=m.alarme_offen_alle(),
                           poller_status=m.poller_status_lesen(),
                           jetzt_utc=jetzt)


# ── Sichtkontroll-Dashboard (14+ Geraete auf einen Blick) ────────────

@bp.get('/sichtkontrolle')
@backoffice_required
def sichtkontrolle_dashboard():
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    return render_template('haccp/sichtkontrolle.html',
                           kacheln=_dashboard_kacheln(jetzt),
                           jetzt_utc=jetzt)


@bp.post('/sichtkontrolle/bulk')
@backoffice_required
def sichtkontrolle_bulk():
    ma_id = int(session.get('ma_id') or 0)
    gids = [int(v) for v in request.form.getlist('geraet_id') if v.isdigit()]
    bem = request.form.get('bemerkung', '').strip() or None
    neu = 0
    for gid in gids:
        if m.sichtkontrolle_quittieren(gid, ma_id, bemerkung=bem):
            neu += 1
    flash(f'{neu} Sichtkontrolle(n) quittiert '
          f'({len(gids) - neu} waren schon quittiert).', 'ok')
    return redirect(url_for('haccp.sichtkontrolle_dashboard'))


# ── Multi-Sensor-Chart (alle Kurven auf einmal) ──────────────────────

@bp.get('/chart.json')
@backoffice_required
def multi_chart_json():
    """Zeitreihen aller aktiven Sensoren fuer das Startseiten-Diagramm.
    Liefert je Sensor: name, farbe, punkte [{t, v, status}]."""
    stunden = int(request.args.get('stunden', 24))
    stunden = max(1, min(stunden, 720))  # zwischen 1 Stunde und 30 Tagen
    bis = datetime.now(timezone.utc).replace(tzinfo=None)
    von = bis - timedelta(hours=stunden)

    # Farben als goldene-Winkel-Hues fuer maximale Unterscheidbarkeit
    def hue(i): return (i * 137.508) % 360

    datasets = []
    for i, g in enumerate(m.geraete_liste(nur_aktive=True)):
        gid = int(g['GERAET_ID'])
        grenz = m.grenzwerte_aktuell(gid)
        werte = m.messwerte_zeitraum(gid, von, bis)
        punkte = []
        for w in werte:
            if w['TEMP_C'] is None or w['NO_CONNECTION']:
                continue
            t = float(w['TEMP_C'])
            punkte.append({
                't': w['ZEITPUNKT_UTC'].isoformat() + 'Z',
                'v': t,
                's': _status_fuer_temp(t, grenz),
            })
        datasets.append({
            'geraet_id': gid,
            'name': g['NAME'],
            'standort': g.get('STANDORT') or '',
            'hue': round(hue(i), 1),
            'grenz_min': float(grenz['TEMP_MIN_C']) if grenz else None,
            'grenz_max': float(grenz['TEMP_MAX_C']) if grenz else None,
            'punkte': punkte,
        })
    return jsonify({'von': von.isoformat() + 'Z',
                    'bis': bis.isoformat() + 'Z',
                    'datasets': datasets})


# ── Geraet Detail + Zeitreihe ────────────────────────────────────────

@bp.get('/<int:geraet_id>')
@backoffice_required
def geraet_detail(geraet_id: int):
    geraet = m.geraet_by_id(geraet_id)
    if not geraet:
        flash('Geraet nicht gefunden.', 'error')
        return redirect(url_for('haccp.dashboard'))
    grenz = m.grenzwerte_aktuell(geraet_id)
    heute_quittung = m.sichtkontrolle_heute(geraet_id)
    alarme = m.alarm_history(geraet_id, limit=50)
    letzte = m.messwerte_letzte(geraet_id, 1)
    letzter_mw = letzte[0] if letzte else None
    return render_template('haccp/detail.html',
                           geraet=geraet, grenz=grenz,
                           heute_quittung=heute_quittung,
                           alarme=alarme,
                           letzter_mw=letzter_mw)


@bp.get('/<int:geraet_id>/messwerte.json')
@backoffice_required
def messwerte_json(geraet_id: int):
    """Zeitreihe fuer Chart.js. Default: letzte 7 Tage.
    Akzeptiert ISO ``YYYY-MM-DDTHH:MM:SS`` und deutsch ``TT.MM.JJJJ``."""
    von_raw = request.args.get('von', '')
    bis_raw = request.args.get('bis', '')
    bis = _parse_datetime(bis_raw) if bis_raw else datetime.now(timezone.utc).replace(tzinfo=None)
    von = _parse_datetime(von_raw) if von_raw else (bis - timedelta(days=7)) if bis else None
    if bis is None or von is None:
        return jsonify({'error': 'ungueltige Zeitangabe'}), 400
    werte = m.messwerte_zeitraum(geraet_id, von, bis)
    grenz = m.grenzwerte_aktuell(geraet_id)
    return jsonify({
        'labels': [w['ZEITPUNKT_UTC'].isoformat() + 'Z' for w in werte],
        'temp':   [float(w['TEMP_C']) if w['TEMP_C'] is not None and not w['NO_CONNECTION'] else None
                   for w in werte],
        'feuchte':[float(w['FEUCHTE_PCT']) if w['FEUCHTE_PCT'] is not None else None
                   for w in werte],
        'grenz':  {'min': float(grenz['TEMP_MIN_C']) if grenz else None,
                   'max': float(grenz['TEMP_MAX_C']) if grenz else None},
    })


# ── Stammdaten / Grenzwerte bearbeiten ───────────────────────────────

@bp.post('/<int:geraet_id>/update')
@backoffice_required
def geraet_update(geraet_id: int):
    felder = {k: (v.strip() or None) if isinstance(v, str) else v
              for k, v in request.form.items()
              if k in ('NAME', 'STANDORT', 'WARENGRUPPE', 'BEMERKUNG')}
    aktiv = request.form.get('AKTIV')
    if aktiv is not None:
        felder['AKTIV'] = 1 if aktiv in ('1', 'on', 'true') else 0
    kal_raw = request.form.get('LETZTE_KALIBRIERUNG', '').strip()
    if kal_raw:
        kal = _parse_datum(kal_raw)
        if kal is None:
            flash('Ungueltiges Kalibrierungs-Datum (erwartet TT.MM.JJJJ).', 'error')
            return redirect(url_for('haccp.geraet_detail', geraet_id=geraet_id))
        felder['LETZTE_KALIBRIERUNG'] = kal
    elif 'LETZTE_KALIBRIERUNG' in request.form:
        felder['LETZTE_KALIBRIERUNG'] = None
    n = m.geraet_update(geraet_id, felder)
    flash(f'{n} Feld(er) aktualisiert.', 'ok')
    return redirect(url_for('haccp.geraet_detail', geraet_id=geraet_id))


@bp.post('/<int:geraet_id>/grenzwerte')
@backoffice_required
def grenzwerte_setzen(geraet_id: int):
    try:
        temp_min = float(request.form.get('temp_min', '').replace(',', '.'))
        temp_max = float(request.form.get('temp_max', '').replace(',', '.'))
        karenz   = int(request.form.get('karenz_min', 15))
        stale    = int(request.form.get('stale_min', 30))
        drift_aktiv = bool(request.form.get('drift_aktiv'))
        drift_k  = request.form.get('drift_k', '').replace(',', '.').strip()
        drift_k_f = float(drift_k) if drift_k else None
        drift_h  = int(request.form.get('drift_fenster_h', 24))
        m.grenzwerte_setzen(
            geraet_id,
            temp_min=temp_min, temp_max=temp_max,
            karenz_min=karenz, stale_min=stale,
            drift_aktiv=drift_aktiv, drift_k=drift_k_f, drift_fenster_h=drift_h,
            erstellt_von=int(session.get('ma_id') or 0),
            bemerkung=request.form.get('bemerkung', '').strip() or None,
        )
        flash('Grenzwerte gespeichert.', 'ok')
    except (ValueError, TypeError) as e:
        flash(f'Fehler: {e}', 'error')
    return redirect(url_for('haccp.geraet_detail', geraet_id=geraet_id))


# ── Sichtkontrolle ───────────────────────────────────────────────────

@bp.post('/<int:geraet_id>/sichtkontrolle')
@backoffice_required
def sichtkontrolle(geraet_id: int):
    ma_id = int(session.get('ma_id') or 0)
    bem = request.form.get('bemerkung', '').strip() or None
    if m.sichtkontrolle_quittieren(geraet_id, ma_id, bemerkung=bem):
        flash('Sichtkontrolle quittiert.', 'ok')
    else:
        flash('Heute schon quittiert.', 'info')
    naechster = request.form.get('next') or url_for('haccp.geraet_detail',
                                                    geraet_id=geraet_id)
    return redirect(naechster)


# ── Alarm-Korrekturmassnahme ─────────────────────────────────────────

@bp.post('/alarm/<int:alarm_id>/korrektur')
@backoffice_required
def alarm_korrektur(alarm_id: int):
    text = request.form.get('text', '').strip()
    try:
        m.alarm_korrektur_eintragen(alarm_id, text,
                                    int(session.get('ma_id') or 0))
        flash('Korrekturmassnahme gespeichert.', 'ok')
    except ValueError as e:
        flash(str(e), 'error')
    ziel = request.form.get('next') or url_for('haccp.alarme')
    return redirect(ziel)


@bp.get('/alarme')
@backoffice_required
def alarme():
    return render_template('haccp/alarme.html',
                           offen=m.alarme_offen_alle(),
                           history=m.alarm_history(limit=100),
                           now_utc=datetime.now(timezone.utc).replace(tzinfo=None))


# ── Alarmkette (Empfaenger-Konfiguration) ────────────────────────────

@bp.get('/alarmkette')
@backoffice_required
def alarmkette_view():
    return render_template('haccp/alarmkette.html',
                           eintraege=m.alarmkette_aktiv())


@bp.post('/alarmkette/anlegen')
@backoffice_required
def alarmkette_anlegen():
    try:
        m.alarmkette_anlegen(
            stufe=int(request.form.get('stufe', 1)),
            name=request.form.get('name', ''),
            email=request.form.get('email', ''),
            delay_min=int(request.form.get('delay_min', 0)),
        )
        flash('Empfaenger hinzugefuegt.', 'ok')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('haccp.alarmkette_view'))


@bp.post('/alarmkette/<int:rec_id>/loeschen')
@backoffice_required
def alarmkette_loeschen(rec_id: int):
    m.alarmkette_loeschen(rec_id)
    flash('Empfaenger entfernt.', 'ok')
    return redirect(url_for('haccp.alarmkette_view'))


# ── Backfill: Historie aus TFA-Cloud holen ───────────────────────────
#
# Die TFA-API liefert max. 7 Tage pro Request (Rate-Limit: 10/h). Wir
# persistieren idempotent via `messwert_insert` (UNIQUE geraet+zeit),
# doppelte Werte kommen also nicht in die DB.
# Use-cases: (a) Stromausfall-Nachholen, (b) Initialisierung nach dem
# Anlernen eines neuen Sensors.

def _backfill_ausfuehren(device_ids: list[str], tage: int
                         ) -> tuple[int, int, list[str]]:
    """Liefert (gefunden, neu, fehler_strings). Fasst alle Geraete in einem
    API-Call zusammen (API akzeptiert deviceIDs-Array)."""
    tage = max(1, min(int(tage), bf.MAX_TAGE_PRO_CALL))
    bis = datetime.now(timezone.utc).replace(tzinfo=None)
    von = bis - timedelta(days=tage)
    client = _tfa_client()
    if not client:
        return 0, 0, ['TFA_API_KEY ist nicht konfiguriert.']
    return bf.nachholen(client, device_ids, von, bis)


@bp.post('/backfill')
@backoffice_required
def backfill_alle():
    """Holt fuer alle aktiven Geraete die letzten N Tage (max 7) aus der Cloud."""
    tage = int(request.form.get('tage', 7) or 7)
    geraete = m.geraete_liste(nur_aktive=True)
    dev_ids = sorted({g['TFA_DEVICE_ID'] for g in geraete if g.get('TFA_DEVICE_ID')})
    if not dev_ids:
        flash('Keine aktiven Geräte mit TFA-Device-ID.', 'info')
        return redirect(url_for('haccp.dashboard'))
    gefunden, neu, fehler = _backfill_ausfuehren(dev_ids, tage)
    if fehler:
        flash('TFA-Fehler: ' + '; '.join(fehler), 'error')
    else:
        flash(f'Historie ({tage} T.) geladen: {gefunden} Messwerte in der Cloud, '
              f'{neu} davon neu in unserer DB ({gefunden - neu} schon vorhanden).',
              'ok')
    return redirect(url_for('haccp.dashboard'))


@bp.post('/<int:geraet_id>/backfill')
@backoffice_required
def backfill_geraet(geraet_id: int):
    """Holt fuer EIN Geraet die letzten N Tage aus der Cloud."""
    tage = int(request.form.get('tage', 7) or 7)
    g = m.geraet_by_id(geraet_id)
    if not g or not g.get('TFA_DEVICE_ID'):
        flash('Geraet hat keine TFA-Device-ID.', 'error')
        return redirect(url_for('haccp.geraet_detail', geraet_id=geraet_id))
    gefunden, neu, fehler = _backfill_ausfuehren([g['TFA_DEVICE_ID']], tage)
    if fehler:
        flash('TFA-Fehler: ' + '; '.join(fehler), 'error')
    else:
        flash(f'Historie ({tage} T.) geladen: {gefunden} Messwerte, '
              f'{neu} davon neu.', 'ok')
    return redirect(url_for('haccp.geraet_detail', geraet_id=geraet_id))


# ── Export CSV ───────────────────────────────────────────────────────

@bp.get('/<int:geraet_id>/export.csv')
@backoffice_required
def export_csv(geraet_id: int):
    von_raw = request.args.get('von')
    bis_raw = request.args.get('bis')
    bis = _parse_datetime(bis_raw) if bis_raw else datetime.now(timezone.utc).replace(tzinfo=None)
    von = _parse_datetime(von_raw) if von_raw else (bis - timedelta(days=30)) if bis else None
    if bis is None or von is None:
        return 'ungueltige Zeitangabe', 400
    werte = m.messwerte_zeitraum(geraet_id, von, bis)
    geraet = m.geraet_by_id(geraet_id) or {}
    grenz  = m.grenzwerte_aktuell(geraet_id) or {}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['Geraet', 'Standort', 'Warengruppe',
                'Grenz_min_C', 'Grenz_max_C'])
    w.writerow([geraet.get('NAME', ''), geraet.get('STANDORT', ''),
                geraet.get('WARENGRUPPE', ''),
                grenz.get('TEMP_MIN_C', ''), grenz.get('TEMP_MAX_C', '')])
    w.writerow([])
    w.writerow(['Zeitpunkt_UTC', 'Temp_C', 'Feuchte_%',
                'Battery_Low', 'Kein_Signal'])
    for v in werte:
        w.writerow([
            v['ZEITPUNKT_UTC'].isoformat(),
            f"{float(v['TEMP_C']):.2f}".replace('.', ',') if v['TEMP_C'] is not None else '',
            f"{float(v['FEUCHTE_PCT']):.1f}".replace('.', ',') if v['FEUCHTE_PCT'] is not None else '',
            '1' if v['BATTERY_LOW'] else '',
            '1' if v['NO_CONNECTION'] else '',
        ])
    fname = f'haccp-{geraet.get("NAME", geraet_id)}-{von.date()}_{bis.date()}.csv'
    return Response(
        buf.getvalue().encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )
