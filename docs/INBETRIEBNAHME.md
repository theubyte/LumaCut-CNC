# LumaCut CNC – erste Inbetriebnahme (21.10.2026)

**Status: Entwicklungs-/Laborversion, keine Freigabe zum Laserbetrieb.**
GitHub-Actions-SUCCESS bedeutet nur, dass der Quellcode auf einem Buildserver übersetzt wurde.
Ein realer Funktions- und Sicherheitstest am BTT SKR Mini MZ V1.0 und am Waveshare ESP32-S3-Touch-LCD-7 Rev1.2 ist noch ausstehend.

## 1. Voraussetzungen / Sicherheitsgrenzen
- **LaserTree-Laser physisch stromlos und vom TTL/PWM-Anschluss getrennt lassen**, bis die gesamte Maschine geprüft ist. Kein Test von `M3`/`S` mit angeschlossenem Laser.
- Bewegungsraum frei; Z-Spindel gegen Anschlag schützen. Motoren zunächst abgekoppelt oder reduzierte Antriebsleistung; Schrittrichtung und Endschalter einzeln verifizieren.
- Externe, hardwarewirksame Not-Aus-/Laserfreigabe sicherstellen. Weder Touchscreen noch Software-Stopp ersetzen einen Not-Aus.
- Treiber-Versorgung, Netzteil, gemeinsame GND-Bezüge, Polarität, 3,3-V-Logik und Pegel vor Anschluss messen.
- Serienmäßig können die TMC2209 auf PC10/PC11 (USART3) angesprochen werden. Diese Leitungen **nicht** fürs HMI verwenden.
- Sicherung der bisherigen `firmware.bin`, vorhandener Einstellungen `$$`, `$I`, `$pins`, Bootloader und STM32-Konfiguration erstellen. Diese Daten werden beim Flash unter Umständen verändert.
- Die `config/laser.yaml` ist **kein direkt eingespieltes grblHAL-NVS-Profil**. Achswege, max. Geschwindigkeiten, Schritte/mm, Homingrichtung, Limit-Pegel etc. vor Bewegungen auf deinem Gerät festlegen.

## 2. SKR Flash – nur nach Bootloader- und Pinprüfung
- In GitHub Actions den aktuell **erfolgreichen** Lauf öffnen; Artifact `UNVERIFIED-skr-<commit>` herunterladen. `firmware.bin` liegt im entpackten ZIP.
- Ein FAT32-formatiertes microSD-Medium verwenden. `firmware.bin` ins Root der SD kopieren. Strom AUS, SD einstecken, Strom EIN und nach Boot überprüfen, ob `FIRMWARE.CUR` oder boardtypisches Umbenennungsmerkmal entstanden ist.
- **Kein UART-/SWD-Flash-Kommando erforderlich:** Normaler SKR Mini MZ v1.0 verwendet einen 28KiB-SD-Bootloader. Falls dein Board einen anderen Bootloader hat oder das Update nicht übernimmt: stoppen, Firmware/Bootloader rückprüfen, nicht blind alternative Offsets flashen.
- USB mit PC verbinden, LightBurn vorerst als GRBL-Testverbindung (nicht Laserjob) bei passenden seriellen Parametern einrichten; Konsole: `$I`, `$$`, `$pins`, `?`, `M5`. Erwartet wird eine grblHAL/GRBL-Antwort. **Keine Bewegungen**, solange Richtung, Endschalter und Weggrenzen nicht geprüft sind.
- Hardware-Schaltplan gegen tatsächliches SKR-Mini-MZ-Pinmapping vergleichen. X PC0 und Y PC1 sind aktuell unbeschaltet, der **einzige mechanische Taster** ist für Z PC2 vorgesehen; PC14 ist unbeschaltet; PWM PA1; Laser-Enable PC7 **ist ein FET-Ausgang, kein garantierter 3,3-V-TTL-Pin**. PC8/PC9 sind Heiz-FETs und ausdrücklich keine frei schaltbaren Ausgänge. Ausgangsspannung bei Boot/Reset/Brownout messen. Nie 24 V an Laserkopf-TTL anschließen.
- Drehrichtung/Achs-Zuordnung/TMC-Adresse und Strom separat verifizieren, insbesondere deine Spindel-Z-Achse und Laserlast (~500 g). Genau ein X-, ein Y- und ein Z-Motor; E/M3 bleibt frei.

## 3. HMI Firmware / Display
Das Projekt enthält zwei separate Images:
- **`lumacut_waveshare_s3`**: Touch-Dashboard, Sicherheitsmodus: keine Jog-Kommandos.
- **`lumacut_waveshare_s3_keypad`**: optionales UART-Jog-Dashboard, nur für stromlose Laser-Labortests und nach erfolgreicher Achs-/Sicherheitseinrichtung.

