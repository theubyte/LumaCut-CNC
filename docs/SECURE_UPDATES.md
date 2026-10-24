# LumaCut Secure Updates – Stand 24.10.2026

## Architektur

Quelle ist weiterhin GitHub `main`. Der Unraid-Compiler klont bei jedem
Build `GIT_BRANCH=main`, erstellt das HMI-Profil
`lumacut_waveshare_s3_pro` und die dazugehörige UART-SKR-Firmware, archiviert
beide Dateien und deren SHA256-Prüfsummen. Ein Build allein ist keine
Freigabe. Über den Login geschützten Knopf `Als Update freigeben` kann ein
validiertes **gepaartes** Build veröffentlicht werden.

`GET /api/updates/latest` veröffentlicht ein kleines JSON-Manifest
mit Version, Boardtypen, Dateigrößen und SHA256; der Binärdownload
`GET /api/updates/file/hmi` ist nur über `X-LumaCut-Device-Key`
zugänglich. HMI-TLS pinnt den CA-Root aus `update_ca.h`; der
Firmwaredownload akzeptiert keine URL aus dem Manifest und keine Redirects.

## HMI OTA (Code vorhanden, echter Hardwaretest ausstehend)

- HMI mit dem aktualisierten Build **einmal per USB flashen**. Erst diese
  Version kennt den neuen OTA-Installer.
- In Unraid `/mnt/user/appdata/lumacut-builder/.env` den bestehenden
  geheimen `UPDATE_DEVICE_KEY` ermitteln. **Nie nach GitHub committen.**
- Auf dem HMI unter **WLAN/System** den Schlüssel über das maskierte
  Eingabefeld eintragen und **Key sichern** tippen. Er muss 64
  kleine Hex-Zeichen besitzen und verbleibt im ESP32-NVS (ohne garantierte
  Flashverschlüsselung).
- Für explizit freigegebene vollständige Builds ist der HMI-OTA-Installer
  ohne zusätzliche serverseitige Freigabevariable verfügbar. Das HMI schreibt
  nur nach bewusster Bestätigung und erfüllten lokalen Voraussetzungen in
  eine zweite OTA-Partition.
- Danach einen **neuen vollständigen gepaarten Build** im Compiler
  erstellen und explizit **Als Update freigeben**.
- HMI im Idle prüfen: **Pruefen** lädt den HTTPS-Status. Die Installation
  verlangt zwei separate Berührungen binnen 15 Sekunden. Der Laser muss
  **physisch stromlos** sein; Software-M5 ersetzt keinen Interlock.
- Die Anwendung lädt *nur* `HMI_OTA_APP_UNVERIFIED.bin` herunter,
  schreibt nur den inaktiven OTA-Slot, kontrolliert Bytezahl und vollständige
  SHA256-Summe **vor** `Update.end()`, und startet erst bei Erfolg neu.
- Ein erneuter Bootfehler oder eine LCD-Initialisierungsstörung versucht
  die vorherige OTA-Partition zu reaktivieren. Dies ist **kein** Ersatz
  für den physischen USB-Recoveryweg, besonders wenn die Anwendung gar nicht
  bis `prefs.begin()` startet. Bootloader-Rollback muss zusätzlich
  nachweislich aktiv sein, ehe ein unbeaufsichtigtes Update erlaubt wird.

**Keine unbeaufsichtigte Installation** beim periodischen Updatecheck:
Der Operator löst HMI-OTA im Systemmenü ausdrücklich aus. Zwei installierbare
ESP32-Partitionen, gültiger Geräteschlüssel und Leerlauf werden technisch
überprüft. Der physische USB-Recoveryweg bleibt unabhängig davon notwendig.
Stromausfall- und Wiederherstellungsverhalten müssen noch real getestet werden.

## SKR-Firmware – physische Grenze

Das SKR Mini MZ V1.0 nutzt STM32F103RC. Der SKR-UART ist über
PA9/PA10 mit dem Waveshare verbunden. Für eine *sichere* autonome
Erstinstallation oder ein Recovery der grblHAL-Firmware muss zuvor
der tatsächliche Bootloaderpfad nachgewiesen werden (z.B. ROM USART1 mit
BOOT0/NRST schaltbar oder ein kontrollierter eigener Bootloader).

