# Projektstand – 2026-10-19

Repository: theubyte/LumaCut-CNC (privat), main.
Konzept: SKR MZ steuert Atomstack/LaserTree via grblHAL, PC mit LightBurn direkt über USB, Waveshare ESP32-S3 7-Zoll-Touch als Bedienpanel. Kein Raspberry Pi.
Erstellt: GitHub-Projektbasis, hardwarefreie Geometrie, Tests, Unraid-Docker-Buildserver mit Browser, GitHub-Checkout, Jobhistorie, Logs, Hashes, herunterladbare ZIPs, Installer und GitHub-Deploy-Key-Assistent.
Nicht erstellt: freigegebene SKR-MZ-BIN, eigenes grblHAL-MZ-PlatformIO-Profil, vollständige HMI-Firmware, Hardwaretests, automatische Höhenkartenkompensation, sichere HMI-Arbitration.
Technische Unbekannte: reale MZ-Pinbelegung/Bootloader, MZ-Schnittstellen-Ressourcen für HMI, PWM-Pegel, Taster und Z-Maße, Hardware-Interlocks.
Nächster Schritt: Unraid-Installer starten und GitHub-Leseschlüssel anbinden; danach Geometrietests im Browser erfolgreich ausführen. Hardwaredaten aufnehmen, bevor die Firmwareentwicklung beginnt.

Jeder neue Chat kann das verbundene private GitHub-Repository lesen (sofern der GitHub-Zugriff für den Chat vorhanden ist) und auf Basis dieser Datei, des README und des konkreten Commits fortsetzen.