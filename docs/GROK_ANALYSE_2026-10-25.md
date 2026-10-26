# Grok Analyse – LumaCut CNC (Raspberry Pi 400 + BTT SKR Mini MZ V1.0 + Marlin)

> **Hinweis zu dieser Fassung (26.10.2026):** Grok hat die Analyse am 25.10.2026 auf dem
> damaligen Stand des Repositories geschrieben (Branch `codex/multi-agent-setup-20261025`).
> Der Text von Grok steht unverändert. Unter jedem Punkt steht in einem Kasten wie diesem,
> was seitdem gilt. „Erledigt“ heißt: im Code umgesetzt und getestet; ob zusätzlich an der
> Maschine geprüft, steht jeweils dabei. Elektrische Punkte kann Software nicht abhaken.

**Stand:** 2026-10-25  
**Ziel:** Probleme finden und Verbesserungen vorschlagen, damit das System (Pi 400 Control Studio + SKR Mini MZ mit Marlin) zuverlässig und sicher funktioniert.

> **Warnung:** Das Projekt markiert den Marlin-Pfad selbst als experimentell (`hardware_verified=false`). Laser **nicht** anschließen, bis Isolation, Interlocks, PWM, Polarität und Not-Aus elektrisch verifiziert sind.

> **Stand 26.10.2026:** Der Laser ist angeschlossen und wurde über LightBurn und den Pi betrieben. Die
> Mechanik-Freigabe auf dem Pi ist erteilt (`docs/MASCHINE.md`). Das Firmware-Manifest steht
> aber weiterhin auf `hardware_verified: false` (`firmware/marlin/build.py`). Es wird erst
> umgestellt, wenn Isolation, Not-Aus und Z-Kalibrierung (Punkte 2.2 und 2.4) dokumentiert
> gemessen sind.

## 1. Übersicht der Architektur

- **Raspberry Pi 400**: Web-UI (HTTP 8080) + LightBurn-Gateway (TCP 23) → USB-CDC zum SKR.
- **BTT SKR Mini MZ V1.0** (STM32F103RC + TMC2209): Entweder grblHAL (aktueller Hauptpfad) oder experimentelles natives Marlin 2.1.2.9.
- Waveshare-ESP32-HMI ist archiviert, nicht mehr aktiv.
- Zwei getrennte systemd-Services verhindern gleichzeitigen USB-Zugriff.

> **Stand 26.10.2026:** Teilweise überholt. Es gibt nur noch **Marlin 2.1.2.9** auf dem SKR; grblHAL, die
> ESP32-HMI und die Unraid-Build-Umgebung wurden am 25.10. aus dem Repository entfernt
> (Commit `2a53e5c`). Auf dem Pi läuft ein Dienst (`pi400/marlin`): Web-UI und API auf 8080,
> LightBurn-Gateway auf TCP 23, alleiniger USB-Zugriff. Dazu kommen die eigenen Programme:
> Windows-App (`software/lumacut-studio-native`) und Android-App (`android/`).

Der Nutzer hat explizit **Marlin** genannt → Fokus auf `firmware/marlin/` und `pi400/marlin/`.

## 2. Kritische Probleme

### 2.1 Experimenteller Status / fehlende Hardware-Verifikation
- CI baut Firmware und Unit-Tests, prüft aber **keine** reale Bewegung, Endschalter, PWM-Amplitude, Isolation oder Fail-Off.
- Eigene Doku (`PI400_MARLIN_MIGRATION.md`, `FAN1_LASER_PI400_RELEASE.md`) verbietet Laserbetrieb bis zur elektrischen Freigabe.
- **Folge:** Software „funktioniert“ in der Simulation, Maschine ist noch nicht sicher.

> **Stand 26.10.2026:** Weiter richtig: Die CI prüft Software, keine Elektrik. An der Maschine geprüft sind
> inzwischen Homing, Jog, G30-Abtasten (inkl. Früh-Auslösung), Aufträge mit Laser und das
> Flashen über den Pi. Nicht als Messprotokoll dokumentiert sind PWM-Pegel/Frequenz,
> Fail-Off bei Reset/USB-Abzug und der Not-Aus-Kreis.

### 2.2 Pin-Mapping-Inkonsistenz und elektrische Gefahr (höchste Priorität)
| Funktion          | grblHAL-Pfad          | Marlin-Pfad (`build.py` PIN_PATCH) |
|-------------------|-----------------------|------------------------------------|
| Laser 24 V Power  | FAN1 / PC7            | FAN0 / PC6 (via M106/M107)         |
| Laser Enable      | —                     | PC7 (explizit „unwired“)          |
| Laser PWM         | PA1                   | PA1                                |
| Abluft (M8)       | BED / PC9             | PC9 (COOLANT_FLOOD)                |
| Licht (M7)        | HE0 / PC8             | PC8 (COOLANT_MIST)                 |
| Aux               | FAN0 / PC6            | —                                  |

