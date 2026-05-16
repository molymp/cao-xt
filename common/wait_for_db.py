"""
Wartet beim Dienst-Start auf TCP-Erreichbarkeit der (remote) DB.

Als systemd ``ExecStartPre`` gedacht. Hintergrund: nach einem Box-
Reboot starten die Units ~5 s nach Boot, die LAN-Route zur DB
(``192.168.178.20:3306``) steht aber erst ~15-25 s spaeter. Ohne
diese Vorbedingung starten die Apps in einen DB-losen Zustand
(Permission fail-closed, frueher Poller-Exit-2). ``After=mariadb.
service`` war wirkungslos, seit die DB remote laeuft.

Verhalten: pollt den DB-TCP-Port bis erreichbar ODER bis ``MAX_WAIT``
abgelaufen ist. Exit-Code IMMER 0 — auch bei Timeout: die App soll
trotzdem starten (das DB-Gate in ``common.db_gate`` faengt eine evtl.
Restverzoegerung mit einer Warteseite ab). Diese Vorbedingung soll
den Boot glaetten, nicht den Dienst dauerhaft blockieren.

Aufruf:  python3 -m common.wait_for_db
"""
import socket
import sys
import time

from common.config import load_db_config

MAX_WAIT_S   = 120.0
INTERVAL_S   = 2.0
TCP_TIMEOUT  = 2.0


def main() -> int:
    try:
        cfg = load_db_config()
        host = cfg['host']
        port = int(cfg['port'])
    except Exception as exc:                       # noqa: BLE001
        print(f'wait_for_db: Konfig nicht lesbar ({exc}) — '
              f'starte ohne Warten.', flush=True)
        return 0

    deadline = time.monotonic() + MAX_WAIT_S
    versuch = 0
    while True:
        versuch += 1
        try:
            with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
                print(f'wait_for_db: {host}:{port} erreichbar '
                      f'(Versuch {versuch}).', flush=True)
                return 0
        except OSError:
            if time.monotonic() >= deadline:
                print(f'wait_for_db: {host}:{port} nach {MAX_WAIT_S:.0f}s '
                      f'NICHT erreichbar — starte trotzdem (DB-Gate '
                      f'faengt ab).', flush=True)
                return 0
            time.sleep(INTERVAL_S)


if __name__ == '__main__':
    sys.exit(main())
