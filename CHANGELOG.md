# Changelog

Alle wichtigen Änderungen am cao-xt Projekt werden hier dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

---

## [Unreleased]

### Hinzugefügt
- Kiosk Terminal 9: Kunden-Selbstbedienungsterminal für Backwarenbestellungen – Kundenkarten-Scan (KARTEN.TYP='K'), eigene Bestellungen anlegen/einsehen/stornieren, Touch-optimierte Oberfläche, Terminal-Einstellung als eigene Seite im Menü, Login-Button für Rückkehr zur Mitarbeiter-Ansicht ([HAB-360](/HAB/issues/HAB-360))
- Alle Apps: Commit-ID auf allen Login-Seiten (Kiosk, Kasse, WaWi, Verwaltung) ([HAB-360](/HAB/issues/HAB-360))
- Kasse: Kundenkarten-Scan – bei Scan einer Kundenkarte (KARTEN.TYP='K') wird der Kunde automatisch dem Vorgang zugewiesen; Name, Ort, Preisebene und Zahlart erscheinen sofort ([HAB-359](/HAB/issues/HAB-359))

### Geändert
- Verwaltungs-App: Backwaren-Seite verwendet jetzt das Farbschema der Kiosk-App (creme/dunkelgrün/gold) – Navbar, Sidebar, Tabelle und Akzente angepasst; alle anderen Verwaltungsseiten behalten ihr dunkles Theme ([HAB-363](/HAB/issues/HAB-363))

### Behoben
- Kiosk-App: Alter, ins Leere führender „⚙️ Verwaltung"-Sidebar-Link (→ `/admin/artikel`) entfernt; App-Switcher-Button zur Verwaltungs-App wiederhergestellt ([HAB-361](/HAB/issues/HAB-361))
- Verwaltungs-App: Bondrucker-Sidebar-Klick öffnet jetzt korrekt die Druckerliste statt sofort das Anlegen-Overlay – `display:none` als Initialzustand gesetzt, fehlende `.hidden`-CSS-Klasse in `base.html` ergänzt ([HAB-364](/HAB/issues/HAB-364))
- Kasse UI: Artikelschnellzugriff-Bereich auf 380 px erhöht – fünfte Reihe wird nicht mehr abgeschnitten ([HAB-327](/HAB/issues/HAB-327))
- Kasse UI: Münz-/Schein-/Zahlenknöpfe im Kassiervorgang-Overlay sind jetzt quadratisch (`aspect-ratio: 1/1`); Zahlengröße auf 15 px angeglichen (wie Hauptbildschirm) ([HAB-327](/HAB/issues/HAB-327))
- Kasse UI: Bonnummer bekommt eigene Zeile über den Parken/Geparkt-Buttons – kein Platzkonflikt mehr ([HAB-327](/HAB/issues/HAB-327))
- Kasse: `_format_vlsnum()` Fallback erzeugt jetzt reines Zahlenformat (z.B. `018165`) statt `LS018165` – kompatibel mit CAO-VRENUM-Feld (VARCHAR ≤ 7) ([HAB-322](/HAB/issues/HAB-322))
- Kasse: VRENUM/VLSNUM wird korrekt aus REGISTRY MAIN\NUMBERS mit STADIUM=121 gelesen ([HAB-240](/HAB/issues/HAB-240), [HAB-310](/HAB/issues/HAB-310))
- Kasse: NULL/leer-Handling für BEST_CODE, BRUTTO_FLAG und Login-Namen (ERST_NAME/GEAEND_NAME) ([HAB-240](/HAB/issues/HAB-240))
- Kasse: FOLGENR=REC_ID und KM_STAND=-1 korrekt initialisiert; SOLL_SKONTO_TAGE aus lieferschein_zu_journal entfernt ([HAB-240](/HAB/issues/HAB-240))
- Kasse: JOURNAL-Eintragsformat an CAO-Kasse-Standard angepasst; `_format_vlsnum()` mit `max_len`/`no_pad` erweitert ([HAB-240](/HAB/issues/HAB-240))

### Geändert
- Kasse Manager: Vollständiges UI-Redesign – Touch-Targets ≥ 52 px, Tab-Bar ohne Kassenbuch-Dominanz, Morgenroutine/Abendroutine inline, Journal mit Volltextsuche und Scroll, Kasse-Button in Navbar navigiert zur Startseite, Bon-Details ohne Seitenreload, „Nachdruck" statt „Nochmal", „Positionen in neuen Bon kopieren" statt „Kopieren" ([HAB-353](/HAB/issues/HAB-353))
- Kasse Journal: Zeitstempel und Datumsfilter verwenden `ABSCHLUSS_DATUM` (Zahlungszeitpunkt) statt `BON_DATUM`; Fallback auf `BON_DATUM` für Altdaten ([HAB-311](/HAB/issues/HAB-311))
- WaWi Preispflege: Artikelfilter erweitert – zeigt jetzt alle aktiven Artikel (Normal, Frei, Stückliste) statt nur Normalartikel; neue Typ-Spalte; Faktor zeigt „–" wenn VK5 oder EK = 0 ([HAB-293](/HAB/issues/HAB-293))

