# LumaCut CNC · 24-V-Ausgänge und Laser-Ansteuerung

**Hardware:** BTT SKR Mini MZ V1.0 (STM32F103RC) mit grblHAL auf
`main`, Waveshare ESP32-S3-Touch-LCD-7 Rev1.2 und LaserTree
LT-80W-AA-PRO. Die Pinbelegung wurde mit dem
`generic-bigtreetech-skr-mini-mz.cfg` von Klipper und dem
originalen BigTreeTech-Marlin-Boardprofil geprüft.

**Wichtig:** PC6, PC7, PC8, PC9 sind MCU-GPIOs mit 3,3 V Logik.
Die gleichnamigen Klemmen FAN0, FAN1, HE0, BED sind mit
Low-Side-Leistungs-MOSFETs verbunden. Nie 24 V an einen freiliegenden
STM32-Pin legen. Die positive Versorgung der 2-poligen
Ausgänge kommt von der 24-V-Eingangsschiene.

## Stromversorgung und Pins

| Klemme | MCU-Ausgang | LumaCut-Aufgabe | GRBL-Funktion |
| --- | --- | --- | --- |
| Servo/Z-PROBE-Signal | PA1 (3,3-V-Signal, nicht 24 V) | Laser-PWM (0..1000) | M3/M4, S |
| FAN1 | PC7 (Low-Side) | Nur Steuereingang für externen High-Side-Laser-24V-Schalter | Spindle Enable |
| FAN0 | PC6 (Low-Side) | 24-V-Abluftlüfter | M8 / Flood, Echtzeit-Toggle 0xA0 |
| HE0 | PC8 (Low-Side) | 24-V-Kabinen-LEDs | M7 / Mist, Echtzeit-Toggle 0xA1 |
| BED | PC9 (Low-Side) | Nicht verwendet; Reserve | keine |

Die Board-Firmware schaltet beide Coolant-Funktionen mit
`COOLANT_ENABLE=3` frei. Die LED-Ansteuerung übernimmt M7, die
Abluft M8. M9 deaktiviert **beide** Kanäle gleichzeitig. Die
HMI-/Webbuttons senden stattdessen **getrennte grblHAL
Echtzeit-Toggles** und lesen den echten `|A:...`-Status aus:
`A:M` LED, `A:F` Abluft. Damit wird LED ein/aus nicht durch einen
blind gesendeten M9-Befehl mit dem Lüfter verwechselt. Der SKR ist
alleinige Quelle für die Ausgangszustände.

## Leistungsklemmen ohne Kurzschluss anschließen

```text
                          24-V-Netzteil
                           +24 V  0 V
                             |     |
            +----------------+     +---------------------+
            |                |                           |
          Sicherung        Sicherung                    Masse
            |                |                           |
    24-V-LED-Streifen(+)  Abluftlüfter(+)          Laser-GND (ständig)
    LED-Streifen(-)       Abluftlüfter(-)              |
            |                |                         |
         HE0 / PC8         FAN0 / PC6            LaserTree 3-polig
             [MOSFET schaltet Minus]               VCC  GND  PWM
                                                       ^        ^
    24 V (+), eigener abgesicherter Zweig --------------|        |
      über externen, DC-tauglichen HIGH-SIDE-Kontakt K1-+        |
                                                                |
               SKR PA1 (3,3-V-TTL) ------------------------------+
               Nur nach Überprüfung des PWM-Signalpegels!

    FAN1 / PC7 ---- 24-V-Schalt-/Relaissteuereingang K1
                   (kein direkter Laser-GND-Rückleiter!)
```

Bei Relais mit einer Spule: diese muss für 24 V geeignet sein, eine
Freilaufdiode/Schutzbeschaltung besitzen, und der Eingangs-/
Spulenstrom muss innerhalb der FAN1-Ausgangsleistung liegen.
Kontaktseite K1 muss die **Gleichstromlast** des Lasermoduls
inklusive Einschaltstrom zuverlässig schalten. Alternativ eignet
sich ein dafür ausgelegter MOSFET-High-Side-Schalter.

