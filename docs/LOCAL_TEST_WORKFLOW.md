# LumaCut CNC – lokale Tests statt GitHub Actions

**Projektentscheidung (25.10.2026):** GitHub dient als Quellcode-Speicher
und Versionskontrolle. Die beiden GitHub-Actions-Workflows
`.github/workflows/ci.yml` und `.github/workflows/marlin.yml`
werden **nicht mehr bei Pushes oder Pull Requests gestartet**.
Ein manueller `workflow_dispatch` bleibt nur als optionaler Rückfallweg.

## Standardablauf bei einer Änderung

1. Änderungen lokal in einem Arbeitsverzeichnis erstellen.
2. Ohne Verbindung zur echten Maschine Syntax-/Frontend-Prüfungen ausführen.
3. USB-Marlin-Transport, TCP-LightBurn-Brücke, Homing, Laserbefehle,
   Notstopp und Pi-Webinterface anhand automatisierter Simulationstests prüfen.
4. Bei Änderungen an Boardpins, PWM oder Firmware: Marlin mit dem lokal
   installierten PlatformIO inklusive STM32F103RC-Toolchain kompilieren,
   die resultierende `firmware.bin` und ihren SHA256 prüfen.
5. **Erst nach bestandenem Test** Quellcode nach GitHub pushen.
   Kein automatischer GitHub-Build ist für den normalen Arbeitsablauf nötig.
6. Hardwaretest separat: mit getrennter Laserleitung starten,
   Endschalter, Z-Richtung, Interlock und PWM elektrisch verifizieren.
   GitHub-/lokale Unit-Tests ersetzen **keinen** solchen Hardwaretest.

## Lokale Befehle (Entwicklungsrechner)

```bash
bash scripts/setup-local.sh       # einmalig, mit Netzwerk; richtet .venv ein
bash scripts/local-test.sh syntax # Python/Bash/JavaScript/JSON
bash scripts/local-test.sh quick  # Marlin-/Pi-Simulationstests
bash scripts/local-test.sh full   # alle Regressionstests inkl. altem grblHAL
bash scripts/local-test.sh firmware  # Marlin-Binary lokal mit PlatformIO bauen
```

Die Marlin-Quellen werden beim ersten Build nach
`~/.cache/lumacut/upstreams` geladen und danach wiederverwendet.
Die benötigten ARM/PlatformIO-Pakete können beim ersten Aufruf noch
heruntergeladen werden. Ohne Internet und ohne lokalen Cache kann
**kein vollständiger Firmwarebuild** durchgeführt werden. Eine bestehende
lokale Installation kann später mit
`python firmware/marlin/build.py --offline` arbeiten.

## Transparente Testergebnisse

Jeder Testbericht unterscheidet verbindlich:

- **Quelltext-/Syntaxprüfung**: Code lässt sich parsen.
- **Automatisierte Simulationstests**: Transport- und Sicherheitslogik mit
  Fake-Serial/Mock-Webrequests geprüft.
- **Firmware-Build**: Marlin für das Zielboard tatsächlich kompiliert;
  Binärdatei und Checksumme geprüft.
- **Echter Hardwaretest**: Nur nach Messungen und Tests am realen SKR;
  niemals aus einem lokalen Build ableiten.

Wenn die Arbeitsumgebung einen benötigten Compiler oder Python-Pakete
nicht enthält, muss dies als **nicht ausgeführt** gemeldet werden.
Tests niemals als bestanden darstellen, wenn sie nicht gelaufen sind.

## Architektur

Raspberry Pi 400 (Wi-Fi Webinterface und LightBurn TCP) verbindet sich über
USB mit BTT SKR Mini MZ V1.0 (Marlin). Marlin ist der aktuelle
Entwicklungszweig; der ältere grblHAL-Code bleibt zu Vergleichs- und
Rettungszwecken versioniert. Den Laserkopf vor Hardwarediagnose und
Firmwareumstellung elektrisch trennen. Die direkte PA1-PWM-Verbindung zu
einem mit Low-Side-FAN1− versorgten Lasermodul ist ohne geeignete
galvanisch getrennte Schnittstelle und unabhängigen Interlock nicht
freigegeben.
