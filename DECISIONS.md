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

## 2026-04-04 DECISIONS.md und Benutzerhandbücher als Merge-Pflicht eingeführt

- **Problem:** Board-Mitglieder konnten nicht nachvollziehen, was sich bei einem Release geändert hat und warum Entscheidungen so getroffen wurden.
- **Entscheidung:** Ab sofort ist jeder Merge in den `master` Branch nur zulässig, wenn DECISIONS.md, die relevanten Benutzerhandbücher und CHANGELOG.md aktualisiert wurden.
- **Begründung:** Transparenz für das Board, Nachvollziehbarkeit für zukünftige Entwickler.
- **Alternativen:** Externe Wiki-Lösung (zu komplex), nur Kommentare in Commits (nicht zugänglich genug).
- **Konsequenzen:** Mehr Dokumentationsaufwand pro Feature, aber dauerhaft bessere Übersicht.
- **Referenz:** [HAB-105](/HAB/issues/HAB-105)
