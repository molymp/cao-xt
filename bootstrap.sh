#!/bin/bash
# ============================================================
# bootstrap.sh – Dorfkern Einzeiler-Installation
#
# Klont das Repo (oder aktualisiert es, falls schon da) und reicht
# an install.sh weiter. Gedacht fuer den `curl | bash`-Einstieg
# auf einer frischen Maschine, wo noch nichts vom Projekt liegt.
#
# Aufruf:
#   sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/molymp/cao-xt/master/bootstrap.sh)"
#     -> PROD-Setup: Repo nach /opt/dorfkern, danach Dialog (waehle Typ 3)
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/molymp/cao-xt/master/bootstrap.sh)"
#     -> Dev/User-Setup: Repo nach ~/dorfkern, danach Dialog (waehle Typ 1 oder 2)
#
# Voraussetzungen: bash, curl, git, python3 >= 3.10. Der Installer
# legt das venv selbst an und installiert die Python-Abhaengigkeiten.
# ============================================================
set -euo pipefail

REPO_URL="${DORFKERN_REPO_URL:-https://github.com/molymp/cao-xt.git}"
REPO_BRANCH="${DORFKERN_REPO_BRANCH:-master}"

# ── Farben ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; exit 1; }
info() { echo -e "  ${BLUE}→${NC}  $*"; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     Dorfkern – Bootstrap (klonen + Installer starten)   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Zielpfad waehlen ──────────────────────────────────────────
if [ "$EUID" -eq 0 ]; then
    TARGET="/opt/dorfkern"
    MODE_HINT="System-Mode (Typ 3 im Dialog)"
else
    TARGET="$HOME/dorfkern"
    MODE_HINT="User-Mode (Typ 1 oder 2 im Dialog)"
fi
info "Zielpfad: $TARGET"
info "Erwarteter Installationstyp: $MODE_HINT"
echo ""

# ── Voraussetzungen ───────────────────────────────────────────
echo "─── Voraussetzungen ────────────────────────────────────────"
command -v git     >/dev/null 2>&1 || fail "git fehlt — bitte 'apt install git' o.ae. ausfuehren."
command -v python3 >/dev/null 2>&1 || fail "python3 fehlt — bitte Python 3.10+ installieren."
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "git, python3 (${PYV})"

# ── Klonen oder updaten ───────────────────────────────────────
echo ""
echo "─── Repo bereitstellen ─────────────────────────────────────"
if [ -d "$TARGET/.git" ]; then
    info "$TARGET existiert bereits — Update via git pull"
    cd "$TARGET"
    git fetch --quiet origin "$REPO_BRANCH"
    git checkout --quiet "$REPO_BRANCH"
    git pull --quiet --ff-only origin "$REPO_BRANCH"
    ok "auf neuestem Stand"
elif [ -e "$TARGET" ]; then
    fail "$TARGET existiert, ist aber kein Git-Repo. Bitte aufraeumen oder anderen Pfad waehlen (DORFKERN_REPO_URL/-BRANCH bzw. erstes Argument unten)."
else
    info "Klone $REPO_URL ($REPO_BRANCH) → $TARGET"
    git clone --quiet --branch "$REPO_BRANCH" "$REPO_URL" "$TARGET"
    cd "$TARGET"
    ok "geklont"
fi

# ── install.sh weiterreichen ──────────────────────────────────
echo ""
echo "─── Installer starten ──────────────────────────────────────"
echo ""
if [ ! -x ./install.sh ]; then
    fail "install.sh nicht ausfuehrbar oder nicht vorhanden in $TARGET"
fi
exec ./install.sh "$@"
