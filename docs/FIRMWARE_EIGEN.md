# Eigene Firmware für den SKR Mini MZ (Vertrag zwischen Firmware und Pi)

Auftrag des Besitzers (05.11.2026): Marlin wird ersetzt durch eine eigene, saubere Firmware, die nur tut, was
LumaCut braucht. Kein Marlin-, kein Grbl-Code. Der Pi bleibt die Zentrale (STAND.md): Einstellungen, Grenzen,
Kalibrierung und Abläufe liegen dort, die Firmware speichert nichts dauerhaft.

Diese Datei ist der Vertrag. Weicht die Umsetzung ab, wird sie im selben Commit geändert.

## Ziel und Grenzen

- Sprache C (C11), Ordner `firmware/lumacut/`, Bau mit PlatformIO, Framework libopencm3 (Register und USB-Stack,
  kein Arduino, kein Maple).
- Die Eingabe bleibt eine schlanke G-Code-Teilmenge. So bleiben die Auftragsdateien der Apps und LightBurn über den
  Pi gültig. Alles, was hier nicht steht, wird mit `Error:Unknown command: <zeile>` abgelehnt, danach `ok`.
- Eine Zeile, ein Befehl. Kommentare `;…` und `(…)` werden ignoriert. Nur mm, nur `G21`.

## Hardware

Chip: **STM32F103RET6** (512 KB Flash, 64 KB RAM, eingelötet 02.11.), 72 MHz aus 8-MHz-Quarz. Der BTT-Bootloader belegt die ersten
28 KB, die Firmware startet bei `0x08007000` (Vektortabelle dorthin setzen). Marlin lief bisher als RC-Build (256/48 KB).

Quelle der Belegung: BTT-Plan des Mini MZ V1.0 vom Besitzer und `docs/MASCHINE.md`. **Marlins Datei
`pins_BTT_SKR_MINI_E3_common.h` beschreibt dieses Board nicht zuverlässig** (05.11. falsch geraten, EXP3 statt EXP1).

| Funktion | Pin | Hinweis |
|---|---|---|
| Laser-PWM | **PA9** (EXP3), TIM1 CH2 | 1 kHz, 0..255 ergibt 0..100 %. TIM1 ist Advanced: MOE setzen. Beim Start und bei jedem Fehler Low |
| Laser-24-V-Relais und Lüfter | PC6 (FAN1-Klemme) | Beim Start aus |
| Licht | PC8 (HE0), TIM8 CH3 | ~1 kHz dimmbar, beim Start aus |
| Abluft | PC9 (BED) | Beim Start aus |
| X STEP / DIR / EN | PB13 / PB12 / PB14 | EN aktiv Low |
| Y STEP / DIR / EN | PB10 / PB2 / PB11 | |
| Z STEP / DIR / EN | PB0 / PC5 / PB1 | |
| Endschalter X / Y / Z | PC0 / PC1 / PC2 | Gedrückt zieht den Pin auf Low, ungedrückt High (wie Marlin `*_ENDSTOP_INVERTING true`, am Gerät gemessen). Ein Drahtbruch liest sich als nicht gedrückt: Schalter vor jeder ersten Referenz prüfen. Z ist auch der Werkstücktaster |
| TMC2209 UART | UART4 TX PC10 / RX PC11 | Eindraht-Bus, Adressen aus dem BTT-Schaltplan oder Marlin 2.1.2.9 prüfen und im Code nennen |
| USB | PA11 / PA12, Pull-up PA14 | PA14 High = getrennt, Low = verbunden (Marlin `pins_BTT_SKR_MINI_E3_V2_0.h`, gilt für den MZ). SWD ist dafür abgeschaltet, Rettung über die SD-Karte. PC13 ist PS_ON und bleibt frei |

Richtungen gegenüber dem Motor: wie `firmware/marlin/build.py`: `INVERT_X_DIR false`, `INVERT_Y_DIR false`, `INVERT_Z_DIR true`.
Marlins „Y_DIR“ und Pegel genau nachvollziehen, die Laufrichtung am Gerät muss gleich bleiben. Motorströme, Mikroschritte (16) und
StealthChop/SpreadCycle aus dem Marlin-Beispiel „AnyCubic Mega Zero / BTT SKR Mini MZ V1.0“ (`Configurations` Tag `release-2.1.2.9`) übernehmen.
Pins PA1, PA8, PC7 bleiben unbenutzt (hochohmig). PA2/PA3 ebenfalls.

