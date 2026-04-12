#!/bin/bash
# ============================================================
# deploy-review.sh – Review-Umgebung aktualisieren
#
# Setzt cao-xt-review auf den aktuellen Stand eines Branches
# und startet alle vier Apps neu:
#   Kiosk  → Port 5001
#   Kasse  → Port 5002
#   WaWi   → Port 5003
#   Verw.  → Port 5004
#
# Usage:
#   ./deploy-review.sh                     # aktueller Branch von cao-xt
#   ./deploy-review.sh cto/hab-194         # bestimmter Branch
#   ./deploy-review.sh claude/hab-139-fix  # Feature-Branch des Flask-Agenten
#
# Hinweis: Jede App braucht eine config_local.py im jeweiligen
# app/-Verzeichnis (nicht in Git). Fehlende Dateien werden
# vor dem Start gemeldet.
#
# Referenz: HAB-194, HAB-345
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVIEW="$SCRIPT_DIR/../cao-xt-review"

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

# ── Deployment-Marker schreiben ──────────────────────────────
DEPLOYED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
cat > "$REVIEW/.deployed" <<EOF
branch=$SOURCE_BRANCH
commit=$COMMIT
short=$SHORT
deployed_at=$DEPLOYED_AT
EOF

# ── Konfigurationsdateien prüfen ─────────────────────────────
echo "🔍 Konfiguration prüfen..."
MISSING_CONFIGS=()
for APP_DIR in kiosk-app kasse-app wawi-app verwaltung-app; do
    CFG="$REVIEW/$APP_DIR/app/config_local.py"
    if [ ! -f "$CFG" ]; then
        MISSING_CONFIGS+=("$APP_DIR")
        echo "   ⚠️  Fehlende config_local.py: $APP_DIR/app/"
    fi
done
if [ ${#MISSING_CONFIGS[@]} -gt 0 ]; then
    echo ""
    echo "   Tipp: config_local.py.example als Vorlage nutzen:"
    for APP_DIR in "${MISSING_CONFIGS[@]}"; do
        echo "     cp $REVIEW/$APP_DIR/app/config_local.py.example \\"
        echo "        $REVIEW/$APP_DIR/app/config_local.py"
    done
    echo ""
fi

# ── Hilfsfunktion: App starten ───────────────────────────────
start_app() {
    local NAME="$1"
    local APP_DIR="$2"
    local PORT="$3"
    local LOG="$4"

    echo "🔄 $NAME (Port $PORT) neu starten..."

    # Laufenden Prozess auf diesem Port beenden
    LISTEN_PID=$(lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$LISTEN_PID" ]; then
        kill -TERM "$LISTEN_PID" 2>/dev/null || true
        for i in $(seq 1 10); do
            sleep 1
            STILL_UP=$(lsof -ti :"$PORT" -sTCP:LISTEN 2>/dev/null || true)
            [ -z "$STILL_UP" ] && break
        done
    fi

    # App starten
    cd "$APP_DIR"
    nohup python3 app.py > "$LOG" 2>&1 &
    NEW_PID=$!

    # Auf Server-Start warten (max 15 Sekunden)
    for i in $(seq 1 15); do
        sleep 1
        if lsof -ti :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "   ✅ $NAME gestartet (PID $NEW_PID)"
            return 0
        fi
        if ! kill -0 "$NEW_PID" 2>/dev/null; then
            echo "   ⚠️  $NAME abgestürzt – Log prüfen: $LOG"
            tail -20 "$LOG"
            return 1
        fi
    done
    echo "   ⚠️  $NAME nicht gestartet (Timeout) – Log: $LOG"
    return 1
}

# ── Alle vier Apps starten ───────────────────────────────────
echo ""
start_app "Kiosk"      "$REVIEW/kiosk-app/app"      5001 "/tmp/kiosk-review.log"
start_app "Kasse"      "$REVIEW/kasse-app/app"      5002 "/tmp/kasse-review.log"
start_app "WaWi"       "$REVIEW/wawi-app/app"       5003 "/tmp/wawi-review.log"
start_app "Verwaltung" "$REVIEW/verwaltung-app/app" 5004 "/tmp/verwaltung-review.log"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Worktree: $REVIEW"
echo "  Kiosk:    http://localhost:5001"
echo "  Kasse:    http://localhost:5002"
echo "  WaWi:     http://localhost:5003"
echo "  Verw.:    http://localhost:5004"
echo ""
echo "  Logs:"
echo "    /tmp/kiosk-review.log"
echo "    /tmp/kasse-review.log"
echo "    /tmp/wawi-review.log"
echo "    /tmp/verwaltung-review.log"
echo "══════════════════════════════════════════════════════════"
echo ""
