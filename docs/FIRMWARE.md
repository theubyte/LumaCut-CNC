# SKR-Firmware

Auf dem SKR Mini MZ soll die eigene Firmware laufen: Vertrag und Hardware in [FIRMWARE_EIGEN.md](FIRMWARE_EIGEN.md),
Quellen in `firmware/lumacut/`. Der Pi im Zweig `eigene-firmware` spricht nur noch diesen Vertrag und lehnt Marlin ab
(M115 braucht `FIRMWARE_NAME:LumaCut CNC` und `MACHINE_TYPE:LumaCut CNC`). Marlin 2.1.2.9 bleibt als Rückweg per SD-Karte,
ist dann aber nur mit dem Pi-Stand davor betreibbar.

## Flashen über den Pi (Standard)

Web-UI → Karte „SKR-Firmware“ → `.bin` wählen → „Flashen“. Voraussetzung: Die laufende Firmware meldet `Cap:SELF_UPDATE:1`. Der Pi:
1. prüft die Datei: Größe 4 KB bis 196 KB, STM32-Vektortabelle für den BTT-Bootloader (Start 0x08007000), Kennung `LumaCut CNC`, `Cap:SELF_UPDATE:1` enthalten. Marlin-Abbilder fallen damit durch;
2. schaltet Laser, die 24-V-Laserversorgung, Licht und Abluft aus und wartet auf Stillstand;
3. sendet `M997 U<Bytes> C<CRC-32>` (CRC-32 wie zlib, beide Zahlen dezimal) und auf `ok READY <chunk>` Blöcke dieser Größe, je Block `ok <offset>` mit der Zahl der bisher empfangenen Bytes;
4. wartet auf `ok DONE`, schließt USB und wartet, bis die neue Firmware antwortet;
5. vergleicht den Build-Stempel der Datei mit `M115`. Nur bei Übereinstimmung meldet er „Neue Firmware aktiv“.

Fehler vor `ok DONE` (Ablehnung, falscher Offset, Stille, Prüfsumme): Die laufende Firmware bleibt, der Pi schließt den Port und verbindet neu. Danach immer neu referenzieren. LightBurn muss getrennt sein.

Per Kommandozeile auf dem Pi: `curl -F file=@firmware.bin http://127.0.0.1:8080/api/firmware`.

Releases für den Pi heißen `lumacut-fw-<Nr.>` mit `LumaCut-Firmware.json`; `marlin-<Nr.>` wird ignoriert ([PI_API_REFERENZ.md](PI_API_REFERENZ.md) §4.16).

## Flashen per SD-Karte (Erstinstallation, Rettung)

`firmware.bin` ins Hauptverzeichnis der FAT32-Karte, Karte ins SKR, 24 V **und** USB kurz trennen, einschalten. Nach dem Flashen heißt die Datei `FIRMWARE.CUR`. Der Bootloader (erste 28 KB) wird nie überschrieben, dieser Weg funktioniert also immer. So kommt die eigene Firmware das erste Mal auf das Board; Rückweg ist das Marlin-Release `marlin-62` auf demselben Weg.

## Was der Pi trotz Vertrag dazugibt

