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

## 2026-04-06 Verbindliche Merge-Pflicht: Sofort-Merge nach Board-Freigabe (HAB-267)

- **Problem:** Fix-Branches wurden implementiert und im Review-Worktree getestet, aber nie in `master` gemergt. Bereits gefixte Issues tauchten erneut auf, weil die Fixes zwar auf Branches existierten, aber nie in die Produktionsbasis landeten. Beispiel: `claude/hab-101-bon-timestamp` existierte Wochen ohne Merge. Das Board verlor das Vertrauen in die Stabilität des Systems.
- **Entscheidung:** Vier verbindliche Regeln:
  1. **Sofort-Merge-Pflicht:** Jeder board-freigegebene Branch MUSS im selben Heartbeat gemergt werden, in dem die Freigabe eingeht. Kein Branch bleibt nach Freigabe offen.
  2. **Kurzlebige Branches:** Feature-Branches dürfen maximal 48 Stunden offen sein. Branches ohne Merge nach 48 Stunden gelten als Prozessfehler und werden im zugehörigen Ticket eskaliert.
  3. **Rebase vor Merge:** Bevor ein Feature-Branch gemergt wird, muss er auf den aktuellen `master` rebased werden (`git rebase master`). Konflikte werden vor dem Merge gelöst.
  4. **Parallelarbeit über Subtasks:** Parallele Features werden als separate Subtasks mit eigenen Branches geführt. Merge-Reihenfolge wird durch Task-Priorität bestimmt; niedrigpriore Branches warten auf Master-Stand und rebasen dann.
- **Begründung:** Lange offene Branches erzeugen Regressions-Spiralen: Fixes fehlen in `master`, parallele Branches divergieren zunehmend, und Merges werden immer aufwändiger. Sofortiger Merge nach Freigabe ist die einzige Lösung.
- **Alternativen:** (a) Separate Merge-Aufgabe als Subtask (erhöht Overhead, Vergessen wahrscheinlich), (b) Automatisierter CI-Merge (zu aufwändig für aktuellen Projektstand), (c) Squash-Commits (verliert Traceability).
- **Konsequenzen:** Ein Heartbeat ist erst abgeschlossen, wenn alle board-freigegebenen Branches gemergt und mit `PAPERCLIP_APPROVAL_ID` gepusht sind. Der CTO ergänzt die Merge-Pflicht in seinen Agenten-Instruktionen als explizite Checkliste.
- **Referenz:** [HAB-267](/HAB/issues/HAB-267)

---

## 2026-04-06 Versionierter pre-push Hook mit Paperclip-Approval-Pflicht (HAB-242)

- **Problem:** Der alte `pre-push` Hook in `.git/hooks/pre-push` blockierte ALLE Pushes auf `master` – auch den CTO nach gültiger Board-Freigabe. Zudem war er nicht versioniert und somit nicht reproduzierbar.
- **Entscheidung:** Neuer Hook in `.githooks/pre-push` (versioniert im Repo). Pushes auf `master`/`main` sind nur erlaubt wenn die Umgebungsvariable `PAPERCLIP_APPROVAL_ID` gesetzt ist. Aktivierung: `git config core.hooksPath .githooks`.
- **Begründung:** Hooks im `.git/`-Verzeichnis sind lokal und nicht committet. Ein Verzeichnis `.githooks/` im Repo-Root wird versioniert und ist für alle Entwickler/Agenten reproduzierbar. Die `PAPERCLIP_APPROVAL_ID`-Pflicht stellt sicher, dass Pushes auf `master` nachvollziehbar mit einer Board-Freigabe verknüpft sind.
- **Alternativen:** (a) GitHub Branch-Protection Rules (setzt GitHub-Admin-Zugriff voraus, schützt nur remote), (b) Vollständige Blockade ohne Escape-Hatch (verhindert CTO-Merge nach Freigabe).
- **Konsequenzen:** CTO muss beim Master-Merge `PAPERCLIP_APPROVAL_ID=<id>` setzen. Alle Entwickler einmalig `git config core.hooksPath .githooks` ausführen.
- **Referenz:** HAB-242

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


---

## 2026-04-07 CFO-Berichte via separatem berichte.py-Modul (HAB-238)

- **Problem:** CFO benötigt operative Berichte (Tagesumsatz, Monatsübersicht, Kassenbuch, EC-Umsätze) direkt in der WaWi-App mit Zeitraumfilter und CSV-Export.
- **Entscheidung:** Neues Modul `berichte.py` mit parametrisierbaren SQL-Queries (direkt aus CAO-Faktura-DB) und 8 Flask-Routen unter `/wawi/berichte/...`. `get_cao_db` als Alias für `get_db` in `db.py` – beide zeigen auf dieselbe CAO-DB.
- **Begründung:** Trennung von Business-Logik (berichte.py) und Routing (app.py) hält die Codebasis wartbar. Alias-Ansatz vermeidet Config-Änderungen (keine neuen CAO_DB_*-Variablen nötig) und nutzt bestehenden Pool.
- **Alternativen:** Berichte direkt im bestehenden `/reporting`-Endpunkt integrieren (würde den bereits vorhandenen Reporting-Bereich überlasten); separater Micro-Service (zu aufwändig).
- **Konsequenzen:** CSV-Export mit UTF-8-BOM für Excel-Kompatibilität. Phase 2 (Lieferantenumsätze, Wareneinsatz/Marge) steht aus.
- **Referenz:** [HAB-238](/HAB/issues/HAB-238)
