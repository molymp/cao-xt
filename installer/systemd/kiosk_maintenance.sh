#!/bin/bash
# ============================================================
# dorfkern-maintenance-mode
#
# Toggle zwischen Kiosk-Auto-Login und manuellem Login-Bildschirm
# (Greeter), ohne die Box neu starten zu muessen.
#
# Aufruf:
#   sudo dorfkern-maintenance-mode             -> Greeter anzeigen
#                                                 (Wartung: User + Session
#                                                 manuell waehlen)
#   sudo dorfkern-maintenance-mode --kiosk     -> zurueck zu Auto-Kiosk
#   sudo dorfkern-maintenance-mode --status    -> aktueller Modus
#
# Mechanik: schiebt /etc/lightdm/lightdm.conf.d/50-dorfkern-kiosk.conf
# in .off (bzw. zurueck) und macht LightDM-Restart. Idempotent.
# Wird vom Installer (host_setup.install_kiosk) nach /usr/local/bin/
# installiert.
# ============================================================
set -e

CONF=/etc/lightdm/lightdm.conf.d/50-dorfkern-kiosk.conf
OFF=${CONF}.off

case "${1:-}" in
    --kiosk|kiosk)
        if [ -f "$OFF" ]; then
            mv "$OFF" "$CONF"
            systemctl restart lightdm
            echo "✓  Kiosk-Modus aktiv (Auto-Login in Vollbild-Chromium)"
        elif [ -f "$CONF" ]; then
            echo "ℹ  Kiosk-Modus bereits aktiv"
        else
            echo "✗  Weder $CONF noch $OFF gefunden — Kiosk-Setup nicht installiert?"
            exit 1
        fi
        ;;
    --status|status)
        if [ -f "$CONF" ]; then
            echo "Modus: KIOSK (Auto-Login)"
        elif [ -f "$OFF" ]; then
            echo "Modus: MAINTENANCE (Greeter)"
        else
            echo "Modus: UNBEKANNT (weder $CONF noch $OFF gefunden)"
            exit 1
        fi
        ;;
    --help|-h|help)
        sed -n '/^# ===/,/^# ===/p' "$0" | head -20
        ;;
    "")
        if [ ! -f "$CONF" ]; then
            if [ -f "$OFF" ]; then
                echo "ℹ  Maintenance-Modus bereits aktiv (Conf liegt unter $OFF)"
                exit 0
            fi
            echo "✗  $CONF nicht gefunden — Kiosk-Setup nicht installiert?"
            exit 1
        fi
        mv "$CONF" "$OFF"
        systemctl restart lightdm
        echo "✓  Maintenance-Modus aktiv (Greeter wird angezeigt)"
        echo "   Am Bildschirm: User waehlen, ggf. Session wechseln,"
        echo "   Passwort eingeben, normaler Desktop kommt."
        echo ""
        echo "   Zurueck zum Kiosk:"
        echo "     sudo dorfkern-maintenance-mode --kiosk"
        echo "   Oder einfach: sudo reboot"
        ;;
    *)
        echo "Usage: $0 [--kiosk|--status|--help]"
        exit 1
        ;;
esac
