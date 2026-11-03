# LumaCut Bedienpanel (Firmware)

Firmware für das **Waveshare ESP32-S3-Touch-LCD-7** (Rev 1.2, 800 × 480,
GT911-Touch, ESP32-S3 N16R8) im hellen Design aus
`hardware/display-7zoll/design/mockup_weiss.html`.

Das Panel ist nur eine weitere Oberfläche wie Web-App und Android-App. Jede
Aktion geht an die Pi-API, der Pi prüft sie (Besitzer, Referenz, Freigabe,
G-Code-Wächter). Gegenstück auf dem Pi: `pi400/marlin/panel.py`, läuft im
Dienst `lumacut-marlin` mit.

## Anschluss

- USB-C-Buchse **„USB“** des Panels → USB des Pi. Ein Kabel für Strom und Daten.
  Die Buchse „UART1“ ist nur die Konsole (Protokoll beim Entwickeln).
- Kein WLAN, kein Passwort auf dem Panel.
- Der Pi erkennt das Panel an der Espressif-Kennung (303a) und hält es nie für
  das SKR (`grbl_bridge.open_controller` überspringt es).

## Bildschirme

| Bildschirm | Inhalt | Aktionen (Pi-`op`) |
| --- | --- | --- |
| Status | Fortschrittsring, Restzeit, Datei, Laufzeit/Zeile, Position, Laserleistung und Vorschub (aus der Auftragsdatei), Laser/24 V/Abluft/Referenz | – |
| Bewegen | Kreuz X/Y (wie von vorne gesehen: X+ links, Y+ nach vorne), Z, Schrittweite 0,1/1/10 mm | `jog`, `home` (Mitte), `park`, `probe` („Fokus tasten“) |
| Kamera | Livebild der Kopfkamera (640 × 480, ca. ein Bild je 1–2 s) | `frame_job` (Rahmen), Zoom, `light`, `exhaust` |
| Auftrag | Aufträge auf dem Pi, Auswahl | `frame_job`, **Laser starten** = `autorun` nach Freigabe-Popup |
| immer rechts | **STOPP** (sofort, ohne Rückfrage), Pause/Weiter (nur Warteschlange), Abbruch | `estop`, `queue_pause`, `queue_run`, `abort` |

- **Laser starten:** Popup „Laser freigeben?“ mit Datei und dem Hinweis
  „Hände raus · Deckel zu · Schutzbrille auf“; erst „Freigeben“ sendet `autorun`.
  Ist die Kopfhöhe unbekannt, steht das im Popup, die Freigabe bestätigt dann
  auch `clear=1`.
- **Referenzfahrt** ohne bekannte Kopfhöhe fragt „Kopf ist frei?“ (`clear=1`).
- **Notstopp aktiv:** roter Hinweis mit „Notstopp quittieren“ (`estop_reset`).
- **Keine Verbindung:** Hinweis; STOPP bleibt bedienbar. Das Software-STOPP
  ersetzt den echten Not-Aus nicht.
- Einzelaufträge kennen auf dem Pi kein Pausieren; Pause/Weiter wirken nur auf
  die Warteschlange und sind sonst ausgegraut.

## Protokoll (USB, JSON-Zeilen)

Siehe Kopf von `pi400/marlin/panel.py`. Kurz: Panel → Pi `hello`, `ping`
(jede Sekunde, `cam` 1 = Kamerabildschirm offen), `jobs`, `act`; Pi → Panel
`st` (Status alle 0,5–1 s), `res` (Antwort mit deutschem Text vom Pi), `jobs`,
`img` (Kopfzeile + JPEG-Bytes). Der Pi lässt nur die Aktionen in
`panel.ACTIONS` und deren Felder durch.

## Bauen und Flashen

```
python -m platformio run                 # baut .pio/build/panel/firmware.bin
python -m platformio run -t upload --upload-port COMx   # erstes Flashen am PC
```

Erstes Flashen am PC, am sichersten über die Buchse **„UART“** (CH343, Auto-Reset).
Ein Abbild zum direkten Flashen ab 0x0 (z. B. vom NAS):
`esptool --chip esp32s3 write_flash 0x0 lumacut-panel.bin`.

**Updates über den Pi:** `PANEL_VERSION` in `src/version.h` hochzählen, dann
`tools/release.sh` (baut und legt App-Image + `manifest.json` nach
`pi400/marlin/panel_fw/`), committen, auf den Pi deployen. Die Panel-Brücke sieht
die ältere Version im Ping und flasht das Panel im Leerlauf selbst mit esptool
über die Buchse „USB“ (ab 0x10000, Bootloader bleibt). Abschaltbar in der
Web-Oberfläche (System → Bedienpanel); dort auch „Panel jetzt aktualisieren“.
Schlägt es fehl, startet das Panel evtl. nicht mehr: dann über den Knopf erneut
oder am PC über „UART“ flashen.

Schriften: `tools/gen_fonts.sh` (Inter 4.0, JetBrains Mono 2.304, FontAwesome 5
aus LVGL; lv_font_conv 1.5.2). Umlaute und „ “ – − sind enthalten.

## Vorschau am PC

`sim/build.sh` baut LVGL und `src/ui.c` für Windows/Linux (Compiler: `pip install
ziglang`) und schreibt die Bildschirme mit Beispieldaten nach `sim/out/*.png`.
So lässt sich die Oberfläche ohne Panel prüfen.

## Stand

Gebaut und am PC gerendert, **noch nicht auf dem echten Panel getestet**
(Display-Timing und Touch stammen aus der Waveshare-Demo).
