> **PINBELEGUNG GEÄNDERT (25.10.2026):** Experimenteller neuer Build: FAN1/PC7 = Laserleistung, PA1 = PWM, BED/PC9 = Abluft M8, HE0/PC8 = Licht M7, FAN0/PC6 = Service-Zusatzausgang. Alte BED-Laser-/FAN0-Abluft-Anleitungen gelten für den neuen Build **nicht**. Eine direkte PWM-Verbindung zu einem auf FAN1− geschalteten Laser ist elektrisch nicht freigegeben. Siehe [FAN1-LASER Integration](FAN1_LASER_PI400_RELEASE.md). Automatischer SKR-Flash über USB fehlt weiterhin.\n\n# LumaCut CNC – Raspberry Pi 400 Control Studio

Stand: 24.10.2026. **Neue Hauptarchitektur:** Raspberry Pi 400
(Webinterface + LightBurn Netzwerk-Gateway + Kamera + Updates) per USB
zum BTT SKR Mini MZ V1.0 (STM32F103RC/grblHAL). Das bisherige
Waveshare ESP32-S3 ist **nicht mehr Teil der aktiven Maschine**. Das SKR
hat weiterhin allein die Echtzeitkontrolle über die Achsen, Z-Homing,
PA1-Laser-PWM, BED/PC9 Laser-24V, HE0/PC8 LEDs und FAN0/PC6 Abluft.

## 1. Hardware & Betriebssystem

- Raspberry Pi 400, Netzteil mit stabiler 5,1-V-Versorgung, geeignete
  microSD (empfohlen mindestens 32 GB) oder USB-SSD.
- **Raspberry Pi OS Lite 64-bit**, mit SSH, bevorzugt Ethernet
  für die Erstinstallation. Danach WLAN über das Webinterface.
- USB-A-Port des Pi → geeignetes **Daten-USB-Kabel** →
  USB-Device-Anschluss des SKR. Das SKR wird separat mit 24 V versorgt.
- SKR muss die zum Pi passende **grblHAL-USB-Firmware**
  (`lumacut_skr_mz_usb`) erhalten. Die alte
  `lumacut_skr_mz_hmi_uart`-Firmware ist **nicht** das passende
  Image für die direkte Pi↔SKR-USB-Verbindung. Ein verbundenes USB-Kabel
  macht ein UART-only-Binary nicht automatisch zu einem USB-Controller.
- **Nicht** die offizielle LightBurn Bridge installieren: LightBurn
  Bridge unterstützt *Ruida*, nicht GRBL. Unser Pi-Dienst bietet einen
  eigenen echten GRBL-TCP-Datenkanal auf Port 23.

## 2. Erstinstallation

Das Repository ist aktuell öffentlich; HTTPS reicht für das Setup.
Auf dem Pi (SSH/Terminal):

```bash
sudo apt-get update
sudo apt-get install -y git
git clone --branch main https://github.com/theubyte/LumaCut-CNC.git
cd LumaCut-CNC
sudo bash pi400/install.sh
```

Das Installationsskript erstellt einen getrennten Systembenutzer,
seinen Datenordner, ein nur beim ersten Mal generiertes API-Token und
Systemdienste. Der Zugangscode wird **einmalig auf dem Terminal**
angezeigt. Er liegt danach in `/etc/lumacut/lumacut.env` (root-only).

Danach:

- Web: **http://lumacut.local:8080** oder
  **http://<Pi-IP>:8080**, Zugangscode unter **System** eingeben.
- LightBurn: **Gerät GRBL → Netzwerk**, Pi-IP/Hostname,
  **TCP-Port 23**.
- Skr prüfen: `ls -l /dev/serial/by-id/`; falls erforderlich,
  `LUMACUT_SKR` in `/etc/lumacut/lumacut.env` setzen, danach
  `sudo systemctl restart lumacut`.
- Logs: `sudo journalctl -u lumacut -f`.

Das Control Studio ist nur im **vertrauenswürdigen LAN** zu betreiben;
die direkte GRBL-TCP-Verbindung Port 23 bietet keine eigene Anmeldung.
Router-Portfreigaben für 23/8080 dürfen nicht eingerichtet werden.

## 3. LightBurn: kein Konsolen-Spam

Die alte ESP32-Firmware hat periodische interne `?`-Statusmeldungen
unaufgefordert an LightBurn durchgereicht. Der Pi hat jetzt **nur
einen** Leser der GRBL-USB-Schnittstelle:

- Realtime `?` des Pi → SKR → **nur interne Web-Telemetrie**.
- Realtime `?` von LightBurn → SKR →
  **eine entsprechende** Statusantwort zu LightBurn.
- `ok`, `error:…`, `ALARM:…`, `$$` und `$I` werden
  unverändert als GRBL-Protokoll weitergereicht, auch im
  gepufferten LightBurn-Modus.
- TCP23 und Web-Jobs besitzen den SKR **exklusiv**; keine
  gleichzeitigen unabhängigen G-Code-Streams.
