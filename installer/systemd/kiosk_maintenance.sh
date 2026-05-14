#!/bin/bash
# ============================================================
# dorfkern-maintenance-mode
#
# Toggle des LightDM-Login-Modus zwischen drei Modi:
#
#   --kiosk        (Default-Betrieb)
#       Auto-Login als kasse -> Vollbild-Chromium auf die Kiosk-App.
#       Der Standardzustand, in den die Box nach Reboot kommt.
#
#   --maintenance / (kein Argument)
#       Auto-Login als kasse -> normaler Wartungs-Desktop
#       (LXDE-pi-x bzw. erste verfuegbare Desktop-Session).
#       KEIN Login-Prompt: wer im Admin "Wartung aktivieren" klickt,
#       landet am Display direkt im Desktop und kann sofort arbeiten.
#       Auf dem Desktop liegt ein Icon "Zurueck zum Kiosk", das
#       dieses Skript mit --kiosk ruft.
#
#   --greeter
#       Klassischer LightDM-Greeter mit User-/Session-/Passwort-Wahl.
#       Selten gebraucht — fuer den Fall, dass jemand anders als kasse
#       sich einloggen soll oder eine andere Session.
#
#   --status
#       Aktueller Modus als einzeiliger Output (kiosk/maintenance/
#       greeter/unbekannt).
#
# Mechanik: schreibt /etc/lightdm/lightdm.conf.d/50-dorfkern-kiosk.conf
# je nach Modus um und macht LightDM-Restart. Im Wartungs-Modus wird
# zusaetzlich ~kasse/Desktop/Zurueck-zum-Kiosk.desktop angelegt
# (idempotent, ueberschreibt nicht).
#
# Wird vom Installer (host_setup.install_kiosk) nach /usr/local/bin/
# installiert.
# ============================================================
set -e

CONF=/etc/lightdm/lightdm.conf.d/50-dorfkern-kiosk.conf
DESKTOP_USER=kasse
DESKTOP_HOME="/home/${DESKTOP_USER}"
RUECK_ICON="${DESKTOP_HOME}/Desktop/Zurueck-zum-Kiosk.desktop"


# Erste verfuegbare Desktop-Session ermitteln (ohne Kiosk-Custom).
# Praeferenz: LXDE-pi-x > openbox > lightdm-xsession > erste beste.
_detect_desktop_session() {
    local prefs=(LXDE-pi-x openbox lightdm-xsession LXDE gnome)
    for s in "${prefs[@]}"; do
        if [ -f "/usr/share/xsessions/${s}.desktop" ]; then
            echo "$s"; return 0
        fi
    done
    # Fallback: irgendeine x-Session die nicht Kiosk ist
    for f in /usr/share/xsessions/*.desktop; do
        name=$(basename "$f" .desktop)
        [ "$name" = "dorfkern-kiosk" ] && continue
        echo "$name"; return 0
    done
    return 1
}


_write_conf() {
    local session="$1"
    local note="$2"
    cat <<EOF | install -m 0644 -o root -g root /dev/stdin "$CONF"
# Auto-generiert von dorfkern-maintenance-mode.
# Modus: ${note}
[Seat:*]
greeter-session=lightdm-gtk-greeter
autologin-user=${DESKTOP_USER}
autologin-session=${session}
EOF
}


_write_conf_greeter() {
    # Im Greeter-Modus KEIN autologin (kein User-Eintrag = greeter).
    cat <<'EOF' | install -m 0644 -o root -g root /dev/stdin "$CONF"
# Auto-generiert von dorfkern-maintenance-mode.
# Modus: greeter (manueller Login)
[Seat:*]
greeter-session=lightdm-gtk-greeter
greeter-show-manual-login=true
EOF
}


_ensure_back_icon() {
    # Desktop-Icon "Zurueck zum Kiosk" fuer den kasse-User anlegen.
    # Klick fuehrt 'sudo dorfkern-maintenance-mode --kiosk' aus.
    install -d -o "$DESKTOP_USER" -g "$DESKTOP_USER" "${DESKTOP_HOME}/Desktop"
    cat <<'EOF' | install -m 0755 -o "$DESKTOP_USER" -g "$DESKTOP_USER" /dev/stdin "$RUECK_ICON"
[Desktop Entry]
Type=Application
Name=Zurück zum Kiosk
Comment=LightDM auf Kiosk-Auto-Login zurueckschalten und neu starten
Icon=view-fullscreen
Exec=sh -c 'pkexec dorfkern-maintenance-mode --kiosk || \
            xterm -e "sudo dorfkern-maintenance-mode --kiosk; sleep 2" || \
            x-terminal-emulator -e "sudo dorfkern-maintenance-mode --kiosk; sleep 2"'
Terminal=false
Categories=System;
EOF
}


_remove_back_icon() {
    [ -f "$RUECK_ICON" ] && rm -f "$RUECK_ICON" || true
}


_current_mode() {
    if [ ! -f "$CONF" ]; then
        echo unbekannt; return
    fi
    if grep -q "^autologin-session=dorfkern-kiosk" "$CONF"; then
        echo kiosk
    elif grep -q "^autologin-user=" "$CONF"; then
        echo maintenance
    else
        echo greeter
    fi
}


case "${1:-}" in
    --kiosk|kiosk)
        _write_conf "dorfkern-kiosk" "kiosk (Auto-Login Vollbild-Chromium)"
        _remove_back_icon
        systemctl restart lightdm
        echo "✓  Kiosk-Modus aktiv (Auto-Login in Vollbild-Chromium)"
        ;;
    --greeter|greeter)
        _write_conf_greeter
        _remove_back_icon
        systemctl restart lightdm
        echo "✓  Greeter-Modus aktiv (manueller Login)"
        ;;
    --maintenance|maintenance|"")
        session=$(_detect_desktop_session) || {
            echo "✗  Keine Desktop-Session unter /usr/share/xsessions/ gefunden."
            echo "   Bitte LXDE/Openbox/GNOME installieren."
            exit 1
        }
        _write_conf "$session" "maintenance (Auto-Login Desktop ${session})"
        _ensure_back_icon
        systemctl restart lightdm
        echo "✓  Wartungs-Modus aktiv (Auto-Login als ${DESKTOP_USER} -> ${session})"
        echo "   Am Display: direkt im Desktop, kein Login-Prompt."
        echo "   Zurueck zum Kiosk:"
        echo "     - Doppelklick auf Desktop-Icon 'Zurueck zum Kiosk'"
        echo "     - oder via Admin-Dashboard"
        echo "     - oder: sudo dorfkern-maintenance-mode --kiosk"
        ;;
    --status|status)
        mode=$(_current_mode)
        case "$mode" in
            kiosk)        echo "Modus: KIOSK (Auto-Login Vollbild-Chromium)" ;;
            maintenance)  echo "Modus: MAINTENANCE (Auto-Login Wartungs-Desktop)" ;;
            greeter)      echo "Modus: GREETER (manueller Login)" ;;
            *)            echo "Modus: UNBEKANNT (Conf $CONF fehlt)"; exit 1 ;;
        esac
        ;;
    --help|-h|help)
        sed -n '/^# ===/,/^# ===/p' "$0" | head -50
        ;;
    *)
        echo "Usage: $0 [--kiosk|--maintenance|--greeter|--status|--help]"
        exit 1
        ;;
esac
