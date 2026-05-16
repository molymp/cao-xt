"""
CAO-XT – Einkauf-Poller (Phase 2b)

Standalone-Daemon, der zyklisch das verbundene Gmail-Postfach nach
neuen Bestellbestaetigungen durchsucht (siehe ``common.einkauf``).

Start (manuell, fuer Tests):
    cd <repo-root>
    python -m installer.einkauf_poller

Im Live-Betrieb wird der Daemon vom ``installer.app_manager`` als
``einkauf-poller`` gestartet (``dorfkern-ctl start einkauf-poller``).

Konfiguration (DORFKERN_KONFIG, Kategorie EINKAUF):
    einkauf.gmail.poll_min   – Intervall in Minuten (Default 5, min 1)
    einkauf.gmail.client_id / .client_secret / .refresh_token  – OAuth
    einkauf.gmail.user_email – Anzeige

Heartbeat in ``XT_EINKAUF_POLLER_STATUS`` (Single-Row), wird vom Admin-UI
unter „System → Einkauf-Poller" angezeigt.

Beenden mit Ctrl-C oder SIGTERM (sauberer Shutdown am Ende des aktuellen
Sleep-Intervalls).
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config           # noqa: E402
from common.db import init_pool                    # noqa: E402
from common import einkauf, konfig                 # noqa: E402

log = logging.getLogger('einkauf.poller')
_LAUFT = True

# Untergrenze fuer das Polling – sonst hammert der Daemon die Gmail-API
# bei einem versehentlichen poll_min=0 in der Konfig.
_MIN_INTERVALL_S = 60

# Default fuer „wie weit zurueck schauen" pro Zyklus. Lieber ein paar
# Tage Overhead, weil Gmail-search billig ist und der UNIQUE-Constraint
# auf GMAIL_MSG_ID Duplikate sicher abfaengt.
_LOOKBACK_TAGE = 14
_MAX_PRO_LIEFERANT = 30


def _stop_handler(signum, _frame):
    global _LAUFT
    log.info('Signal %s -> beende Poller', signum)
    _LAUFT = False


def _intervall_s() -> int:
    """Aktuelles Poll-Intervall in Sekunden, jedes Mal frisch aus
    DORFKERN_KONFIG gelesen — so greifen Admin-UI-Aenderungen ohne
    Daemon-Restart spaetestens beim naechsten Zyklus.
    """
    minuten = konfig.get(einkauf.KEY_GMAIL_POLL_MIN,
                         einkauf.DEFAULT_GMAIL_POLL_MIN)
    try:
        sek = int(minuten) * 60
    except (TypeError, ValueError):
        sek = einkauf.DEFAULT_GMAIL_POLL_MIN * 60
    return max(_MIN_INTERVALL_S, sek)


def _einen_zyklus(host: str) -> None:
    """Ein Polling-Zyklus: Gmail-Fetch ausfuehren, Heartbeat schreiben.

    Fehler werden geloggt, aber nicht propagiert – der Daemon laeuft
    weiter (transiente Fehler wie kurzer Netzausfall sollen den Prozess
    nicht killen).
    """
    try:
        res = einkauf.gmail_fetch_neue_bestellungen(
            neuer_als_tage=_LOOKBACK_TAGE,
            max_pro_lieferant=_MAX_PRO_LIEFERANT,
        )
    except Exception as exc:
        log.exception('Gmail-Fetch crashed')
        einkauf.poller_status_schreiben(
            gmail_ok=False,
            last_error=f'Crash: {exc}',
            neu_gefunden=0,
            hostname=host,
        )
        return

    if res.get('ok'):
        log.info('Zyklus OK · %s neu, %s gefunden, %s Lieferanten',
                 res.get('neu', 0), res.get('gefunden', 0),
                 len(res.get('lieferanten', [])))
        einkauf.poller_status_schreiben(
            gmail_ok=True,
            last_error=None,
            neu_gefunden=int(res.get('neu') or 0),
            hostname=host,
        )
    else:
        err = res.get('fehler') or 'unbekannt'
        log.warning('Zyklus fehlgeschlagen: %s', err)
        einkauf.poller_status_schreiben(
            gmail_ok=False,
            last_error=err,
            neu_gefunden=0,
            hostname=host,
        )


def _reconcile_zyklus() -> None:
    """Phase E.3: SEPA-Vormerkungen gegen Bankumsätze abgleichen.
    Best-effort — Fehler dürfen den Gmail-Poller nicht killen. Läuft
    im selben Intervall mit (Settlement dauert Stunden/Tage; das
    Gmail-Intervall ist mehr als eng genug)."""
    try:
        from modules.orga.bestellwesen import hibiscus_reconcile as hr
        r = hr.reconcile_vormerkungen()
        if r.get('gebucht') or r.get('zurueckgesetzt') or r.get('fehler'):
            log.info('Reconcile · %s gebucht, %s zurückgesetzt, '
                     '%s offen, %s Fehler', r.get('gebucht'),
                     r.get('zurueckgesetzt'), r.get('offen'),
                     r.get('fehler'))
    except Exception:
        log.exception('Reconcile-Zyklus crashed (Poller läuft weiter)')


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-5s %(name)s: %(message)s',
    )

    # DB-Pool. Eigene Pool-Bezeichnung – damit das HACCP-Modul, das im
    # gleichen Prozess gar nicht laeuft, keinen Pool-Namen-Konflikt
    # bekommt, falls jemand beide Daemons jemals zusammenfuehrt.
    init_pool('einkauf_poller_pool', pool_size=2,
              db_config=load_db_config('EINKAUF_POLLER'))

    signal.signal(signal.SIGINT,  _stop_handler)
    signal.signal(signal.SIGTERM, _stop_handler)

    # Sicherstellen, dass die Tabellen existieren – falls der Daemon vor
    # der Admin-App startet (Erstinstallation, ungewohnliche Bootreihenfolge).
    try:
        einkauf.run_migration()
    except Exception:
        log.exception('Einkauf-Migration im Daemon-Bootstrap')

    host = socket.gethostname()
    intervall = _intervall_s()
    log.info('Einkauf-Poller gestartet · Intervall %s s · Lookback %s Tage',
             intervall, _LOOKBACK_TAGE)

    while _LAUFT:
        start = time.monotonic()
        _einen_zyklus(host)
        _reconcile_zyklus()

        # Konfig-Wert pro Zyklus neu lesen (Admin kann das Intervall
        # anpassen, ohne den Daemon zu restarten).
        intervall = _intervall_s()
        dauer = time.monotonic() - start
        warte = max(5, intervall - int(dauer))
        for _ in range(warte):
            if not _LAUFT:
                break
            time.sleep(1)

    log.info('Poller gestoppt.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