| Verhalten der Firmware (Vertrag) | Folge | Lösung auf dem Pi |
|---|---|---|
| `M5 I` wirkt sofort und wartet nicht auf die Warteschlange | Der Rest eines Auftrags liefe unbeleuchtet (`M5 I` am Dateiende der App) | Aus Auftrag und LightBurn geht `M400` voraus. Abbruch, Tippen und Service bleiben sofort |
| Ein Endschalter stoppt alle Achsen und leert die Warteschlange | Der Auftrag liefe an falscher Stelle weiter | Z-Treffer und X/Y-Treffer abseits von Null brechen ab. Nur auf dem Weg nach X0/Y0 (Parken) ist ein Treffer normal |
| `G0` kennt kein `S` | Ein `S0` könnte als modale Leistung gelten | Der Pi streicht `S` aus `G0`, `S>0` lehnt der Wächter ab |
| `G30` prüft den Taster vor dem Start | Nach einem Hub wäre er noch gedrückt, solange die Fahrt läuft | `M400` vor jedem `G30` |
| Dauerleistung endet nach 5 s ohne Befehl | TTL-Test würde abbrechen | Der Test sendet jede Sekunde `M114`; sonst läuft der Herzschlag alle 2 s |
| Wegprüfung auch ohne Referenz | `op=z_test` nach unten wäre abgelehnt | `G92 Z40` vor dem Test, `G92 Z0` danach |
| `M2`, `M30`, `G54`, `M7`, `G17`, `G40` gibt es nicht | LightBurn sendet sie | Der Pi filtert sie (`M2` parkt) |
| `M112` verriegelt bis `M999` | Nach Neustart des Pi-Dienstes noch verriegelt | Beim Verbinden erkennt der Pi das und verriegelt selbst, `op=estop_reset` sendet `M999` |

## Marlin bauen (Rückweg)

```bash
pip install -r firmware/marlin/requirements.txt   # PlatformIO 6.2.0
python firmware/marlin/build.py                   # Ergebnis: firmware/marlin/dist/firmware.bin + manifest.json
```

`build.py` klont Marlin 2.1.2.9 und die passende Beispielkonfiguration „AnyCubic Mega Zero / BTT SKR Mini MZ V1.0“ und wendet alle LumaCut-Anpassungen per Skript an. Ändert sich die Upstream-Datei unerwartet, bricht das Skript ab. Jede Anpassung ist dort mit Begründung kommentiert. Die wichtigsten:

- Name „LumaCut CNC Marlin“. Nur der Pi-Stand vor dem Zweig `eigene-firmware` akzeptiert diese Kennung.
- Laser: `LASER_FEATURE`, PWM PA9 (EXP3, 1 kHz), `CUTTER_POWER_UNIT PWM255`, Startleistung 0 %.
- Fester Z-Taster am Z-MIN-Pin (`FIX_MOUNTED_PROBE`, `Z_SAFE_HOMING` an X0/Y0, Tasterversatz 0, Grenze für zu frühes Auslösen 16 mm).
- `COOLANT_CONTROL` (M7/M8), `EMERGENCY_PARSER`, `ADVANCED_OK`.
- `BINARY_FILE_TRANSFER` für Updates über den Pi.
- **Dimmbares Licht an PC8:** `CASE_LIGHT_ENABLE` mit `CASE_LIGHT_PIN PC8` (`M355 S<0|1> P<0-255>`, beim Start aus). `COOLANT_MIST` ist dafür abgeschaltet; die Abluft bleibt `M8`/`M9` an PC9.
- **Motortöne `M300 S<Hz> P<ms> [X] [Y]`** (`firmware/marlin/motor_tone.cpp`): Das Board hat keinen Summer, deshalb spielt `M300` auf den Spulen von X und Y. Pro Tonperiode ein Mikroschritt vor und einer zurück, also ohne Bewegung (höchstens 0,0125 mm Ausschlag, Ergebnis exakt 0). Die Treiber schalten dafür kurz von StealthChop auf SpreadCycle (laut) und danach zurück. Strom, Positionszähler und Richtungs-Pins bleiben unverändert. Bei eingeschaltetem Laser lehnt Marlin ab (`echo:LumaCut M300 refused: laser on`). `S0` ist eine Pause, ein Aufruf spielt höchstens 2 s.

Auf GitHub baut `.github/workflows/marlin.yml` die Firmware bei jeder Änderung unter `firmware/marlin/`. Die `firmware.bin` liegt 14 Tage als Download in den Actions. `.bin`-Dateien kommen bewusst nicht ins Repository.

Unter Windows mit langem Benutzerpfad scheitert der Marlin-Clone an der Pfadlänge. Abhilfe: kurze Ordner (`--cache-dir`, `--output`, `TMP`) und `git -c core.longpaths=true` (siehe [ENTWICKLUNG.md](ENTWICKLUNG.md)).

