# LumaCut CNC: 24-V-Laser direkt am SKR-BED-Ausgang (PC9)

Stand: 24.10.2026, LumaCut `main`. Gewünschter Aufbau mit LaserTree LT-80W-AA-PRO,
Waveshare ESP32-S3 und BTT SKR Mini MZ V1.0.

## SKR-Belegung – ein Kanal pro Funktion

| Physische Klemme | STM32-Port | Steuerung |
| --- | --- | --- |
| **BED** | **PC9** | **24-V-Lasermodul EIN/AUS durch M3/M4/M5** |
| **PT-DET-Signal** | **PA1** | Laser-TTL/PWM 0–3,3 V; nicht der Servo-Header |
| **HE0** | **PC8** | 24-V-LED-Beleuchtung M7 |
| **FAN0** | **PC6** | 24-V-Gehäuseabluft M8 |
| **FAN1** | **PC7** | Nicht belegt, Reserve |

BED/HE0/FAN0 sind MOSFET-Ausgänge, die **Minus schalten**. Die
STM32-Signalpins PC9/PC8/PC6 führen selber **keine 24 V**.
Am **BED+** liegen durchgeschleifte 24 V vom SKR-Netzteil an,
**BED−** wird beim Einschalten nach Netzteil-GND geschaltet.

## BED für den Laser: drei Leiter eindeutig zuordnen

```text
 SKR MINI MZ                       LaserTree LT-80W-AA-PRO
 BED + (24V, abgesichert)  ------>  ROT  VCC +24V
 BED - (MOSFET PC9)       ------>  SCHWARZ  Laser-GND
 PA1 (3,3-V-Logik) ---> [PWM-Optokoppler/Isolator] ---> GELB Laser-PWM
 SKR-GND -----------> [Eingangs-GND des Isolators]

 BED-/Laser-GND -------> [Ausgangs-GND des Isolators]
 5-V-Ausgangsspannung fuer den isolierten PWM-Treiber
 aus der geschalteten Laser-24-V-Seite (BED+ und BED-).
 Der isolierte Ausgang soll 0/5 V am gelben Draht erzeugen.
```

Der PA1-Anschluss ist auf dem **SKR Mini MZ V1.0 am PT-DET-Header**
herausgefuehrt. **Nicht** am normalen Servo-Header suchen; niemals
das +5-V-Bein des PT-DET-Headers mit dem PWM-Signal verwechseln.
Die grblHAL-Firmware nutzt PA1 als Hardware-PWM (STM32-Timer).

**Daher ja: VCC + GND des Lasers gehen direkt an die zweipolige
BED-Klemme des SKR.** Die gelbe PWM-Leitung braucht eine
galvanisch getrennte 5-V-Ansteuerung. Ursache: BED trennt Laser-GND
vom Netzteil-GND; ein direkter PA1–PWM-Draht könnte den
ausgeschalteten Lasertreiber über den GPIO rückspeisen.
Der Isolator darf die beiden Masse-Seiten nicht durchverbinden;
die Laserseite darf auch nicht über das Metallgehäuse oder andere
Kabel einen gemeinsamen Masse-Rückweg erhalten. Im stromlosen
Zustand mit Durchgangsprüfer zwischen Laser-GND, Metallgehäuse
und SKR-GND kontrollieren.

LaserTree-Daten: VCC 12/24 V, typische 24-V-Last etwa 1,5–2 A,
PWM-Eingang 0/3–12 V bis 5 kHz. Vor Anschluss des Lasers
BED-Ausgangspolarität, reale Schaltspannung, Optokoppler-Polung,
PWM-Pegel und Stromaufnahme messen. Leiter, Sicherung und
MOSFET-Wärme müssen für die tatsächliche Last ausgelegt sein.

## Schaltlogik im angepassten grblHAL

Im LumaCut-SKR-Build ist
`AUXOUTPUT2_PIN 9` = `SPINDLE_ENABLE_PIN PC9` statt PC7.

- **`M3 S0`**: BED an, PA1-PWM bleibt 0 %. Geeignet zum Vorversorgen.
- **`G4 P2`**: Zwei Sekunden Vorlauf für Laser-Treiber und internen Lüfter.
- **`M3 S500`**: BED bleibt an, PWM wird auf den gewählten S-Wert
  gestellt (Beispiel bei `$30=1000`).
- **`S0` bei weiterhin aktivem M3/M4**: Laserstrahl aus, **BED bleibt
  an**, damit der Laserlüfter bei Leerfahrten nicht ständig aus-/angeht.
- **`M5`**: PWM 0 und BED aus. Das ist ein expliziter
  Stromabschaltbefehl; dafür ist keine softwareseitige Nachlaufzeit
  garantiert.
- **`M7` / `M8`**: LEDs beziehungsweise Abluft separat einschalten.
  **`M9`** schaltet beide wieder aus.

Die Firmware hält die Stromversorgung innerhalb eines aktiven M3/M4
bei **S0** eingeschaltet. So kann LightBurn den Laserstrahl abschalten,
während der interne Kühllüfter weiterarbeitet.

### Passendes LightBurn-Profil

`lightburn/LumaCut-CNC-USB.lbdev` und der Live-Profildownload
vom HMI verwenden folgende Sequenzen:

**Start-G-Code:**
```gcode
G21
G90
M5
M8
M3 S0
G4 P2
```

