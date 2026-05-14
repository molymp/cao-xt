# Dorfkern als systemd-Dienste

Im Ad-hoc-Betrieb startet `dorfkern-ctl` die Apps als `subprocess.Popen`-
Kinder — die hängen am Cgroup desjenigen, der das Skript aufgerufen hat,
sterben mit dem Terminal und werden beim Reboot nicht wieder gestartet.

Für eine dauerhaft laufende Installation gibt es zwei systemd-Modi.

## Schnellster Weg: Einzeiler

Auf einer frischen Maschine reicht ein Befehl. `bootstrap.sh` prüft
Voraussetzungen (git, python3 ≥ 3.10), klont das Repo an die passende
Stelle und startet den Installer-Dialog.

**Für Produktivbetrieb** (Repo nach `/opt/dorfkern`, Dialog → Typ 3):

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/molymp/cao-xt/master/bootstrap.sh)"
```

**Für Entwicklung / User-Dienst** (Repo nach `~/dorfkern`, Dialog → Typ 1 oder 2):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/molymp/cao-xt/master/bootstrap.sh)"
```

Anderes Repo/Branch: per Env-Var `DORFKERN_REPO_URL` / `DORFKERN_REPO_BRANCH`.

Wer das Repo schon hat (z. B. nach manuellem `git clone`), springt direkt:

```bash
./install.sh
```

Beide Modi treffen sich in derselben Dialog-Tabelle:

## Modus-Übersicht

**Beide werden im interaktiven Dialog von `./install.sh` ausgewählt**,
nicht über CLI-Flags:

| Modus | Dialog-Option | Units in | Läuft als | Repo-Pfad |
|---|---|---|---|---|
| Ad-hoc                | 1 | – | Login-User | egal |
| Dienst pro Benutzer   | 2 | `~/.config/systemd/user/` | Login-User | egal |
| Dienst systemweit     | 3 | `/etc/systemd/system/` | `dorfkern` | bevorzugt `/opt/dorfkern` |

`./install.sh` führt durch:

```
Phase 0: Installations-Typ (1/2/3)
Phase 1: DB-Verbindung
Phase 2: DB-Init
Phase 3: App-Auswahl
Phase 4: Apps installieren + starten   ← unterschiedlich je nach Phase 0
Abschlussbericht
```

Im non-interactive Modus (`./install.sh --non-interactive`) kommt der Typ
aus `XT_INSTALL_TYPE=ad_hoc|service_user|service_system`. Default: `ad_hoc`.

## Was die Modi tun

### 1) Ad-hoc

`installer/app_manager.py` startet die Apps via `subprocess.Popen`,
schreibt PIDs nach `/tmp/caoxt-pids.json` und Logs nach
`/tmp/caoxt-<app>.log`. Stop/Status laufen über dieselbe Datei.
Keine systemctl-Berührung, kein root, kein Lingering.

### 2) Dienst pro Benutzer

`installer/systemd/host_setup.py:install_user()` macht:

1. Units in `~/.config/systemd/user/` rendern (ohne `User=`/`Group=`,
   da User-Units automatisch als der Login-User laufen).
2. `sudo loginctl enable-linger $USER` (einmalig, damit die Services
   nach Logout weiterlaufen). Falls sudo nicht passwortlos klappt:
   Warnung + manuelle Anleitung — Install läuft trotzdem weiter.
3. `systemctl --user daemon-reload`
4. `systemctl --user enable --now dorfkern.target`

Steuerung danach:

```bash
./dorfkern-ctl status                  # erkennt automatisch User-Mode
systemctl --user status dorfkern-admin
journalctl --user -u dorfkern-kasse -f
```

### 3) Dienst systemweit

`installer/systemd/host_setup.py:install_system()` macht:

