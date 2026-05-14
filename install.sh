#!/bin/bash
# ============================================================
# install.sh – Dorfkern Installationsroutine & Update
#
# Prueft Systemvoraussetzungen, richtet ein virtuelles Python-
# Environment ein und startet den interaktiven Installer.
#
# Verwendung:
#   ./install.sh                   # Interaktive Installation
#   ./install.sh --non-interactive # Automatisch (aus Umgebung / INI)
#   ./install.sh --update          # System updaten (Fallback)
#   ./install.sh --check-update    # Nur auf Updates pruefen
#
# Im interaktiven Modus fragt der Installer in Phase 0, welcher
# Installationstyp gewuenscht ist:
#   1) Ad-hoc                   (kein systemd, lebt mit der Login-Session)
#   2) Dienst pro Benutzer      (systemd --user, Lingering)
#   3) Dienst systemweit        (systemd-System-Units, braucht sudo)
# Im non-interactive Modus kommt der Typ aus XT_INSTALL_TYPE
# (Default: ad_hoc). Details: installer/systemd/README.md
#
# Referenz: HAB-355, HAB-356
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
# venv-Python (gibt's nach dem Venv-Setup). NICHT 'PYTHON' nennen, weil
# diese Env-Var von ausserhalb zur expliziten System-Python-Wahl genutzt
# wird (siehe weiter unten, Python-Versions-Check).
VENV_PYTHON="${VENV_DIR}/bin/python3"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# ── Farben ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; exit 1; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     Dorfkern – Vorbereitung (Python, venv, deps)        ║"
echo "║     (vormals CAO-XT)                                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Root-Hinweis ──────────────────────────────────────────────
# Sudo ist nur fuer Typ 3 ("Dienst systemweit") noetig. Wer als root
# startet und dann im Dialog Typ 1/2 waehlt, kriegt das venv unter
# root-Ownership und (bei Typ 2) die User-Units in /root/.config — beides
# fast immer ungewollt. Einmal warnen, weitermachen.
if [ "$EUID" -eq 0 ]; then
    echo -e "  ${YELLOW}⚠${NC}  Du startest als root."
    echo -e "  ${YELLOW}⚠${NC}    → Sinnvoll nur fuer Typ 3 ('Dienst systemweit')."
    echo -e "  ${YELLOW}⚠${NC}    → Fuer Typ 1 (Ad-hoc) oder Typ 2 (Dienst pro Benutzer)"
    echo -e "  ${YELLOW}⚠${NC}      bitte als normaler User neu starten."
    echo ""
fi

# ── Python-Version prüfen ─────────────────────────────────────
echo "─── Systemvoraussetzungen prüfen ───────────────────────────"
# PYTHON-Env-Var erlaubt explizite Wahl (z.B. unter sudo, wo pyenv-
# Pythons nicht im PATH stehen):
#   sudo PYTHON=/home/kasse/.pyenv/versions/3.11.9/bin/python3 ./install.sh
# Falls nicht gesetzt: erst nach python3.11 / python3.10 suchen
# (bevorzugt explizite Minor-Versionen), dann auf 'python3' fallen.
PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    for cand in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" >/dev/null 2>&1; then
            PYTHON_BIN="$(command -v "$cand")"
            break
        fi
    done
fi
if [ -z "$PYTHON_BIN" ] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    fail "python3 nicht gefunden. Bitte Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ installieren."
fi

PYTHON_VER=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VER" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VER" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt "$MIN_PYTHON_MAJOR" ] || \
   ([ "$PYTHON_MAJOR" -eq "$MIN_PYTHON_MAJOR" ] && [ "$PYTHON_MINOR" -lt "$MIN_PYTHON_MINOR" ]); then
    fail "Python ${PYTHON_VER} (${PYTHON_BIN}) zu alt. Benötigt: ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+
        Falls eine neuere Version unter anderem Pfad liegt (z.B. pyenv):
          sudo PYTHON=/pfad/zu/python3.11 ./install.sh"
fi
ok "Python ${PYTHON_VER} (${PYTHON_BIN})"

# ── lsof prüfen (für Port-Management) ─────────────────────────
if command -v lsof &>/dev/null; then
    ok "lsof verfügbar"
else
    warn "lsof nicht gefunden – Port-Management eingeschränkt"
fi

# ── Virtuelles Environment einrichten ─────────────────────────
echo ""
echo "─── Virtuelle Python-Umgebung ──────────────────────────────"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Erstelle virtualenv in .venv (mit $PYTHON_BIN) …"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    ok "Virtualenv erstellt"
else
    ok "Virtualenv vorhanden: .venv"
fi

# Abhängigkeiten installieren
echo "  Installiere Abhängigkeiten …"
"$VENV_DIR/bin/pip3" install --quiet --upgrade pip

# Installer-Abhängigkeiten (inkl. cryptography)
# Hinweis: Auf älteren Linux-Systemen ohne Rust-Toolchain kann cryptography
# beim Build fehlschlagen. In diesem Fall:
#   .venv/bin/pip3 install "cryptography==3.3.2"
# und danach install.sh erneut ausführen.
if ! "$VENV_DIR/bin/pip3" install --quiet -r "$SCRIPT_DIR/installer/requirements.txt"; then
    warn "Abhängigkeiten-Installation fehlgeschlagen."
    warn "Falls 'cryptography' der Grund ist (kein Rust installiert):"
    warn "  .venv/bin/pip3 install 'cryptography==3.3.2'"
    warn "Dann install.sh erneut starten."
    exit 1
fi
ok "Installer-Abhängigkeiten"

# Abhängigkeiten aller Apps
for APP_REQ in "$SCRIPT_DIR"/*/app/requirements.txt; do
    if [ -f "$APP_REQ" ]; then
        APP_NAME=$(echo "$APP_REQ" | awk -F'/' '{print $(NF-2)}')
        "$VENV_DIR/bin/pip3" install --quiet -r "$APP_REQ"
        ok "Abhängigkeiten: $APP_NAME"
    fi
done

echo ""

# ── Update-Modus ──────────────────────────────────────────────
# --update und --check-update werden an installer/updater.py weitergeleitet.
# Alle anderen Argumente gehen an installer/install.py.
for arg in "$@"; do
    case "$arg" in
        --update)
            echo "─── Update-Modus ───────────────────────────────────────────"
            echo ""
            exec "$VENV_PYTHON" -m installer.updater --update
            ;;
        --check-update)
            echo "─── Update-Prüfung ─────────────────────────────────────────"
            echo ""
            exec "$VENV_PYTHON" -m installer.updater --check
            ;;
    esac
done

echo "─── Installer starten ──────────────────────────────────────"
echo ""

# Installer aufrufen (alle übergebenen Argumente durchreichen)
exec "$VENV_PYTHON" -m installer.install "$@"