Erzeugen über GitHub Actions Artifact `UNVERIFIED-hmi-<commit>` oder in PlatformIO:
```sh
pio run -d firmware/hmi -e lumacut_waveshare_s3
pio run -d firmware/hmi -e lumacut_waveshare_s3 -t upload
pio device monitor --baud 115200
```
Für UART-Betrieb `-e lumacut_waveshare_s3_keypad` beim Build und Upload verwenden. **Achtung:** ESP32-S3-Images von `pio run` können zusätzliche Bootloader-/Partitionstabellen benötigen; verwende daher PlatformIO `-t upload` statt nur eine einzelne `firmware.bin` per esptool auf Flashadresse 0 zu schreiben.

Waveshare muss ausreichend mit 5 V versorgt sein. Das Board nutzt RGB565 800×480, GT911, CH422G (Reset/Beleuchtung). LCD und Touch nach Flash testen.

## 4. HMI-Verkabelung – erst nach elektrischer Prüfung
**3,3-V-TTL, keine RS485 A/B-Leitungen!** Laut Waveshare UART2-Auswahl: HMI GPIO43 TX → SKR USART1 PA10 RX (EXP1), HMI GPIO44 RX ← SKR USART1 PA9 TX; **GND ↔ GND**. Pin-Nummern des EXP1-Steckers anhand des SKR-Schaltplans gegenprüfen; nicht am Steckplatz nach Vermutung verdrahten. Kein 5-V-TTL; bei getrennt versorgten Boards keine ungeprüfte 5-V-Brücke legen. Für serielle Bewegungsbedienung Waveshare-UART2-Schalter korrekt wählen; die USB-Debug-/Flash-Schnittstelle muss unabhängig davon funktionieren.

Im SKR ist `KEYPAD_ENABLE=2` aktiviert: grblHAL nimmt einzelne Steuerzeichen über USART1 entgegen, LightBurn bleibt auf SKR-USB-CDC. Das HMI sendet `2` für Step-Jogging, `L/R/B/F/D/U` für die Achsen und `0x85` bei Loslassen. Jog-Schritte werden **im SKR** konfiguriert, nicht aus der Bildschirm-Schrittauswahl des Offline-Dashboards abgeleitet. Der UART-Weg hat **keine Rückmeldung/Quittung im HMI**. Nur im Leerlauf testen; während LightBurn-Jobs keine Jogfreigabe erteilen. GrblHAL-Plugin-Sperren sind kein Ersatz für diese Betriebsregel.

## Aktualisierte Hardware-Konfiguration

**Korrektur 23.10.2026:** Die reale Maschine hat jeweils einen Motor für X, Y und Z und nur einen mechanischen Taster, der Z-Endstop und Werkstückmessung übernehmen soll. Keine X/Y-Schalter, kein separater Probe-Sensor. Die ältere Beispielverkabelung für PC14 als separaten Probe-Eingang ist **nicht** für dieses Gerät gültig. Der HMI-`$H`-Befehl wurde aus Sicherheitsgründen gesperrt; G38-Probing ist in der Firmware bis zum geprüften gemeinsamen Eingangsmodus deaktiviert. [Aktuelles Hardwareprofil](HARDWARE.md).

## 5. Testreihenfolge
1. HMI nur per USB versorgen, erst einmal **Offline-Image** flashen: Logo/UI/Touch, sämtliche Jog-Tasten ohne Bewegung.
2. SKR separat ohne Laser testen: USB erkannt, `$I`, `$$`, `$pins`; Endschalter und Probe von Hand betätigen und Zustände prüfen.
3. Achsen bei deaktiviertem Laser in sicheren kleinen Schritten prüfen; Grenzen und Richtungen festlegen; Not-Aus betätigen und vollständige Wirkung verifizieren.
4. Erst danach UART2-TTL verdrahten, optionales **Keypad-Image** flashen, mit freiem Arbeitsraum und ohne Laser 0,1-mm-Jog im Stand überprüfen; loslassen, Abbruch und 30-s-Freigabezeit testen.
5. Laserkopf, TTL/PWM, externe Laserfreigabe und Abstände ausschließlich nach Messprotokoll einrichten; erst bei bestandenem Test freigeben.

## Offene Punkte
- **Mit der tatsächlichen Hardware deaktiviert:** automatisches XYZ-Homing (X/Y ohne Schalter) und separates G38-Probing (nur ein Z-Taster vorhanden). **Nicht vorhanden:** bestätigte grblHAL-TMC2209-Laufparameter, verifizierte Endschalter-/Probe-Pegel, echter Live-DRO/GRBL-Status am HMI, Autofokus, automatische XY/Taster-Kalibrierung und Höhenkarte.
- **Nicht getestet:** STM32 Flash auf dieser spezifischen SKR-Platine, reales LCD/GT911-Verhalten auf Rev1.2, UART zwischen den beiden Boards, Start-/Stoppsicherheit und reales Laserverhalten.
- **Nicht freigegeben:** Lasergravur oder Schneidbetrieb. Weitere Schritte hängen von der Elektro-/Hardwareverifikation ab.

## Quellen
- SKR Mini MZ: https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-mini-mz.cfg
- Waveshare: https://docs.waveshare.com/ESP32-S3-Touch-LCD-7
- UART Keypad: https://github.com/grblHAL/Plugin_keypad
