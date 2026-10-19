# Hardwareprofil – Stand 2026-10-19

Bekannt: Atomstack A5 Pro, LaserTree LT-80W-AA-Pro; BIGTREETECH SKR Mini MZ V1.0 mit STM32F103RC/TMC2209; Waveshare ESP32-S3-Touch-LCD-7 Rev1.2. Hauptplatine per USB CDC unmittelbar an LightBurn; Unraid ist nur Buildserver.

## Risiken vor dem ersten Flash
1. SKR Mini MZ ist NICHT automatisch pin-kompatibel mit SKR Mini E3 V2. Insbesondere TMC2209-Y-/Z-Adressen, UART und Treiber-Modus anhand Original-Schaltplan und realem Board prüfen.
2. Vorherige grblHAL-Konfiguration/Einstellungen/BIN und Bootloader-Restore sichern. Bootloader-Offset und vorhandenes Board-Flashverfahren abgleichen.
3. Z-Endschalter (PC2 Kandidat) und separater Werkstück-Taster (PC14 Kandidat) elektrisch durchmessen, inklusive Pullups, Ruhestellung, Fehler bei Kabelbruch und Bewegung.
4. Laser-PWM/TTL-Ausgang PA1 ist nur ein Kandidat. Spannung, PWM-Frequenz, Pegel bei Reset/Brownout und geschaltete Versorgung am Kopf messen.
5. Externe Hardware-Freigabekette: Not-Aus, Schlüssel, Gehäuse, optional Rauch/Abluft. Hardware muss Laserstrahlung ohne Kooperation der Firmware stoppen können.
6. ESP32-RS485 ist nicht direkt kompatibel zu 3,3-V-TTL; Transceiver oder geprüften TTL-UART-Header verwenden. Masseführung, isolierte Spannungsversorgung und Leitungspegel beachten.
7. ESP32-Bedienung darf LightBurn-Jobstream nicht überlagern. Laufende Jobs sperren Jog, Probe, Home und Setup bis kontrollierter Stop/Hold.
8. Bewegungs-/Vibrationssensor ist vorerst als Erweiterung vorgesehen; kein sicherheitsgerichteter Sensor ohne Zertifizierung.
9. Unbekannt: Z-Verfahrweg, Achsrichtung, Endschalterrichtung, Laser-Schaltlogik, Z-Genauigkeit, Distanz Optik zu Mikroschalter, thermische Z-Drift.

## Offiziell hilfreiche Quellen
- MZ-Pinreferenz: https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-mini-mz.cfg
- grblHAL STM32F1xx: https://github.com/grblHAL/STM32F1xx
- Waveshare: https://docs.waveshare.com/ESP32-S3-Touch-LCD-7
- LightBurn: https://docs.lightburnsoftware.com/

Alle genannten GPIOs und Profil-Eigenschaften gelten bis zur realen Prüfung als UNVERIFIED.