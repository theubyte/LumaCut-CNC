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

Es ist genau **ein** mechanischer Taster vorhanden, der am Laserkopf sitzt und sowohl als Z-Endstop/Referenztaster als auch zur Messung des Werkstücks dienen soll. Keine zusätzlichen X- oder Y-Endschalter und kein zweiter Z-Probe-Sensor.

| Funktion | GPIO | Anschluss | Ist-Zustand |
|---|---|---|---|
| Einziger mechanischer Z-Taster | PC2 | Z-STOP (Signal + GND) | Vorgesehen, Signal/Ruhestellung prüfen |
| X-STOP | PC0 | X-STOP | Nicht angeschlossen |
| Y-STOP | PC1 | Y-STOP | Nicht angeschlossen |
| Separate Probe | PC14 | PROBE | Nicht angeschlossen |

**Nur ein physischer Taster ≠ automatisch ein doppelt verwendbarer Firmware-Eingang.** GrblHAL hat normalerweise getrennte Z-Limit- und Probe-Eingangsverarbeitung. Die aktuelle Konfiguration wertet PC2 nur als Z-Endstop aus; Probe ist in der SKR-Firmware deaktiviert. Ohne spezifisch implementiertes und geprüftes dynamisches Umschalten von Z-Limit/Probe darf der Taster **nicht** per G38.x als Probe verwendet werden. Keinesfalls den Taster blind mit beiden Pins brücken: während Probe-Fahrt könnte ein Hard-Limit-Alarm statt einer sicheren Probe-Erkennung ausgelöst werden.

Ohne X/Y-Referenzschalter darf kein gewöhnlicher automatischer `$H`-XYZ-Homing-Lauf gestartet werden; X/Y würden sonst ohne Auslösesignal gegen Anschläge fahren können. Der HMI-Button ist bis zu einer gesonderten sicheren XY-Referenzlösung gesperrt. Hard-Limits und Homing nicht pauschal aktivieren. Maschinenweg, Endlagen, Bewegungsrichtung, Z-Schalterlage und Not-Aus müssen vor jeder Bewegung überprüft werden.

**Geometrisch wichtig:** Ein beweglicher Taster am Laserkopf ist nur dann ein Maschinen-Z-Referenzgeber, wenn er an einem **festen, reproduzierbaren Referenzkörper** auslöst. Wenn er auf einem unterschiedlich hohen Werkstück betätigt wird, ist das lediglich ein Werkstücknullpunkt, kein stabiler Maschinenreferenzpunkt.

## Waveshare-Verbindung

HMI GPIO43 TX → SKR PA10 RX, HMI GPIO44 RX ← SKR PA9 TX, GND ↔ GND, 3,3 V TTL, Waveshare UART-Schalter auf UART2. Die genaue mechanische Lage der EXP1-Kontakte auf dem Board prüfen. Keine ungesicherten 5V- oder RS485-Verbindungen.

## Sicherheitsprüfungen

1. Board-Pinout und Treiberadressen prüfen. BTT Mini MZ ist nicht pauschal identisch mit Mini E3 V2.
2. Alte Firmware, Bootloader-Eigenschaften, `$$` und `$I` sichern.
3. Einzigen Z-Taster PC2 elektrisch durchmessen; NO/NC, Ruhestellung, Pullup, Kabelbruch und Bouncing prüfen.
4. Automatisches XYZ-Homing und G38-Probe bis zur Implementierung deaktiviert lassen.
5. PWM PA1, Laser-Enable/FET PC7 und Not-Aus-Kette ohne verbundenen Laser verifizieren. LaserTree-Laser bei allen frühen Tests physisch stromlos.
6. Mechanische Endlagen, Schrittwege und Z-Spindel-/Laserkopf-Kollisionen separat testen.

Offizielle Referenzen:
- https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-mini-mz.cfg
- https://github.com/grblHAL/STM32F1xx
- https://docs.waveshare.com/ESP32-S3-Touch-LCD-7

**Firmwarebuilds sind Laborimages, keine getestete Laserfreigabe.**
