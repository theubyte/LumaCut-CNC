# LumaCut Build Lab V2 – Firmware bauen, archivieren und installieren

## Neue Bedienoberfläche (Dashboard V2)

Die Benutzeroberfläche auf Port **18744** hat fünf Primäraktionen:
1. **Build komplett**: GitHub-Commit einmal abrufen, SKR-grblHAL und Waveshare HMI daraus bauen, ein gepaartes ZIP mit Firmware/Prüfsummen ausgeben.
2. **Build HMI**: Waveshare ESP32-S3 Control OS bauen, Komplett-BIN und Windows-Flashpaket erzeugen.
3. **Build Laser grblHAL**: passendes SKR Mini MZ UART-Firmwareprofil bauen.
4. **HMI flashen**: letzten erfolgreichen HMI-Build wählen; Flash per Web Serial unter HTTPS/localhost oder Windows-Flashpaket unter normalem LAN-HTTP.
5. **grblHAL auf SD-Karte**: die SKR-Firmware eines abgeschlossenen Builds als **firmware.bin** herunterladen. Ein unterstützender HTTPS-Browser kann sie direkt in einen ausgewählten microSD-Ordner schreiben; bei HTTP greift der reguläre Browser-Download.

Der Build-Fortschritt wird anhand tatsächlicher Stufen und PlatformIO-Compiler-Ausgaben abgeleitet; Prozente und Restzeit sind **Schätzwerte**, keine exakten Messungen. Historische erfolgreiche Laufzeiten der gleichen Buildvariante fließen in die ETA ein. Während des Builds aktualisiert sich die Webseite etwa alle 2,2 Sekunden. Abschluss oder Fehler öffnen einen Dialog mit explizitem **X** sowie ZIP-, Log-, Flash- und SD-Folgeaktionen.

Im Archiv können Builds durchsucht und nach Status gefiltert werden. Für jeden Build gibt es Manifest, SHA256-Prüfsummen, Artefakte und gespeichertes Buildlog. Die **Terminalansicht** zeigt die echte Prozessausgabe; ihre Eingabe unterstützt bewusst nur Diagnosebefehle (`help`, `status`, `jobs`, `log`, `files`, `manifest`, `source`, `refresh`, `clear`). **Kein frei ausführbarer Shell-Zugang im Browser**: Host- und Container-Befehle laufen über NextTerm/SSH, damit das Build Lab keinen Remote-Code-Ausführungskanal bietet.

**Sicherheits- und Hardwaregrenze:** Eine auf microSD gespeicherte `firmware.bin` aktualisiert das SKR erst, wenn ein mit dem Board kompatibler Bootloader den Dateiablauf tatsächlich unterstützt. Ein erfolgreicher Build beweist weder sichere Achsrichtungen noch Laserschutz. Flashen am Waveshare erfolgt vom PC aus, nicht vom Unraid-Docker-Container.



Unraid Docker mit Flask, PlatformIO und esptool; Web-Port **18744** (Container 8080).
Quellen werden für jeden Job aus GitHub geholt. Der Deploy-Key wird ausschließlich
für GitHub-Lesezugriff verwendet; Passwort und Schlüssel bleiben im Unraid Appdata.

## Builds

- **Projekt-Tests:** Unit-Tests, Kompilierprüfung.
- **SKR Mini MZ:** experimentelles STM32/grblHAL-Image. Kein Flash durch den Builder.
- **Waveshare HMI – nur Touch:** Profil `lumacut_waveshare_s3`; zunächst dieses flashen.
- **Waveshare HMI – UART-Jog:** Profil `lumacut_waveshare_s3_keypad`; nur nach erfolgreicher separater Motor-/Endschalterprüfung und bei stromlosem Laser.
- **LumaCut Control OS:** Profil `lumacut_waveshare_s3_pro`, neue grafische Oberfläche, USB-C CDC, WLAN-GRBL/TCP, Handy-Jobportal, BLE-Status und gespeicherte Parkmakros. **Erfordert passende SKR-UART-Firmware!**
- **SKR UART für Control OS:** Profil `lumacut_skr_mz_hmi_uart` aus `python firmware/skr/build.py --bridge`; USART1 als grblHAL-Hauptverbindung zum Waveshare, nicht das alte Keypad-Protokoll.
- **Komplettes LumaCut Control OS (HMI + SKR)**: Ein-Klick-Build beider Profile mit gemeinsamer Quellcode-Version, vollständigem Flash-Paket und Prüfsummen.

