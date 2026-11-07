# LumaCut Studio: Test am echten Pi

Ablauf für den ersten Test der nativen Windows-App an der echten Maschine. Stufe 0 läuft ohne Besitzer und nur lesend.
Ab Stufe 1 ist der Besitzer vor Ort. Vor jeder Fahrt und jedem Lasern gilt: „Hände raus, Deckel zu, Brille – starten?“,
und erst sein Go löst den Auftrag aus, auch wenn die App schon einen eigenen Go-Dialog zeigt. Einzelne Jog-Schritte brauchen keine Rückfrage.

## Vor dem Termin

- Während des Tests steuert nur diese App die Maschine: keine andere Sitzung, kein Tablet, kein LightBurn. Status muss `Idle` und Besitzer `Frei` sein.
- MSI [windows-0.2.9](https://github.com/theubyte/LumaCut-CNC/releases/download/windows-0.2.9/LumaCut-Studio.msi) oder neuer installieren. Unsigniert: SmartScreen warnt, „Weitere Informationen“, „Trotzdem ausführen“.
- Hand am Netzschalter der Maschine. Die Tablet-App bleibt als Rückweg bereit, deinstalliert wird über die Windows-Einstellungen.

## Stufe 0: nur lesen (ohne Besitzer möglich)

```bash
python software/lumacut-native/tools/pi_readonly_check.py
```

Die App spricht dabei nur mit einer Sperre auf diesem PC. Die reicht GET auf einer festen Liste an den Pi durch und weist alles andere ab.
Das Kamerabild ist nicht auf der Liste, weil jede Aufnahme am Pi die LEDs einschaltet. Braucht Python mit dem Standardumfang.

Stand 07.11.2026, Pi-Software `3963bd6b5`, Firmware 0.2.6: bestanden. Position, Zustand, Referenz, Kalibrierstand, Bettkarte, Materialien und das
gemeinsame Projekt (Revision 401) kommen richtig an, kein Schreibversuch, am Pi hat sich nichts geändert.

## Stufe 1: Verbindung, ohne Bewegung

| Schritt | Erwartung |
|---|---|
| Optionen: Pi-Adresse `http://192.168.2.89:8080` | Anzeige oben wie am Tablet |
| Projekt ansehen | Dasselbe Projekt wie am Tablet. **Ab der ersten Änderung geht es an alle Geräte**, darum vorher „Auf dem Pi speichern“ |
| Licht an und aus, Helligkeit | Stimmt am Gerät und am Tablet |
| Abluft an und aus | Läuft wirklich |
| Maschine, Kamera | Live-Bild, LEDs gehen an und danach zurück |

## Stufe 2: Fahren, Laser aus

| Schritt | Erwartung |
|---|---|
| Kopf von Hand prüfen: frei, Bett leer. Go. Referenzieren | X/Y an die Schalter, dann Z, Meldung „referenziert“. Der Pi fragt heute nicht nach der Kopfhöhe (`home_needs_confirm` aus) |
| Jog 0,1 / 1 / 10 mm, je Achse beide Richtungen | Pfeil und Fahrtrichtung stimmen von der Tür gesehen, Anzeige folgt, Maß mit Lineal bei 10 mm |
| Go. Zu Position X100 Y100 | Stimmt mit dem Tablet überein |
| Go. Zu Position, dabei Abbrechen | Hält an, App bleibt bedienbar |
| Go. Parken | Park-Ecke X370 Y35 |
| Go. Langsame Fahrt, dabei NOT-AUS in der App | Sofort Stillstand, „Not-Aus aktiv“. Quittieren, danach neu referenzieren |

## Stufe 3: kleiner Auftrag

Nur auf MDF 3 mm, dafür sind Werte gemessen. Ein anderes Material erst nach eigenem Leistungstest und OK des Besitzers.
Eine neue Platte oder eine verschobene wird vor dem Auftrag neu abgetastet.

| Schritt | Erwartung |
|---|---|
| Material „MDF (hell)“, Rechteck 20 × 10 mm Gravieren, mitten auf der Platte, außerhalb des Sperrstreifens | Vorschau und Zeitschätzung plausibel, Prüfungen grün |
| Go. Rahmen | Umriss liegt auf der Platte. Es kann ein schwacher Laserpunkt laufen (0,5 %), darum nie über Kunststoff |
| Go. Starten | Referenz, Abtasten, Lasern, Parken laufen durch, Fortschritt läuft, Abluft nach Einstellung |
| Ergebnis ansehen und messen | Lage und Größe auf 0,5 mm |
| Zweites Rechteck daneben, Go, während des Laufs Abbrechen | Laser sofort aus (`laser_armed` nein), kein Brennfleck beim Wegfahren |

Stufe 3 prüft den Weg der App, nicht die Gravurqualität: Die Bildkette und der Hin/Rück-Ausgleich bei 1050 mm/s² sind eigene offene Punkte in `STAND.md`.

## Sofort abbrechen, wenn

- die Richtung nicht zum Pfeil passt, eine Anzeige vom Gerät abweicht oder die App etwas ohne Go startet,
- der Laser außerhalb eines Auftrags leuchtet oder die Maschine auf den NOT-AUS nicht sofort reagiert,
- die App einfriert, während sich etwas bewegt: dann Not-Aus an der Maschine, Tablet übernimmt.

Danach wird nichts weitergetestet, bis die Ursache geklärt ist.

## Darauf besonders achten

- **Not-Aus quittieren:** Der Pi lehnt das ab, solange noch ein Besitzer eingetragen ist („Steuerung belegt“). Das passt zu der einen Zeitüberschreitung im Simulator, belegt ist es nicht. Am echten Gerät notieren, ob ein zweiter Klick nötig ist.
- **Besitzer bleibt stehen:** Im Simulator blieb nach einem abgelehnten `op=home` ohne `clear=1` der Besitzer auf `web` stehen. Die App schickt `clear` mit, wenn der Pi danach fragt.
- **Schrittverlust in Y:** Der echte Y-Weg ist kürzer als früher angenommen. Nicht an die Grenze joggen.

## Was dieser Test nicht abdeckt

Werkstatt, Platine, Arbeitsplatz-Scan und Platzieren per Kamera gibt es nativ noch nicht. Das Tablet bleibt dafür zuständig.

## Protokoll

Für jede Stufe festhalten: Datum, App-Version, Pi-Software, Firmware, bestanden oder Abweichung, Foto vom Ergebnis. Das Ergebnis kommt in `WINDOWS_APP.md`.

## Ergebnis 07.11.2026 (Besitzer vor Ort, App 0.2.9, Pi `3963bd6b5`, Firmware 0.2.6)

- **Stufe 0:** bestanden (siehe oben).
- **Stufe 1:** laut Besitzer alles wie erwartet. **Abweichung:** Die Sicherung „Auf dem Pi speichern“ kam nie an. Im Pi-Log steht kein `POST /api/projects`, nur fünf Abrufe der Liste. Das gemeinsame Projekt ging dadurch von Revision 401 auf 413 ohne Sicherung. Ursache offen: Dialog ohne Bestätigen geschlossen oder Fehler in der App.
- **Stufe 3 (vor Stufe 2 gelaufen):** Rahmen und zwei Aufträge aus der App, der große mit 67.874 Zeilen, Gravur 25 % / 3000 mm/min plus Kontur 100 % / 150 mm/min. Hin/Rück-Ausgleich und Höhenkorrektur griffen. Der Besitzer sieht keinen Versatz in Lage oder Form.
  Danach meldete der Pi um 09:32 „X-Schalter offen an X0/Y0“ und um 09:36 einen USB-Abbruch zum SKR. Beides ist ungeklärt, auf der Gravur ist keine Folge zu sehen.
  Der Pi lehnte um 09:03 eine Z-Fahrt ohne Werkstückhöhe ab, obwohl die App Z dann sperren sollte. Außerdem lehnte er einen Abtastpunkt außerhalb von X10..360/Y10..350 ab, den die App nicht vorher gesperrt hatte.
- **Stufe 2:** laut Besitzer Referenz, Jog, Zu Position, Abbrechen, Parken, NOT-AUS, Quittieren und erneute Referenz wie erwartet. Den NOT-AUS kann das Pi-Log nicht belegen, denn es schreibt keine Aktionsnamen.
- **Nebenbei:** Die Abfrage des nicht vorhandenen Auftrags „Materialtest Gravur“ um 09:50 kam von 127.0.0.1, also vom Bedienpanel am Pi, nicht von der App.
- **Abbruch im laufenden Auftrag:** Laut Besitzer ging der Laser beim Abbrechen sofort aus. Im Pi-Log steht nach 09:16 kein weiterer Auftrag aus der App. Zu sehen sind von 09:57 bis 10:00 rund 40 Aktionen vom Windows-PC und ein Materialtest Gravur MDF mit 7 Schritten. Was abgebrochen wurde, ist noch zu klären. Ein Abbruch-Test an einem Auftrag Er wartet auf den Umbau des Z-Antriebs: Der Taster streute am 07.11. an derselben Stelle zwischen 1,36 und 5,72 mm, damit ist der Autofokus nicht verlässlich (`STAND.md`).

**Nacharbeiten in der App:** Speichern auf dem Pi prüfen, Z-Sperre gegen Tastatur und Zustandswechsel, Abtasten außerhalb des erlaubten Bereichs vorher sperren.
