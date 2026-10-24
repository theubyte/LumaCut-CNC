# LumaCut CNC – Projektstatus 24.10.2026 (Pi400)

**Aktiver Branch:** `main` auf https://github.com/theubyte/LumaCut-CNC (öffentlich).
**Keine separaten Entwicklungsbranches erforderlich.**

## Zielarchitektur
Raspberry Pi 400 ist die zentrale Maschine: Web-UI, Service-Zugang, Aufträge,
Konfiguration, GRBL/LightBurn-TCP23, G-Code-Geometrieanalyse, USB-Verwaltung
und Updates. Das SKR Mini MZ V1.0 führt die zeitkritischen Stepper-, PWM-,
Endschalter- und MOSFET-Signale mit grblHAL über eine eigene USB-CDC-Verbindung aus.
Die frühere Waveshare-ESP32-S3-HMI-Software ist nur Archiv.

## Implementierte Software
- `pi400/lumacut/app.py`, `core.py`: Webserver, GRBL-Host-TCP-Brücke,
  exklusiver USB-Besitz, gefilterte Statusabfragen, geblockte kritische
  Host-Einstellungen, manuelle XYZ-Fahrt, Z-Homing, fokusspezifische
  Nach-Homing-Freifahrt und native Dateien/Jobs.
- `pi400/static/index.html`: responsive Maschinenoberfläche, SVG-G-Code-Vorschau,
  WLAN, USB-Kamera, Status, Homing, Park-/Fokusfunktionen, Dateien und Parameter.
- `pi400/static/service.html`: geschützte Serviceoberfläche mit Passwort
  `lumaservice` (gehasht), 10-minütiger Anmeldung, Firmwarediagnose,
  GRBL-Parameterkonsole und I/O-Pinbelegung.
- `firmware/skr/build.py`: USB-grblHAL STM32F103RC mit X/Y/Z, TMC2209,
  Z20-Homing, PA1 Laser-PWM, PC9 BED, PC8/M7 LEDs, PC6/M8 Abluft,
  zusätzlichem PC7/FAN1 über `$LCIO` samt Readback.
  Das ESP32-Keypad-Plugin wird nicht mehr in den USB-Build eingeschaltet.
- CI erzeugt Firmware-Binärdaten mit SHA-256-Fähigkeitsdatei und
  `LumaCut-Pi400-SKR-USB.zip` (GitHub Actions).
- Täglicher Pi-Updater mit Maintenance-Sperre und Rollback bei Dienstfehlern.

## Nicht hardwareverifiziert / noch offen
- Der SKR arbeitet derzeit weiter auf grblHAL als hartem Echtzeitkern;
  eine frei umkonfigurierbare universelle GPIO-Firmware ist **nicht** fertig.
- Automatisches SKR-Flashing allein via USB ist **nicht** implementiert.
- Ein separater G38-Werkstücktaster, gemessene Höhenkarte und vollautomatische
  Werkstückabtastung sind **nicht** realisiert.
- Die elektrische Isolation des PC9-BED-Low-Side-Schalters zum LaserTree-PWM,
  alle Z/Motorbewegungen, Signalpegel und externe Schutzkette sind nicht am
  realen Aufbau geprüft. Kein Freigabevermerk für realen Laserbetrieb.

## Inbetriebnahme
Siehe [PI400_CONTROL_STUDIO.md](PI400_CONTROL_STUDIO.md) und
[PI400_CONTROL_OS_2.md](PI400_CONTROL_OS_2.md).

**CI grün bedeutet Quellcode/Firmwarekompilierung, nicht hardwaregeprüfte
Laserfunktion.**
