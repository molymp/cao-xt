# Git-Hooks – cao-xt Entwickler-Dokumentation

## Übersicht

Das Repo enthält versionierte Git-Hooks in `.githooks/`. Diese müssen einmalig aktiviert werden.

## Einmalige Aktivierung

```bash
git config core.hooksPath .githooks
```

Danach greifen die Hooks automatisch bei jedem Push.

---

## pre-push Hook – Merge-Schutz (HAB-242)

### Geschützte Branches

- `master`
- `main`

### Verhalten

Direkte Pushes auf `master`/`main` werden **blockiert**, solange keine Paperclip-Approval-Referenz gesetzt ist.

```
╔══════════════════════════════════════════════════════════╗
║  FEHLER: Push auf 'master' blockiert                     ║
╚══════════════════════════════════════════════════════════╝

  Direkte Pushes auf 'master' sind ohne Board-Freigabe
  nicht erlaubt (Paperclip-Approval erforderlich).
  ...
```

### Richtiger Ablauf für Agenten (CTO)

1. Feature-Branch erstellen:
   ```bash
   git checkout -b cto/<aufgaben-name>
   ```
2. Änderungen committen und Branch pushen
3. Review-Umgebung deployen:
   ```bash
   ./deploy-review.sh cto/<aufgaben-name>
   ```
4. Task in Paperclip auf `in_review` setzen
5. Auf schriftliche Board-Freigabe warten
6. Nach Freigabe – Master-Merge mit Approval-ID:
   ```bash
   git checkout master
   git merge --no-ff cto/<aufgaben-name>
   PAPERCLIP_APPROVAL_ID=<approval-id> git push origin master
   ```

### Für Board-Mitglieder / Notfall-Pushes

```bash
PAPERCLIP_APPROVAL_ID=manual git push origin master
```

---

## Wartung

Der Hook liegt unter `.githooks/pre-push` und ist Teil des Repos. Änderungen am Hook werden wie normaler Code über Feature-Branches eingereicht.
