"""
Selbstregistrierung eines Hosts in der TERMINAL-Tabelle (Phase 9).

Startet ein Terminal (Kiosk/Kasse/Orga) und kein passender Eintrag in
``TERMINAL`` existiert (weder per MAC noch per Hostname), legt diese
Funktion ihn automatisch an. Existiert er, wird nur der letzte Kontakt
aktualisiert und ggf. die IP nachgezogen.

Bewusst FAIL-SOFT: Schlaegt die DB nicht an (z.B. erste Inbetriebnahme
bevor DB laeuft), wird nur gewarnt – die App startet trotzdem.
"""
from __future__ import annotations

import logging
import socket
from typing import Optional

from common import terminal as _terminal

log = logging.getLogger(__name__)


def selbst_registrieren(typ: str,
                        bezeichnung: Optional[str] = None) -> Optional[int]:
    """Legt/aktualisiert den TERMINAL-Eintrag fuer diesen Host.

    Args:
        typ:         ``KASSE`` | ``KIOSK`` | ``ORGA`` | ``ADMIN``
        bezeichnung: Optional. Default: ``<typ> auf <hostname>``.

    Returns:
        ``TERMINAL_ID`` oder ``None`` bei Fehler.
    """
    try:
        host = _terminal.hostname()
        mac = _terminal.mac_adresse()
        ip = _terminal.lokale_ip()
        eintrag = _terminal.erkenne(typ, host=host, mac=(mac or None))
        if eintrag:
            tid = int(eintrag['TERMINAL_ID'])
            _terminal.setze_letzten_kontakt(tid, ip=(ip or None))
            log.info("Terminal %d (%s) registriert als bekannt.",
                     tid, eintrag.get('BEZEICHNUNG'))
            return tid
        # neu anlegen
        label = bezeichnung or f'{typ.capitalize()} auf {host or "?"}'
        tid = _terminal.anlegen(bezeichnung=label, typ=typ,
                                hostname_=(host or None),
                                mac=(mac or None))
        if ip:
            _terminal.setze_letzten_kontakt(tid, ip=ip)
        log.info("Terminal %d (%s) neu angelegt.", tid, label)
        return tid
    except Exception as exc:
        log.warning("Terminal-Selbstregistrierung fehlgeschlagen: %s", exc)
        return None


# Socket-Timeout begrenzen (UDP-Trick in terminal.lokale_ip() kann in
# isolierten Netzen blockieren).
socket.setdefaulttimeout(socket.getdefaulttimeout() or 2.0)
