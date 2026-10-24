# LumaCut: automatisches SKR-Update direkt vom Waveshare HMI

## Technischer Pfad

Der ESP32-S3 laedt **die von `luma.millione.de` freigegebene**
`SKR_UART_UNVERIFIED_firmware.bin` mit HTTPS und
`X-LumaCut-Device-Key`. Er prueft Laenge, SHA-256 und Cortex-M-Vektoren,
speichert die Datei in `/updates/skr-staged.bin` auf der 4-GB-FAT32-Karte
(ohne Karte alternativ im LittleFS), prueft die gespeicherte SHA-256 erneut
und programmiert dann den SKR Mini MZ V1.0 ueber dessen STM32F103RC
**werkseitigen ROM-USART1-Bootloader**.

Die bestehende HMI↔SKR-UART-Leitung wird dazu von 115200/8N1 auf
115200/8E1 (Bootloader-Modus) umgeschaltet. Das HMI nutzt die dokumentierten
ST-AN3155-Befehle Get, Get ID, Erase (0x43 bzw. 0x44), Write Memory (0x31)
und Read Memory (0x11). Es akzeptiert nur die High-Density-ID 0x0414.
Es loescht **ausschliesslich** die Applikationsseiten ab
`0x08007000` / Flashseite 14, niemals den ersten 28-KB-SD-Bootloader
oder den ganzen Flash. Jeder geschriebene Block (maximal 256 Byte)
wird anschliessend gelesen und Byte fuer Byte verglichen.
Danach BOOT0 LOW, Hardware-Reset und GRBL-UART zurueck auf 115200/8N1.

### Einmalige Verbindung (fuer vollautomatisches Flashen notwendig)

Die vorhandenen Leitungen bleiben:

- ESP32-S3 UART TX (GPIO43) → SKR PA10 / USART1 RX
- ESP32-S3 UART RX (GPIO44) ← SKR PA9 / USART1 TX
- HMI GND ↔ SKR GND

Zusatzmodul: **PCA9685** 16-Kanal-PWM-/I2C-Breakout, I2C-Adresse
**0x40** (Standard; A0..A5 an GND). Das ist kein CH422G und belegt keine
der Waveshare-Adressen 0x20..0x3F.

Waveshare I2C-Buchse → PCA9685:

| Waveshare I2C | PCA9685 |
|---|---|
| 3V3 | VCC (Logikversorgung, 3,3 V) |
| GND | GND |
| SDA/GPIO8 | SDA |
| SCL/GPIO9 | SCL |

**Keinesfalls 5 V an VCC/BOOT0/NRST.** PCA9685 `V+` (Servostrom)
unbenutzt lassen. Die Ausgangssignale P0/P1 sind 3,3-V-Logik, keine
5-V-Servo-Stromversorgung.

| PCA9685 | SKR | Beschaltung |
|---|---|---|
| PWM-Ausgang **P0** | BOOT0-Pad/BOOT-Jumper **STM32-Seite** | Über 1 kΩ Serienwiderstand, zusätzlich 10 kΩ nach GND am BOOT0-Pad |
| PWM-Ausgang **P1** | NRST / EXP1_4 **über NPN-Schaltstufe** | P1 → 2,2 kΩ → Basis eines NPN (z.B. 2N3904), 10 kΩ Basis–GND; Emitter → GND; Kollektor → SKR NRST |

**P1 niemals direkt push-pull auf NRST legen!** Die vorhandene
3,3-V-Reset-Pullup-Beschaltung der SKR-Platine bleibt erhalten; der
Transistor zieht NRST nur fuer einen kurzen Resetimpuls gegen GND.
Die feste 10-kΩ-BOOT0-Pulldown sorgt auch bei unversorgtem HMI fuer
normalen SKR-Start. Die BOOT-Jumperkontakte des Mini MZ V1.0 muessen
anhand des **eigenen** Platinendrucks/Herstellerplans geprueft werden;
BOOT0 ist nicht zu verwechseln mit GND oder 3V3.

Offizielle Pin-Belege:
- SKR Mini MZ V1.0: EXP1_4 = RST, EXP1_3 = PA9, EXP1_5 = PA10,
  EXP1_9 = GND
- Waveshare ESP32-S3 Touch LCD 7: I2C an GPIO8/GPIO9.
- STM32 USART1 ROM-Bootloader: 8E1, PA9/PA10.
- Der PCA9685 besitzt digitale **FULL_ON/FULL_OFF**-Ausgangsbits;
  diese werden statt PWM-Pulsen verwendet.

### Bedienung

1. Bei ausgeschalteter Laser-Versorgung PCA9685, gemeinsame Masse,
   BOOT0 und NRST verbinden. SKR-Verbindung im HMI muss vorher als
   Idle erreichbar sein.
2. **Luma-Compiler** aus aktuellem `main` aktualisieren, vollständiges
   HMI+SKR-Build erzeugen, dieses als Stable-Release freigeben.
3. Das HMI einmal per USB auf den neuen Stand flashen, weil die
   Updatefunktion selbst noch nicht im aelteren HMI enthalten ist.
4. Unter **System/WLAN** Update-Key aus Unraid `.env` speichern,
   **Pruefen** → **SKR installieren** → binnen 15 s nochmals
   **SKR installieren**. Den Laser vorher physisch stromlos machen.
5. Das HMI laedt und prueft die Datei, wechselt den SKR per P0/P1
   in die ROM-Konsole, schreibt und liest sie, setzt BOOT0 zurueck,
   startet SKR neu und zeigt das Resultat an.

### Konkrete Fehlerdiagnose

| Anzeige | Bedeutung |
|---|---|
| `PCA9685 (0x40) nicht gefunden` | I2C-Erweiterung/Adresse/Verkabelung fehlt |
| `ROM USART1 antwortet nicht` | BOOT0, NRST, GND, UART RX/TX oder Quarz-/Versorgung pruefen |
| `Falsches Silizium` | Kein STM32F103 High-Density ID 0x0414 gefunden |
| `SHA256 fehlerhaft` | Download, SD-Karte oder falscher Release |
| `Schreib-/Ruecklese-Pruefung fehlgeschlagen` | Flash-/UART-/Stromversorgungsproblem; app ggf. unvollstaendig |

**Recovery:** Ein unterbrochenes Update kann die GRBL-Applikation
unbrauchbar machen. Die ersten 28 KB SKR-SD-Bootloader bleiben bestehen.
`firmware.bin` aus dem Compiler ist weiterhin per SKR-eigener
microSD wiederherstellbar. Alternativ BOOT0 hardwaremaessig setzen
und mit STM32-Programmer oder SWD flashen. Eine erfolgreich
kompilierte Software allein ist kein Nachweis, dass P0/P1 richtig an
deiner konkreten Rev1.0-Platine angelötet wurden.

## Quellen

- ST AN3155 — How to use USART protocol in bootloader
  https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf
- ST AN2606 — STM32 system memory boot mode
  https://www.st.com/resource/en/application_note/an2606-stm32microcontroller-system-memory-boot-mode-stmicroelectronics.pdf
- Waveshare 7inch ESP32-S3 board
  https://docs.waveshare.com/ESP32-S3-Touch-LCD-7
- NXP PCA9685 register datasheet
  https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf
- BIGTREETECH SKR Mini MZ board
  https://github.com/bigtreetech/BIGTREETECH-SKR-MINI-MZ
