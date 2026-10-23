# LumaCut CNC

Quellcode, dokumentierte Builds und Inbetriebnahmeunterlagen für Atomstack A5 Pro / LaserTree LT-80W-AA-Pro mit **BIGTREETECH SKR Mini MZ V1.0** (STM32F103RC, TMC2209) sowie **Waveshare ESP32-S3-Touch-LCD-7 Rev1.2**.

**Stand 21.10.2026 – LumaCut Control OS (Waveshare als USB/WLAN-Gateway) und passende SKR-UART-Variante kompiliert, Hardwarevalidierung fehlt.** Quellcode und GitHub-Action-Builds sind vorhanden. Diese Builds sind **nicht für produktiven Laserbetrieb freigegeben**. Sie sind Labor-/Inbetriebnahmeimages. Prüfe vor Benutzung unbedingt die elektrische Belegung und die externe Sicherheitskette.

**Reales Hardwareprofil (23.10.2026):** Genau drei Stepper (je einer für X, Y, Z), E-Treiber unbenutzt, **je ein Endschalter an X/Y/Z**, Z-Taster soll später auch Werkstückabtastung übernehmen. **XYZ-Homing ist verfügbar**, G38-Werkstückabtastung benötigt erst eine geprüfte gemeinsame Endstop/Probe-Logik. [Hardwarebelegung](docs/HARDWARE.md).

**[INBETRIEBNAHME: zuerst lesen](docs/INBETRIEBNAHME.md)**

## Firmware

| Projekt/Buildziel | Aufgabe | Status |
|---|---|---|
| `firmware/skr` → `lumacut_skr_mz_usb` | Altes grblHAL USB-/Keypad-Testprofil | Kompiliert; nicht mit Control OS kombinieren |
| `firmware/skr` → `lumacut_skr_mz_hmi_uart` | **Control OS SKR-Profil:** grblHAL USART1 PA9/10 Hauptstream zum Waveshare | Kompiliert; Hardware ungetestet |
| `firmware/hmi` → `lumacut_waveshare_s3` | 7-Zoll-RGB/GT911, Touch-Dashboard, keine Bewegungsbefehle | Kompiliert; LCD und Touch am echten Gerät ungetestet |
| `firmware/hmi` → `lumacut_waveshare_s3_keypad` | Altes experimentelles UART-Keypad-Profil | Kompiliert; nicht mit Control OS kombinieren |
| `firmware/hmi` → `lumacut_waveshare_s3_pro` | **Control OS:** 7″ Apple-inspiriertes UI, USB-C CDC und WLAN-GRBL für LightBurn, G-Code-Jobportal, BLE-Status, Parkmakros | Kompiliert; physische Tests ausstehend |
| Z-Autofokus, XY-Tasterversatz, Höhenkarte | Ziel-Funktionen | Noch nicht implementiert; gemeinsamer Z-Taster benötigt validierte Probe-Umschaltung |

Die alte Keypad-HMI hat keine grblHAL-Rückmeldung. Die neue **Control-OS-HMI** wertet dagegen Statusdaten und X/Y/Z-Maschinenkoordinaten über den SKR-UART-Hauptstream aus. Das ist bisher nur softwareseitig kompiliert, nicht an der realen Maschine verifiziert.

**[GitHub Actions – Firmwarebuilds / Artefakte](https://github.com/theubyte/LumaCut-CNC/actions/workflows/ci.yml)**: einen mit grünem Haken abgeschlossenen Lauf auswählen, unten `UNVERIFIED-skr-...` und `UNVERIFIED-hmi-...` herunterladen. Im HMI-ZIP befinden sich beide Varianten unter den unterschiedlichen `.pio/build`-Verzeichnissen. Dateinamen sind nicht als Freigabe zu verstehen.

## Architektur

**Control OS:** `LightBurn (USB oder Wi-Fi/TCP) / Handy (WLAN) → Waveshare ESP32-S3 → UART2 3,3-V-TTL → SKR Mini MZ (USART1 grblHAL) → Motoren/Laser`.

Das SKR benötigt dabei keine eigene USB-Verbindung zum PC. Der native USB-C des Waveshare ist der LightBurn-Port; der USB-TO-UART-Port teilt sich seine UART2-Pins und kann dafür nicht parallel verwendet werden. BLE unterstützt Status, aber kein LightBurn-Bluetooth-Serial.

**[LumaCut Control OS: Bedienung, Verkabelung, Grenzen](docs/LUMACUT_CONTROL_OS.md)**

Der Laser darf nur nach externer hardwarewirksamer Sicherheitsfreigabe zugeschaltet werden. USART3 PC10/PC11 bleibt für TMC2209 reserviert. Unraid ist ausschließlich GitHub-Buildserver, nicht Teil der Maschinensteuerung.

## Quellen und Buildserver

- `firmware/skr/build.py`: verwendet gepinnten offiziellen grblHAL-STM32F1xx-Code mit Mini-MZ-Pinanpassung und 28KiB-SD-Bootloader-Layout.
- `firmware/hmi/src/main.cpp`: native ESP32-S3-RGB/GT911/CH422G-LVGL-Steuerung.
- `setup/`, `builder/`: Unraid-Docker-Buildserver, LAN-UI auf Port 18744; neue Firmwareziele **LumaCut Control OS** und **SKR UART für Control OS**. HMI-Flashpaket für Windows oder bei HTTPS Browser-Web-Serial-Flash; kein USB-/Flash-Zugriff durch den Container.
- `config/laser.yaml`: Planungsparameter, **keine** automatisch auf den SKR übertragenen Maschinenwerte.
- `tools/probe_math.py`, `tests/`: Geometrieberechnung und hardwarefreie Unit-Tests.
- `docs/INBETRIEBNAHME.md`: verpflichtende Checkliste, Pinbelegung und sichere Prüfschritte.

**Waveshare HMI vom Build Lab flashen:** [Anleitung und Update des Unraid-Containers](builder/README.md). Der Builder erstellt ein vollständiges ESP32-S3-BIN und ein Windows-Paket mit lokalem Browser-Flashassistenten. Zuerst die HMI-Variante ohne UART-Jog testen.

Unraid: `bash setup/unraid-install.sh` und `bash setup/github-setup.sh` nur nach Prüfung der Scripts ausführen.

## Freigabe

Alle per CI erstellten Images heißen ausdrücklich `UNVERIFIED`. Nicht mit angeschlossenem aktiven Laser flashen oder testen. Not-Aus-/Schlüssel-/Gehäuse-Interlocks müssen hardwareseitig wirken, nicht nur durch Firmware.
