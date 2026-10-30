# LumaCut: aktueller Stand

Diese Datei ist der eine Ort für „was gilt gerade“. Sie wird nach jeder
Änderung nachgezogen. Was wann gemacht wurde, steht im
[CHANGELOG](../CHANGELOG.md); Einzelheiten zum Pi stehen in
[PI_STATUS_UND_OFFENE_PUNKTE.md](PI_STATUS_UND_OFFENE_PUNKTE.md).

Stand: 30.10.2026

## Maschine heute

- Rahmen Atomstack A5 Pro, 10-W-Diodenlaser LT-80W-AA-PRO, SKR Mini MZ mit
  Marlin 2.1.2.9, Pi 400 unter `192.168.2.89:8080` als Zentrale.
- **Kopf v6 ist eingebaut** (Z über Zahnstange, Kamera und Taster fahren
  mit, Reibbremse). Die Software ist noch auf den alten Kopf eingestellt –
  siehe „In Arbeit“.
- Bremse: greift, seit die Vorspannschraube angezogen ist (30.10.).
- GY-521 (Beschleunigungssensor) sitzt im Kopf, ist aber nicht angeschlossen.

## Software heute

- Pi-Dienst `lumacut-marlin` auf `main` (zuletzt `6cc2826`), neu gestartet
  am 30.10.; Merkmale u. a. `projects` (Projektablage) und Regler für gleiche
  Schwärze.
- Android-App 1.0.49 liegt auf dem Pi zum Update bereit.
- Windows-Studio ruht, bis die Android-App fertig ist.

## Zuletzt erledigt

- 29./30.10.: Projekte auf dem Pi speichern und öffnen; Regler für gleiche
  Schwärze (nie unter 8 %); Sperrholz-Werte korrigiert; Einladungskarte
  Smaragd neu aufgebaut (Füllung statt Umrisslinien) und gelasert.
- Ältere Einträge: [CHANGELOG](../CHANGELOG.md).

## In Arbeit: Umstellung auf Kopf v6

Reihenfolge, jeder Schritt erst, wenn der vorige an der Maschine passt.
Fahrten, Messungen und Flashen nur mit dem Besitzer daneben.

1. **Taster tiefer als die Düse.** Der Knopf saß zu hoch, die Laserdüse
   berührte das Material zuerst. Entscheidung: gedruckter Hut auf den Knopf
   (nicht Sensorless-Antasten über den Motor: drückt die Düse mit Motorkraft
   ins Material, ungenauer, und der Knopf ist zugleich Z-Endschalter).
   - [x] Bremse greift (Vorspannschraube)
   - [ ] Hut drucken (Besitzer druckt eigenen Entwurf)
   - [ ] Messen: Tasterspitze unter Düsenspitze, Ziel etwa 2 mm, höchstens
         5 mm (Fokus liegt 7 mm unter der Düse)
   - [ ] Wert im Pi eintragen (`probe_tip_offset_mm`, heute 1,5)
2. **Firmware für v6:** Z-Schritte 380 → 80 (GT2 20 Z, 40 mm/Umdrehung),
   Z-Tempo und Antast-Tempo neu, Z-Motor nie abschalten.
3. **Fahrwege messen:** echter X- und Y-Weg mit dem neuen Kopf (Y lief schon
   mit dem alten Kopf bei etwa 350 statt 370 an), Kopfmaße für das Parkband.
4. **Neue Aufteilung der Fläche (Pi zuerst, dann App und Web):**
   - Die 30-mm-Zone in L-Form entfällt.
   - Neu: **Parkband** über die ganze X-Breite auf der Y-Referenzseite, so
     tief wie der Kopf + 10 mm. Dort wird referenziert und geparkt; dort
     liegt nie Material.
   - Alles andere ist Arbeitsfläche; Editor, Kamerabild, Rahmen, Scan und
     Import zeigen genau diese Fläche.
   - Randstreifen, die der Laser erreicht, Taster/Kamera aber nicht, werden
     angezeigt statt still gesperrt.
5. **Parken nach jedem Auftrag:** Laser aus → hoch → ins Parkband → absenken,
   bis der Taster das Bett berührt; Z-Motor bleibt bestromt. Vor dem nächsten
   Auftrag erst hoch, dann raus.
6. **Kamera neu kalibrieren** (fährt jetzt mit Z mit).
7. **G-Code-Optimierer auf dem Pi** für jeden Auftrag (auch LightBurn):
   Innenteile vor Außenkontur, weniger Leerfahrten, Geradenstücke zu Bögen
   (weniger Zeilen, flüssigere Fahrt), leere Rasterzeilen überspringen,
   genaue Restzeit.

## Danach

- GY-521 anschließen (VCC 3,3 V, GND, SDA, SCL, INT; verdrilltes Kabel):
  Schwingung messen und Input Shaping selbst einstellen, Abrutschen von Z und
  Stöße erkennen.
- Weitere offene Punkte des Pi:
  [PI_STATUS_UND_OFFENE_PUNKTE.md §4](PI_STATUS_UND_OFFENE_PUNKTE.md#4-offene-punkte).

## Ideen (noch nicht geplant)

- Infrarot-LEDs im Kopfgehäuse als Licht für die Kamera.