- FAN1− (und ähnliche Low-Side-MOSFETs) sind **geschaltete Negative**, kein permanentes Logic-GND.
- Direktes Verbinden von PA1-PWM mit einem Laser, dessen GND auf dem geschalteten Minus liegt → Risiko von Backfeeding, ungewolltem Zünden oder STM32-Schaden.
- Frühere ~8 V-Messung war zwischen PA1 und geschaltetem BED− – **kein** gültiger PA1-zu-GND-Wert.
- **Muss:** Galvanisch isolierte PWM-Stufe + unabhängiger Hardware-Interlock (Fail-Off bei Stromausfall/Reset).

> **Stand 26.10.2026:** Die Pin-Inkonsistenz ist mit dem Wegfall von grblHAL erledigt; es gilt nur noch die
> Marlin-Belegung: PA1 = PWM, PC6 (FAN0, `M106 P0`/`M107 P0`) = Laserversorgung,
> PC7 = Laser-Enable (nicht verdrahtet), PC8 = Licht (M7), PC9 = Abluft (M8).
> Laut `docs/MASCHINE.md` sitzt zwischen PA1 und Laser ein galvanisch getrennter
> PWM-Treiber. **Offen:** Messprotokoll dazu (PA1 gegen Logikmasse, PWM-Pegel am Laser,
> Zustand bei Reset/USB-Abzug) und ein von der Software unabhängiger Not-Aus/Interlock
> für Laserversorgung und Motoren. Das ist Hardware und bleibt Pflicht.

### 2.3 Homing-Strategie (Docs vs. Code)
- Docs sprechen teilweise von „Z-first“ (sicherer gegen Material).
- Code in `MarlinTransport.safe_home`: **XY zuerst** (`G28 X Y` in 30 mm Safe-Zone), dann `G28 Z`, dann Retract um `clearance_mm`.
- Funktioniert nur, wenn:
  - die 30 mm Ecke wirklich frei ist,
  - positive Z **nach oben** (weg vom Material) zeigt,
  - Endschalter-Polarität und Invert korrekt sind.
- Bei Fehler wird USB geschlossen – Recovery manuell.

> **Stand 26.10.2026:** Code und Doku stimmen überein: erst X/Y in die leere 30-mm-Ecke, dann Z über den Taster
> an X0/Y0, dann Rückzug auf 20 mm (`safe_home` in `pi400/marlin/transport.py`,
> `docs/MASCHINE.md`). Positives Z zeigt vom Material weg, Endschalter (Öffner) und
> Richtungen sind am Gerät geprüft. Ein abgelehnter G-Code-Befehl trennt USB nicht mehr;
> die Verbindung bleibt bestehen (Test `test_z_motion_floor_blocks_below_2mm_from_material_contact`).
> Die 30-mm-Ecke ist jetzt in beiden Apps unsichtbar und für den Nutzer gesperrt; dort
> wird nie gelasert, auch kein Überlauf.

### 2.4 Kalibrierung unvollständig
- `DEFAULT_AXIS_STEPS_PER_UNIT { 80, 80, 380 }` – Z ist Platzhalter (Anet-Spindel).
- Endstop `*_MIN_ENDSTOP_INVERTING true`, Directions (`INVERT_*_DIR false`) basieren auf „physical jogging“, müssen am Gerät bestätigt werden.
- Bed-Size 390×370, Z_MAX 90 – messen!
- Alte grblHAL-EEPROM-Werte **nicht** blind übernehmen.
- Z-Probe nutzt Z_MIN_ENDSTOP mit erhöhten Clearances (wegen MDF-Blech) – frühe Trigger-Fehler möglich.

> **Stand 26.10.2026:** - Endschalter-Polarität und X/Y-Richtung: am Gerät geprüft (`docs/MASCHINE.md`).
> - Bettgröße 390 × 370 mm, Arbeitsbereich ohne Safezone 360 × 340 mm.
> - **Offen: Z-Schritte/mm.** In der Firmware steht weiterhin `{ 80, 80, 380 }`. Ob 380
>   für die Z-Spindel stimmt, ist nicht gemessen dokumentiert. Davon hängen Fokushöhe,
>   Z-Absenkung je Durchgang und das Höhenmesh ab. Messen: 20 mm in Z fahren, Ist-Weg mit
>   Messschieber/Messuhr, dann `neu = 380 × Soll / Ist`.
> - Alte EEPROM-Werte: Der Pi setzt bei jeder Verbindung `M203 Z9` und `M851 X0 Y0 Z0`
>   nur zur Laufzeit, ohne EEPROM zu schreiben.
> - Frühe Taster-Auslösung („Probing Failed“ bei Kontakt oberhalb der Firmware-Grenze)
>   ist behoben: Der Pi erkennt den geschalteten Taster und übernimmt die Kontakthöhe.