LaserTree LT-80W-AA-PRO laut Hersteller: 24 V bei etwa
1,5–2 A, Lasersteuerung am gelben PWM-Draht, schwarzer GND,
roter 24-V-VCC. Das 3,3-V-PWM-Signal der SKR-Logik liegt am
unteren Rand der 3–12-V-Spezifikation. Vor Freigabe wird
PWM-High/Low direkt am Eingang gemessen und überprüft, dass
PWM=0 bzw. stromloser SKR **niemals** den Laser einschaltet.

**Nicht so verdrahten:** Die rote und schwarze Laser-Versorgung
einfach zwischen VIN+ und FAN1-/HE0- schalten, während PWM
mit einer gemeinsamen Platinenmasse verbunden bleibt. Dadurch
würde die Laser-Masse im Aus-Zustand schweben und möglicherweise
über die PWM-Signalleitung unerwünscht rückgespeist.

## Laser nur bei Job, aber mit Vorlauf und Nachkühlung

Die vorhandene grblHAL-Firmware setzt mit `SPINDLE0_ENABLE=
SPINDLE_PWM0_NODIR` den PC7-Spindle-Enable-Ausgang
bei aktiver Spindel-/Laseransteuerung. Das ist **keine**
fertige sichere Stromversorgungsschaltung für LaserTree:

- Der LaserTree-Hersteller verlangt, dass die Betriebsspannung
  vorhanden ist, bevor PWM-Leistung ausgegeben wird.
- LightBurn kann M3/M4 und S0 an mehreren Stellen eines Jobs
  ausgeben. Die Laser-Stromversorgung darf bei Leerfahrten
  oder 0 % PWM nicht fortlaufend hart ein- und ausgeschaltet
  werden. Ein externes Halte-/Verzögerungsmodul oder eine
  weitere Freigabestufe muss die Versorgung vorab aufbauen,
  die PWM-Freigabe erst **danach** erlauben und die
  Nachkühlung des Lasermoduls gewährleisten.
- Die Laserenergie benötigt darüber hinaus einen unabhängig
  wirksamen Not-Aus, Schlüssel- und Gehäuse-Interlock;
  eine HMI-Taste oder ein 24-V-MOSFET ist keine
  sicherheitsgerichtete Abschaltung.

Die erzeugten LightBurn-USB-Profile senden `M8` bereits zu
Jobbeginn und am Jobende `M5`, dann `G4 P30` (30 s
Abluftnachlauf) und `M9`. Dies automatisiert die **Abluft**,
nicht die sichere Schaltfolge des Lasermoduls. Beim manuellen
HMI-/Webjob sollte der Bediener den Lüfter vor dem Start
einschalten und nach dem Abzug der Rauchgase ausschalten.
Die optionale 30-s-Nachlaufzeit gilt daher im Augenblick
nur bei Verwendung des neuen LightBurn-Geräteprofils.

## Vor Anschluss unbedingt prüfen

1. Netzteil 24 V; Gesamtbedarf = Laser (bis ca. 2 A) +
   Schrittantriebe + 24-V-LED-Last + Abluftlüfter +
   Elektronik + Einschaltspitzen. Die verfügbaren
   Ströme der konkreten **FAN0/FAN1/HE0-Ausgangs-MOSFETs**
   müssen anhand des Board-Schaltplans und der tatsächlichen
   angeschlossenen Last überprüft werden.
2. Jeden 24-V-Zweig separat passend absichern,
   Leitungsquerschnitt und Polung prüfen, Schrankgehäuse erden.
3. Erst ohne Lasermodul LED und Lüfter getrennt testen
   (`M7/M8/M9` / HMI / Web), dabei Spannung und Polung
   am Ausgang mit Multimeter prüfen.
4. PC7-Freigabe und PA1-PWM zunächst ausschließlich mit
   Messgerät oder geeigneter Prüflast testen; anschließend
   externe Einschalt-/Abschaltsequenz und Interlocks nachweisen.
5. Mit physisch getrenntem Laserstrom Homing, LightBurn
   und automatische Lüftersteuerung prüfen; erst danach
   einen kontrollierten Lasertest durchführen.

**Status:** Firmware-Zuordnung und HMI-/Webbedienung sind
implementiert, aber **nicht elektrisch auf der realen Maschine
verifiziert**. Die Laser-Versorgungsfreigabe ist als externe
High-Side-Schaltung ausdrücklich noch nicht fertig aufgebaut.
