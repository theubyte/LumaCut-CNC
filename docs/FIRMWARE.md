# SKR-Firmware (Marlin 2.1.2.9)

## Bauen

```bash
pip install -r firmware/marlin/requirements.txt   # PlatformIO 6.2.0
python firmware/marlin/build.py                   # Ergebnis: firmware/marlin/dist/firmware.bin + manifest.json
```

`build.py` klont Marlin 2.1.2.9 und die passende Beispielkonfiguration „AnyCubic Mega Zero / BTT SKR Mini MZ V1.0“ und wendet alle LumaCut-Anpassungen per Skript an. Ändert sich die Upstream-Datei unerwartet, bricht das Skript ab. Jede Anpassung ist dort mit Begründung kommentiert. Die wichtigsten:

- Name „LumaCut CNC Marlin“. Der Pi akzeptiert nur Firmware mit dieser Kennung.
- Laser: `LASER_FEATURE`, PWM PA1, `CUTTER_POWER_UNIT PWM255`, Startleistung 0 %.
- Fester Z-Taster am Z-MIN-Pin (`FIX_MOUNTED_PROBE`, `Z_SAFE_HOMING` an X0/Y0, Tasterversatz 0, Grenze für zu frühes Auslösen 16 mm).
- `COOLANT_CONTROL` (M7/M8), `EMERGENCY_PARSER`, `ADVANCED_OK`.
- `BINARY_FILE_TRANSFER` für Updates über den Pi.
- **Motortöne `M300 S<Hz> P<ms> [X] [Y]`** (`firmware/marlin/motor_tone.cpp`): Das Board hat keinen Summer, deshalb spielt `M300` auf den Spulen von X und Y. Pro Tonperiode ein Mikroschritt vor und einer zurück, also ohne Bewegung (höchstens 0,0125 mm Ausschlag, Ergebnis exakt 0). Die Treiber schalten dafür kurz von StealthChop auf SpreadCycle (laut) und danach zurück. Strom, Positionszähler und Richtungs-Pins bleiben unverändert. Bei eingeschaltetem Laser lehnt Marlin ab (`echo:LumaCut M300 refused: laser on`). `S0` ist eine Pause, ein Aufruf spielt höchstens 2 s.

Auf GitHub baut `.github/workflows/marlin.yml` die Firmware bei jeder Änderung unter `firmware/marlin/`. Die `firmware.bin` liegt 14 Tage als Download in den Actions. `.bin`-Dateien kommen bewusst nicht ins Repository.

Unter Windows mit langem Benutzerpfad scheitert der Marlin-Clone an der Pfadlänge. Abhilfe: kurze Ordner (`--cache-dir`, `--output`, `TMP`) und `git -c core.longpaths=true` (siehe [ENTWICKLUNG.md](ENTWICKLUNG.md)).

## Flashen über den Pi (Standard)

Voraussetzung: Im SKR steckt **dauerhaft** eine FAT32-microSD, und die laufende Firmware hat bereits `BINARY_FILE_TRANSFER`. Das ist seit dem Build vom 25.10.2026 22:57 der Fall.

Web-UI → Karte „SKR-Firmware“ → `.bin` wählen → „Flashen“. Der Pi:
1. prüft die Datei: Größe, STM32-Vektortabelle für den BTT-Bootloader (Start 0x08007000), LumaCut-Kennung, Upload-Funktion enthalten;
2. schaltet Laser, die 24-V-Laserversorgung, Licht und Abluft aus und prüft die SD-Karte (`M21`);
3. schreibt `firmware.bin` per Marlin-Binärprotokoll (`M28 B1`) auf die Karte und startet neu (`M997`);
4. wartet, bis der Bootloader geflasht hat und USB wieder da ist;
5. vergleicht den Build-Zeitstempel der Datei mit `M115`. Nur bei Übereinstimmung meldet er „Neue Firmware aktiv“.

Dauer etwa 12 s (am 25.10.2026 am echten SKR gemessen). Danach neu referenzieren. LightBurn muss getrennt sein.

Per Kommandozeile auf dem Pi: `curl -F file=@firmware.bin http://127.0.0.1:8080/api/firmware`.

## Flashen per SD-Karte (Erstinstallation, Rettung)

`firmware.bin` ins Hauptverzeichnis der FAT32-Karte, Karte ins SKR, 24 V **und** USB kurz trennen, einschalten. Nach dem Flashen heißt die Datei `FIRMWARE.CUR`. Der Bootloader (erste 28 KB) wird nie überschrieben, dieser Weg funktioniert also immer.

## Marlin-Besonderheiten, die der Pi ausgleicht

| Verhalten von Marlin 2.1.2.9 | Folge | Lösung auf dem Pi |
|---|---|---|
| G30 meldet „Probing Failed“, wenn der Kontakt über `Z_CLEARANCE_MULTI_PROBE` liegt (Probe::run_z_probe). Der Kopf bleibt aber exakt am Kontakt stehen. | Gültige Messung wird als Fehler gemeldet | M114-Höhe übernehmen, wenn M119 `z_min: TRIGGERED` zeigt und der Kopf unter der Starthöhe steht |
| Nach G30 folgt eine Positionsmeldung **nach** dem Hochfahren | Falsche Oberfläche, wenn man irgendein `Z:` liest | Nur die Zeile `Bed X: … Y: … Z: …` zählt |
| M3/M5 laufen mit `planner.synchronize()` | Stillstand an jedem Pfad, Brennpunkte | Studio sendet ein `M3 I` pro Auftrag |
| `M400` leert den Planer | Stillstand an jedem Segment | Safezone-Prüfung mit den vom Pi selbst gesendeten Koordinaten statt M400/M114 |
| `G0` setzt die Inline-Leistung auf 0 | `G1` ohne S nach einer Leerfahrt lasert nicht | Studio schreibt S in jedes G1. Für LightBurn ergänzt der Pi den letzten S-Wert |
| EEPROM behält Werte älterer Firmware | z. B. Z auf 6 mm/s begrenzt, falscher Tasterversatz | Bei jeder Verbindung `M203 Z9`, `M851 X0 Y0 Z0` |
| Nach `M112` hängt Marlin in `kill()` und antwortet nicht | Kein Weiterarbeiten | Erst nach Reset des SKR mit „Notstopp quittieren“ freigeben |
