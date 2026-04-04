# Architekturentscheidungen (DECISIONS.md)

Dieses Dokument protokolliert alle wesentlichen technischen und architekturellen Entscheidungen im cao-xt Projekt.

**Format:**
```
## [DATUM] [KURZTITEL]
- **Problem:** Was war das Problem oder die Anforderung?
- **Entscheidung:** Was wurde entschieden?
- **Begründung:** Warum diese Entscheidung?
- **Alternativen:** Welche Alternativen wurden erwogen?
- **Konsequenzen:** Was sind die Auswirkungen?
- **Referenz:** HAB-XX (Paperclip-Issue)
```

---

## 2026-04-04 deploy-review.sh: git reset --hard statt git checkout für Review-Deployment

- **Problem:** Änderungen aus Feature-Branches landeten nicht zuverlässig im Review-Worktree (`cao-xt-review`). Dateien wurden manuell kopiert, Server nicht neu gestartet → inkonsistenter Testzustand.
- **Entscheidung:** `deploy-review.sh` nutzt `git reset --hard <commit>` auf dem Review-Worktree statt `git checkout <branch>`.
- **Begründung:** Git-Worktrees erlauben keinen gleichzeitigen Checkout desselben Branches in zwei Worktrees. `reset --hard` umgeht diese Einschränkung, indem der `review`-Branch-Zeiger direkt auf den gewünschten Commit gesetzt wird. Das Script startet außerdem den WaWi-Server (Port 5003) automatisch neu.
- **Alternativen:** (a) flask-debug-reload (setzt `WAWI_DEBUG=true` voraus, ungeeignet für Produktionsähnlichkeit), (b) Änderungen direkt im `review`-Worktree committen (verhindert saubere Branch-Trennung).
- **Konsequenzen:** Review-Worktree `review`-Branch zeigt immer auf den zuletzt deployten Feature-Branch-Commit. Kein manuelles Dateikopieren oder Server-Neustart mehr nötig.
- **Referenz:** HAB-194

## 2026-04-04 wawi-app als eigenständige Flask-App auf Port 5003

- **Problem:** Das bestehende WaWi-Modul (`modules/wawi`) hatte keinen eigenen Einstiegspunkt für den Browser; CFO-Kennzahlen waren nicht zugänglich.
- **Entscheidung:** Neue Flask-App `wawi-app` analog zu `kasse-app` und `kiosk-app` erstellt (Port 5003). WaWi-Blueprint aus `modules/wawi/routes.py` wird eingebunden. kasse-app und kiosk-app erhalten einen WaWi-Schnellzugriff-Button in der Navbar.
- **Begründung:** Trennung der Apps nach Aufgabe (Kasse, Kiosk, WaWi) hält die Codebasis übersichtlich und erlaubt unabhängige Starts/Deployments.
- **Alternativen:** WaWi als Blueprint in kasse-app integrieren (Kopplung zu hoch); separater Webserver mit anderem Framework (zu fremdartig im Stack).
- **Konsequenzen:** Dritter Port im LAN (5003). DB-Zugangsdaten werden analog aus `caoxt/caoxt.ini` gelesen. `wawi-app` ist unabhängig startbar.
- **Referenz:** [HAB-131](/HAB/issues/HAB-131)

---

## 2026-04-04 Verbindlicher Merge-Workflow: review → master (HAB-196)

- **Problem:** Implementierte und board-getestete Änderungen (z. B. Navbar-Fixes aus HAB-139) landeten im `review`-Branch, wurden aber nie in `master` gemergt. Beim nächsten Deploy aus `master` verschwanden diese Änderungen.
- **Entscheidung:** Der Merge-Workflow wird verbindlich wie folgt festgelegt:
  1. Feature-Branch (`cto/<name>`) wird aus `master` erstellt.
  2. `deploy-review.sh cto/<name>` deployt auf den Review-Worktree (Testumgebung).
  3. Board testet und gibt **schriftlich im Ticket** frei.
  4. Nach Freigabe: `git merge --no-ff cto/<name>` in `master`, dann `git push origin master`.
  5. Der `review`-Branch wird nach jedem Master-Merge automatisch via `deploy-review.sh` aktualisiert.
  **Sonderfall Sofort-Merge:** Wenn board-genehmigte Commits bereits im `review`-Branch stehen (ohne zugehörigen CTO-Branch), wird ein `cto/hab-XXX-release-fix`-Branch erstellt, der `review` merged, und der gleiche Freigabeprozess durchlaufen.
- **Begründung:** Cherry-picks sind fehleranfällig und lassen sich schlecht auditieren. Ein vollständiger Branch-Merge (`--no-ff`) hält die History klar.
- **Alternativen:** (a) Direkt auf `review` deployen ohne Feature-Branch (verliert Traceability), (b) Automatisiertes CI (zu aufwändig für aktuellen Projektstand).
- **Konsequenzen:** Kein Commit kommt mehr ohne Board-Freigabe in `master`. Der `review`-Branch wird stets als Staging-Umgebung betrieben und entspricht dem letzten board-geprüften Stand.
- **Referenz:** [HAB-196](/HAB/issues/HAB-196)

## 2026-04-04 DECISIONS.md und Benutzerhandbücher als Merge-Pflicht eingeführt

- **Problem:** Board-Mitglieder konnten nicht nachvollziehen, was sich bei einem Release geändert hat und warum Entscheidungen so getroffen wurden.
- **Entscheidung:** Ab sofort ist jeder Merge in den `master` Branch nur zulässig, wenn DECISIONS.md, die relevanten Benutzerhandbücher und CHANGELOG.md aktualisiert wurden.
- **Begründung:** Transparenz für das Board, Nachvollziehbarkeit für zukünftige Entwickler.
- **Alternativen:** Externe Wiki-Lösung (zu komplex), nur Kommentare in Commits (nicht zugänglich genug).
- **Konsequenzen:** Mehr Dokumentationsaufwand pro Feature, aber dauerhaft bessere Übersicht.
- **Referenz:** [HAB-105](/HAB/issues/HAB-105)
