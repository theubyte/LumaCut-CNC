# LumaCut CNC

Eigenständiges, privates Entwicklungsprojekt für Atomstack A5 Pro / LaserTree LT-80W-AA-Pro, BIGTREETECH SKR Mini MZ V1.0 (STM32F103RC, TMC2209) und Waveshare ESP32-S3-Touch-LCD-7 Rev1.2.

**Stand 2026-10-19:** Infrastruktur und Geometrie-Tests; **KEINE** freigegebene flashfertige SKR-/ESP32-Firmware. Unraid ist ausschließlich ein GitHub-Buildserver; der Maschinenbetrieb soll ohne Raspberry Pi über LightBurn → USB → SKR (grblHAL) und die separate Touch-HMI laufen.

## Projektinhalte
- `builder/`: Browser-Buildserver mit GitHub-Checkout, Buildlogs, Archiv/Prüfsummen, keinen Flashrechten.
- `setup/`: Unraid-Docker-Installation und GitHub-Schlüssel-Einrichtung.
- `config/laser.yaml`: offene Maschinengeometrie, Tasterversatz, Fokusparameter, Sicherheit.
- `tools/probe_math.py` / `tests/`: reine, hardwarefreie XY-/Z-/Raster-Berechnung.
- `docs/`: Hardware, Taster-/Z-Probe-Konzept, Bedienprotokoll, Freigabe und nächster Entwicklungsstand.
- `firmware/skr`, `firmware/hmi`: reserviert für geprüfte Firmwarequellen.

## Unraid-Installation
Nach `git clone git@github.com:theubyte/LumaCut-CNC.git` aus dem Quellverzeichnis:
```bash
bash setup/unraid-install.sh
bash setup/github-setup.sh
```
Builder: `http://<UNRAID-IP>:18744` (nur LAN/VPN); zufällig generiertes Basic-Auth-Passwort aus `/mnt/user/appdata/lumacut-builder/.env`. Quellen werden bei jedem Build von `main` abgerufen.

**Keine Firmware automatisch flashen.** Laserleistung muss unabhängig von MCU-/HMI-Abstürzen hardwareseitig sperrbar sein. Der Z-Referenzendschalter und der seitlich versetzte Werkstück-Taster sind getrennte Signale. Es sind keine realen PINs, Abmessungen oder Fokusabstände verifiziert. Das E3-V2-Profil ist nicht identisch mit der SKR-Mini-MZ-Belegung.

Referenzen: https://github.com/grblHAL/STM32F1xx, https://docs.waveshare.com/ESP32-S3-Touch-LCD-7, https://docs.lightburnsoftware.com/, https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-mini-mz.cfg.
