# LumaCut CNC – Hinweise für Claude

**Zuerst [docs/STAND.md](docs/STAND.md) lesen.** Dort stehen Projekt,
Zugänge, Sicherheitsregeln, Chronik, laufende Arbeit und Fahrplan.

Kurzfassung der wichtigsten Regeln (Details in STAND.md §3–§5):
- Vor jeder Änderung `git fetch` + `pull` – andere Sitzungen arbeiten parallel auf `main`.
- Vor JEDEM Laser- oder Fahrauftrag ein ausdrückliches Go des Besitzers
  („Hände raus, Deckel zu, Brille – starten?“). Nie auf ungetestetem Material lasern.
- Pi-Dienst nur mit Zustimmung und nie während eines Auftrags neu starten; Flashen nur mit dem Besitzer vor Ort.
- Der Pi ist die Zentrale: Einstellungen und Grenzen gehören auf den Pi.
- Keine Passwörter oder Schlüssel lesen, eingeben oder committen.
- Nach jeder Änderung `docs/STAND.md` und `CHANGELOG.md` im selben Commit nachziehen.
- Doku und Commit-Nachrichten auf Deutsch.
