# Grok Analyse – LumaCut CNC (Raspberry Pi 400 + BTT SKR Mini MZ V1.0 + Marlin)

**Stand:** 2026-10-25  
**Ziel:** Probleme finden und Verbesserungen vorschlagen, damit das System (Pi 400 Control Studio + SKR Mini MZ mit Marlin) zuverlässig und sicher funktioniert.

> **Warnung:** Das Projekt markiert den Marlin-Pfad selbst als experimentell (`hardware_verified=false`). Laser **nicht** anschließen, bis Isolation, Interlocks, PWM, Polarität und Not-Aus elektrisch verifiziert sind.

## 1. Übersicht der Architektur

- **Raspberry Pi 400**: Web-UI (HTTP 8080) + LightBurn-Gateway (TCP 23) → USB-CDC zum SKR.
- **BTT SKR Mini MZ V1.0** (STM32F103RC + TMC2209): Entweder grblHAL (aktueller Hauptpfad) oder experimentelles natives Marlin 2.1.2.9.
- Waveshare-ESP32-HMI ist archiviert, nicht mehr aktiv.
- Zwei getrennte systemd-Services verhindern gleichzeitigen USB-Zugriff.

Der Nutzer hat explizit **Marlin** genannt → Fokus auf `firmware/marlin/` und `pi400/marlin/`.

## 2. Kritische Probleme

### 2.1 Experimenteller Status / fehlende Hardware-Verifikation
- CI baut Firmware und Unit-Tests, prüft aber **keine** reale Bewegung, Endschalter, PWM-Amplitude, Isolation oder Fail-Off.
- Eigene Doku (`PI400_MARLIN_MIGRATION.md`, `FAN1_LASER_PI400_RELEASE.md`) verbietet Laserbetrieb bis zur elektrischen Freigabe.
- **Folge:** Software „funktioniert“ in der Simulation, Maschine ist noch nicht sicher.

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

### 2.3 Homing-Strategie (Docs vs. Code)
- Docs sprechen teilweise von „Z-first“ (sicherer gegen Material).
- Code in `MarlinTransport.safe_home`: **XY zuerst** (`G28 X Y` in 30 mm Safe-Zone), dann `G28 Z`, dann Retract um `clearance_mm`.
- Funktioniert nur, wenn:
  - die 30 mm Ecke wirklich frei ist,
  - positive Z **nach oben** (weg vom Material) zeigt,
  - Endschalter-Polarität und Invert korrekt sind.
- Bei Fehler wird USB geschlossen – Recovery manuell.

### 2.4 Kalibrierung unvollständig
- `DEFAULT_AXIS_STEPS_PER_UNIT { 80, 80, 380 }` – Z ist Platzhalter (Anet-Spindel).
- Endstop `*_MIN_ENDSTOP_INVERTING true`, Directions (`INVERT_*_DIR false`) basieren auf „physical jogging“, müssen am Gerät bestätigt werden.
- Bed-Size 390×370, Z_MAX 90 – messen!
- Alte grblHAL-EEPROM-Werte **nicht** blind übernehmen.
- Z-Probe nutzt Z_MIN_ENDSTOP mit erhöhten Clearances (wegen MDF-Blech) – frühe Trigger-Fehler möglich.

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

### 2.6 Weitere Lücken
- Kein automatisches SKR-USB-Flashing (Bootloader-abhängig, nur SD/SWD).
- Multi-Point-Höhenkarte / vollständiges G30-Raster nicht fertig.
- Exclusive USB-Ownership korrekt, aber Reconnect-Logik und M114-Parsing empfindlich.
- Studio-Desktop-App (neuere Commits) ist ein separater Strang.

## 3. Empfohlene Verbesserungen (priorisiert)

### Sicherheit (sofort)
1. **Hardware-Interlock** vor jeder Software: Relais oder FET mit independent Fail-Off (Not-Aus, Gehäuse, Stromausfall).
2. **Isolierte PWM-Stufe** (Optokoppler / isolierter Buffer) mit Sekundärseite auf Laser-GND referenziert.
3. Klare Verdrahtungsanleitung + Messprotokoll (PA1 gegen Logic-GND, MOSFET-Off-Zustand, PWM-Frequenz/Amplitude).
4. Pin-Map vereinheitlichen (eine Wahrheit für grblHAL und Marlin) und mit Schaltplan absichern.

### Software / Firmware
1. Docs und Code synchronisieren (Homing-Reihenfolge explizit dokumentieren).
2. Kalibrierungs-Workflow im Web-UI: Soll/Ist-Weg → neue steps/mm schreiben + Readback.
3. Endstop-Polarität und Direction im UI testbar machen (Jog + M119).
4. Fan-Afterrun hardwareseitig lösen (oder zumindest klar als „nicht crash-sicher“ kennzeichnen).
5. Mehr defensive State-Resets und Logging bei USB-Disconnect / Error.
6. Optional: grblHAL als stabilen Fallback behalten, bis Marlin elektrisch freigegeben ist.

### Tests
- End-to-End auf echter Hardware (ohne Laser): Homing, Jog, Endstops, M114-Genauigkeit, USB-Reconnect.
- PWM mit Dummy-Load + Scope.
- LightBurn Custom-GCode-Jobs (nur Motion) durchspielen.
- Fail-Off nach Reset / USB-Pull testen.

## 4. Nächste konkrete Schritte

1. Laser physisch trennen (VCC + PWM).
2. Aktuelle SKR-Firmware + Pi-Software sichern.
3. Marlin-Firmware nur flashen, wenn Bootloader akzeptiert und Isolation geplant ist.
4. `sudo bash pi400/marlin/activate.sh --laser-disconnected` nach Flash.
5. Web-UI: M115, M119, M114 prüfen; Homing nur mit freier Ecke und verifizierter Z-Richtung.
6. Steps/mm und Directions kalibrieren.
7. Erst danach Isolation + Interlock bauen und Dummy-Load-Tests machen.

## 5. Fazit

Das Projekt ist ambitioniert und hat gute Sicherheits-Gedanken (Guards, exclusive Ownership, Fail-Closed bei Disconnect). Die größten Blocker sind:

- fehlende elektrische Verifikation / Isolation,
- Pin-Mapping-Inkonsistenz zwischen den beiden Firmware-Pfaden,
- unvollständige Kalibrierung,
- Docs-vs-Code-Abweichungen.

Solange diese Punkte nicht abgehakt sind, ist der Marlin-Pfad **nicht** für realen Laserbetrieb geeignet. Der grblHAL-Pfad hat ähnliche elektrische Warnungen, ist aber der aktuell aktivere.

---
*Analyse erstellt von Grok auf Basis des Repositories `theubyte/LumaCut-CNC` (Commit um 2026-10-25). Keine Hardware vor Ort getestet.*
