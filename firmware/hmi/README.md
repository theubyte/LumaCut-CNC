# Waveshare ESP32-S3-Touch-LCD-7 Rev1.2 – HMI v0.1

Arduino/PlatformIO + LVGL 8.3, 800×480 RGB LCD, GT911 Touch und CH422G I/O-Expander.

`pio run -d firmware/hmi -e lumacut_waveshare_s3`

Quellen: `src/main.cpp`, `src/lv_conf.h`; Ergebnis unter `.pio/build/lumacut_waveshare_s3/firmware.bin`.

Funktional vorgesehen: sichtbares Dashboard mit Jog-/Home-/Autofokus-Elementen, Touch-Events und Offline-Warnung. **Bewegungsbefehle bleiben bewusst deaktiviert**. Ein sicherer zweiter UART-Kanal neben LightBurn-USB existiert erst, wenn er im SKR mit expliziter Kommando-Arbitration integriert und elektrisch geprüft wurde. Ein nur kompilierter Touchscreen darf niemals Bewegungen oder Laserleistung direkt auslösen.

Anpassungen für GT911-Koordinaten, RGB-Timings, Rev1.2 und Serialschnittstelle müssen am physischen Board verifiziert werden. Kein unbeaufsichtigter Laserbetrieb.