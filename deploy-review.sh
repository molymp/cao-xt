#!/bin/bash
# ============================================================
# deploy-review.sh – Review-Umgebung aktualisieren
#
# Setzt einen Review-Worktree auf den aktuellen Stand eines
# Branches und startet den zugehörigen WaWi-Server neu.
#
# Usage:
#   ./deploy-review.sh                          # aktueller Branch, Slot auto-detect
#   ./deploy-review.sh cto/hab-200-fix          # bestimmter Branch, Slot auto-detect
#   ./deploy-review.sh claude/hab-139-fix       # Claude-Agent-Branch → Slot default
#   ./deploy-review.sh cto/hab-345 --slot cto   # expliziter Slot
#   ./deploy-review.sh master --slot default    # Slot explizit überschreiben
#
# Slot-Konfiguration:
#   default  →  cao-xt-review        Port 5003  (Claude Agent)
#   cto      →  cao-xt-review-cto    Port 5013  (CTO)
#
# Referenz: HAB-194, HAB-345
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PARENT="$(dirname "$SCRIPT_DIR")"

# ── Parameter parsen ─────────────────────────────────────────
SOURCE_BRANCH=""
SLOT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --slot)
            SLOT_OVERRIDE="$2"
            shift 2
            ;;
        --slot=*)
            SLOT_OVERRIDE="${1#--slot=}"
            shift
            ;;
        -*)
            echo "❌ Unbekannte Option: $1"
            echo "   Verwendung: $0 [<branch>] [--slot <default|cto>]"
            exit 1
            ;;
        *)
            SOURCE_BRANCH="$1"
            shift
            ;;
    esac
done

# Branch bestimmen (Default: aktueller Branch)
SOURCE_BRANCH="${SOURCE_BRANCH:-$(git -C "$SCRIPT_DIR" branch --show-current)}"

# ── Slot auto-detect anhand Branch-Prefix ────────────────────
if [ -n "$SLOT_OVERRIDE" ]; then
    SLOT="$SLOT_OVERRIDE"
else
    PREFIX="${SOURCE_BRANCH%%/*}"
    case "$PREFIX" in
        cto)     SLOT="cto" ;;
        *)       SLOT="default" ;;
    esac
fi

# ── Slot-Konfiguration ───────────────────────────────────────
case "$SLOT" in
    default)
        REVIEW="$REPO_PARENT/cao-xt-review"
        WAWI_PORT=5003
        LOG="/tmp/wawi-review.log"
        ;;
    cto)
        REVIEW="$REPO_PARENT/cao-xt-review-cto"
        WAWI_PORT=5013
        LOG="/tmp/wawi-review-cto.log"
        ;;
    *)
        echo "❌ Unbekannter Slot: '$SLOT'. Gültig: default, cto"
        exit 1
        ;;
esac

WAWI_APP="$REVIEW/wawi-app/app"

# ── Branch/Commit bestimmen ───────────────────────────────────
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
echo "  Slot:    $SLOT  ($REVIEW)"
echo "  Port:    $WAWI_PORT"
echo ""

# ── Review-Worktree erstellen falls nicht vorhanden ──────────
if [ ! -d "$REVIEW" ]; then
    echo "🆕 Review-Worktree '$SLOT' existiert noch nicht – wird angelegt..."
    git -C "$SCRIPT_DIR" worktree add --detach "$REVIEW" "$COMMIT"
    echo "✅ Worktree angelegt: $REVIEW"
    echo ""
fi

# ── Review-Worktree aktualisieren ────────────────────────────
# Nutze reset --hard statt checkout:
# git-worktrees erlauben keinen branch-Checkout wenn der Branch
# bereits in einem anderen Worktree ausgecheckt ist.
echo "🔄 Review-Worktree aktualisieren..."
git -C "$REVIEW" reset --hard "$COMMIT"
echo "✅ Worktree ist jetzt auf: $(git -C "$REVIEW" rev-parse --short HEAD)"
echo ""

# ── Deployment-Marker schreiben ──────────────────────────────
DEPLOYED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
cat > "$REVIEW/.deployed" <<EOF
branch=$SOURCE_BRANCH
commit=$COMMIT
short=$SHORT
slot=$SLOT
port=$WAWI_PORT
deployed_at=$DEPLOYED_AT
EOF

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
cd "$WAWI_APP"
WAWI_PORT=$WAWI_PORT nohup python3 app.py > "$LOG" 2>&1 &
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
echo "  Slot:              $SLOT"
echo "  WaWi-App (Review): http://localhost:$WAWI_PORT"
echo "  Log:               $LOG"
echo "══════════════════════════════════════════════════════════"
echo ""
