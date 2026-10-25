> **PINBELEGUNG GEÄNDERT (25.10.2026):** Experimenteller neuer Build: FAN1/PC7 = Laserleistung, PA1 = PWM, BED/PC9 = Abluft M8, HE0/PC8 = Licht M7, FAN0/PC6 = Service-Zusatzausgang. Alte BED-Laser-/FAN0-Abluft-Anleitungen gelten für den neuen Build **nicht**. Eine direkte PWM-Verbindung zu einem auf FAN1− geschalteten Laser ist elektrisch nicht freigegeben. Siehe [FAN1-LASER Integration](docs/FAN1_LASER_PI400_RELEASE.md). Automatischer SKR-Flash über USB fehlt weiterhin.\n\n# LumaCut CNC · Raspberry Pi 400 Control Studio

**Aktive Architektur (Oktober 2026): Raspberry Pi 400 ohne Display
als zentraler Webserver und LightBurn-GRBL-Gateway.**

```text
Handy / PC  ───────┐
                   ├── Pi 400 Control Studio (HTTP 8080)
LightBurn (GRBL) ──┘   TCP 23 → USB serial → grblHAL SKR Mini MZ V1.0
                                           ├─ XYZ + Z20 pre-XY homing
                                           ├─ PA1 Laser-PWM
                                           ├─ BED PC9 Laser-24V-Schalter
                                           ├─ HE0 PC8 24V-LEDs (M7)
                                           ├─ FAN0 PC6 24V-Abluft (M8)
                                           └─ FAN1 PC7 konfigurierbarer Ausgang ($LCIO)
Pi 400 Camera ────> Control Studio (JPEG snapshot)
```

Das Waveshare-ESP32-S3-HMI wird **nicht mehr benötigt**. Seine
Quellcode-Historie bleibt als Archiv unter `firmware/hmi` erhalten.
Keine doppelte LightBurn-USB-/UART-Gateway-Verbindung mehr.

## Control OS Service Studio

In dieser Entwicklungsfassung kann der Raspberry Pi 400 über
`http://lumacut.local:8080/service` als zentrale Bedien- und
Konfigurationsinstanz betrieben werden. Separate Service-Anmeldung
(Erstpasswort `lumaservice`, lokal gehasht, 10-minütige Sitzung),
echte SKR-Diagnose, GRBL-Konfigurationskonsole und konfliktgeprüfte
logische M7/M8-Zubehörbelegung sowie der dedizierte PC7/FAN1-Ausgang mit $LCIO-Zustandsrückmeldung sind implementiert.

**Das ist noch keine vollständige, dynamische physische STM32-Pinbelegung.**
Die Echtzeitsteuerung läuft weiterhin im grblHAL-Build des SKR.
Hardwaretest, unabhängige Laser-Interlocks und automatisches SKR-Flashing
sind nicht abgeschlossen. Status und offene Schritte:
[Pi400 Control OS 2](docs/PI400_CONTROL_OS_2.md).

## Installation Raspberry Pi 400

**[Komplette Pi400-Einrichtung, Netzwerk, LightBurn und Updates](docs/PI400_CONTROL_STUDIO.md)**.

Mit Raspberry Pi OS Lite 64-Bit und Repository-Zugriff:

```bash
git clone --branch main https://github.com/theubyte/LumaCut-CNC.git
cd LumaCut-CNC
sudo bash pi400/install.sh
```

Danach im LAN `http://lumacut.local:8080` (HMI-Code vom
Installationsskript eingeben). In LightBurn manuell **GRBL → Network**
mit Pi-IP/`lumacut.local`, **Port 23**, einrichten. LightBurn Bridge
im offiziellen Sinne ist ausschließlich für Ruida und deshalb hier
kein Teil der Installation.

**Achtung:** Der SKR muss die native USB-grblHAL-Firmware
`lumacut_skr_mz_usb` erhalten, nicht die frühere
`lumacut_skr_mz_hmi_uart`-Version. Falls der STM32 nur UART-GrblHAL
hat, findet der Pi noch keinen GRBL-USB-Port.

**Automatische Pi-Softwareupdates:** `pi400/update.sh` mit
`lumacut-update.timer`. Das öffentliche Repository kann per HTTPS
aktualisiert werden. Read-only SSH-Deploy-Keys sind nur bei privaten Repositories erforderlich.

**Automatisches SKR-Firmwareflashen ist USB-only noch nicht
hardwareverifiziert**. Neue Firmware-Binaries werden vom Buildserver
als Paket geliefert; Installation via vorhandenem SD-/SWD-Bootloader,
bis ein geeigneter Programmierweg nachgewiesen ist.

## Builds und Tests

- GitHub CI: [Pi 400 + SKR USB](https://github.com/theubyte/LumaCut-CNC/actions/workflows/ci.yml)
- Unraid-Compiler: `https://luma.millione.de/`, Hauptoption
  **Pi 400 + SKR USB**, erstellt LumaCut-Pi400-SKR-USB.zip.
- SKR-Build: `python firmware/skr/build.py`.
- Webserver: `python -m lumacut.app` mit
  `PYTHONPATH=pi400` und `LUMACUT_KEY` Umgebungsvariablen.
- Tests: `python -m unittest discover -s tests -v`.

## Bedienumfang

Responsive Webinterface mit Maschinenstatus, GRBL-Einstellungen,
X/Y/Z-Jog, Homing, G-Code-Dateien, Parkplätzen, Fokus, offset-korrektem
Werkstückraster (noch keine gemessene Höhenkarte), LEDs/Abluft,
Router-WLAN-Auswahl, Kamera-Schnappschuss, LightBurn-Verbindung und
Verbindungs-/Spamdiagnose. GRBL-Echtzeit-Status für die Webanzeige
bleibt vom LightBurn-TCP-Stream getrennt. Der Pi leitet LightBurn
`ok`, `error`, `ALARM`, `$`, `$I` und hosteigene
`?`-Antworten zuverlässig weiter. Kritische Einstellungen sowie
`$LCIO`/freie digitale I/O-Befehle sind über den ungeschützten
LightBurn-TCP-Kanal gesperrt und nur über die Service-Schnittstelle zulässig.
Die Pi-Oberfläche enthält außerdem einen G-Code-Geometrieanalysator
mit Kreisbogen- und Auftragsvorschau.

**Hardware-Status:** Software-Builds ersetzen keine Inbetriebnahme
am realen Pi/SKR. Laserleistung für Ersttests physisch abschalten.
Die externe Not-Aus-/Gehäuse-Schutzkette darf nicht durch die
Websteuerung ersetzt werden.

Alte Waveshare-Dokumentation: `docs/LUMACUT_CONTROL_OS.md`.
24V-Laser/BED-Verdrahtung: `docs/24V_AUSGAENGE_LASER_LED_ABLUFT.md`.
