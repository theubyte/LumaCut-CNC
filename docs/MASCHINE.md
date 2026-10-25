# Maschine

## Komponenten

| Teil | Typ |
|---|---|
| Steuerrechner | Raspberry Pi 400 (Raspberry Pi OS 64-bit), WLAN, `lumacut.local` |
| Controller | BTT SKR Mini MZ V1.0 (STM32F103RC, TMC2209), Marlin 2.1.2.9, USB-CDC zum Pi |
| Laser | LaserTree LT-80W-AA-Pro (24 V, TTL/PWM-Eingang) |
| Mechanik | Arbeitsraum X 390 × Y 370 × Z 90 mm, drei Motoren, drei Endschalter |

## Belegung SKR Mini MZ

Ausgänge laut `firmware/marlin/build.py` (`PIN_PATCH`):

| Funktion | Anschluss | STM32 | Befehl |
|---|---|---|---|
| Laser PWM | PT-DET-Header (über PWM-Isolator) | PA1 | `M3 I`, `G1 … S0–255`, `M5 I` |
| Laser-24-V-Versorgung + Lüfter | FAN1-Klemme | PC6 (Marlin FAN0) | `M106 P0 S255` / `M107 P0` (vom Pi gesteuert) |
| Licht (LED) | HE0 | PC8 | `M7` an, `M9` aus |
| Abluft | BED | PC9 | `M8` an, `M9` aus |
| Laser-Enable (Marlin-Pflicht) | FAN2 | PC7 | **nicht verdrahten** |

Motoren und Endschalter:

| Achse | Motorbuchse | STEP / DIR / EN | Endschalter |
|---|---|---|---|
| X | XM | PB13 / PB12 / PB14 | X-STOP PC0 |
| Y | YM | PB10 / PB2 / PB11 | Y-STOP PC1 |
| Z | ZAM (oder ZBM, nur eine) | PB0 / PC5 / PB1 | Z-STOP PC2 = auch Werkstücktaster |

Alle drei Endschalter sind Öffner (in der Firmware invertiert). X/Y-Motorrichtung gegenüber dem Mega-Zero-Beispiel umgedreht (am Gerät geprüft), Z unverändert. Schritte/mm: X 80, Y 80, Z 380.

Hinweise zur Elektrik:
- Die MOSFET-Ausgänge (FAN1, HE0, BED) schalten **Minus**. Die Laser-Masse an FAN1− ist keine feste Logikmasse; PA1 darf deshalb nicht direkt an den Laser-PWM-Eingang. Dafür gibt es einen galvanisch getrennten PWM-Treiber.
- PC6 schaltet die Laserversorgung. Nach dem Einschalten wartet der Pi 800 ms, bevor `M3 I` kommt (sonst brennt die erste Linie schwach). Nach Jobende läuft die Versorgung 180 s nach (Kühlung), dann `M107 P0`. Dieser Nachlauf hängt am Pi, nicht an der Hardware.
- Ein unabhängiger Not-Aus für Laserversorgung und Motoren bleibt Pflicht.

## Koordinaten und Zonen

- Maschinen-Null: X0/Y0 = Homing-Ecke, Z0 = Taster berührt das leere Bett an X0/Y0 (Z-Homing über den Taster an der Safe-Homing-Position 0/0).
- Positives Z zeigt **vom Material weg**.
- Safezone: X < 30 oder Y < 30 bleibt frei. Schnitte (auch Bögen, geprüft über den Vollkreis) nur in X 30–390 / Y 30–370. Leerfahrten dürfen in die Safezone (Parken X0/Y0).
- Z-Untergrenze: Kein Z-Ziel unter Werkstückoberfläche + 2 mm.

## Z-Taster, Abtasten und Fokus

Der Z-Taster sitzt seitlich versetzt zum Laserpunkt. Ablauf G30 auf dem Pi:
1. Laser aus, Position abgleichen, Z mindestens auf Rückzughöhe (20 mm).
2. Kopf um den Tasterversatz verschieben, damit die Tasterspitze genau unter dem gewünschten Laserpunkt liegt.
3. Marlin-`G30`. Die Oberfläche ist die Höhe, auf der der Taster schaltet.
4. Anheben auf max(20 mm, Oberfläche + 2 mm), zurück auf den Laserpunkt.

Fokus (vor der ersten Laserbewegung, automatisch): `Z = Oberfläche + Fokusabstand − Schalter→Laserspitze`.

### Aktuelle Kalibrierwerte (Pi, Stand 25.10.2026)

Gespeichert in `/var/lib/lumacut/marlin/config.json`, änderbar in der Web-UI unter „Fokus & Taster“:

| Wert | Einstellung |
|---|---|
| Tasterversatz X / Y (Tasterspitze relativ zum Laserpunkt) | −23,0 / +15,0 mm |
| Schalter → Laserspitze | 1,5 mm |
| Fokusabstand Laserspitze → Material | 7,0 mm |
| Rückzug nach Homing | 20,0 mm |
| Mechanik-Freigabe | erteilt |

Beispiel: Oberfläche Z = 3,0 mm → Fokus Z = 3,0 + 7,0 − 1,5 = 8,5 mm, tiefstes erlaubtes Z = 5,0 mm.

## Geschwindigkeiten

| | Wert |
|---|---|
| XY-Leerfahrt (Pi setzt F9000, wenn kein F angegeben) | 150 mm/s |
| Z-Fahrten des Pi | 600 mm/min |
| Z-Homing / G30 schnell / G30 langsam | 432 / 432 / 216 mm/min |
| Max. Vorschub X/Y/Z (Firmware) | 150 / 150 / 9 mm/s |
| Beschleunigung X/Y / Z | 500 / 100 mm/s² |

Der EEPROM des SKR enthielt alte Werte (u. a. M203 Z6). Der Pi setzt deshalb bei jeder USB-Verbindung `M203 Z9` und `M851 X0 Y0 Z0`, nur zur Laufzeit, ohne Schreiben ins EEPROM.
