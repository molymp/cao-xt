#!/bin/bash
# ============================================================
# dorfkern-set-kiosk-password
#
# Setzt das Passwort des Kiosk-/Wartungs-Users (Default 'kasse').
# Das neue Passwort wird ueber STDIN gelesen (eine Zeile) — nie als
# Argument, damit es nicht in der Prozessliste oder in Logs auftaucht.
# Eng begrenzt: aendert ausschliesslich den Kiosk-User.
#
# Aufruf (durch die Admin-App als 'dorfkern' via passwortloses sudo;
# Regel in /etc/sudoers.d/dorfkern-shutdown):
#   printf '%s' "$NEUES_PW" | sudo -n /usr/local/bin/dorfkern-set-kiosk-password
#
# Wird vom Installer (host_setup.install_kiosk) nach /usr/local/bin/
# installiert; KIOSK_USER wird dabei auf den tatsaechlichen Kiosk-User
# gesetzt.
# ============================================================
set -euo pipefail

KIOSK_USER=kasse

# Genau eine Zeile von stdin lesen (ohne fuehrende/abschliessende NL).
IFS= read -r pw || true

if [ -z "${pw:-}" ]; then
    echo "Fehler: leeres Passwort" >&2
    exit 2
fi

if ! id "$KIOSK_USER" >/dev/null 2>&1; then
    echo "Fehler: User '$KIOSK_USER' existiert nicht" >&2
    exit 3
fi

# chpasswd splittet nur am ERSTEN ':' -> ':' im Passwort ist erlaubt.
if printf '%s:%s\n' "$KIOSK_USER" "$pw" | chpasswd; then
    echo "ok: Passwort fuer '$KIOSK_USER' gesetzt"
else
    echo "Fehler: chpasswd fehlgeschlagen" >&2
    exit 4
fi
