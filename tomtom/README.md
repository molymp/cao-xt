# TomTom START 62 — eigene Software aufspielen?

Rechercheergebnis und Diagnosewerkzeug zur Frage, ob sich auf einem TomTom START 62
eigene Software betreiben lässt.

**Stand:** August 2026. **Kurzantwort:** Ein eigenes Betriebssystem — praktisch nein.
Eigener Code als Programm auf dem TomTom-Linux — vielleicht, mit erheblichem Aufwand
und realem Risiko, das Gerät unbrauchbar zu machen.

---

## 1. Um welches Gerät geht es genau

| Merkmal | Angabe | Beleg |
|---|---|---|
| Interne Modellnummer | `4AA63` (Schwestermodelle START 42 = `4AA43`, START 52 = `4AA53`) | TomTom-Handbuch der Serie |
| Gerätegeneration | **NAV4** | TomTom-Handbuchseiten `…-Nav4.htm`; Community-Modellliste |
| Display | 6", 800 × 480, **resistiver** Touch (Single-Touch) | Händler-/Handbuchangaben |
| microSD-Slot | vorhanden, unter der Halterung | offizielles Handbuch START 42/52/62 |
| Betriebssystem | ARM-Linux mit TomTom-Navigationssoftware („NavCore") | TomTom-GPL-Freigaben |

Die Modellnummer steht auf dem Typenschild und ist verlässlicher als der Marketingname.

> **Wichtig:** Der optisch ähnliche **START 60** ist eine *andere*, ältere Baureihe
> (START 40/50/60). Beide sind NAV4, aber nicht dieselbe Hardware.

## 2. Die entscheidende Abgrenzung: NAV2 vs. NAV4

Fast alles, was man im Netz zum „TomTom hacken" findet, betrifft die **alte** Generation.
Das ist die häufigste Fehlerquelle bei diesem Thema.

| | **NAV2** (GO/ONE/XL, ca. 2005–2010) | **NAV4** (ab ca. 2013, inkl. START 62) |
|---|---|---|
| USB am Rechner | Massenspeicher, Volume wird gemountet | **Netzwerkadapter** (RNDIS / CDC-ECM), kein Volume |
| Boot-Image | Datei `ttsystem` auf FAT, frei austauschbar | eMMC mit Partitionstabelle `uboot` / `fdt` / `rescue` / `content` |
| Root-Zugang | Telnet über USB, gut dokumentiert | nur über Recovery-Modus, Community-Werkzeuge |
| Custom-Linux | **OpenTom, NavitTom** — funktionieren | **existiert nicht** |

**Für den START 62 sind OpenTom, NavitTom, TomPlayer, AirNavigator und TTconsole
allesamt nicht anwendbar.** Sie setzen die NAV2-Architektur voraus.

## 3. Was das praktisch heißt

### Am Mac wird kein Laufwerk erscheinen
Das ist **kein Defekt**, sondern das normale NAV4-Verhalten. `diskutil list` und
`/Volumes` zeigen das Gerät nicht. Es meldet sich als USB-Netzwerkadapter und
betreibt einen kleinen HTTP-Server (Link-local, typischerweise `169.254.255.1`),
mit dem sonst MyDrive Connect spricht. Dateien lassen sich so nicht einfach kopieren.

### Ein eigenes OS zu booten ist versperrt
Der TomTom-Kernel dieser Linie kennt die Build-Option `SIGN_ZIMAGE`
(„zImage signing with TomTom DSA key") — Kernel-Images sind signiert. Bootloader
oder Kernel auszutauschen ist damit kein realistisches Wochenendprojekt.
Es wurde **kein einziger dokumentierter Fall** gefunden, in dem jemand ein eigenes
Betriebssystem auf einem NAV4-START zum Laufen gebracht hat.

### Eigener Code im Userspace: der einzige realistische Pfad
Auf TomTom-Geräten gibt es einen Mechanismus für Zusatzprogramme:

- eine Datei **`ttn`** im Wurzelverzeichnis (bzw. auf der SD-Karte) wird beim Start
  als Skript ausgeführt,
- Menüeinträge entstehen über den Ordner **`SdkRegistry`** aus je einer `.cap`-Textdatei
  plus `.bmp`-Icon.

Dass das grundsätzlich trägt, zeigt **[TTconv](https://github.com/treysis/TTconv)** (GPLv3):
ein natives ARM-C-Programm, das auf NavCore-Geräten produktiv läuft und sich über die
Named Pipes `/var/run/gpspipe` bzw. `/var/run/gpspip2` zwischen GPS-Treiber und
Navigationssoftware klinkt. Gebaut wird schlicht mit `arm-linux-gcc`; die Toolchain
hat TomTom im Rahmen der GPL selbst veröffentlicht.

**Aber:** TTconv zielt auf Geräte der `go12`-/ARM11-Linie (Rider 2013 u. ä.).
Dass derselbe `ttn`-Pfad auf einem START 62 greift, ist **nicht belegt** — und weil
NAV4 keinen Massenspeicher anbietet, ist schon das Ablegen der Datei die erste Hürde.

### Root auf NAV4: es gibt einen Community-Weg
In einschlägigen Foren (gpsurl.com, digital-eliteboard) existiert eine Anleitung
„A guide to patching NAV4 devices" der MSTMS-Gruppe: Gerät im **Recovery-Modus**,
präparierte SD-Karte („sdmagic"), ein Skript aktiviert eine **ADB-Shell als root**.
Diese Foren erfordern Registrierung, die Werkzeuge sind Windows-`.bat`-Dateien,
und es gibt ausdrücklich keine Garantie.

Das ist der Punkt, an dem das Projekt vom Basteln zum ernsthaften Reverse Engineering wird.

## 4. Das Risiko hat sich verschärft

Früher war ein verkonfiguriertes TomTom über die Herstellerserver wiederherstellbar.
Dieser Rettungsanker wird brüchig: Die MyDrive-**Mobile**-App wurde am **22. Januar 2025**
abgeschaltet, weil sie aktuellen Sicherheitsstandards nicht mehr genügte.

Ob die Recovery-/Firmware-Server für ein Gerät von 2016 im Jahr 2026 noch
Images ausliefern, **konnte nicht geklärt werden** — und es wurde auch kein
vollständiges Werksfirmware-Image zum Offline-Wiederherstellen gefunden.

> **Konsequenz:** Vor jedem Schreibzugriff ein vollständiges eMMC-Dump anfertigen.
> Ohne Backup ist ein Fehlschlag mit hoher Wahrscheinlichkeit endgültig.

## 5. Realistische Alternativen

| Option | Aufwand | Bewertung |
|---|---|---|
| **Nur Inhalte ändern** (eigene POIs als `.ov2`, Routen als `.itn`) | gering | Ohne jeden Hack möglich, viele Open-Source-Konverter. Aber: bleibt eine Navi-Anwendung. |
| **Gehäuse neu bestücken** (Raspberry Pi Zero / ESP32 + eigenes Display) | mittel | Verlässlichster Weg zu „eigener Software". Nutzt Gehäuse, Akku, Halterung. |
| **Display ernten** | hoch | Für den *Vorgänger* START 60 ist im TomTom-GPL-Kernel ein Panel-Treiber `LMS606KF01` dokumentiert (480 × 800, RGB565, paralleles RGB über AMBA-CLCD, SPI-Init mit 9 Bit/Wort, vollständige Init-Sequenz im Quellcode). Welches Panel im START **62** sitzt, ist unbekannt. Paralleles RGB an einen Pi zu bringen erfordert einen Adapter. |
| **GPS-Modul ernten** | hoch | Oft aussichtslos: Auf Broadcom-BCM4760-Geräten ist der GPS-Empfänger **im SoC integriert**. Nur auf Samsung-S5P6440-Plattformen sitzt ein separater Atheros AR15xx per UART. Welche Variante der START 62 nutzt, ist unbekannt. |
| **Root + eigener Userspace-Code** | sehr hoch | Der einzige Weg zu eigenem Code *auf* dem Gerät. Undokumentiert für genau dieses Modell. |

## 6. Diagnose

`tomtom-recon.sh` identifiziert das angeschlossene Gerät am Mac. **Rein lesend** —
es schreibt, formatiert und flasht nichts.

```bash
bash tomtom/tomtom-recon.sh
```

Der Bericht landet als `tomtom-recon.txt` auf dem Schreibtisch. Das Skript prüft
beide Generationen und sagt am Ende, welche vorliegt:

- USB-Erkennung über Vendor-ID `0x1390` (TomTom B.V.)
- Netzwerkschnittstellen und Link-local-Adresse (NAV4-Signatur)
- HTTP-Endpunkte des Geräteservers (`/`, `/mpnd/status`, `/mpnd/settings`, `/sa/hello`)
- Gegenprobe auf Massenspeicher inkl. `ttsystem` / `ttgo.bif` (NAV2-Signatur)

Findet es ein gemountetes Volume, ist es **nicht** das erwartete NAV4-Verhalten —
dann lohnt der Blick aufs Typenschild, denn für NAV2 wäre die Lage deutlich besser.

## 7. Belastbarkeit dieser Recherche

Ehrlich zur Quellenlage, weil das die Schlussfolgerungen begrenzt:

- Die Recherche lief über einen Egress-Proxy, der **die meisten Primärquellen
  blockierte** — `tomtom.com`, `download.tomtom.com`, `discussions.tomtom.com`,
  `tomtomforums.com`, `gpsurl.com`, `fccid.io`, `ifixit.com`, `archive.org`.
- Von zehn adversarial gegengeprüften Behauptungen kam **keine einzige als
  „bestätigt" zurück** — nicht weil sie widerlegt wurden, sondern weil die
  Gegenprüfung technisch nicht durchführbar war.
- Gut belegt sind die Aussagen, die sich auf **öffentliche Quelltexte** stützen
  (TomTom-GPL-Freigabe, TTconv, OpenTom/NavitTom) sowie die Generationsabgrenzung.
- **Nicht ermittelbar** waren: SoC/CPU, RAM-Größe, Flash-Typ, GPS-Chip,
  Display-Controller und UART-/JTAG-Pads des START 62. Es existiert kein Teardown
  und kein FCC-Filing für `4AA63`. Wo hier Zahlen kursieren, sind sie geraten —
  in diesem Dokument stehen deshalb bewusst keine.

Der zuverlässigste nächste Erkenntnisschritt ist deshalb nicht weitere Websuche,
sondern **das Gerät selbst zu befragen** — dafür ist `tomtom-recon.sh` da.

## Haftungsausschluss

Eingriffe an der Firmware können das Gerät dauerhaft unbrauchbar machen.
Keine Gewähr, Nutzung auf eigenes Risiko.