### 2.5 LightBurn-Gateway & State-Machine
- Muss **Custom GCode / Marlin**-Flavor sein (kein altes GRBL `.lbdev`).
- Anforderungen: M3 I (kein M3 S), S 0..255, Emit S bei jedem G1, Max S=255.
- Strenge Filterung in `MarlinLaserGuard` + `command()`:
  - Nur erlaubte G/M-Befehle,
  - G28 wird intercepted,
  - Motion erst nach `homing_verified` + `surface_z`,
  - Safe-Zone (30 mm) für Cuts,
  - Auto-Focus vor erstem powered G1.
- State (`laser_enabled`, `fan_power`, `surface_z`, `focused_this_job`, `absolute_mode`) ist komplex und kann desynchronisieren (stale M114, Disconnect, Chime-Fehler).
- Fan-Cooldown (180 s via M107) ist nur Pi-seitig – kein hardware-backed Afterrun.
- Stepper-Chime (`_play_stepper_chime_locked`) kann Position verlieren.

> **Stand 26.10.2026:** - LightBurn-Profil: Marlin, `M3 I`, S 0..255, S in jedem G1 – so dokumentiert und vom
>   Gateway erzwungen. Daneben gibt es jetzt eigene Programme, LightBurn ist nicht mehr nötig.
> - Ruckeln/Brennpunkte durch `M400` je Segment sind behoben (Schnitt-Sperre nutzt die
>   zuletzt kommandierte Position; absolute Z-Ziele werden ohne `M400` geprüft).
> - Aufträge mit eigenem Z (Höhenkorrektur) überspringen den automatischen Einzelfokus.
> - **Offen:** Der Lüfter-/Versorgungsnachlauf (180 s) hängt am Pi, nicht an der Hardware.
>   Fällt der Pi aus, läuft nichts nach.
> - Melodie: erledigt. Die Motoren spielen über die Spulen (Firmware-`M300`), der Kopf
>   bewegt sich nicht mehr, die Position kann dadurch nicht verloren gehen.
>   Braucht die neue Firmware (geflasht über den Pi).

### 2.6 Weitere Lücken
- Kein automatisches SKR-USB-Flashing (Bootloader-abhängig, nur SD/SWD).
- Multi-Point-Höhenkarte / vollständiges G30-Raster nicht fertig.
- Exclusive USB-Ownership korrekt, aber Reconnect-Logik und M114-Parsing empfindlich.
- Studio-Desktop-App (neuere Commits) ist ein separater Strang.

> **Stand 26.10.2026:** - **SKR flashen über USB:** erledigt und an der Maschine getestet: Upload per
>   `M28 B1` auf die SD-Karte im SKR, dann `M997` (`docs/FIRMWARE.md`). SD-Karte bleibt
>   als Rettungsweg.
> - **Höhenkarte / G30-Raster:** erledigt in Software: Windows-App (Scan + Probe) und
>   Android-App (Arbeitsplatz → Höhenmesh) tasten ein Raster ab, der tiefste Punkt zuletzt,
>   dann bekommt jedes ≤ 2 mm lange Laserstück sein eigenes Z. An der Maschine noch nicht
>   mit mehreren Werkstückhöhen gelaufen.
> - **Kopfkamera für den Scan:** Software fertig (Pi: `/api/camera/snapshot`, Fahrbefehl
>   `moveto`), aber am Pi ist noch keine Kamera angeschlossen.
> - Studio-Desktop: weiterentwickelt wird die native Windows-App (`software/lumacut-studio-native`); die ältere Tauri-Studio (`software/lumacut-studio`) liegt noch im Repository.

## 3. Empfohlene Verbesserungen (priorisiert)

### Sicherheit (sofort)
1. **Hardware-Interlock** vor jeder Software: Relais oder FET mit independent Fail-Off (Not-Aus, Gehäuse, Stromausfall).
2. **Isolierte PWM-Stufe** (Optokoppler / isolierter Buffer) mit Sekundärseite auf Laser-GND referenziert.
3. Klare Verdrahtungsanleitung + Messprotokoll (PA1 gegen Logic-GND, MOSFET-Off-Zustand, PWM-Frequenz/Amplitude).
4. Pin-Map vereinheitlichen (eine Wahrheit für grblHAL und Marlin) und mit Schaltplan absichern.

> **Stand 26.10.2026:** Punkt 4 erledigt (nur noch Marlin). Punkte 1–3 offen: Hardware-Interlock mit Fail-Off,
> Messprotokoll zur PWM-Trennung, Verdrahtungsplan mit Messwerten.

