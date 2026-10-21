# LumaCut CNC – Projektstatus 2026-10-21

**GitHub:** https://github.com/theubyte/LumaCut-CNC (main). **Wichtiger Hinweis: Repository ist derzeit PUBLIC**, nicht privat. Kein API-Token, SSH-Schlüssel oder personenbezogene Daten committen.
**Erststart:** [INBETRIEBNAHME.md](INBETRIEBNAHME.md). Die Datei ist der verbindliche Hardware-Testplan.

## Hardware und Ziel
Atomstack A5 Pro, LaserTree LT-80W-AA-Pro, BTT SKR Mini MZ v1.0 (STM32F103RC, TMC2209), Waveshare ESP32-S3-Touch-LCD-7 Rev1.2; keine Raspberry-Pi-Abhängigkeit. **LightBurn ⇄ USB CDC ⇄ SKR (grblHAL)** bleibt Haupt-G-Code-Stream. **HMI → 3,3-V-UART → SKR USART1** für einzelne grblHAL-Keypad-Zeichen; PC10/PC11 USART3 gehören TMC2209.

## Aktuelle Firmware und Tests
- **SKR:** `firmware/skr/build.py`; gepinnte grblHAL-STM32F1xx-Quellen; angepasste MZ-Motor-/Limit-/FET-Pins; nativer USB-Anschluss; `KEYPAD_ENABLE=2` USART1; **Y_GANGED=1 für Atomstack-Doppel-Y (vierter E-Treiber PB3/PB4/PD2 als Y2)**. Y2-Drehrichtung, Treiberstrom und mechanische Synchronisation am realen Gerät prüfen. **GitHub-Actions-Build erfolgreich**, einschließlich Keypad-Änderung. Physischer SKR-Flash **nicht getestet**.
- **HMI:** `firmware/hmi/src/main.cpp` v0.4, LVGL 8, RGB565 800×480, GT911 auf 0x5D/0x14, CH422G-Reset/Backlight-Korrektur. `lumacut_waveshare_s3` offline für sicheren Displaytest; `lumacut_waveshare_s3_keypad` optionales Gated-Jogging (30-s-Freigabe, Keyup 0x85). **Beide Buildziele wurden in Actions erfolgreich kompiliert**. Touch, tatsächlicher UART-Datenaustausch und Bewegungen **nicht an Hardware geprüft**.
- **CI:** `.github/workflows/ci.yml`: Tests und beide Controller, Toolchain-Cache, Wiederholungen bei Paketserverstörung, Download-Artefakte `UNVERIFIED-skr-...`, `UNVERIFIED-hmi-...`.
- **Inbetriebnahmeanleitung:** `docs/INBETRIEBNAHME.md`.

## Einschränkungen / Sicherheit
Kein fertiger Laserbetrieb: Prüfen von Motor- und Anschlagsrichtungen, Z-Spindelwegen, elektrischen Pegeln, Laser-PWM PA1, Laser-Enable, TMC-UART-Adresse/Strom, 28KiB-Bootloader und GND/5V vor Motor-/Laseranschluss. Insbesondere PC6/PC7 sind MOSFET-Fanausgänge und keine sicheren TTL-Pins. Laser bei Flash und Bewegungstests **stromlos und TTL abgeklemmt** lassen. E-Stop/Laserschlüssel/Interlocks unabhängig von der MCU hardwareseitig realisieren.

## Noch nicht entwickelt
- Live-DRO/GRBL-Status auf HMI (UART-Keypad besitzt aktuell **keine Quittierung/Rückmeldung**).
- Sichere Zustands-/Job-Arbitration über HMI über das Keypad-Plugin hinaus.
- Referenzfahrt des mechanischen Werkstücktasters, Fokus-/XY-Versatz automatisch anwenden, Z-Autofokus, Höhenkarte, Materialerkennung/Kamera, Kalibrierroutine.
- Vollständiger Hardware-Abnahmetest.

**Erfolg bei CI ≠ funktionierende, geprüfte Gesamtmaschine.** Das nächste Arbeitspaket ist die elektrische und mechanische Inbetriebnahme anhand dokumentierter Messwerte; funktionierende Flash-Images und Quellcode stehen in Actions bereit.
