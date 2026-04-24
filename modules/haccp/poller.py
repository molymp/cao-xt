"""Standalone-Poller: holt zyklisch TFA-Messwerte, persistiert, triggert Alarme.

Start:
    cd repo-root
    python -m modules.haccp.poller

Konfig ueber ``orga-app/app/config.py`` (``TFA_API_KEY``, ``HACCP_POLL_INTERVALL_S``).
Beenden mit Ctrl-C (oder systemd stop).
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

# App-Config laden (DB-Credentials + TFA-Key)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'orga-app', 'app'))
sys.path.insert(0, _REPO_ROOT)

import config as wc  # noqa: E402

from common.db import init_pool  # noqa: E402
from common.email import email_senden  # noqa: E402
from modules.haccp import backfill as bf  # noqa: E402
from modules.haccp import models as m  # noqa: E402
from modules.haccp.alarm_engine import Aktion, AktionTyp, auswerten  # noqa: E402
from modules.haccp.tfa_client import TFAClient, TFAError  # noqa: E402


log = logging.getLogger('haccp.poller')
_LAUFT = True

# Wie alt darf der letzte Heartbeat sein, bevor wir beim Start einen
# Auto-Backfill triggern? Normal laeuft der Poller im Sekunden- bis
# Minuten-Takt; wenn er > 15 min nichts geschrieben hat, hatte er einen
# Ausfall, und wir versuchen die Luecke aus der TFA-Cloud nachzuladen.
_BACKFILL_SCHWELLE_MIN = 15


def _stop_handler(signum, frame):
    global _LAUFT
    log.info('Signal %s -> beende Poller', signum)
    _LAUFT = False


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-5s %(name)s: %(message)s',
    )
    if not wc.TFA_API_KEY:
        log.error('TFA_API_KEY nicht konfiguriert. Siehe config_local.py.')
        return 2

    init_pool('haccp_poller_pool', pool_size=3, db_config={
        'host': wc.DB_HOST, 'port': wc.DB_PORT,
        'name': wc.DB_NAME, 'user': wc.DB_USER, 'password': wc.DB_PASSWORD,
    })

    client = TFAClient(wc.TFA_API_KEY, base_url=wc.TFA_BASE_URL)
    if not client.ping():
        log.error('TFA-API nicht erreichbar (Ping fehlgeschlagen). Abbruch.')
        return 3

    signal.signal(signal.SIGINT,  _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    # Nach Ausfall: Luecke seit letztem erfolgreichen Heartbeat aus der
    # Cloud nachladen. Tolerant gegen Fehler — Poller startet trotzdem.
    try:
        _auto_backfill(client)
    except Exception:
        log.exception('Auto-Backfill fehlgeschlagen — Poller laeuft weiter.')

    log.info('Poller gestartet. Intervall %s s.', wc.HACCP_POLL_INTERVALL_S)
    while _LAUFT:
        start = time.monotonic()
        try:
            _einen_zyklus(client)
        except Exception:
            log.exception('Fehler im Poll-Zyklus.')
        dauer = time.monotonic() - start
        warte = max(5, wc.HACCP_POLL_INTERVALL_S - int(dauer))
        for _ in range(warte):
            if not _LAUFT:
                break
            time.sleep(1)
    log.info('Poller gestoppt.')
    return 0


def _auto_backfill(client: TFAClient) -> None:
    """Nach Ausfall: Luecke seit letztem erfolgreichen Heartbeat holen.

    - Erstlauf (kein LAST_SUCCESS_AT) -> nichts tun; der Poller beginnt
      einfach live zu pollen.
    - Heartbeat < ``_BACKFILL_SCHWELLE_MIN`` alt -> nichts tun (normaler
      Restart, keine Luecke).
    - Aelter -> ``bf.nachholen_ab`` ab LAST_SUCCESS_AT, gekappt aufs
      API-Limit (max 7 Tage — aeltere Luecken sind nicht mehr
      rekonstruierbar).
    """
    ps = m.poller_status_lesen()
    last_ok: datetime | None = (ps or {}).get('LAST_SUCCESS_AT') if ps else None
    if not last_ok:
        log.info('Auto-Backfill: kein vorheriger Heartbeat — Erstlauf, '
                 'nichts nachzuholen.')
        return
    alter = datetime.now(timezone.utc).replace(tzinfo=None) - last_ok
    if alter < timedelta(minutes=_BACKFILL_SCHWELLE_MIN):
        log.info('Auto-Backfill: letzter Heartbeat %s min alt — kein '
                 'Ausfall, nichts nachzuholen.',
                 int(alter.total_seconds() // 60))
        return

    geraete = m.geraete_liste(nur_aktive=True)
    dev_ids = sorted({g['TFA_DEVICE_ID'] for g in geraete
                      if g.get('TFA_DEVICE_ID')})
    if not dev_ids:
        log.info('Auto-Backfill: keine aktiven Geraete mit TFA-Device-ID.')
        return

    kappe_tage = bf.MAX_TAGE_PRO_CALL
    log.info('Auto-Backfill: Ausfall erkannt (Heartbeat %s h alt), hole '
             'Luecke fuer %s Geraete aus der Cloud (max %s Tage).',
             round(alter.total_seconds() / 3600, 1), len(dev_ids), kappe_tage)
    gefunden, neu, fehler = bf.nachholen_ab(client, dev_ids, last_ok,
                                            max_tage=kappe_tage)
    if fehler:
        log.warning('Auto-Backfill: %s Chunk-Fehler: %s',
                    len(fehler), '; '.join(fehler))
    log.info('Auto-Backfill fertig: %s Messwerte in der Cloud, %s davon '
             'neu in unserer DB (%s waren schon vorhanden).',
             gefunden, neu, gefunden - neu)


def _einen_zyklus(client: TFAClient) -> None:
    """Ein Durchlauf: Messwerte ziehen, persistieren, Alarme evaluieren.
    Schreibt am Ende Heartbeat (Erfolg/Fehler) in XT_HACCP_POLLER_STATUS."""
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    host = socket.gethostname()
    neu_count = 0
    try:
        messwerte = client.aktuelle_messwerte()
    except TFAError as e:
        log.warning('TFA-Abruf fehlgeschlagen: %s', e)
        m.poller_status_schreiben(tfa_ok=False, last_error=str(e),
                                  neu_entdeckt=0, hostname=host)
        return

    # Auto-Discovery neuer Sensoren: wenn TFA eine Device-ID liefert, die wir
    # noch nicht kennen, legen wir einen Platzhalter-Geraet an. Benutzer
    # pflegt Namen/Standort/Warengruppe spaeter im UI.
    # Zusaetzlich: API-Metadaten (id, name, measurementInterval) in die DB
    # spiegeln, falls sie sich geaendert haben.
    for mw in messwerte:
        g = m.geraet_by_tfa(mw.device_id, mw.sensor_index)
        if not g:
            gid = m.geraet_anlegen(
                mw.device_id,
                name=mw.device_name or f'Neu: {mw.device_id}/{mw.sensor_index}',
                sensor_index=mw.sensor_index,
                tfa_internal_id=mw.internal_id,
                tfa_name=mw.device_name,
                tfa_messintervall_s=mw.mess_intervall_s,
            )
            neu_count += 1
            log.info('Neues Geraet entdeckt: %s (idx %s) -> GERAET_ID %s',
                     mw.device_id, mw.sensor_index, gid)
        else:
            gid = int(g['GERAET_ID'])
            # Nur updaten, wenn die API-Werte sich geaendert haben (vermeidet
            # ungebrauchte Writes pro Zyklus).
            updates: dict = {}
            if mw.internal_id and mw.internal_id != g.get('TFA_INTERNAL_ID'):
                updates['tfa_internal_id'] = mw.internal_id
            if mw.device_name and mw.device_name != g.get('TFA_NAME'):
                updates['tfa_name'] = mw.device_name
            if mw.mess_intervall_s and \
                    mw.mess_intervall_s != g.get('TFA_MESSINTERVALL_S'):
                updates['tfa_messintervall_s'] = mw.mess_intervall_s
            if updates:
                m.geraet_tfa_metadata_aktualisieren(gid, **updates)

        neu = m.messwert_insert(
            gid, mw.zeitpunkt_utc,
            temp_c=mw.temp_c, feuchte_pct=mw.feuchte_pct,
            battery_low=mw.battery_low, no_connection=mw.no_connection,
            transmission_counter=mw.transmission_counter,
        )
        if neu:
            log.debug('Messwert %s idx%s @ %s temp=%s tx#=%s',
                      mw.device_id, mw.sensor_index, mw.zeitpunkt_utc,
                      mw.temp_c, mw.transmission_counter)

    # Alarm-Evaluation pro aktivem Geraet
    alarmkette = m.alarmkette_aktiv()
    for g in m.geraete_liste(nur_aktive=True):
        grenz = m.grenzwerte_aktuell(int(g['GERAET_ID']))
        aktionen = auswerten(g, grenz or {}, jetzt, alarmkette=alarmkette)
        for a in aktionen:
            _aktion_ausfuehren(a, g, grenz or {}, alarmkette)

    m.poller_status_schreiben(tfa_ok=True, last_error=None,
                              neu_entdeckt=neu_count, hostname=host)


def _aktion_ausfuehren(a: Aktion, geraet: dict, grenz: dict,
                       alarmkette: list[dict]) -> None:
    if a.typ == AktionTyp.OEFFNEN:
        alarm_id = m.alarm_oeffnen(a.geraet_id, a.alarm_typ,
                                   a.start_at or datetime.now(timezone.utc).replace(tzinfo=None),
                                   max_wert=a.wert)
        log.warning('ALARM auf: %s (%s) dev=%s wert=%s',
                    a.alarm_typ, alarm_id, geraet['NAME'], a.wert)
        # Stufe-1 Empfaenger mit DELAY_MIN=0 sofort benachrichtigen
        stufe1_sofort = [e for e in alarmkette
                         if int(e['STUFE']) == 1 and int(e['DELAY_MIN']) == 0]
        if stufe1_sofort:
            _mail_stufe(alarm_id, 1, stufe1_sofort, geraet, grenz, a)

    elif a.typ == AktionTyp.SCHLIESSEN:
        m.alarm_schliessen(int(a.alarm_id),
                           a.ende_at or datetime.now(timezone.utc).replace(tzinfo=None))
        log.info('ALARM zu: %s id=%s dev=%s', a.alarm_typ, a.alarm_id,
                 geraet['NAME'])

    elif a.typ == AktionTyp.ESKALIEREN:
        empf = [e for e in alarmkette if int(e['STUFE']) == a.stufe]
        if empf:
            _mail_stufe(int(a.alarm_id), int(a.stufe), empf, geraet, grenz, a)
            m.alarm_stufe_setzen(int(a.alarm_id), int(a.stufe))


def _mail_stufe(alarm_id: int, stufe: int, empfaenger: list[dict],
                geraet: dict, grenz: dict, aktion: Aktion) -> None:
    typ = aktion.alarm_typ or '?'
    betreff = (f'[HACCP Stufe {stufe}] {geraet["NAME"]}: {typ}')
    standort = geraet.get('STANDORT') or '—'
    warengruppe = geraet.get('WARENGRUPPE') or '—'
    soll = ''
    if grenz:
        soll = (f"{float(grenz['TEMP_MIN_C']):.1f} °C … "
                f"{float(grenz['TEMP_MAX_C']):.1f} °C  "
                f"(Karenz {int(grenz['KARENZ_MIN'])} min)")
    wert = f'{aktion.wert:.1f} °C' if aktion.wert is not None else '—'
    text = (f"HACCP-Alarm Stufe {stufe}\n"
            f"Geraet:      {geraet['NAME']}\n"
            f"Standort:    {standort}\n"
            f"Warengruppe: {warengruppe}\n"
            f"Alarm-Typ:   {typ}\n"
            f"Akt. Wert:   {wert}\n"
            f"Soll-Range:  {soll}\n"
            f"Seit:        {aktion.start_at.isoformat() if aktion.start_at else '?'}\n\n"
            f"Bitte Anlage pruefen und im HACCP-Modul die Korrekturmassnahme eintragen.\n")
    for e in empfaenger:
        r = email_senden(e['EMAIL'], betreff, text)
        erfolg = r.get('modus') == 'ok'
        m.eskalation_loggen(alarm_id, stufe, e['EMAIL'], erfolg,
                            None if erfolg else r.get('fehler'))
        log.info('Mail Stufe %s an %s: %s', stufe, e['EMAIL'], r.get('modus'))


if __name__ == '__main__':
    sys.exit(main())
