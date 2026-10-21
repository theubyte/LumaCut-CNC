# LumaCut Build Lab – Firmware bauen und Waveshare HMI flashen

Unraid Docker mit Flask, PlatformIO und esptool; Web-Port **18744** (Container 8080).
Quellen werden für jeden Job aus GitHub geholt. Der Deploy-Key wird ausschließlich
für GitHub-Lesezugriff verwendet; Passwort und Schlüssel bleiben im Unraid Appdata.

## Builds

- **Projekt-Tests:** Unit-Tests, Kompilierprüfung.
- **SKR Mini MZ:** experimentelles STM32/grblHAL-Image. Kein Flash durch den Builder.
- **Waveshare HMI – nur Touch:** Profil `lumacut_waveshare_s3`; zunächst dieses flashen.
- **Waveshare HMI – UART-Jog:** Profil `lumacut_waveshare_s3_keypad`; nur nach erfolgreicher separater Motor-/Endschalterprüfung und bei stromlosem Laser.

Bei HMI-Erfolg erzeugt das Build Lab außer der normalen Entwicklungs-Firmware:
1. `LUMACUT_HMI_ESP32S3_MERGED.bin`: vollständiges 16-MB-kompatibles ESP32-S3-Flashabbild aus Bootloader, Partitionstabelle, OTA-Bootstub und Anwendung (Startadresse 0), mit Prüfsumme.
2. `Waveshare-HMI-Flash-Paket-Windows.zip`: Firmware, Manifest und localhost-Flasher.
3. Ein Web-Flash-Manifest, das zu genau diesem Build gehört.

## Flashen, wenn Waveshare am Windows-PC steckt

**Ohne HTTPS**, also beim Standard-Zugriff `http://UNRAID-IP:18744`:

1. Build `Waveshare HMI (nur Touch)` starten und auf Status `success` warten.
2. Im selben Listeneintrag auf **Windows-Flashpaket** klicken.
3. ZIP vollständig entpacken. Python 3 auf Windows installieren, sofern nicht vorhanden.
4. Das Waveshare über den **USB TO UART**-Anschluss mit Datenkabel anschließen; Umschalter auf **UART1**. Andere serielle Programme schließen.
5. `Flash-Waveshare-Windows.cmd` doppelklicken. Es öffnet sich ein lokaler Web-Flasher unter `http://127.0.0.1` (zufälliger Port). Dieses Terminal offen lassen.
6. Im automatisch geöffneten **Chrome/Edge** den Web-Flashknopf anklicken, den Waveshare-COM-Port auswählen und Flashvorgang bestätigen.
7. Bei Erfolg **RESET** am Waveshare drücken. Oberfläche und Touch prüfen.

Der Browser darf auf `localhost` den Web-Serial-Zugriff erfragen – auf beliebige HTTP-LAN-Adressen jedoch nicht. Der Windows-Flasher lauscht ausschließlich auf `127.0.0.1` und kennt keine Unraid-Zugangsdaten. Das Web-Flashmodul wird beim Start von `unpkg.com` geladen; dafür wird eine Internetverbindung benötigt.

**Mit vertrauenswürdigem HTTPS** am Build Lab: Nach Build-Erfolg **Jetzt per PC-USB flashen** wählen; der Installer erscheint unterhalb der Build-Liste. Hier wird kein ZIP/Python benötigt. Ohne HTTPS ist dieser Knopf technisch nicht verfügbar (Browser-Sicherheitsregel).

## Sicherheit und Status

- Firmware/Flashpaket automatisiert erstellt und auf Konsistenz geprüft, **nicht an echter Hardware verifiziert**. Kein freigegebener Laserbetrieb.
- Laser vor allen ersten Flash-/Anlauftests **physisch stromlos und TTL getrennt** lassen.
- Der Browser wählt per Nachfrage einen USB-COM-Port des PCs; der Unraid-Container bekommt **keine USB-Geräte, keinen Docker-Socket und keine Flash-Fernzugriffe**.
- Flash nur für Waveshare **ESP32-S3-Touch-LCD-7 Rev1.2**, niemals das SKR-MZ-Board mit dem ESP-Image beschreiben.
- Verbindungs-/USB-Probleme: Datenkabel, UART1-Position, Chrome/Edge, COM-Port, andere Terminalprogramme und ggf. BOOT-Taste prüfen.
- Authentifizierung: HTTP Basic. LAN/VPN verwenden, nicht ins Internet freigeben; für externen Zugriff HTTPS/TLS.

## Update des bereits installierten Unraid-Containers

Die GitHub-Quellen werden bei Build-Jobs aktualisiert, aber **nicht die laufende Weboberfläche im Docker-Image**. Daher für Änderungen am Build Lab das Docker-Image neu installieren. Der Installer erhält vorhandenes Passwort und Buildarchive:

```bash
TMP_DIR="$(mktemp -d)"
curl -fL --retry 3 -o "$TMP_DIR/lumacut-main.tar.gz" \
  https://github.com/theubyte/LumaCut-CNC/archive/refs/heads/main.tar.gz &&
tar -xzf "$TMP_DIR/lumacut-main.tar.gz" -C "$TMP_DIR" &&
bash "$TMP_DIR/LumaCut-CNC-main/setup/unraid-install.sh"
```

Nur wenn das Repository öffentlich abrufbar ist; andernfalls die aktualisierten Dateien mit bestehender GitHub-Berechtigung beziehen. Danach Build Lab wie gewohnt auf Port 18744 öffnen, Login bleibt `lumacut`. Unraid SSH-Verbindung nicht beenden; der Installer tauscht nur den Docker-Container aus.
