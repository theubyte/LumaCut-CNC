# LumaCut Control OS – USB, WLAN, BLE und Touch

**Stand: 21. Oktober 2026. Noch nicht an echter Laserhardware geprüft; keine Freigabe für produktiven Laserbetrieb.**

## Hardware und Datenweg

LightBurn PC (USB-C CDC oder WLAN/TCP) → Waveshare ESP32-S3-Touch-LCD-7 Rev1.2 → 3,3-V-UART2 → SKR Mini MZ V1.0.
Handy (WLAN) → integriertes HMI-Webportal → Waveshare → derselbe SKR-Maschinencontroller.

**Verkabelung:** Waveshare UART2 GPIO43 TX auf SKR USART1 PA10 RX; Waveshare GPIO44 RX auf SKR PA9 TX; GND mit GND verbinden. Der Waveshare-DIP-Schalter muss auf UART2 stehen. Vor Anschluss anhand beider Schaltpläne physische Steckplatzbelegung prüfen. Kein 5-V-TTL, keine RS485-Leitungen.

Die Waveshare-Buchse USB TO UART verwendet dieselben Pins GPIO43/44 und ist im UART2-Betrieb **nicht** als LightBurn-PC-Anschluss nutzbar. Für den PC den separaten nativen Type-C-USB-Anschluss des ESP32-S3 verwenden; der CH422G-USB/CAN-Multiplexer wird durch die Firmware auf USB gestellt. Firmware-Flash über den USB-TO-UART-Anschluss bei Switch auf UART1, anschließend zurück auf UART2.

## Gekoppelte Firmwareprofile

- Waveshare: `lumacut_waveshare_s3_pro` – grafische HMI, Wi-Fi, natives USB-CDC, BLE-Lesestatus, Job-Portal und Makros.
- SKR: `lumacut_skr_mz_hmi_uart` – `python firmware/skr/build.py --bridge`; grblHAL USART1 PA9/PA10 als **Hauptstream**. SKR-USB braucht keinen PC-Anschluss.
- Die bisherige SKR-USB-Firmware `lumacut_skr_mz_usb` und die alte HMI-Keypad-Firmware **nicht** mit dem Pro-HMI mischen: ihre Protokolle sind unterschiedlich.
- Beide Ziele im Unraid Build Lab mit den neuen Tasten „SKR UART für Control OS“ und „LumaCut Control OS“ erstellen. Im Windows-Flashpaket das Waveshare per Browser am USB flashen. SKR nach gesonderter Bootloader-/Pinprüfung per FAT32-microSD aktualisieren.

## Bedienoberfläche

Unteres Dock: **Home · Jobs · Steuerung · Makros · System**. Heller Hintergrund, weiße abgerundete Karten, blauer Primärakzent, große Schaltflächen. Home zeigt Zustand, X/Y/Z-Maschinenkoordinaten, aktuelle Steuerquelle, Start/Pause/Abbruch und Park.

### LightBurn USB

Den nativen ESP32-S3-USB-Port mit dem PC verbinden (nicht USB TO UART). In LightBurn GRBL per COM-Port/CDC einstellen. USB CDC und Wi-Fi-TCP führen Bytes samt GRBL-Rückmeldungen zum selben SKR weiter.

### LightBurn WLAN

Im HMI unter System SSID/Passwort des 2,4-GHz-Heimnetzes eingeben. In LightBurn manuell GRBL-Gerät mit Verbindung „Ethernet or Wi-Fi/TCP“ und der HMI-IP einrichten. GRBL TCP auf Port **23**. Es darf immer nur ein externer Host oder ein lokaler HMI-Job/Makro die Steuerung besitzen; bei aktiven Jobs niemals Quellen umschalten.

### Handy

Das Waveshare bietet einen WPA2-Hotspot `LumaCut-xxxx` und verbindet sich optional zum eigenen WLAN. Im HMI unter System stehen Hotspot-Passwort und Web-Zugangscode. Über `http://192.168.4.1` im Hotspot oder die angezeigte HMI-IP im Heimnetz sind G-Code-Upload (`.gcode`, `.nc`, `.tap`, `.txt`), Datei-Auswahl, Trockenrahmen, Start/Pause/Fortsetzen/Abbruch und Parkposition verfügbar.

LightBurn-Projektdateien `.lbrn2` können nicht nativ vom HMI interpretiert werden. LightBurn über USB/WLAN direkt verbinden oder G-Code exportieren. WLAN-HTTP und GRBL-TCP sind nicht TLS-geschützt; Gerät niemals über Router-Portweiterleitungen ins Internet stellen.

### Bluetooth

ESP32-S3 hat nur BLE und kein klassisches Bluetooth-SPP. Das HMI veröffentlicht einen read-only BLE-Maschinenzustand, **kein direktes LightBurn-Bluetooth-Serial**. BLE Service `a50d8324-5e0d-42db-92f8-c3f3b5b93051`, Status-Characteristic `a50d8324-5e0d-42db-92f8-c3f3b5b93052`.

### Makros / Parkpositionen

Die Oberfläche erlaubt drei gespeicherte XY-Parkpositionen, die im HMI dauerhaft abgelegt werden. Nach Homing und lokaler Zeitfreigabe aktuelle Maschinen-X/Y speichern und in Idle mit `M5`, `G21 G90`, `G53 G0 X... Y...` anfahren. Kein automatisches Z-Verfahren: Eine sichere Kollisionsfreihöhe kann ohne genaue Maschineinrichtung nicht angenommen werden. Diese Funktion erfordert einen von Hindernissen freien Fahrweg.

### Jobsteuerung / Framing

Für lokale G-Code-Jobs wartet das HMI auf grblHAL-Antworten pro Zeile. Hold mit `!`, Resume mit `~`, Reset/Abort mit Ctrl-X. Framing wird derzeit nur als **Trockenrahmen mit M5** bereitgestellt und nur bei auslesbaren absoluten metrischen X/Y-Grenzen zugelassen.

**Die vom Nutzer gewünschte 1-%-Laser-Umrandung ist bewusst NICHT aktiviert.** Selbst niedrige Laserleistung kann gefährlich sein. Dazu müssen `$30`, PWM-Pegel, Laserausgang, Schutzgehäuse, Interlocks, externer Not-Aus, Startzustände und die gesamte Mechanik erst an echter Hardware überprüft werden.

## Wichtige Grenzen

- Kompiliert bedeutet nicht elektrisch oder funktional auf echter Hardware validiert.
- Nach Reset und vor eigener Bewegung ist Homing `$H` nötig; beim Jog/Start außerdem `Idle`-Status und lokale 30-Sekunden-Freigabe.
- Eine abreißende WLAN-Verbindung kann Hold anfordern, garantiert aber keine sichere Laser-Stromunterbrechung.
- Ein extern verdrahteter Not-Aus und eine hardwarewirksame Laser-Leistungsfreigabe sind unabdingbar.
- Vollständige LightBurn-G-Code-Varianten wie relative Moves, Bögen/Arcs und spezielle Modalbefehle brauchen vor verlässlichem Framing einen ausgereiften Interpreter.
- Maschine und Schalterbelegung, PWM, TMC-Treiber und die beiden Y-Motoren vor echtem Laserjob prüfen.
