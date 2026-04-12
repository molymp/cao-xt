#!/bin/bash
# ============================================================
# install.sh – CAO-XT Installationsroutine
#
# Prüft Systemvoraussetzungen, richtet ein virtuelles Python-
# Environment ein und startet den interaktiven Installer.
#
# Verwendung:
#   ./install.sh                   # Interaktive Installation
#   ./install.sh --non-interactive # Automatisch (aus Umgebung / INI)
#
# Referenz: HAB-355
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="${VENV_DIR}/bin/python3"
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
echo "║     CAO-XT Installationsroutine                         ║"
echo "║     Habacher Dorfladen                                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Python-Version prüfen ─────────────────────────────────────
echo "─── Systemvoraussetzungen prüfen ───────────────────────────"
if ! command -v python3 &>/dev/null; then
    fail "python3 nicht gefunden. Bitte Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ installieren."
fi

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VER" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VER" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt "$MIN_PYTHON_MAJOR" ] || \
   ([ "$PYTHON_MAJOR" -eq "$MIN_PYTHON_MAJOR" ] && [ "$PYTHON_MINOR" -lt "$MIN_PYTHON_MINOR" ]); then
    fail "Python ${PYTHON_VER} zu alt. Benötigt: ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+"
fi
ok "Python ${PYTHON_VER}"

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
    echo "  Erstelle virtualenv in .venv …"
    python3 -m venv "$VENV_DIR"
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
echo "─── Installer starten ──────────────────────────────────────"
echo ""

# Installer aufrufen (alle übergebenen Argumente durchreichen)
exec "$PYTHON" -m installer.install "$@"
