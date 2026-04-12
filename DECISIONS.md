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

## 2026-04-12 deploy-review.sh startet alle vier Apps; ein gemeinsamer Review-Worktree (HAB-345)

- **Problem:** `deploy-review.sh` startete nur die WaWi-App (Port 5003). Das Board kann nicht alle vier Apps (Kiosk 5001, Kasse 5002, WaWi 5003, Verwaltung 5004) testen. Außerdem fehlte `config_local.py` für die Verwaltungs-App im Review-Worktree. Gemeldet via [HAB-341](/HAB/issues/HAB-341).
- **Entscheidung:** `deploy-review.sh` startet jetzt alle vier Apps in einem einzigen Review-Worktree (`cao-xt-review`). Race Conditions bei simultanen Deployments werden durch Prozessregeln verhindert: nur der CTO ruft `deploy-review.sh` auf.
- **Begründung:** Ein Worktree entspricht dem Board-Workflow (alle Apps unter bekannten Ports). Race Conditions sind bei zwei Agenten durch klare Prozessregeln beherrschbar.
- **Alternativen:** (a) Separate Worktrees je Agent (vom Board abgelehnt – Board will eine einheitliche Test-URL), (b) Lock-Datei-Mechanismus (unnötiger Overhead bei 2 Agenten).
- **Konsequenzen:** `deploy-review.sh` startet/stoppt jetzt alle 4 Prozesse. Board testet immer unter localhost:5001–5004. `config_local.py` für Verwaltung im Review-Worktree angelegt (manuell, da gitignored).
- **Referenz:** [HAB-345](/HAB/issues/HAB-345)

## 2026-04-12 Verwaltungs-App als eigenständige Flask-App (Port 5004) (HAB-330)

- **Problem:** Admin-Funktionen (DB-Konfiguration, Drucker, Terminals, TSE) wurden bisher nicht zentral verwaltet. Konfigurationsänderungen erforderten direkten Dateizugriff.
- **Entscheidung:** Neue eigenständige Flask-App `verwaltung-app` auf Port 5004 nach dem Thin-Wrapper-Pattern der bestehenden Apps.
- **Begründung:** Gleiche Architektur wie kasse-app/kiosk-app/wawi-app – geringer Lernaufwand, konsistente Deployment-Strategie, einfache Erweiterung.
- **Alternativen:** (a) Admin-Bereich in bestehender WaWi-App integrieren (vermischt Verantwortlichkeiten), (b) Separates Admin-Framework (zu viel Overhead).
- **Konsequenzen:** Vierter App-Prozess auf dem System. Login-Schutz ist obligatorisch, da Admin-Zugang kritische DB-Konfiguration enthält.
- **Referenz:** [HAB-330](/HAB/issues/HAB-330), [HAB-335](/HAB/issues/HAB-335)

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

## 2026-04-05 Teststrategie & CI-Pipeline: GitHub Actions + Unit Tests mit Mocks

- **Problem:** Kein automatisiertes Testing vorhanden. Nur kasse-app hatte manuell ausführbare Tests; wawi-app und kiosk-app hatten keine Tests. Kein CI/CD-System.
- **Entscheidung:** GitHub Actions als CI-Plattform. Unit Tests mit `unittest.mock` (kein echter DB-Server). Separate Jobs pro App. Coverage-Messung auf dem jeweiligen Kernmodul.
- **Begründung:** GitHub Actions ist kostenfrei für das Repo und benötigt keine eigene Infrastruktur. Der Mock-Ansatz (bereits in kasse-app bewährt) funktioniert ohne DB-Server – CI läuft auf Standard-Ubuntu-Runner. Coverage-Gate absichtlich nicht scharf geschaltet (Vertrauen auf Disziplin), kann bei Bedarf nachgezogen werden.
- **Alternativen:** (a) Self-hosted Runner auf RPi – abgelehnt, RPi ist Produktions- und Review-System; (b) Integrationstests mit echter SQLite-DB – optional, später möglich; (c) pytest-django / pytest-flask – nicht nötig, da Geschäftslogik ohne laufenden Server testbar ist.
- **Konsequenzen:** CI läuft bei jedem Push auf Feature-Branches und bei PRs gegen `master`. Coverage-Baselines: kasse-app (kasse_logik) 17%, wawi-app (models) 48%. Ziele: kasse-app → 80%, wawi-app → 40% (bereits erreicht).
- **Referenz:** HAB-201 (Umsetzung), HAB-106 (Teststrategie-Beschluss)

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


---

## 2026-04-12 Common-Bereich / Shared Modules Package (HAB-332)

- **Problem:** DB-Verbindung, Config-Laden, Auth-Middleware und Druck-Logik waren dreifach dupliziert (kasse-app, kiosk-app, wawi-app). Änderungen mussten in drei Apps parallel gepflegt werden.
- **Entscheidung:** Neues `common/`-Package im Repo-Root mit den Modulen `db.py`, `config.py`, `auth.py` und `druck/escpos.py`. Alle drei Apps wurden auf dieses gemeinsame Package migriert.
- **Begründung:** Single Source of Truth für infrastrukturelle Logik. Neue Apps (z.B. Verwaltungs-App) können das Package sofort nutzen ohne Codeduplizierung.
- **Alternativen:** Separate pip-Package-Veröffentlichung (zu aufwändig für internes Projekt); Symlinks (nicht portabel, Git-unfreundlich).
- **Konsequenzen:** `PYTHONPATH` muss beim App-Start auf Repo-Root zeigen. Kiosk-App liest eigene `Backwaren`-DB – nutzt daher `common/db.py` mit eigenem DB-Namen, nicht die Standard-CAO-DB.
- **Referenz:** [HAB-332](/HAB/issues/HAB-332)