### Hinzugefügt
- Login: Kartenlogin per Barcode-Scan für Mitarbeiter (KARTEN.TYP='M') in allen vier Apps (Kiosk, Kasse, WaWi, Verwaltung); gemeinsame Logik in `common/auth.py`; Tab-Umschaltung „Karte scannen" / „Passwort" ([HAB-358](/HAB/issues/HAB-358))
- Login: Touch-Tastatur (QWERTZ-Layout) im Passwort-Login aller vier Apps – kein Tastatur-Zwang mehr am Touchscreen; Shift, Backspace, Sonderzeichen, OK-Submit ([HAB-358](/HAB/issues/HAB-358))
- Update-Mechanismus: `VERSION.json` im Repo-Root; `installer/updater.py` (git-basierte Update-Prüfung und -Durchführung mit Rollback); `install.sh --update` / `--check-update` als Konsolen-Fallback; Verwaltungs-App: neue Seite „System → Updates" mit Version-Vergleich, Impact-Anzeige (DB-Migration, neue Abhängigkeiten, Breaking Change), Commit-Liste und geführtem Update-Ablauf ([HAB-356](/HAB/issues/HAB-356))
- Installationsroutine: `install.sh` (Bash-Wrapper) + `installer/`-Paket mit `install.py`, `app_manager.py`, `db_init.py`; `dorfkern-ctl` für install/start/stop/restart/status aller vier Apps; CAO-DB-Erkennung über MITARBEITER-Tabelle; idempotente XT_*-Tabellen-Initialisierung; Umgebungs-Flag (produktion/training) in caoxt.ini ([HAB-355](/HAB/issues/HAB-355))
- Kasse Trainingsmodus: `xt_environment`-Flag (`produktion`|`training`) in `caoxt.ini [Umgebung]`; `load_environment()` in `common/config.py`; Kasse-Config exponiert `TRAININGSMODUS`-Boolean – Grundlage für JOURNAL/TSE-Bypass im Trainingsmodus ([HAB-350](/HAB/issues/HAB-350))
- Entwicklungsinfrastruktur: `deploy-review.sh` startet jetzt alle vier Apps (Kiosk 5001, Kasse 5002, WaWi 5003, Verwaltung 5004) im Review-Worktree; Konfigurationsprüfung und `.deployed`-Marker hinzugefügt ([HAB-345](/HAB/issues/HAB-345))
- Verwaltungs-App (Port 5004): Neue Admin-App mit DB-Konfiguration, Bondrucker-Verwaltung (CRUD), Terminal-Verwaltung, TSE-Geräte-Konfiguration und Login-Schutz ([HAB-330](/HAB/issues/HAB-330), [HAB-335](/HAB/issues/HAB-335))
- Common-Bereich / Shared Modules: Neues `common/`-Package mit gemeinsamer DB-, Config-, Auth- und Druck-Logik; alle drei Apps (Kasse, Kiosk, WaWi) migriert ([HAB-332](/HAB/issues/HAB-332))
- WaWi Preispflege: On-Screen-Numpad für Touch-Eingabe ([HAB-332](/HAB/issues/HAB-332))
- Kasse Manager: Volle Breite, Transfer-Bereich nebeneinander, Ein-Klick-Buchung ([HAB-329](/HAB/issues/HAB-329))
- Kasse: Letzter Bon druckt Lieferschein-Layout bei Lieferschein-Vorgängen korrekt ([HAB-328](/HAB/issues/HAB-328))
- WaWi CFO-Berichte (Phase 1): Tagesumsatz, Monatsübersicht, Kassenbuch, EC-Umsätze – parametrisierbare Zeitraumfilter, CSV-Export je Bericht, Monats-Chart (Chart.js) ([HAB-238](/HAB/issues/HAB-238))
- WaWi Preispflege: Touch-optimierter Warengruppenbaum (größere Tap-Targets, aktiver Zustand) und verbessertes Anpassen-Panel für Touch-Bedienung ([HAB-280](/HAB/issues/HAB-280))
- WaWi Preispflege-Tabelle: Alle Normalartikel mit EK / VK5 (Brutto) / Marge auf einen Blick; VK5 inline editierbar, Filter nach Warengruppe, Sortierung nach Marge, Rot-Markierung bei Marge < 10 % ([HAB-235](/HAB/issues/HAB-235))
- Commit-ID-Anzeige: In allen drei Apps (Kasse, Kiosk, WaWi) wird der aktuelle Git-Commit-Hash oben links als kleiner orangener Hinweis angezeigt (position:fixed, kein Layout-Einfluss) ([HAB-244](/HAB/issues/HAB-244))
- Verbindliche Merge-Pflicht: Sofort-Merge nach Board-Freigabe, 48h-Limit für offene Branches, Rebase-Strategie für Parallelarbeit ([HAB-267](/HAB/issues/HAB-267))
- `.githooks/pre-push`: Versionierter Git-Hook mit Paperclip-Approval-Pflicht für `master`/`main` Pushes ([HAB-242](/HAB/issues/HAB-242))
- CI-Pipeline: GitHub Actions Workflow (`.github/workflows/tests.yml`) mit separaten Jobs für kasse-app und wawi-app ([HAB-201](/HAB/issues/HAB-201))
- wawi-app: Erste Testdatei `wawi-app/tests/test_vk_berechnen.py` (10 Tests, Coverage-Baseline 48%) für `vk_berechnen()` und `preis_setzen()` in `modules/wawi/models.py` ([HAB-201](/HAB/issues/HAB-201))
- `deploy-review.sh`: Script zum atomaren Deployment von Feature-Branches in den Review-Worktree inkl. automatischem WaWi-Server-Neustart ([HAB-194](/HAB/issues/HAB-194))
- `deploy-review.sh`: Robusteres Port-Handling (SIGTERM + PID-Datei) ([HAB-194](/HAB/issues/HAB-194))
- Neue Flask-App `wawi-app` auf Port 5003 mit Dashboard (CFO-Kennzahlen), Sidebar-Navigation und WaWi-Blueprint-Integration ([HAB-131](/HAB/issues/HAB-131))
- WaWi-Button in Navbar von kasse-app und kiosk-app ([HAB-131](/HAB/issues/HAB-131))
- WaWi-Navbar: App-Switcher (Kiosk → Kasse → WaWi), Logo-Wrapper, Uhrzeit/Datum, Login-Name ([HAB-139](/HAB/issues/HAB-139))
- Kasse-Navbar: App-Switcher mit aktiv/inaktiv-Zuständen, Login-Name ([HAB-139](/HAB/issues/HAB-139))
- Kiosk-App: Session-Login (Login-Required, Login/Logout-Routen), App-Switcher, Context-Processor ([HAB-139](/HAB/issues/HAB-139))
- Verbindlicher Merge-Workflow `review → master` dokumentiert ([HAB-196](/HAB/issues/HAB-196))
- Kasse: %-Schnellauswahl-Knöpfe für Prozentsatz-Rabatt ([HAB-142](/HAB/issues/HAB-142))
- Kiosk-App: vollständiger Session-Login-Mechanismus (Login/Logout, Login-Required, login.html) mit Anzeige von Login-Name, Uhrzeit und Datum rechts in der Navbar ([HAB-162](/HAB/issues/HAB-162))
- Kiosk-App: `firma_name` und `db_name` im Context-Processor; FIRMA_NAME-Konfigurationsvariable ([HAB-149](/HAB/issues/HAB-149))

