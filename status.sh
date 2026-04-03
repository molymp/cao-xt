#!/bin/bash
# ============================================================
# CAO-XT Projekt-Status Dashboard
# Ausführen: ./status.sh
# ============================================================

REPO="/Volumes/MacDisk01/ml/Documents/GitHub/cao-xt"
REVIEW="/Volumes/MacDisk01/ml/Documents/GitHub/cao-xt-review"
PAPERCLIP_API="http://127.0.0.1:3100"

cd "$REPO" || exit 1

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          CAO-XT ENTWICKLUNGSSTAND                       ║"
echo "║          $(date '+%d.%m.%Y %H:%M')                            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Master: letzte Commits ───────────────────────────────────
echo "📦 MASTER – Letzte 5 Commits:"
echo "────────────────────────────────────────────"
git log --oneline -5 master | sed 's/^/  /'
echo ""

# ── Offene Feature-Branches ──────────────────────────────────
echo "🌿 FEATURE-BRANCHES (noch nicht in master):"
echo "────────────────────────────────────────────"
branches=$(git branch -a | grep "claude/" | grep -v "remotes/origin" | tr -d ' ')
if [ -z "$branches" ]; then
    echo "  Keine offenen Feature-Branches"
else
    for branch in $branches; do
        count=$(git log master..$branch --oneline 2>/dev/null | wc -l | tr -d ' ')
        last=$(git log -1 --format="%s" "$branch" 2>/dev/null)
        echo "  $branch ($count commits)"
        echo "    → $last"
    done
fi
echo ""

# ── Review-Worktree ──────────────────────────────────────────
echo "🔍 REVIEW-WORKTREE:"
echo "────────────────────────────────────────────"
if [ -d "$REVIEW" ]; then
    review_branch=$(git -C "$REVIEW" branch --show-current 2>/dev/null)
    review_hash=$(git -C "$REVIEW" rev-parse --short HEAD 2>/dev/null)
    echo "  Branch: $review_branch ($review_hash)"
    echo "  Kasse:  $REVIEW/kasse-app/app/"
    echo "  Kiosk:  $REVIEW/kiosk-app/app/"
else
    echo "  ⚠️  Review-Worktree nicht gefunden"
fi
echo ""

# ── Uncommitted Changes ──────────────────────────────────────
dirty=$(git status --porcelain | grep -v "^??" | wc -l | tr -d ' ')
if [ "$dirty" -gt 0 ]; then
    echo "⚠️  UNCOMMITTED CHANGES IN MASTER REPO: $dirty Datei(en)"
    git status --short | grep -v "^??" | sed 's/^/  /'
    echo ""
fi

echo "══════════════════════════════════════════════════════════"
echo "  Test-URL Kasse: http://localhost:5002"
echo "  Test-URL Kiosk: http://localhost:5001"
echo "══════════════════════════════════════════════════════════"
echo ""
