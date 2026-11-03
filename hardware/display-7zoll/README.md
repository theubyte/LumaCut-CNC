# Bedienpanel 7 Zoll (Waveshare ESP32-S3-Touch-LCD-7)

Design-Entwurf für ein Bedienpanel am Gehäuse. Hardware: Waveshare
ESP32-S3-Touch-LCD-7 Rev 1.2 (800 × 480, kapazitiver Touch, ESP32-S3 N16R8).

Geplante Anbindung: USB-C direkt am Pi (Strom + Daten, kein WLAN-Passwort auf
dem Display). Der Pi bleibt die Zentrale; das Panel ist nur eine weitere
Oberfläche wie Web-App und Android-App. Laser starten nur nach derselben
Go-Abfrage („Hände raus, Deckel zu, Brille“). Not-Aus und Deckelschalter
bleiben Hardware am Relais, nicht auf dem Display.

## Stand

Nur Design (Mockup), noch keine Firmware.

- `design/mockup.html`: alle vier Bildschirme; `?s=1..4` zeigt einen einzeln
  in 800 × 480.
- `design/screen_1..4.png`: Status, Bewegen, Kamera, Laserfreigabe (2× gerendert).
- `design/uebersicht.png`: alle vier auf einem Bild.

Stil: gebürstetes Alu, Riffelblech, Schrauben, Metallknöpfe, Leuchtziffern
(Cyan für Werte, Amber für Laser), Warnstreifen. Für die Firmware (LVGL)
werden Alu- und Riffelblech-Flächen als Bitmaps eingebunden.
