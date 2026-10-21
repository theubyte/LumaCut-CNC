# LumaCut CNC

Quellcode, dokumentierte Builds und Inbetriebnahmeunterlagen für Atomstack A5 Pro / LaserTree LT-80W-AA-Pro mit **BIGTREETECH SKR Mini MZ V1.0** (STM32F103RC, TMC2209) sowie **Waveshare ESP32-S3-Touch-LCD-7 Rev1.2**.

**Stand 21.10.2026 – technisch kompiliert, Hardwarevalidierung fehlt.** Quellcode und GitHub-Action-Builds sind vorhanden. Diese Builds sind **nicht für produktiven Laserbetrieb freigegeben**. Sie sind Labor-/Inbetriebnahmeimages. Prüfe vor Benutzung unbedingt die elektrische Belegung und die externe Sicherheitskette.

**[INBETRIEBNAHME: zuerst lesen](docs/INBETRIEBNAHME.md)**

## Firmware

| Projekt/Buildziel | Aufgabe | Status |
|---|---|---|
| `firmware/skr` → `lumacut_skr_mz_usb` | grblHAL X/Y/Z, USB CDC für LightBurn; USART1 UART-Keypad (`KEYPAD_ENABLE=2`) | Kompiliert; Port-Mapping und Sicherheitsfunktionen am echten SKR ungetestet |
| `firmware/hmi` → `lumacut_waveshare_s3` | 7-Zoll-RGB/GT911, Touch-Dashboard, keine Bewegungsbefehle | Kompiliert; LCD und Touch am echten Gerät ungetestet |
| `firmware/hmi` → `lumacut_waveshare_s3_keypad` | experimentelles UART-Keypad GPIO43/44 mit Jog-Freigabe, Stop bei Loslassen | Kompiliert; Verbindung mit SKR und Fahrverhalten ungetestet |
| Z-Autofokus, XY-Tasterversatz, Höhenkarte, Live-DRO | Ziel-Funktionen | Noch nicht implementiert |

Die HMI hat derzeit **keine grblHAL-Statusrückmeldung**, zeigt also keine live gemessenen X/Y/Z-Koordinaten. Die UART-Tasten sind **nicht** als Sicherheitseinrichtung nutzbar.

**[GitHub Actions – Firmwarebuilds / Artefakte](https://github.com/theubyte/LumaCut-CNC/actions/workflows/ci.yml)**: einen mit grünem Haken abgeschlossenen Lauf auswählen, unten `UNVERIFIED-skr-...` und `UNVERIFIED-hmi-...` herunterladen. Im HMI-ZIP befinden sich beide Varianten unter den unterschiedlichen `.pio/build`-Verzeichnissen. Dateinamen sind nicht als Freigabe zu verstehen.

## Architektur

`LightBurn → USB CDC → SKR Mini MZ (grblHAL) → Motoren`

`Waveshare Touch → UART2 (3,3-V-TTL) → SKR USART1 → grblHAL Keypad`

Der Laser darf nur nach externer hardwarewirksamer Sicherheitsfreigabe zugeschaltet werden. USART3 PC10/PC11 bleibt für TMC2209 reserviert. Unraid ist ausschließlich GitHub-Buildserver, nicht Teil der Maschinensteuerung.

## Quellen und Buildserver

- `firmware/skr/build.py`: verwendet gepinnten offiziellen grblHAL-STM32F1xx-Code mit Mini-MZ-Pinanpassung und 28KiB-SD-Bootloader-Layout.
- `firmware/hmi/src/main.cpp`: native ESP32-S3-RGB/GT911/CH422G-LVGL-Steuerung.
- `setup/`, `builder/`: Unraid-Docker-Buildserver, LAN-UI auf Port 18744. HMI-Flashpaket für Windows oder bei HTTPS Browser-Web-Serial-Flash; kein USB-/Flash-Zugriff durch den Container.
- `config/laser.yaml`: Planungsparameter, **keine** automatisch auf den SKR übertragenen Maschinenwerte.
- `tools/probe_math.py`, `tests/`: Geometrieberechnung und hardwarefreie Unit-Tests.
- `docs/INBETRIEBNAHME.md`: verpflichtende Checkliste, Pinbelegung und sichere Prüfschritte.

**Waveshare HMI vom Build Lab flashen:** [Anleitung und Update des Unraid-Containers](builder/README.md). Der Builder erstellt ein vollständiges ESP32-S3-BIN und ein Windows-Paket mit lokalem Browser-Flashassistenten. Zuerst die HMI-Variante ohne UART-Jog testen.

Unraid: `bash setup/unraid-install.sh` und `bash setup/github-setup.sh` nur nach Prüfung der Scripts ausführen.

## Freigabe

Alle per CI erstellten Images heißen ausdrücklich `UNVERIFIED`. Nicht mit angeschlossenem aktiven Laser flashen oder testen. Not-Aus-/Schlüssel-/Gehäuse-Interlocks müssen hardwareseitig wirken, nicht nur durch Firmware.