## Maschine (Grundwerte, Pi überschreibt zur Laufzeit)

| Wert | X | Y | Z |
|---|---|---|---|
| Schritte/mm | 80 | 80 | 1018,59 |
| Max. Vorschub mm/s | 150 | 150 | 9 |
| Max. Beschleunigung mm/s² | 500 | 500 | 100 |
| Weg mm | 0..390 | 0..370 | -2..80 |
| Referenzfahrt mm/min | 3000 | 3000 | 432 |

Z darf nie über 80 mm: harte Grenze in der Firmware, nicht änderbar. Bewegungen außerhalb des Wegs: `Error:Out of bounds`, kein Fahren.

Ohne Z-Referenz (nach Reset, `M999`, fehlgeschlagener `G28 Z`, geändertem `M92 Z`) ist die echte Höhe unbekannt: Z darf dann höchstens `Z_UNHOMED_LIFT_MM` (Vorgabe **25 mm**, `firmware/lumacut/src/config.h`, M115 meldet `Cap:Z_UNHOMED_LIFT:<mm>`) über die Stelle steigen, an der die Referenz verloren ging. `G92` verschiebt nur die Zahlen, das Budget bleibt an derselben Stelle. Der Rückzug von `G28` bei schon offenem Schalter zählt mit, ein klemmender Schalter endet also bei `Error:Homing failed`. Mit Z-Referenz gelten auch nach `G92` physisch -2..80 mm.

## Sicherheit (nicht verhandelbar)

1. Nach Reset, Watchdog, HardFault, M112, Fehler: PWM aus (Pin Low), Relais aus, Licht/Abluft aus, Bewegung sofort stopp. Fault-Handler schalten selbst direkt am Register.
2. Unabhängiger Watchdog (IWDG, ca. 2 s), nur in der Hauptschleife bedient; lange Vorgänge (Referenzfahrt, Taster) blockieren die Hauptschleife nicht.
3. M112 und M410 werden direkt beim Empfang ausgewertet, auch wenn die Warteschlange voll ist. M112 verriegelt bis `M999` oder Reset; solange antwortet die Firmware auf alles außer M115, M119, M999 mit `Error:Emergency stop`, danach `ok`.
4. Im Inline-Modus (`M3 I`) brennt der Laser nur während einer G1/G2/G3-Fahrt mit S>0. Die Leistung gehört zum Block und wird im Schritt-Interrupt beim Blockstart gesetzt. Läuft kein Block, ist das PWM 0. G0 ist immer 0.
5. Dauerleistung (`M3 S<n>` ohne I) nur im Stillstand, für das Service-Menü, ohne Zeitgrenze (Besitzer, 05.11.). Eine Fahrt beendet sie.
6. USB getrennt (kein DTR oder Bus-Reset) oder USB-Stille während Dauerleistung > 5 s: Laser aus. Jeder empfangene Befehl zählt, auch M114.
7. Endschalter wirken immer: Löst der Schalter der Fahrtrichtung aus (zum Minus-Ende), stoppen alle Achsen sofort, Laser aus, Warteschlange leer, Meldung `endstops hit: X:<mm> Y:<mm> Z:<mm>` mit den Achsen, die ausgelöst haben (Format: Pi-Regex `Z_ENDSTOP_HIT`). Vom Schalter wegfahren ist immer erlaubt. Ausnahme: Referenziertes X/Y läuft in den letzten 0,5 mm vor Null weiter, dort löst der Schalter beim Parken normal aus (`SWITCH_ZONE_MM`); die Referenzfahrt stoppt immer, Z ebenfalls. Der Schneckenlift drückt mit über 250 N.
8. Motorstrom an erst mit der ersten Fahrt, oder durch `M17`. `M84` nimmt ihn weg. Kein Selbstabschalten sonst.

## Befehle

Jede Zeile wird mit `ok P<freie Blöcke> B<freie Zeilen>` beantwortet, sobald sie angenommen ist (Fahrten: in der Warteschlange, nicht fertig).
Fehler: zuerst `Error:<text>`, dann `ok`. Die Warteschlange fasst mindestens 32 Blöcke, die Empfangsseite mindestens 16 Zeilen à 96 Zeichen.

