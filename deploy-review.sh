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

# Nur den LISTENING-Prozess auf dem Port beenden (keine Client-Verbindungen)
LISTEN_PID=$(lsof -ti :"$WAWI_PORT" -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$LISTEN_PID" ]; then
    kill -TERM "$LISTEN_PID" 2>/dev/null || true
    echo "   Alter Prozess ($LISTEN_PID) beendet – warte auf Port-Freigabe..."
    # Warten bis Port frei ist (max 10 Sekunden)
    for i in $(seq 1 10); do
        sleep 1
        STILL_UP=$(lsof -ti :"$WAWI_PORT" -sTCP:LISTEN 2>/dev/null || true)
        if [ -z "$STILL_UP" ]; then
            break
        fi
    done
fi

# Neuen Prozess starten
LOG="/tmp/wawi-review.log"
cd "$WAWI_APP"
nohup python3 app.py > "$LOG" 2>&1 &
NEW_PID=$!

# Warten bis der Server tatsächlich lauscht (max 15 Sekunden)
echo "   Warte auf Server-Start..."
for i in $(seq 1 15); do
    sleep 1
    if lsof -ti :"$WAWI_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "✅ WaWi-Server gestartet (PID $NEW_PID)"
        break
    fi
    if ! kill -0 "$NEW_PID" 2>/dev/null; then
        echo "⚠️  Server-Prozess abgestürzt – Log prüfen: $LOG"
        tail -20 "$LOG"
        exit 1
    fi
done

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  WaWi-App (Review): http://localhost:$WAWI_PORT"
echo "  Log:               $LOG"
echo "══════════════════════════════════════════════════════════"
echo ""
