# Benutzerhandbuch – Verwaltungs-App

**Version:** 1.1.0 | **Stand:** 2026-04-13 | **App:** Verwaltung (Port 5004)

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
