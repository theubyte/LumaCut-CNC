# Maschine

## Komponenten

| Teil | Typ |
|---|---|
| Steuerrechner | Raspberry Pi 400 (Raspberry Pi OS 64-bit), WLAN, `lumacut.local` |
| Controller | BTT SKR Mini MZ V1.0 (STM32F103RET6, TMC2209), eigene Firmware (`docs/FIRMWARE_EIGEN.md`, löst Marlin 2.1.2.9 ab), USB-CDC zum Pi |
| Laser | LaserTree LT-80W-AA-Pro (24 V, TTL/PWM-Eingang) |
| Mechanik | Arbeitsraum X 370 × Y 360 × Z 80 mm (mit Kopf v6 bis an die Enden gefahren, 31.10.; Park-Ecke X0–78 / Y0–35),  drei Motoren, drei Endschalter. **Z nie über 80 mm** (Tasterspitze über dem referenzierten Bett), darüber läuft der Kopf aus der Z-Linearschiene: harte Grenze in der Firmware, Pi-Z-Sperre, App. |

## Belegung SKR Mini MZ

Ausgänge laut `docs/FIRMWARE_EIGEN.md`:

| Funktion | Anschluss | STM32 | Befehl |
|---|---|---|---|
| Laser PWM | EXP3 (obere Reihe laut BTT-Plan: GND, PB8, PA10, **PA9**, PB5; PA9 + GND über Optokoppler, seit 05.11., vorher BL_Touch-Header PA1) | PA9 | `M3 I`, `G1 … S0–255`, `M5 I` |
| Laser-24-V-Versorgung + Lüfter | FAN1-Klemme | PC6 | `M106 P0 S255` / `M107 P0` (vom Pi gesteuert) |
| Licht (24-V-LED-Streifen, dimmbar) | HE0 | PC8 | `M355 S1 P0–255` (Hardware-PWM TIM8 ~1 kHz), `M355 S0` aus |
| Abluft | BED | PC9 | `M8` an, `M9` aus |
| frei (war Marlins Laser-Enable) | FAN2 | PC7 | **nicht verdrahten**, Pin bleibt hochohmig |

Motoren und Endschalter:

| Achse | Motorbuchse | STEP / DIR / EN | Endschalter |
|---|---|---|---|
| X | XM | PB13 / PB12 / PB14 | X-STOP PC0 |
| Y | YM | PB10 / PB2 / PB11 | Y-STOP PC1 |
| Z | ZAM (oder ZBM, nur eine) | PB0 / PC5 / PB1 | Z-STOP PC2 = auch Werkstücktaster |

Alle drei Endschalter ziehen den Pin gedrückt auf Low, ungedrückt liest er High. X/Y-Motorrichtung gegenüber dem Mega-Zero-Beispiel umgedreht (am Gerät geprüft), Z unverändert. Schritte/mm: X 80, Y 80, Z 1018,59 (Schneckenlift, der Pi setzt den Wert bei jeder Verbindung).

Hinweise zur Elektrik:
- Die MOSFET-Ausgänge (FAN1, HE0, BED) schalten **Minus**. Die Laser-Masse an FAN1− ist keine feste Logikmasse; PA9 darf deshalb nicht direkt an den Laser-PWM-Eingang. Dafür gibt es einen galvanisch getrennten PWM-Treiber.
- PC6 schaltet die Laserversorgung. Nach dem Einschalten wartet der Pi 800 ms, bevor `M3 I` kommt (sonst brennt die erste Linie schwach). Nach Jobende läuft die Versorgung 180 s nach (Kühlung), dann `M107 P0`. Dieser Nachlauf hängt am Pi, nicht an der Hardware.
- Ein unabhängiger Not-Aus für Laserversorgung und Motoren bleibt Pflicht.

## Koordinaten und Zonen

- Maschinen-Null: X0/Y0 = Homing-Ecke, Z0 = Taster berührt das leere Bett an X0/Y0 (der Pi referenziert erst X/Y, dann Z dort).
- Positives Z zeigt **vom Material weg**.
- Safezone: X < 30 oder Y < 30 bleibt frei. Schnitte (auch Bögen, geprüft über den Vollkreis) nur in X 30–390 / Y 30–370. Leerfahrten dürfen in die Safezone (Parken X0/Y0).
- Z-Untergrenze: Kein Z-Ziel unter Werkstückoberfläche + 2 mm.

## Z-Taster, Abtasten und Fokus

Der Z-Taster sitzt seitlich versetzt zum Laserpunkt. Ablauf G30 auf dem Pi:
1. Laser aus, Position abgleichen, Z mindestens auf Rückzughöhe (20 mm).
2. Kopf um den Tasterversatz verschieben, damit die Tasterspitze genau unter dem gewünschten Laserpunkt liegt.
3. `M400`, dann `G30`: Der Kopf sinkt bis zum Kontakt und bleibt dort stehen. Die Oberfläche steht in der Zeile `Bed X:… Y:… Z:…`. Kein Kontakt bis Z-2: `Error:Probing failed`; Taster schon gedrückt: `Error:Probe already triggered`.
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
| Z-Homing / G30 | 432 / 216 mm/min |
| Max. Vorschub X/Y/Z (Firmware) | 150 / 150 / 9 mm/s |
| Beschleunigung X/Y / Z | 500 / 100 mm/s² |

Die Firmware speichert nichts dauerhaft. Der Pi setzt bei jeder USB-Verbindung `M92 Z`, `M201`, `M203`, `M204` aus seinen Werten. `M203 Z` begrenzt die Firmware auf 9 mm/s; ein höherer `z_speed_mm_s` wirkt dort nicht.