### Software / Firmware
1. Docs und Code synchronisieren (Homing-Reihenfolge explizit dokumentieren).
2. Kalibrierungs-Workflow im Web-UI: Soll/Ist-Weg → neue steps/mm schreiben + Readback.
3. Endstop-Polarität und Direction im UI testbar machen (Jog + M119).
4. Fan-Afterrun hardwareseitig lösen (oder zumindest klar als „nicht crash-sicher“ kennzeichnen).
5. Mehr defensive State-Resets und Logging bei USB-Disconnect / Error.
6. Optional: grblHAL als stabilen Fallback behalten, bis Marlin elektrisch freigegeben ist.

> **Stand 26.10.2026:** 1. Erledigt (Homing-Reihenfolge in `docs/MASCHINE.md`).
> 2. Offen: Kalibrier-Assistent für Schritte/mm (Soll/Ist → `M92` + `M500` + Rücklesen).
> 3. Teilweise: Jog und Endschalter-Abfrage (`op=endstops`, M119) gibt es in der Web-UI.
> 4. Offen (Hardware): Nachlauf ist nicht absturzsicher; in `docs/MASCHINE.md` so vermerkt.
> 5. Teilweise: Fehlerpfade schalten kontrolliert ab (`M5 I`, Parken), Notstopp bleibt
>    gesperrt bis zur Quittierung.
> 6. Entfällt: grblHAL wurde auf Wunsch entfernt; Rückweg ist das Flashen per SD-Karte.

### Tests
- End-to-End auf echter Hardware (ohne Laser): Homing, Jog, Endstops, M114-Genauigkeit, USB-Reconnect.
- PWM mit Dummy-Load + Scope.
- LightBurn Custom-GCode-Jobs (nur Motion) durchspielen.
- Fail-Off nach Reset / USB-Pull testen.

> **Stand 26.10.2026:** Homing, Jog, Endschalter, Abtasten, LightBurn-Aufträge und Flashen sind an der Maschine
> gelaufen. Offen und als Protokoll festzuhalten: PWM mit Dummy-Last und Oszilloskop,
> Fail-Off bei Reset und USB-Abzug, Not-Aus.

## 4. Nächste konkrete Schritte

1. Laser physisch trennen (VCC + PWM).
2. Aktuelle SKR-Firmware + Pi-Software sichern.
3. Marlin-Firmware nur flashen, wenn Bootloader akzeptiert und Isolation geplant ist.
4. `sudo bash pi400/marlin/activate.sh --laser-disconnected` nach Flash.
5. Web-UI: M115, M119, M114 prüfen; Homing nur mit freier Ecke und verifizierter Z-Richtung.
6. Steps/mm und Directions kalibrieren.
7. Erst danach Isolation + Interlock bauen und Dummy-Load-Tests machen.

> **Stand 26.10.2026:** Schritte 1–6 sind durch: Firmware über den Pi geflasht, M115/M119/M114 geprüft, Homing
> und Richtungen am Gerät bestätigt. `activate.sh` gibt es nach dem Aufräumen nicht mehr;
> der Dienst wird wie in `docs/PI_BETRIEB.md` installiert. Offen bleiben Z-Schritte/mm
> (6) und das dokumentierte Messen von Isolation und Interlock (7).

## 5. Fazit

Das Projekt ist ambitioniert und hat gute Sicherheits-Gedanken (Guards, exclusive Ownership, Fail-Closed bei Disconnect). Die größten Blocker sind:

- fehlende elektrische Verifikation / Isolation,
- Pin-Mapping-Inkonsistenz zwischen den beiden Firmware-Pfaden,
- unvollständige Kalibrierung,
- Docs-vs-Code-Abweichungen.

Solange diese Punkte nicht abgehakt sind, ist der Marlin-Pfad **nicht** für realen Laserbetrieb geeignet. Der grblHAL-Pfad hat ähnliche elektrische Warnungen, ist aber der aktuell aktivere.

> **Stand 26.10.2026:** **Offen (Reihenfolge nach Sicherheit):**
> 1. Unabhängiger Not-Aus/Interlock für Laserversorgung und Motoren (Hardware).
> 2. Messprotokoll der PWM-Trennung (Dummy-Last, Oszilloskop, Reset/USB-Abzug).
> 3. Z-Schritte/mm messen und einstellen.
> 4. Hardware-Nachlauf für Lüfter/Versorgung oder bewusst akzeptieren.
> 5. Danach `hardware_verified` im Firmware-Manifest auf `true`.
> 
> **Erledigt seit der Analyse:** nur noch Marlin (Pin-Widerspruch weg), Homing-Doku = Code,
> Flashen über den Pi, G30-Früh-Auslösung, Höhenmesh mit Fokuskorrektur, ruckelfreie
> Schnitte, Safezone in den Apps unsichtbar und gesperrt.

---
*Analyse erstellt von Grok auf Basis des Repositories `theubyte/LumaCut-CNC` (Commit um 2026-10-25). Keine Hardware vor Ort getestet.*
