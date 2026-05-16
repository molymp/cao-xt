#!/usr/bin/env python3
"""
Jameica ``-P passwordcommand``-Helfer.

Gibt AUSSCHLIESSLICH das Jameica-Master-Passwort aus
``DORFKERN_KONFIG['hibiscus.master_passwort']`` (TYP=SECRET) auf stdout
aus – nichts sonst. Jameica startet diesen Befehl headless und liest
dessen stdout als Master-Passwort (``-P``), damit das Bank-Passwort
NICHT als Datei auf der Platte liegt (analog dazu, wie die Dorfkern-
Apps DB-Credentials zur Laufzeit aus der Konfiguration lesen).

Exit-Code:
  0  Passwort ausgegeben
  1  Passwort fehlt / DB nicht erreichbar (Jameica scheitert dann
     sauber an der Wallet-Entsperrung mit klarer Meldung)

Aufruf (von Jameica gesetzt, siehe hibiscus_setup.jameica_start_cmd):
  python3 -m installer.hibiscus_pw
"""
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main() -> int:
    try:
        from common import konfig
        pw = konfig.get('hibiscus.master_passwort') or ''
    except Exception as e:
        # NICHT das Passwort, nur die Ursache auf stderr.
        print(f"hibiscus_pw: Konfig nicht lesbar: {e}", file=sys.stderr)
        return 1
    pw = str(pw).strip()
    if not pw:
        print("hibiscus_pw: kein Master-Passwort in DORFKERN_KONFIG "
              "(Admin → System → Banking).", file=sys.stderr)
        return 1
    # Ohne Zeilenumbruch wäre auch ok; Jameica trimmt. newline=False,
    # damit kein abschließendes \n ins Passwort gerät.
    sys.stdout.write(pw)
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