| Befehl | Wirkung |
|---|---|
| `G0 [X][Y][Z][F]` | Leerfahrt, Laser 0. F modal getrennt von G1 |
| `G1 [X][Y][Z][F][S]` | Fahrt mit Leistung S 0..255 (modal, G0 setzt sie nicht zurück) |
| `G2`/`G3 [X][Y][I][J][F][S]` | Bogen, in der Firmware in Sehnen ≤ 0,1 mm Fehler zerlegt |
| `G4 P<ms>` / `G4 S<s>` | Warten, reiht sich in die Warteschlange, Laser nach Regel 4/5 |
| `G21`, `G90`, `G91` | mm, absolut, relativ. `G20` wird abgelehnt |
| `G92 [X][Y][Z]` | Position setzen, wartet auf Stillstand. Hebt keine Z-Grenze auf |
| `G28 [X][Y][Z] [R0]` | Referenzfahrt der genannten Achsen (ohne Achse: alle, erst Z, dann X, Y). Zum Schalter, 5 mm zurück, langsam (1/4) wieder hin, Position 0. Danach steht der Kopf am Schalter. `Error:Homing failed` bei Wegüberschreitung. Antwortet erst nach dem Ende, sendet alle 1 s `echo:busy: processing` |
| `G30` | Taster an der aktuellen XY: Z sinkt mit 216 mm/min bis zum Kontakt oder bis Z=-2, bleibt **am Kontakt stehen**. Antwort: `Bed X:<x> Y:<y> Z:<z>`, dann ok. Sonst `Error:Probing failed`, Kopf bleibt dort. Vorher Z-Schalter offen, sonst `Error:Probe already triggered` |
| `M3 I` / `M5 I` | Inline-Modus an / aus. `M5 I`: modale Leistung 0, wartet nicht auf die Warteschlange. Schon eingereihte Blöcke behalten ihre Leistung (Regel 4), damit das Ende eines Auftrags brennt; sofort dunkel machen `M410` und `M112` |
| `M3 S<n>` | Dauerleistung n im Stillstand, wartet auf leere Warteschlange. n=0 ist aus |
| `M5` | Laser aus (Dauerleistung und Inline-Leistung), Modus bleibt |
| `M106 P0 S<n>` / `M107 P0` | Relais an (n>0) / aus. Sofort, außer die Warteschlange läuft: dann erst danach |
| `M8` / `M9` | Abluft an / aus |
| `M355 S<0/1> P<0..255>` | Licht |
| `M17`, `M84` | Motorstrom an / aus, wartet auf Stillstand |
| `M92 [X][Y][Z]` | Schritte/mm zur Laufzeit, 1..5000, sonst `Error:Invalid value`. Ein geänderter Wert macht die Achse unreferenziert, derselbe Wert nicht |
| `M201 [X][Y][Z]`, `M203 [X][Y][Z]`, `M204 [P][T]` | Beschleunigung und Vorschub, nur im RAM. M203 Z wird auf 9 begrenzt |
| `M114` | `X:<x> Y:<y> Z:<z> Count X:<n> Y:<n> Z:<n>`: geplante Endposition. Darf PWM und Schritte in keiner Weise stören |
| `M115` | `FIRMWARE_NAME:LumaCut CNC <version> (<__DATE__> <__TIME__>) MACHINE_TYPE:LumaCut CNC` und `Cap:Z_PROBE:1`, `Cap:SELF_UPDATE:1`, `Cap:Z_UNHOMED_LIFT:<mm>` |
| `M119` | `Reporting endstop status`, dann `x_min: open`/`TRIGGERED`, gleich für y und z |
| `M122` | TMC-Register (Strom, Mikroschritte, Fehler) je Achse als Text, Diagnose |
| `M300 S<Hz> P<ms> [X][Y]` | Motorton ohne Fahrt wie `firmware/marlin/motor_tone.cpp` (neu geschrieben). Nur im Stillstand mit Laser aus. S0 = Pause, höchstens 2 s |
| `M400` | Antwortet, wenn die Warteschlange leer und alle Achsen stehen |
| `M410` | Sofort: Bewegung stopp, Laser aus, Warteschlange leer. Position neu gültig aus den Schrittzählern, Referenz bleibt |
| `M112` | Sofort: Notstopp, siehe Sicherheit |
| `M999` | Notstopp quittieren. Referenz ist danach ungültig |
| `M997 U<bytes> C<crc32>` | Selbst-Update, siehe unten |