Bei HMI-Erfolg erzeugt das Build Lab außer der normalen Entwicklungs-Firmware:
1. `LUMACUT_HMI_ESP32S3_MERGED.bin`: vollständiges 16-MB-kompatibles ESP32-S3-Flashabbild aus Bootloader, Partitionstabelle, OTA-Bootstub und Anwendung (Startadresse 0), mit Prüfsumme.
2. `Waveshare-HMI-Flash-Paket-Windows.zip`: Firmware, Manifest und localhost-Flasher.
3. Ein Web-Flash-Manifest, das zu genau diesem Build gehört.

## Komplettpaket auf einmal erstellen

Im Build Lab **„Komplettes LumaCut Control OS bauen (HMI + SKR)“** anklicken. Wenn der Status erfolgreich ist, erscheint **„Gesamtsystem-ZIP herunterladen“**. Das ZIP enthält `SKR-Mini-MZ/firmware.bin`, `Waveshare/Waveshare-HMI-Flash-Paket-Windows.zip`, das gesamte ESP32-S3-Image und die Dokumentation. Beide Images werden aus exakt demselben Git-Commit gebaut. Das SKR wird dabei **nicht** automatisch geflasht.

Alternativ ist dasselbe Firmwarepaar nach erfolgreicher Pipeline unter GitHub Actions als Artifact `LUMACUT-KOMPLETT-<Git-SHA>` erhältlich.

## Flashen, wenn Waveshare am Windows-PC steckt

**Ohne HTTPS**, also beim Standard-Zugriff `http://UNRAID-IP:18744`:

1. Build **LumaCut Control OS (USB/WLAN/Jobs)** starten und auf Status `success` warten. Das ältere Nur-Touch-Profil bleibt als sicheres erstes Display-Diagnoseprofil verfügbar.
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

## Build Lab aktualisieren – NextTerm auf Unraid (privates GitHub-Repo)

Da das GitHub-Repository privat ist, funktioniert der alte öffentliche tar.gz-Download nicht zuverlässig. Verwende stattdessen den vorhandenen, ausschließlich lesenden Deploy-Key auf Unraid:

```bash
bash <<'LUMACUT_UPDATE'
set -Eeuo pipefail
STATE=/mnt/user/appdata/lumacut-builder
test -f "$STATE/secrets/deploy_key" || { echo "GitHub Deploy-Key fehlt."; exit 1; }
test -f "$STATE/secrets/known_hosts" || { echo "GitHub known_hosts fehlt."; exit 1; }
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
export GIT_SSH_COMMAND="ssh -i $STATE/secrets/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$STATE/secrets/known_hosts"
git clone --depth 1 --branch main git@github.com:theubyte/LumaCut-CNC.git "$TEMP/repo"
python3 -m py_compile "$TEMP/repo/builder/app.py"
if command -v node >/dev/null 2>&1; then
  node --check "$TEMP/repo/builder/dashboard.js"
fi
bash "$TEMP/repo/setup/unraid-install.sh"
docker ps --filter 'name=^/lumacut-builder$'
echo "Build Lab: http://DEINE-UNRAID-IP:18744"
LUMACUT_UPDATE
```

Der Installer ersetzt das Docker-Image einschließlich HTML/CSS/JS, nicht nur die Firmwarequelle. Die Daten unter `/mnt/user/appdata/lumacut-builder/data`, bestehende Buildarchive, das Passwort und der Deploy-Key bleiben erhalten. **Nicht während eines aktiven Builds aktualisieren:** Ein laufender Build wird beim Containerersatz abgebrochen.

## Gekoppelte SKR-Firmware und LightBurn

Das **neue** Control OS benötigt ebenfalls ein Board-Update: Im Build Lab **SKR UART für Control OS bauen** auswählen und dessen SKR-`firmware.bin` **nur nach Bootloader-, Anschluss-, Pin- und Sicherheitsprüfung** über microSD auf das SKR Mini MZ schreiben. Die normale SKR-USB-/Keypad-Firmware ist kein kompatibler Datenpartner.

Im Normalbetrieb Waveshare auf **UART2**: Waveshare GPIO43 TX → SKR PA10 RX, Waveshare GPIO44 RX ← SKR PA9 TX, GND ↔ GND. Verbindung ist 3,3 V TTL. Der LightBurn-PC wird am **nativen USB-Type-C** des Waveshare angeschlossen, nicht am Schalter-geteilten USB TO UART. Oder LightBurn per WLAN/TCP zur HMI-IP, Port 23. Das Gerät baut außerdem einen WPA2-Hotspot und ein Handy-Webportal auf; Login-Daten werden am Display unter System gezeigt.

Technische Details, Schutzmaßnahmen und bisher nicht freigegebene Laserfunktionen: [LumaCut Control OS](../docs/LUMACUT_CONTROL_OS.md).
