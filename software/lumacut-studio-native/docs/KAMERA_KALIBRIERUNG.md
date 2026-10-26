# Kamera-Kalibrierung für den Kachel-Scan (`camera.json`)

Der Scan setzt viele Kamerabilder bei **fester Höhe** zu einem vermessenen Bettbild
zusammen. Damit das Mosaik millimetergenau auf dem Canvas liegt, braucht Studio
einmalig die Kalibrierwerte der Kopf-Kamera. Sie gehören zur Maschine und liegen **auf dem Pi**
(`/etc/lumacut/camera_calibration.json`, `GET/PUT /api/camera/calibration`, Details in
[KAMERA_STATUS_UND_KALIBRIERUNG.md](KAMERA_STATUS_UND_KALIBRIERUNG.md#3a-kalibrierung-auf-dem-pi-speichern)).
Gemessen wird in eine `camera.json` (gleiches Format), die im Scan-Panel über **„Importieren …"**
geladen und mit **„Auf Pi speichern"** auf die Maschine übertragen wird (Modus „Maschine (Pi-API + Kamera)").
Im Modus „Simulation (ohne Hardware)" wird eine eingebaute Beispielkalibrierung oder eine importierte
`camera.json` benutzt.

Zurück zur Übersicht: [SCAN_PROBE.md](SCAN_PROBE.md)

## Welche Werte gebraucht werden

| Feld | Bedeutung | Wie ermitteln |
|---|---|---|
| `image_width`, `image_height` | Aufnahmeauflösung in Pixel. Studio fordert genau diese Auflösung an; Verzeichnung gilt nur für diese Größe. | Feste Auflösung wählen (z. B. 1280×720), nicht die Maximalauflösung, wenn die Kamera dabei langsamer wird. |
| `px_per_mm` | Maßstab **auf der Bettoberfläche bei `scan_z`**. | Lineal/gelasertes Raster fotografieren, Pixelabstand ÷ mm (Schritt 4). |
| `scan_z` | Feste Maschinen-Z-Höhe beim Scan (mm). Muss über allen Werkstücken liegen. | Typisch 40 mm. Nicht ändern ohne neu zu kalibrieren – der Maßstab hängt davon ab. |
| `offset_mm` `[dx, dy]` | Position der **Bildmitte relativ zum Laserpunkt** in Maschinenkoordinaten (mm). | Fadenkreuz lasern, Kopf verfahren, bis es in Bildmitte liegt (Schritt 5). |
| `rotation_deg` | Drehung des Kamerabilds gegenüber den Maschinenachsen (Grad, gegen den Uhrzeigersinn). | Aus der gelaserten Linie (Schritt 6). |
| `flip_x`, `flip_y` | `+1`/`-1`: Spiegelung. `flip_y = 1`, wenn Bildzeilen nach unten mit Maschinen‑+Y wachsen. | Kopf in +X/+Y joggen und beobachten, wohin das Bild wandert (Schritt 3). |
| `crop_fraction` | Anteil am Bildrand, der verworfen wird (Vignettierung/Restverzeichnung), 0–0,4. | Standard 0,04; bei starker Randunschärfe 0,08–0,12. |
| `camera_matrix` | 3×3 Kameramatrix aus `cv2.calibrateCamera` (optional). | Schachbrett-Kalibrierung (Schritt 2). |
| `dist_coeffs` | Verzeichnungskoeffizienten `[k1, k2, p1, p2, k3]` (optional). | Schachbrett-Kalibrierung (Schritt 2). |
| `exposure` | Feste Belichtung (Wert für `CAP_PROP_EXPOSURE`, treiberabhängig; DirectShow meist −13…−1, V4L2 z. B. 50–500). `null` = Automatik. | Mit Auto-Belichtung starten, dann den Wert festlegen, bei dem helles Holz nicht ausbrennt. |
| `comment` | Freier Text (optional, wird ignoriert). | – |
| `format` | Muss `"lumacut-camera-calibration/1"` sein. | – |

**Feste Belichtung, fester Weißabgleich und fester Fokus** sind wichtig: Sonst hat jede
Kachel eine andere Helligkeit und das Mosaik zeigt Kanten. Autofokus-Kameras auf
manuellen Fokus stellen (scharf bei `scan_z`).

### Koordinatenmodell

```
Maschine(x, y) = Kopf(x, y) + offset_mm + R(rotation_deg) · diag(flip_x, flip_y) · (Pixel − Bildmitte) / px_per_mm
```

„Kopf" ist die Laserpunkt-Position zum Aufnahmezeitpunkt. Der Taster hat einen eigenen
Versatz (X −23 / Y +15), den rechnet der Pi selbst – er gehört **nicht** in `camera.json`.

## Beispiel `camera.json`

```json
{
  "format": "lumacut-camera-calibration/1",
  "comment": "USB-Kamera 1280x720, kalibriert 2026-10-25, scan_z 40",
  "image_width": 1280,
  "image_height": 720,
  "px_per_mm": 5.12,
  "scan_z": 40.0,
  "offset_mm": [31.5, -18.2],
  "rotation_deg": 0.6,
  "flip_x": 1,
  "flip_y": 1,
  "crop_fraction": 0.05,
  "camera_matrix": [[1043.2, 0.0, 641.7], [0.0, 1041.8, 358.9], [0.0, 0.0, 1.0]],
  "dist_coeffs": [-0.312, 0.118, 0.0004, -0.0007, -0.021],
  "exposure": -6
}
```

Die Zahlen sind **Platzhalter** – die echte Kamera muss nach dem Ablauf unten vermessen
werden. Ohne Verzeichnungsdaten (`camera_matrix`/`dist_coeffs` = `null`) funktioniert
der Scan auch, die Kacheln passen dann am Rand schlechter zusammen.

Erzeugen/prüfen per Python:

```python
from scanprobe import CameraCalibration
cal = CameraCalibration(1280, 720, px_per_mm=5.12, scan_z=40, offset_mm=(31.5, -18.2))
cal.save("camera.json")
print(CameraCalibration.load("camera.json").usable_fov_mm)   # nutzbares Sichtfeld in mm
```

## Ablauf Schritt für Schritt

Voraussetzung: Maschine gehomt, Not-Aus frei, Laser **aus** außer in Schritt 5/6,
Schutzbrille bei Laserbetrieb.

1. **Kamera festlegen.** Auflösung wählen, Autofokus/Auto-Belichtung/Auto-Weißabgleich
   aus. Kamera fest am Kopf montieren – jede Verschiebung erfordert eine neue Kalibrierung.
   `image_width`/`image_height` eintragen.
2. **Linsenverzeichnung (optional, empfohlen bei Weitwinkel).** Schachbrett (z. B. 9×6
   Innenecken, 10 mm Felder) drucken, flach auf eine Platte kleben, 15–25 Bilder aus
   verschiedenen Winkeln/Positionen in der gewählten Auflösung aufnehmen:

   ```python
   import cv2, glob, numpy as np, json
   pattern, square = (9, 6), 10.0
   objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
   objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square
   obj, img = [], []
   for f in glob.glob("schachbrett/*.png"):
       g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
       ok, c = cv2.findChessboardCorners(g, pattern)
       if ok:
           c = cv2.cornerSubPix(g, c, (11, 11), (-1, -1),
                                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))
           obj.append(objp); img.append(c)
   rms, K, dist, _, _ = cv2.calibrateCamera(obj, img, g.shape[::-1], None, None)
   print("RMS", rms)          # gut: < 0,5 px
   print(json.dumps({"camera_matrix": K.tolist(), "dist_coeffs": dist.ravel().tolist()}))
   ```

   Ausgabe in `camera.json` übernehmen. Studio entzerrt mit derselben Kameramatrix,
   der Maßstab aus Schritt 4 bleibt dadurch gültig – Schritt 4 aber **nach** dem
   Eintragen der Verzeichnung messen (am entzerrten Bild).
3. **Scanhöhe und Spiegelung.** Kopf auf `scan_z` (z. B. 40) fahren. Kopf 10 mm in +X
   joggen: wandert der Bildinhalt nach **links**, ist `flip_x = 1`, sonst `-1`. 10 mm in +Y:
   wandert der Inhalt nach **oben**, ist `flip_y = 1`, sonst `-1`.
4. **Maßstab `px_per_mm`.** Ein Stahllineal (oder ein gelasertes 100 mm-Quadrat) auf das
   Bett legen, Bild aufnehmen (entzerrt, falls Schritt 2 gemacht), Pixelabstand zweier
   weit auseinanderliegender Marken messen: `px_per_mm = Pixel / mm`. In X und Y messen;
   weichen sie > 1 % ab, Kamera schräg montiert → nachjustieren.
5. **Versatz Kamera → Laser (`offset_mm`).** Auf einem Probestück an Position
   (Lx, Ly) ein kleines Fadenkreuz lasern (Kopf dabei auf Fokus = Oberfläche + 5,5).
   Kopf auf `scan_z` heben und joggen, bis das Kreuz genau in der Bildmitte liegt; Kopfposition
   (Hx, Hy) ablesen. Dann `offset_mm = [Lx − Hx, Ly − Hy]`.
   Wichtig: Z nie unter Oberfläche + 2 mm.
6. **Rotation `rotation_deg`.** Eine 100 mm lange Linie entlang Maschinen‑X lasern, im Bild
   den Winkel gegen die Bildhorizontale messen (`atan2(dv, du)` in Grad, Vorzeichen so, dass
   das Bild danach achsparallel ist). Typisch < 2°.
7. **Belichtung.** Hellstes und dunkelstes Material aufs Bett legen, `exposure` so wählen,
   dass beide Zeichnung haben. Eintragen.
8. **Prüfen.** In Studio Modus „Maschine (Pi-API + Kamera)", Kamera-Quelle eintragen (USB-Index `0`
   oder Stream-URL), `camera.json` importieren und „Auf Pi speichern", „Scan starten". Das Mosaik muss auf dem Canvas
   deckungsgleich mit einem gelaserten Testmuster liegen (Abweichung < 0,5 mm). Bei
   konstantem Versatz `offset_mm` korrigieren, bei wachsendem Fehler zum Rand `px_per_mm`
   oder Verzeichnung.

Nach jedem Umbau am Kopf (Kamera, Laser-Modul, Halter) Schritte 3–8 wiederholen.
