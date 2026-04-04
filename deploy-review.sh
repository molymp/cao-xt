#!/bin/bash
# ============================================================
# deploy-review.sh – Review-Umgebung aktualisieren
#
# Setzt cao-xt-review auf den aktuellen Stand eines Branches
# und startet den WaWi-Server neu.
#
# Usage:
#   ./deploy-review.sh                     # aktueller Branch von cao-xt
#   ./deploy-review.sh cto/hab-194         # bestimmter Branch
#   ./deploy-review.sh claude/hab-139-fix  # Feature-Branch des Flask-Agenten
#
# Referenz: HAB-194
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVIEW="$SCRIPT_DIR/../cao-xt-review"
WAWI_APP="$REVIEW/wawi-app/app"
WAWI_PORT=5003

# ── Branch/Commit bestimmen ───────────────────────────────────
SOURCE_BRANCH="${1:-$(git -C "$SCRIPT_DIR" branch --show-current)}"

COMMIT=$(git -C "$SCRIPT_DIR" rev-parse "$SOURCE_BRANCH" 2>/dev/null || true)
if [ -z "$COMMIT" ]; then
    echo "❌ Branch oder Commit '$SOURCE_BRANCH' nicht gefunden."
    exit 1
fi

SHORT=$(git -C "$SCRIPT_DIR" rev-parse --short "$SOURCE_BRANCH")
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  DEPLOY → REVIEW                                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Branch:  $SOURCE_BRANCH"
echo "  Commit:  $SHORT ($COMMIT)"
echo ""

# ── Review-Worktree aktualisieren ────────────────────────────
# Nutze reset --hard statt checkout:
# git-worktrees erlauben keinen branch-Checkout wenn der Branch
# bereits in einem anderen Worktree ausgecheckt ist.
echo "🔄 Review-Worktree aktualisieren..."
git -C "$REVIEW" reset --hard "$COMMIT"
echo "✅ Worktree ist jetzt auf: $(git -C "$REVIEW" rev-parse --short HEAD)"
echo ""

# ── WaWi-Server neu starten ──────────────────────────────────
echo "🔄 WaWi-Server auf Port $WAWI_PORT neu starten..."

# Alten Prozess beenden
PID=$(lsof -ti :"$WAWI_PORT" 2>/dev/null || true)
if [ -n "$PID" ]; then
    kill -TERM "$PID" 2>/dev/null || true
    sleep 2
    echo "   Alter Prozess ($PID) beendet."
fi

# Neuen Prozess starten
LOG="/tmp/wawi-review.log"
cd "$WAWI_APP"
nohup python3 app.py > "$LOG" 2>&1 &
NEW_PID=$!

# Kurz warten und prüfen ob der Prozess läuft
sleep 2
if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "✅ WaWi-Server gestartet (PID $NEW_PID)"
else
    echo "⚠️  Server-Start fehlgeschlagen – Log prüfen: $LOG"
    tail -20 "$LOG"
    exit 1
fi

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  WaWi-App (Review): http://localhost:$WAWI_PORT"
echo "  Log:               $LOG"
echo "══════════════════════════════════════════════════════════"
echo ""
