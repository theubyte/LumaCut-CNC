# LightBurn: ein Klick, wiederholtes Homing — aktuelle Übergangskonfiguration

## Stand
LumaCut Smart CAM hat nun eine **geometrische Vorschau für hochgeladenen G-Code**, aber noch keinen vollständigen LightBurn-TCP-Spooler / automatischen Höhenkarten-Ausführer.
**Nicht** behaupten, dass adaptive Abtastung, dynamischer Z-Fokus oder adaptive Multi-Pass-Zustellung heute schon aktiv sind.

## Vorläufiger Startcode in LightBurn Custom GCode
```gcode
G21
G90
M5 I
G28
G0 X120 Y120 F9000
G30
M8
M3 I
```
Achtung: X120/Y120 ist nur korrekt, wenn der Taster nach X/Y-Offset-Korrektur tatsächlich auf Material trifft. Der Startcode ersetzt keinen materialabhängigen Planer. Für andere Werkstückpositionen anpassen, bis automatische Koordinaten aus der Motivgeometrie implementiert sind.

## Endcode
```gcode
M5 I
M9
M2
```

Damit führt **jeder LightBurn-Job** bei Start zuerst G28 aus, ohne dass die Bedienperson getrennt referenziert. Der Pi führt G28 XY zuerst, dann Z und Rückzug aus. G30 misst danach einen Punkt. Firmware/Mechanik separat prüfen.

## Neue Motivvorschau
GCode über Webinterface hochladen, Auftrag auswählen, **Motivfläche analysieren** anklicken. Backend liefert X/Y-Bounds und ein Probe-Raster als Kandidaten, fährt diese aber noch nicht ab. Der Analysator verweigert G2/G3 bis Bogenextrema implementiert sind.

## Für den nächsten Implementierungsschritt
LightBurn streamt Befehle normalerweise direkt (ohne vollständige Geometrie am ersten G30). Nötig: TCP-Spooler mit einem klaren Jobende-Protokoll, vollständige Validierung/Geometrie, danach reale Proberasterfahrt und erst darauf folgende Laserbahnen. Keine falschen ACK für nicht ausgeführte Laserbefehle.

Die Probe-Punkte innerhalb der Bounding-Box dürfen nicht ungeprüft abgefahren werden: innenliegende Löcher, Konturrahmen und nicht vorhandenes Werkstück sind nicht automatisch belegt.
