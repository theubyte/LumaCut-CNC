# Releases und Flashfreigabe

1. Build erhält Source-Commit SHA, Git-Branch, UTC-Datum, Ziel, Prüfsumme und Buildlog.
2. Der Webserver darf **nicht** flashen und hat keinen angeschlossenen USB-Laser oder Docker-Socket.
3. Ein erfolgreicher Compiler-Lauf ist **keine** Hardwarefreigabe.
4. Für eine reale SKR-Freigabe: MCU-Variante, Pinbelegung, Bootloader und Flash-Restore, Motorachsen ohne Laser, Endschalter, Probe-Limits, PWM-Reset-Pegel, reale Hardware-Interlocks, USB und HMI-Kollision testen.
5. Vorher Original-BIN + Config exportieren. Ohne verifiziertes Restore keine Versuche.
6. Erst nach dokumentierter Sign-off Freigabe eines Git-Tags und Release mit geprüften Checksummen.
7. ESP32-Images (Bootloader, Partitionen, App) getrennt versionieren. Einstellungen müssen migrierbar sein.