1. Service-User anlegen (`useradd --system dorfkern`), falls fehlt.
2. `/var/log/dorfkern` und `/var/backups/dorfkern` anlegen (Owner `dorfkern`).
3. `chown -R dorfkern:dorfkern <install_root>` (sodass der Service-User
   den Code lesen/ausführen kann).
4. Units in `/etc/systemd/system/` rendern (mit `User=dorfkern`).
5. `systemctl daemon-reload`
6. `systemctl enable --now dorfkern.target`

Steuerung danach (gleicher Wrapper, intern via sudo):

```bash
./dorfkern-ctl status
systemctl status dorfkern-admin
journalctl -u dorfkern-kasse -f
```

## sudo-Konfiguration (optional, für Modus 3)

Damit `dorfkern-ctl` auch ohne Root-Login die System-Units bedienen
kann, ein sudoers-Snippet anlegen:

```bash
sudo install -m 0440 /dev/stdin /etc/sudoers.d/dorfkern <<'EOF'
%dorfkern ALL=(root) NOPASSWD: /bin/systemctl start dorfkern-*, \
                                /bin/systemctl stop dorfkern-*, \
                                /bin/systemctl restart dorfkern-*, \
                                /bin/systemctl start dorfkern.target, \
                                /bin/systemctl stop dorfkern.target, \
                                /bin/systemctl restart dorfkern.target, \
                                /bin/systemctl daemon-reload
EOF
```

Den eigenen Login-User per `sudo usermod -aG dorfkern <user>` in die
Gruppe `dorfkern` aufnehmen — dann läuft `dorfkern-ctl restart kasse`
ohne Passwort-Prompt.

`is-active`, `show`, `list-unit-files` brauchen keine Privilegien.

## Updates

`installer/updater.py` ruft intern `dorfkern-ctl stop/start` — und das
delegiert über `app_manager._use_systemd()` automatisch an `systemctl`
(User- oder System-Mode, je nachdem was installiert ist). Es gibt
also keinen extra Update-Pfad für PROD; `./install.sh --update` läuft
in jedem Modus durch.

Wenn `installer/systemd/units.py` durch ein Update verändert wurde,
regeneriert der Updater die Unit-Files automatisch
(`Schritt 4: systemd-Units pruefen …`) und macht `daemon-reload`.

## Unit-Files manuell neu erzeugen

Wenn jemand Ports oder ExecStart-Pfade ändert und ohne Update neu
ausrollen will:

```bash
# System-Mode
sudo python3 -m installer.systemd.units --write /etc/systemd/system
sudo systemctl daemon-reload
sudo systemctl restart dorfkern.target

# User-Mode
python3 -m installer.systemd.units --mode user --write ~/.config/systemd/user
systemctl --user daemon-reload
systemctl --user restart dorfkern.target
```

## Deinstallation

Über die Helper:

```bash
# User-Mode
python3 -c "from installer.systemd import host_setup; host_setup.uninstall_user()"

# System-Mode
sudo python3 -c "from installer.systemd import host_setup; host_setup.uninstall_system()"
```

Oder von Hand:

```bash
# System-Mode
sudo systemctl disable --now dorfkern.target
sudo rm /etc/systemd/system/dorfkern-*.service /etc/systemd/system/dorfkern.target
sudo systemctl daemon-reload
# optional: User entfernen
sudo userdel dorfkern
```

Das `dorfkern`-Verzeichnis unter `/opt/`, `/var/log/`, `/var/backups/`
wird absichtlich nicht automatisch gelöscht — Backups und Logs könnten
noch gebraucht werden.

## Fallback-Verhalten

Ist auf einem Host weder User- noch System-Target installiert, läuft
`app_manager` automatisch in den alten Popen-Pfad zurück — die
Ad-hoc-Entwickungsumgebung bleibt davon also komplett unberührt.

Wenn (versehentlich) BEIDE Modi installiert sind, gewinnt der User-Mode
mit einer Warnung im Log; bitte dann manuell den unerwünschten Modus
deinstallieren.
