# Benutzerhandbuch – Verwaltungs-App

**Version:** 1.3.0 | **Stand:** 2026-04-19 | **App:** Verwaltung (Port 5004)

---

## Übersicht

Die Verwaltungs-App ist die zentrale Konfigurationsoberfläche für den Habacher Dorfladen.
Sie ist über **http://localhost:5004** erreichbar und erfordert eine Mitarbeiter-Anmeldung.

---

## Navigation

Die Sidebar links gliedert sich in zwei Bereiche:

| Bereich  | Menüpunkt        | Funktion                                     |
|----------|------------------|----------------------------------------------|
| System   | Datenbank        | DB-Verbindung konfigurieren und testen        |
| System   | Bondrucker       | Thermobondrucker verwalten (CRUD)             |
| System   | Terminals        | Terminal-Nummern konfigurieren               |
| System   | TSE-Geräte       | TSE-Geräte-Verbindungen einrichten           |
| System   | **Updates**      | System-Updates prüfen und installieren       |
| Daten    | Backwaren        | Artikel für den Kiosk verwalten              |
| Daten    | **Funktionen**   | Feature-Toggles für Kiosk- und Kasse-App    |
| Personal | **Feiertage**    | Bundesland-Auswahl und Feiertage pflegen     |
| Personal | **Benachrichtigungen** | E-Mail-Verteiler für Hinweise pro Bereich |
| Personal | **Zeiten-Import** | ShiftJuggler-CSV in die Zeiterfassung importieren |
| Hilfe    | **Handbuch**     | Mitarbeiter-Handbuch (lesbar, bearbeitbar)   |

---

## System → Updates

### Zweck

Die Updates-Seite zeigt, ob eine neuere Version von CAO-XT verfügbar ist,
und ermöglicht das geführte Einspielen des Updates direkt aus der Browser-Oberfläche.

### Bedienung

1. **„Auf Updates prüfen" klicken**
   - Die App verbindet sich mit dem Git-Repository und vergleicht die installierte
     Version mit der aktuell verfügbaren.
   - Dazu ist eine Internetverbindung (oder Netzwerkzugang zum Repository-Server) erforderlich.

2. **Ergebnis lesen**
   - *„Das System ist aktuell"* – kein Handlungsbedarf.
   - Neue Version verfügbar: Versionsangabe, Changelog-Zusammenfassung und
     neue Commits werden angezeigt.

3. **Impact-Hinweise beachten**

   | Badge                  | Bedeutung                                                  |
   |------------------------|------------------------------------------------------------|
   | ⚠️ Breaking Change     | Manuelle Prüfung vor dem Update empfohlen                 |
   | 🗄️ DB-Migration        | Datenbank wird automatisch aktualisiert                   |
   | 📦 Neue Abhängigkeiten | Python-Pakete werden neu installiert                      |
   | 🔄 Neustart erforderlich | Alle Apps werden gestoppt und neu gestartet             |

4. **„Update jetzt installieren" klicken** (nur wenn Update verfügbar)
   - Es erscheint eine Sicherheitsabfrage.
   - Nach Bestätigung wird das Update im Hintergrund durchgeführt.
   - Die Apps werden gestoppt, das Update eingespielt und die Apps neu gestartet.
   - Die Seite lädt sich nach ca. 15 Sekunden automatisch neu.
   - Detaillierter Fortschritt: Datei `/tmp/caoxt-update.log` auf dem Server.

### Konsolen-Fallback

Falls die Verwaltungs-App selbst nicht erreichbar ist (z.B. nach einem fehlerhaften Update),
kann das Update direkt über die Kommandozeile auf dem Server durchgeführt werden:

```bash
./install.sh --update          # Update durchführen
./install.sh --check-update    # Nur prüfen, nicht updaten
```

Das Script schreibt den Fortschritt nach `/tmp/caoxt-update.log`.

---

## Daten → Funktionen

Die Funktionen-Seite ermöglicht das Ein- und Ausschalten einzelner Features in der Kiosk- und Kasse-App.

### Verfügbare Schalter

| Schalter | Wirkung |
|----------|---------|
| Kiosk – Beleg parken | Zeigt/versteckt die Buttons „Parken" und „Geparkt" in der Kiosk-App |
| Kasse – Beleg parken | Zeigt/versteckt die Buttons „Parken" und „Geparkt" in der Kasse-App |

### Bedienung

1. **Toggle-Schalter** umlegen (grün = aktiv, grau = inaktiv)
2. Bestätigung erscheint als Toast-Meldung
3. **Kiosk-/Kasse-App im Browser neu laden** (F5 / Ctrl+F5) – die Änderung wird erst beim nächsten Seitenaufruf wirksam

### Einschränkungen

- **Deaktivierung blockiert**, wenn noch Bons/Warenkörbe geparkt sind (Fehlermeldung 409)
- Zuerst alle geparkten Vorgänge abschließen oder entparken, dann deaktivieren

---

## Personal → Feiertage

Pflegt die Liste der gesetzlichen und betrieblichen Feiertage, die im Arbeitszeitkonto und in den Stundenzetteln berücksichtigt werden.

### Bundesland auswählen

Oben auf der Seite ein Dropdown mit allen 16 deutschen Bundesländern (plus `BUND` für bundesweite Feiertage). Die Auswahl gilt systemweit und wird in `XT_EINSTELLUNGEN` (`schluessel='personal_bundesland'`) gespeichert.

### Feiertage synchronisieren

Button **„Feiertage synchronisieren"** (je Jahr). Die App verwendet das Python-Paket `holidays` und schreibt alle gesetzlichen Feiertage für das gewählte Bundesland und Jahr via `INSERT IGNORE` in `XT_PERSONAL_FEIERTAG`:

- Bereits vorhandene Einträge bleiben unberührt (Quelle: `holidays`).
- Zusätzlich bundesweite Einträge mit `BUNDESLAND='BUND'` (Neujahr, Tag der Arbeit, …).
- Fehlt das `holidays`-Paket, erscheint eine Fehlermeldung.

### Manuelle Einträge

Für betriebsinterne freie Tage (z. B. Betriebsausflug, Brückentag) kann ein Eintrag manuell angelegt werden:

- **Datum** (Datepicker mit Jahr-/Monats-Sprung)
- **Name** (z. B. „Betriebsausflug Dorfladen")
- **Bundesland** — bei betriebsweiter Gültigkeit auf das aktive Bundesland setzen.

Manuelle Einträge werden in der Liste oben angezeigt (erkennbar an Quelle `manuell`), bleiben beim nächsten Sync erhalten und lassen sich per Klick löschen.

### Jahr wählen

URL-Parameter `?jahr=YYYY` oder Jahresauswahl auf der Seite. Default: aktuelles Kalenderjahr.

---

## Personal → Benachrichtigungen

Verwaltet pro Hinweis-Bereich die Liste der E-Mail-Empfänger, die beim entsprechenden Ereignis automatisch informiert werden.

### Verfügbare Bereiche

| Schlüssel | Beschreibung |
|-----------|-------------|
| `abwesenheit_antrag` | Neue Abwesenheits-Meldung eines Mitarbeiters (Krank / Fortbildung / Sonstiges) |
| `urlaub_antrag` | Neuer Urlaubsantrag eines Mitarbeiters |

Weitere Bereiche werden ergänzt, sobald neue Kategorien hinzukommen.

### Empfänger anlegen

Pro Bereich eine kleine Liste mit Formular:

- **E-Mail-Adresse** (Pflicht, validiert gegen `@` und Länge ≤ 150).
- **Name** (optional, für Lesbarkeit).
- **Aktiv** (Toggle) — inaktive Empfänger bleiben in der Liste, bekommen aber keine Mails. Nützlich für Urlaubsvertretung.

### Aktiv-/Inaktiv-Toggle

Klick auf den Toggle in einer Zeile wechselt den Status ohne Seitenreload (AJAX). Gelöscht wird dauerhaft über den 🗑-Button.

### SMTP-Konfiguration

Der Mail-Versand nutzt den gleichen gemeinsamen Helper wie die Schichtplan-Freigabe (`common/email.py`): SMTP-Daten stammen primär aus der CAO-REGISTRY (`MAINKEY='MAIN\EMAIL'`), Fallback auf `XT_EMAIL_*`-ENV und `[Email]`-Sektion in `caoxt.ini`. Ist SMTP nicht konfiguriert, werden Mails schlicht nicht versendet — ohne Fehler für den Antragsteller.

---

## Personal → Zeiten-Import

Importiert historische Zeiterfassungsdaten aus dem früher genutzten **ShiftJuggler**-System als CSV in die `XT_PERSONAL_ZEITEN`-Tabelle der WaWi.

### Ablauf

1. **CSV auswählen** (UTF-8, ShiftJuggler-Attendance-Format).
2. Toggle **„Dry-Run"** (Default: aktiv). Bei Dry-Run wird die Datei geparst und geprüft, aber nichts geschrieben.
3. **Importieren** klicken.

### Report

Nach Verarbeitung zeigt die Seite:

- **Gelesene Zeilen** und **erkannte Mitarbeiter** (per Personalnummer oder Kürzel gematcht).
- **Neu einzufügende Buchungen** (nur im Dry-Run als Vorschau).
- **Übersprungene Zeilen** mit Begründung (MA nicht gefunden, Zeitraum-Duplikat, unzulässiges Format).
- **Fehler** bei echtem Import — die Transaktion rollt in dem Fall zurück.

### Empfohlenes Vorgehen

1. Zuerst **immer** mit aktivem Dry-Run laden → Report prüfen.
2. Bei 0 Fehlern und plausiblen Zahlen Dry-Run deaktivieren und erneut importieren.
3. Nach erfolgreichem Import in der WaWi die Stempel-Ansicht eines Mitarbeiters stichprobenartig prüfen.

**Achtung:** Der Import arbeitet idempotent über ein eindeutiges Tupel (MA, Datum, Typ, Zeit); ein versehentlich doppelt gestarteter Import erzeugt keine Dubletten.

---

## Login

Die Verwaltungs-App bietet zwei Anmeldearten:

### Kartenlogin (Barcode-Scan)
Standardmäßig ist der Tab **„Karte scannen"** aktiv. Mitarbeiterausweis vor den Barcode-Scanner halten – die Anmeldung erfolgt automatisch. Es werden nur Mitarbeiterkarten akzeptiert (KARTEN.TYP='M').

### Passwort-Login mit Touch-Tastatur
Tab **„Passwort"** wählen. Benutzername und Passwort eingeben – bei Bedarf über die eingeblendete Touch-Tastatur (QWERTZ-Layout). Shift (⇧) für Großbuchstaben, Backspace (⌫) zum Löschen, OK zum Absenden.

Passwörter werden als MD5-Hash gespeichert (CAO-Standard).

---

## App-Switcher

In der Navigationsleiste oben sind Schnelllinks zu den anderen Apps:

- **Kiosk** (Port 5001)
- **Kasse** (Port 5002)
- **WaWi** (Port 5003)

Nicht konfigurierte Apps werden ausgegraut angezeigt.
