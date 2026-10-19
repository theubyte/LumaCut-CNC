# Homing, Werkstückabtastung, Fokus und Höhenkompensation

## Unterschiedliche Referenzsysteme
- **Homing:** X/Y/Z-Referenzendschalter bestimmen Maschinenkoordinaten. Separater Z-Schalter zwingend; Werkstücktaster ist kein Endschalter.
- **Probing:** mechanischer Taster am Laserkopf bestimmt Werkstückoberfläche. Laser-Hardware muss dabei energielos sein.
- **Autofokus:** Der Laser wird mit Fokusabstand über der gemessenen Oberfläche positioniert.
- **Höhenkarte:** viele Oberflächenpunkte, anschließend interpolierte Z-Bahn nur nach Freigabe implementieren.

## Geometrie
Laser-Mitte L=(Lx,Ly); Taster-Sensorpunkt P=(Lx+dx,Ly+dy). Für Messpunkt M=(Mx,My) ist
L=(Mx-dx, My-dy). Jedem Abtastpunkt geht eine Grenzprüfung für Laserzentrum UND Tastpunkt voraus.

Ein gemeinsamer optischer Bezugspunkt O definiert den positiven Z-Abstand. Wenn der ausgelöste Tastertip bei Abstand t=6 mm unter O liegt und der Laserfokus f=45 mm Abstand zu O verlangt, ist die relative Verfahrbewegung nach Kontakt f-t=+39 mm (nur Beispiel).
Für abweichende Schaltergeometrie muss der Bezugspunkt einschließlich Schaltweg und ggf. Materialnachgiebigkeit konsistent neu kalibriert werden. Der Algorithmus enthält nur Mathematik, **keine Motorfreigabe**.

## Antast-Reihenfolge
Hardware-Laser sperren, aktive Bewegung beenden; Referenzlage/Koordinaten validieren; Z sicher anheben; offset-korrigierte XY-Position mit Kollisionsprüfung anfahren; Taster-Zustand prüfen; langsames Abtasten G38.x; zügig retract; erneut feiner Antasten, sofern entsprechende Controllerunterstützung verifiziert; Fokusposition berechnen; Z-Limits prüfen; positionieren; neue Messung mit Datum, Tasterversion und Temperatur speichern.

## Höhenkarte
Raster in Schlangenlinie; 2–30 Punkte pro Achse als Planungsgrenze. Berücksichtige versetzten Taster und Randzonen; Werkstückgrenzen, Klemmen und Hubweg separat prüfen. Fehlerhafte Probes stoppen Messung. Spätere Interpolation benötigt Bewegungsplanung und LightBurn-Kompatibilität; nicht ungeprüft Z während Laserauftrag manipulieren.

## Unbedingt noch messen
dx, dy, Triggerabstand, optischer Fokusabstand, Trigger-Wiederholbarkeit, zulässiges Überfahren, Retract, Homingrichtung und maximale Probe-Fahrstrecke. Werte gehören versioniert in config/laser.yaml, Hardware-Validierungen getrennt von Nutzerprofilen.