### Geändert
- Update-Funktion in kasse-app und kiosk-app: `git pull` durch `git fetch` + `git reset --hard origin/master` ersetzt – behebt Fehler bei abweichenden Branches ([HAB-272](/HAB/issues/HAB-272))
- `kasse-app/app/config.py`: WAWI_URL / WAWI_PORT ergänzt ([HAB-131](/HAB/issues/HAB-131))
- `kiosk-app/app/config.py`: WAWI_URL / WAWI_PORT ergänzt ([HAB-131](/HAB/issues/HAB-131))
- WaWi-Reporting: SQL Datumsformat-Escaping und Warengruppen-SQL korrigiert ([HAB-139](/HAB/issues/HAB-139))
- Kasse: EP-Button auf Größe der X-Schaltfläche angepasst; Numpad-Grid quadratisch ([HAB-147](/HAB/issues/HAB-147), [HAB-148](/HAB/issues/HAB-148))
- WaWi-App: Logo „WaWi" jetzt vertikal unter Firmenname (flex-column), nicht mehr daneben ([HAB-149](/HAB/issues/HAB-149))
- Kiosk-App: App-Switcher in `<header>` verschoben (war in `<nav>`); Firmenname und Mandantname im Logo; Nav-Knöpfe mit Rahmen und einheitlicher Höhe; „Kiosk"-Button navigiert zur Startseite ([HAB-149](/HAB/issues/HAB-149))

## [0.2.0] – 2026-04-04

### Behoben
- Kundenauswahl korrekt mit geparkt/entparkt verknüpfen – Kunde wird beim Parken zurückgesetzt und beim Entparken wiederhergestellt; Geparkte-Bons-Liste zeigt Kundennamen (HAB-95)
- 3 Abend-Routine UI-Bugs behoben: Kassensturz nach Z-Bon gesperrt, Weiterleitung nach Transfer Kasse→Bank, Status-Wiederherstellung bei nach_bank=1 (HAB-100)

## [0.1.0] – 2026-04-04

### Hinzugefügt
- DECISIONS.md für Architekturentscheidungen eingeführt
- CHANGELOG.md eingeführt
- Benutzerhandbücher unter `docs/` angelegt
- Merge-Pflicht für Dokumentationsaktualisierung in AGENTS.md verankert

### Geändert
- *noch keine*

### Behoben
- *noch keine*