**End-G-Code:**
```gcode
M3 S0
G4 P30
M5
M9
```

Beim regulären Ende bleibt BED während des 30-s-Nachlaufs versorgt,
ohne Laser-PWM. Falls ein LightBurn-Job selbst vorher `M5` sendet,
kann die Versorgung zwischenzeitlich abschalten; das Start- und
End-G-Code-Profil garantiert **nicht** die lückenlose Versorgung
bei beliebigem Fremd-G-Code und ersetzt keine thermische Überwachung.
Spezielle Pausen, `ALARM`, Not-Aus oder Neustart können den
Kühlungsnachlauf unterbrechen. Die Abfolge mit einer Prüflast testen,
bevor der Laserstrahl überhaupt zugeschaltet wird.

## Weitere 24-V-Ausgänge

- **HE0 → 24-V-LED-Streifen:** positiver Anschluss an HE0+,
  negativer an HE0−; M7 / LED-Taste am HMI und im Web.
- **FAN0 → 24-V-Abluftlüfter:** positiver Anschluss an FAN0+,
  negativer an FAN0−; M8 / Abluft-Taste am HMI und im Web.
- **FAN1 → frei** (PC7 wird durch den LumaCut-Build nicht als
  Laser-Stromfreigabe genutzt).

## Erste Inbetriebnahme ohne Laserenergie

1. SKR mit abgesichertem 24-V-Netzteil betreiben. LED- und Lüfterlasten
   separat auf Ausgangsleistung/Polung prüfen.
2. Vor Anschluss des Lasers zuerst mit einer geeigneten
   **24-V-Prüflast** an BED kontrollieren:
   nach `M5` 0 V Lastspannung; nach `M3 S0` 24 V;
   nach `G4 P2` weiterhin 24 V; nach `M5` wieder aus.
3. PWM-Isolator separat prüfen: **0 V bei S0 und M5**, 0–5-V-PWM
   bei S>0, Signalfrequenz maximal gemäß LaserTree-Spezifikation.
4. Sicherstellen, dass das Modulgehäuse, seine Luft-/Mechanikteile
   und eventuelle Anschlussadapter BED− nicht mit dauerhaftem
   Netzteil-GND verbinden.
5. Erst nach bestätigter Polarität, sicherer Einschaltreihenfolge,
   thermischer Versorgung/Nachkühlung und unabhängigen
   Interlocks den Laser elektrisch verbinden.

Dieser Aufbau wird in der Software vorbereitet, nicht als
hardwaregeprüfte Fertigmaschine behauptet.

## Fehlersuche: LaserTree-Leistung bleibt konstant

Der 24-V-BED-Ausgang ist nur die **Versorgung**. Er regelt nicht die
Laserleistung. Die optische Leistung wird vom separaten PWM-Eingang
des Moduls gesteuert. LaserTree spezifiziert 0–5 kHz PWM, je nach
Version 3–12 V beziehungsweise 5–12 V High-Pegel. Das HMI/SKR erzeugt
an PA1 maximal 3,3 V – je nach Eingang/Isolator zu wenig.

**Laser-Modul vollständig vom SKR trennen, keine Laserstrahlung
während der Messung.** Bei eingeschalteter SKR-Elektronik das
PWM-Signal direkt am echten PT-DET/PA1-Pin **gegen SKR-GND** messen
(nicht gegen den geschalteten BED-Minus). Sollwerte für DC-Mittelwert
bei 3,3-V-PWM sind ungefähr 0, 0,83, 1,65, 2,48, 3,3 V
bei S0/S250/S500/S750/S1000 und `$30=1000`.
Ein Oszilloskop ist für sichere PWM-Frequenz-/Tastgradmessung besser
geeignet als ein Multimeter.

Über die **LightBurn-Konsole / SKR-Seriellschnittstelle** zunächst
`$$` prüfen, insbesondere: `$9` PWM/Spindel-Optionen,
`$16` PWM/Enable-Polarität, `$30=1000`, `$31=0`,
`$32=1`, `$33=1000` (zum Test, maximal 5000),
`$34=0`, `$35=0`, `$36=100`.
Die jeweils gemeldeten Werte sind ausschlaggebend; bei bestehender
Anlage die Parameter vor einer Änderung dokumentieren.

Im stromlosen, abgesteckten Laserzustand können die folgenden
Befehle den PWM-Ausgang messbar beeinflussen:
```gcode
M3 S0
S250
S500
S750
S1000
M5
```
`M3` statt `M4` zur Diagnose verwenden, weil dynamische
M4-Laserleistung vom Fahrzustand abhängt. Wenn PA1 keine
veränderliche PWM liefert, liegt die Ursache im SKR-Pin,
der grblHAL-Konfiguration oder der Firmware.
Wenn PA1 variiert, der Laser bei korrekter, isolierter Ansteuerung
aber unveränderlich arbeitet, sind Signalpegel,
Laser-Massebezug, galvanische PWM-Isolation oder die
Laser-Treiberelektronik zu prüfen.

**PA1 darf bei BED-Low-Side-Schaltung nicht direkt mit Gelb PWM
verbunden werden**: Die Masse des Lasers auf BED− schwebt im
ausgeschalteten Zustand und könnte über PA1 gegen SKR-GND
rückgespeist werden.