Die SKR-Firmware wird mit jedem freigegebenen gepaarten Release als
`firmware.bin` im Compiler bereitgestellt. Der Benutzer kann sie aus dem
Freigabedialog herunterladen und auf eine microSD für **den SKR-eigenen**
Bootloader übertragen. Der SKR Mini MZ V1.0 unterstützt den microSD-
Bootloaderweg mit 28-KiB-Firmware-Offset; der tatsächliche installierte
Bootloader und das Updateverhalten müssen am konkreten Board geprüft werden.

Das HMI meldet `skr_firmware_available` anhand der geprüften
Release-Metadaten statt eines fest codierten `skr_ota_ready:false`.
Das ist **keine automatische Übertragung auf den STM32**: Die vorhandene
PA9/PA10-Verbindung versetzt das SKR nicht selbsttätig in den ROM-Bootloader;
die grblHAL-Anwendung enthält derzeit keinen Netzwerk-/UART-Self-Flasher.
Für eine automatische Installation durch das HMI muss ein wirksamer
SKR-Bootloaderübergang inklusive Recovery umgesetzt werden.

Eine **optionale 4-GB-microSD** (FAT32) ist nun in der HMI-Quelle integriert:
SPI GPIO11/12/13 mit SD_CS über CH422G EXIO4 (nach touchInit). Wenn die
Karte eingebunden wird, verwendet der HMI-Job-Manager sie für alle
`/jobs`-Dateien und kopiert vorhandene LittleFS-Jobs beim ersten Start
unter Beibehaltung der Originale, ohne SD-Dateien zu überschreiben.
`/updates`, `/backups` und `/logs` werden angelegt; die Datei
`/logs/hmi_boot.log` protokolliert Firmware-Version und Resetgrund.
Ohne Karte bzw. bei Einbindefehler bleibt LittleFS aktiv. Die SD-Treiber-
und Kopierfunktion muss noch am echten Waveshare überprüft werden. Die SD-Karte
ersetzt aber **weder BOOT0/NRST noch einen Bootloader**. Der derzeitige
HMI-OTA-Schreibpfad benötigt die Karte nicht und nutzt die zwei
ESP32-internen OTA-Anwendungspartitionen.

## Zugangsdaten des Compilers

Loginname ist im Python-Server fest `lumacut` und Passwort kommt nur
aus `BUILDER_PASSWORD` in `.env`. Die Unraid-Installerdatei erstellt
ein Passwort nur, wenn `.env` noch fehlt; die existierende Datei
wird bei jedem Upgrade wieder verwendet. **Das Wunschpasswort gehört
ausschließlich auf den Unraid-Host; niemals in den öffentlichen GitHub-Code,
ein Dockerfile, HTML oder Buildartefakt.** Passwortänderungen werden erst
nach dem Neuaufsetzen des Containers mit aktualisiertem `--env-file`
wirksam.

## Akzeptanznachweise

- [x] GitHub-Quellen, CI, gepaartes Build und Prüfsummen
- [x] HMI-OTA-Datenpfad (Source), HTTPS und Boot-Slot-Beschränkung
- [x] HMI-Key-Eingabe und doppelte Installationsbestätigung
- [ ] HMI A/B, Recovery und Stromausfalltest **auf echter Hardware**
- [ ] Reverse Proxy/TLS und Downloadrouten vom echten Gerät
- [ ] SKR-ROM-Bootloader, BOOT0-/Reset-Leitungen und SWD-Rettungsweg
- [ ] Sicherer Board-Flasher mit verifiziertem Readback und Rollback
- [x] Optionaler FAT32-microSD-Treiber, Ordner und LittleFS-Fallback (Quellcode)
- [ ] microSD-Lese-/Schreibtest und Verhalten bei Kartenverlust am Waveshare
- [ ] Automatische gekoppelte Gesamtinstallation nach Freigabe