Nicht mehr nötig und entfallen: M21, M28, M30, M105, M120, M402, M503, M851, M7, M593, G54, M2. Der Pi schickt sie nicht mehr; M2/M30/G54/M7/G17/G40 aus LightBurn filtert der Pi.

## Bewegung

Lookahead-Planer mit Trapezprofilen und Kurvengeschwindigkeit (Junction Deviation 0,05 mm), Bresenham im Schritt-Interrupt mit Hardware-Timer, unterbrechungsfrei für TIM1. Bis 15 kHz Schritte je Achse. Lange Rasterzeilen mit kurzen Segmenten dürfen nicht stocken: Die Warteschlange läuft leer, wenn der Pi nicht schnell genug liefert; dann bremst der Planer normal. Rundungsfehler dürfen sich nicht aufsummieren: Zielposition in ganzen Schritten führen.

Der Planer hält 50 ms fertig geplante Blöcke vor. Endet trotzdem ein Block mit Geschwindigkeit, ohne dass der nächste fertig ist (Hauptschleife blockiert): harter Halt, Laser aus, Warteschlange leer, alle Achsen unreferenziert, `Error:Planner underrun`. Vor einer Fahrt aus dem Stillstand prüft die Firmware höchstens einmal je Sekunde `GSTAT.reset` der Treiber. War einer stromlos: Treiber neu einstellen, alle Achsen unreferenziert, `Error:Driver reset`, die Fahrt entfällt. Der Pi behandelt beide Fehler als Referenzverlust.

Keine Eingabeformung im ersten Stand (war bei Marlin aus).

## Selbst-Update

`M997 U<bytes> C<crc32>` antwortet `ok READY <chunk>`. Dann kommen `<chunk>` Bytes roh, je Block `ok <offset>`. Der Empfang landet im oberen Flash ab `0x08040000`; nach Abschluss CRC prüfen, Kennung `LumaCut CNC` im Abbild prüfen, Antwort `ok DONE`, dann USB trennen, Routine aus dem RAM kopiert nach `0x08007000`, Reset. Größe höchstens 196 KB, Flash-Größe im Register `0x1FFFF7E0` prüfen. Bei Stromausfall im Kopieren bleibt die SD-Rettung (`firmware.bin` auf die Karte, BTT-Bootloader). Der Bootloader wird nie angefasst. Nur im Stillstand, Laser aus, Relais aus. Im Rohmodus des Empfangs werden M112 und M410 nicht erkannt: Die Bytes sind Teil des Abbilds, die CRC verwirft es. Nach 10 s ohne Daten geht die Firmware in den Zeilenbetrieb zurück.

Erste Installation: `firmware.bin` per SD-Karte (mit dem Besitzer vor Ort). Rückweg: Marlin-Release `marlin-62` ebenfalls per SD.

## Versionen und Release

`firmware/lumacut/version.h`. Workflow `.github/workflows/lumacut-fw.yml` baut bei Änderungen unter `firmware/lumacut/` und führt die Host-Tests aus, Artefakt `firmware.bin` und `manifest.json` im gleichen Aufbau wie bisher. Solange die Firmware nicht auf der Maschine geprüft ist: **kein Release, das der Pi anbietet.**

## Inbetriebnahme (mit dem Besitzer)

Jeder Schritt braucht ein Go; ohne Laserdiode beginnen, Service-Regler erst danach.

1. Per SD flashen, `M115`, `M119` (Schalter von Hand betätigen), USB-Stabilität.
2. Relais, Licht, Abluft einzeln.
3. PA9 messen: 0, 50, 100 % ohne Diode, dauerhaft stehend während `M114` läuft (Flackern!).
4. Motoren je Achse: kurz in Plusrichtung, Richtung prüfen, Schritte/mm mit Maßband.
5. G28 einzeln: Z zuerst mit Hand am Not-Aus, dann X, Y.
6. G30 auf dem Bett, Wiederholgenauigkeit.
7. Auftrag ohne Laser (S0), dann auf getestetem Material nach Materialtest.
