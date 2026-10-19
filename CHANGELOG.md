# Changelog

## 2026-10-19 – Firmwareimplementierung (experimental)
- grblHAL STM32F1xx: festgelegte Upstream-Version + SKR-MZ-Pinpatch, 28KiB-Bootloader-Layout, reproduzierbarer PlatformIO-Build.
- Waveshare ESP32-S3-Touch-LCD-7: eigener Arduino/LVGL-Quellcode mit RGB 800×480, GT911, CH422G, 7-Zoll-Dashboard und absichtlich gesperrten Maschinenbefehlen.
- Browser-Compiler mit echten SKR-/ESP32-Buildkommandos verbunden, GitHub Actions Buildprüfungen und Firmware-Artefakte.
- Weiterhin **keine Hardware-/Flashfreigabe** und keine abgeschlossene LightBurn/HMI-Arbitration.

## 2026-10-19 – v0.3 Projektstart
- Projektarchitektur, Dokumentation, Unit-Tests, privater GitHub-/Unraid-Browser-Compiler.