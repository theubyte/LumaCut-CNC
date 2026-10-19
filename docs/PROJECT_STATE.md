# LumaCut CNC – Projektstatus 2026-10-19

Private Hauptquelle: https://github.com/theubyte/LumaCut-CNC, Branch main.
Verbindliche Dokumente: README.md, HARDWARE.md, PROBE_AND_LEVELING.md, UNRAID.md und GitHub Issues.

Hardware: Atomstack A5 Pro, LaserTree LT-80W-AA-Pro, BTT SKR Mini MZ V1.0 (STM32F103RC / TMC2209), Waveshare ESP32-S3-Touch-LCD-7 Rev1.2. LightBurn soll via USB CDC direkt am SKR laufen, ohne Raspberry Pi; Unraid nur als GitHub-Compiler.

Neu: Firmwarequellen im Repo.
- SKR `firmware/skr/build.py` baut offiziellen, versionierten grblHAL-Code mit eigener MZ-Pinübersetzung und 28KiB-Bootloaderoffset.
- HMI `firmware/hmi` hat eigene ESP32-S3-/LVGL-Touch-Firmware mit realem LCD-/Touch-Ansteuerungscode. Bedien-Events sind aus Sicherheitsgründen noch gesperrt.
- CI erstellt Firmware und Tests; Unraid GUI kann dieselben Ziele per festem Kommando starten.
- Höhengeometrie-Tests bleiben unabhängig von der Echtzeit-Firmware.

Unbedingt unterscheiden: GitHub-Quellcode, erfolgreicher Compiler-Build, echte Hardware-Freigabe und fertige Bedienintegration sind verschiedene Entwicklungsstände. Nach jeder Änderung in CI prüfen. Bis zur ausdrücklichen Freigabe sind die .bin Dateien UNVERIFIED_DO_NOT_FLASH.

Noch offen: zweite GRBL-UART-Schnittstelle mit konfliktfreiem LightBurn-Betrieb, Messwerte und sichere Servo-/PWM-/Interlock-Beschaltung, tatsächlich fahrender Z-Taster/Autofokus und Höhenkarte.