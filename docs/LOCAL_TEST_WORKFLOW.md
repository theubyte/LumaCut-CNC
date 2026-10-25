# LumaCut CNC – schneller hybrider Testablauf

GitHub ist der Quellcode- und Versionsspeicher. **Firmware-Builds dürfen
gezielt über GitHub Actions laufen**, wenn PlatformIO oder die STM32-Toolchain
in der Assistenzumgebung fehlen. Der Marlin-Workflow wird **nicht automatisch
bei jedem Commit** ausgelöst, sondern nur bei Bedarf manuell gestartet.

## Standard für jede Änderung

1. **Kurzer lokaler Check**: geänderte Python-/Webdateien prüfen;
   bei Marlin USB-Transport, Homing, Laser-Sicherheit oder LightBurn nur
   die relevanten Simulationstests ausführen:
   `bash scripts/local-test.sh quick`.
2. **Firmware geändert?** GitHub Actions
   `LumaCut Marlin Firmware` manuell auslösen. Der Workflow baut
   ausschließlich `firmware.bin` und `manifest.json`, ohne parallel den
   vollständigen Python-Testkatalog auszuführen. Marlin-Quellen und
   PlatformIO-Pakete werden zwischen Builds gecacht.
3. **Größere Code-Umbauten / Releases**: auf Bedarf
   `bash scripts/local-test.sh full` (gesamte Regressionstests).
4. **Früheres grblHAL**: nur für Legacy-Arbeiten kompilieren; Standard ist
   das neue Marlin-System.
5. Geprüfte Änderungen und eindeutigen Teststatus mit Commit auf GitHub speichern.

## Befehle

```bash
bash scripts/setup-local.sh        # einmalig, nur wenn lokale Pakete fehlen
bash scripts/local-test.sh quick   # kurzer Standardtest
bash scripts/local-test.sh syntax  # breite Syntaxprüfung
bash scripts/local-test.sh full    # vollständige Regression
bash scripts/local-test.sh firmware # optional Marlin-Firmware lokal statt GitHub
```

In der GitHub-Oberfläche:
`Actions → LumaCut Marlin Firmware → Run workflow`.
Danach ist die Firmware unter **Artifacts** verfügbar.

## Aussagekraft

- **Syntaxprüfung:** Code lässt sich interpretieren.
- **Lokale Simulation:** Antworten und Fehlersituationen mit Test-Doubles geprüft.
- **GitHub-Firmwarebuild:** STM32-Marlin kompiliert und Paket erzeugt.
- **Hardwaretest:** Echte Funktion von Motoren, Endschaltern, PWM,
  Abschaltung und Laser am SKR überprüft.

Diese vier Stufen strikt auseinanderhalten. Ein erfolgreich erzeugtes
Firmware-Binary ist kein Nachweis elektrischer Sicherheit. Insbesondere
benötigt die Kombination FAN1-Low-Side-Masse mit PA1-PWM eine geeignete
Signaltrennung sowie einen unabhängig wirkenden Hardware-Interlock.
