# SKR Mini MZ v1.0 – grblHAL experimenteller Firmwarebuild

Der Quellcode wird mittels `python firmware/skr/build.py` von `grblHAL/STM32F1xx` (gepinnter Commit in `platformio.ini`) samt Untermodulen geholt. Das Skript übernimmt die gut dokumentierte E3-V2-Treiberstruktur mit USB CDC, 28-KiB-Bootloaderoffset und TMC2209, korrigiert MZ-Anschlüsse und entfernt insbesondere PC8/PC9 (Heiz-MOSFETs) als universelle Aux-Ausgänge. Ergebnis: `firmware/skr/.pio/build/lumacut_skr_mz_usb/firmware.bin` und .elf.

**Nicht zum Flashen freigegeben.** Die MZ-Pins unterscheiden sich vom E3-V2; insbesondere Pin PA1 (Laser PWM nur Kandidat), PC6/PC7 (Lüfter), Taster PC14 und Hardware-Interlock müssen vor einem realen Flash mit Messgerät und Schaltplan verifiziert werden. Separate Z-Referenz PC2. Taster-Geometrie derzeit im Python-Simulationsmodul, nicht in der Echtzeitfirmware implementiert. ESP32-UART ist noch nicht als konkurrierungsfreier Steuereingang implementiert.

Keine beliebigen Flashbefehle oder USB-Device-Mounts im Docker-Compiler. Originalflash und Wiederherstellung vorher sichern.