- Verbindungseinbruch während eines Jobs: der Pi fordert GRBL
  Feed-Hold an. Das ersetzt keinen hardwareseitigen Not-Aus.
- `$30` (S-Max), `$130`/ `$131` (Arbeitsfläche) werden nach
  `$$` live in Weboberfläche und herunterladbares
  LightBurn-Geräteprofil übernommen.

LightBurn bekommt die echte Firmware-Antwort aus `$I`/ `$$`,
statt einer erfundenen Maschinenkennung. Viele Geräteeinstellungen
(wie physischer Nullpunkt, Motorströme oder optischer Fokus) können
von LightBurn **nicht automatisch** durch GRBL ermittelt werden;
diese bleiben maschinenseitige Einstellungen bzw. Geräteprofilfelder.

## 4. Bedienoberfläche ohne Display

Das mobile Control Studio basiert auf der bisherigen dunklen
LumaCut-Oberfläche und bietet:

- Übersicht mit GRBL-Livezustand, X/Y/Z, ausgewähltem Job;
- Jog X/Y/Z über die tatsächlich vom SKR gemeldeten Maximalwerte,
  Homing, Parkpositionen, Motorsteuerung;
- `$$`-Parameter als Wertetabelle, Änderung und Rücklesung;
- G-Code-Dateien vom Handy/PC hochladen, auswählen, ausführen,
  pausieren und abbrechen;
- Fokuswerte und offset-korrekte XY-Werkstückrasterdatei
  (keine gefälschte Z-Höhenkarte);
- Wi-Fi-Router-Suche/Verbindung über NetworkManager;
- optional USB-Webcam (UVC) über `/dev/video0` und ffmpeg
  (Schnappschuss / automatische Vorschau). Der Pi 400 hat keinen CSI-Kameraanschluss;
- USB- und LightBurn-Diagnose: intern verworfene Statusberichte,
  Bytes, Fehlerzähler;
- LED/Abluft über grblHAL-Coolant-Realtime-Overrides;
- Service Studio mit kritischer Rechteverwaltung und PC7/FAN1-Ausgang;
- Pi-seitige G-Code-SVG-Geometrievorschau und automatische Z-Freifahrt.
  
**Taster-Höhenkarte:** Der gemeinsame Z-Endschalter PC2 ist
ohne nachgewiesenen separaten G38-Probeeinstieg kein sicherer
mehrpunktiger Messtaster. Geplant ist erst eine korrekte
Taster-Signalquelle und danach der automatische Messlauf.

## 5. Automatische Updates

`lumacut-update.timer` prüft täglich das öffentliche GitHub
`main` auf einen Fast-Forward-Commit. Der Updater:

1. prüft, dass kein LightBurn-/Web-/Dateijob läuft;
2. sperrt neue Maschinenkommandos über ein
   Maintenance-Lockfile;
3. holt nur bestätigte Änderungen aus GitHub;
4. aktualisiert den Pi-Dienst, validiert den Python-Quellcode,
   startet den Dienst und setzt ihn bei Startfehler zurück.

Das öffentliche Repository ist ohne Deploy-Key über HTTPS lesbar.
Bei einem späteren Wechsel auf ein privates Repo kann der separate
read-only GitHub-Schlüssel über `pi400/setup-update-key.sh`
eingerichtet werden.

**SKR-Firmwareupdates sind mit alleiniger USB-Seriellverbindung
nicht automatisch flashbar, solange kein bekannter und geprüfter
USB-DFU-/Bootloader-Einstieg existiert.** Das bisherige MZ-Build
verwendet einen **28-KiB-Bootloader-Offset**. Die
erste Umstellung von UART-grblHAL auf USB-grblHAL erfordert eine
SKR-Firmwareinstallation über den vorhandenen Bootloader
(`firmware.bin` auf FAT32-SD, sofern vom Board unterstützt)
oder über ein nachgewiesenes SWD/ST-Link-Programmiergerät.

Ein späterer automatischer Flashweg ist möglich, sobald zusätzliche
Flash-Hardware, Bootloaderzugriff, Flash-Layout, Prüfsumme und
Rollback-Verfahren auf deinem SKR verifiziert wurden.
**Pi-Code-Updates laufen bereits autonom, SKR-USB-Autoflash
ist ausdrücklich noch nicht implementiert.**

## 6. Test und Freigabe

Die GitHub-CI baut nun SKR **USB** und Pi-Webserver; sie
erstellt ein `LumaCut-Pi400-SKR-USB.zip` mit Startskripten
und einer GRBL-USB-Firmware. Ein grüner Build prüft Quellcode,
nicht die reale USB-Pegel-/Taster-/Laserinstallation.

Für den ersten Test Laserenergie und PWM elektrisch trennen,
USB-Port und `$$` prüfen, die SKR-Echtzeitmeldungen mit
Web-Diagnose und LightBurn vergleichen und zuerst eine
laserlose Konturfahrt ausführen. Hardwareseitige Not-Aus-,
Türinterlock- und Lasersicherheitsfunktionen bleiben wirksam.
