# LumaCut CNC – tatsächliche Hardware (korrigiert am 23.10.2026)

BTT SKR Mini MZ V1.0, STM32F103RC/TMC2209, Waveshare ESP32-S3-Touch-LCD-7 Rev1.2, Atomstack A5 Pro / LaserTree LT-80W-AA-Pro.

## Motoranschlüsse – genau drei Motoren

| Achse | Motortreiber/Buchse | STEP | DIR | ENABLE |
|---|---|---|---|---|
| X | XM | PB13 | PB12 | PB14 |
| Y | YM | PB10 | PB2 | PB11 |
| Z (Spindel) | ZAM oder ZBM | PB0 | PC5 | PB1 |
| E / M3 | **frei** | — | — | — |

**Kein zweiter Y-Motor, keine ganged axes, kein aktiver Extruder-/E-Treiber.** ZAM und ZBM hängen am selben Z-Treiber und sind alternative Buchsen; genau einen Motor anschließen.

## Genau ein mechanischer Taster

**X, Y und Z besitzen jeweils einen Endschalter.** Der Z-Schalter am Laserkopf soll in einem noch separat zu implementierenden Modus auch als Werkstücktaster dienen. Es gibt keinen zusätzlichen vierten Probe-Schalter.

| Funktion | GPIO | Anschluss | Ist-Zustand |
|---|---|---|---|
| Einziger mechanischer Z-Taster | PC2 | Z-STOP (Signal + GND) | Vorgesehen, Signal/Ruhestellung prüfen |
| X-STOP | PC0 | X-STOP | Vorhanden |
| Y-STOP | PC1 | Y-STOP | Vorhanden |
| Separate Probe | PC14 | PROBE | Nicht angeschlossen |

**Der eine Z-Taster ≠ automatisch ein doppelt verwendbarer Firmware-Eingang.** GrblHAL hat normalerweise getrennte Z-Limit- und Probe-Eingangsverarbeitung. Die aktuelle Konfiguration wertet PC2 nur als Z-Endstop aus; Probe ist in der SKR-Firmware deaktiviert. Ohne spezifisch implementiertes und geprüftes dynamisches Umschalten von Z-Limit/Probe darf der Taster **nicht** per G38.x als Probe verwendet werden. Keinesfalls den Taster blind mit beiden Pins brücken: während Probe-Fahrt könnte ein Hard-Limit-Alarm statt einer sicheren Probe-Erkennung ausgelöst werden.

**XYZ-Homing ist im HMI wieder verfügbar.** Für die drei tatsächlich montierten Endschalter ist der normale `$H`-Lauf vorgesehen. `$22=1` aktiviert grblHAL-Homing, `$23` steuert die Suchrichtung und `$24` bis `$27` das Such-/Freifahrverhalten. Vor der ersten Fahrt die Lage und elektrische Schaltfunktion jedes Schalters verifizieren und die Achsrichtung einstellen. Der HMI-Button **Homing aktivieren** sendet nur `$22=1`; **Referenzfahrt** startet `$H`. Andere Fehler, E-Stop/Not-Aus und Hardware-Schutz bleiben wirksam. Maschinenweg, Endlagen, Bewegungsrichtung, Z-Schalterlage und Not-Aus müssen vor jeder Bewegung überprüft werden.

**Geometrisch wichtig:** Ein beweglicher Taster am Laserkopf ist nur dann ein Maschinen-Z-Referenzgeber, wenn er an einem **festen, reproduzierbaren Referenzkörper** auslöst. Wenn er auf einem unterschiedlich hohen Werkstück betätigt wird, ist das lediglich ein Werkstücknullpunkt, kein stabiler Maschinenreferenzpunkt.

## Waveshare-Verbindung

HMI GPIO43 TX → SKR PA10 RX, HMI GPIO44 RX ← SKR PA9 TX, GND ↔ GND, 3,3 V TTL, Waveshare UART-Schalter auf UART2. Die genaue mechanische Lage der EXP1-Kontakte auf dem Board prüfen. Keine ungesicherten 5V- oder RS485-Verbindungen.

## Sicherheitsprüfungen

1. Board-Pinout und Treiberadressen prüfen. BTT Mini MZ ist nicht pauschal identisch mit Mini E3 V2.
2. Alte Firmware, Bootloader-Eigenschaften, `$$` und `$I` sichern.
3. Einzigen Z-Taster PC2 elektrisch durchmessen; NO/NC, Ruhestellung, Pullup, Kabelbruch und Bouncing prüfen.
4. Bei jedem vorhandenen X-/Y-/Z-Endschalter den korrekten Eingang und `$23` prüfen, dann `$22=1` und `$H` verwenden. G38-Probe über den gemeinsam benutzten Z-Schalter bis zur getrennten Modusimplementierung deaktiviert lassen.
5. PWM PA1, Laser-Enable/FET PC7 und Not-Aus-Kette ohne verbundenen Laser verifizieren. LaserTree-Laser bei allen frühen Tests physisch stromlos.
6. Mechanische Endlagen, Schrittwege und Z-Spindel-/Laserkopf-Kollisionen separat testen.

Offizielle Referenzen:
- https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-mini-mz.cfg
- https://github.com/grblHAL/STM32F1xx
- https://docs.waveshare.com/ESP32-S3-Touch-LCD-7

**Firmwarebuilds sind Laborimages, keine getestete Laserfreigabe.**
