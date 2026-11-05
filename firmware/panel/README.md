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
| Status | Fortschrittsring, Restzeit, Datei, Laufzeit/Zeile, wartende Aufträge, Position, Laserleistung und Vorschub (aus der Auftragsdatei), Laser/24 V/Abluft/Referenz | – |
| Bewegen | Kreuz X/Y (wie von vorne gesehen: X+ links, Y+ nach vorne), Z, Schrittweite 0,1/1/10 mm, Hinweis, warum gesperrt | `jog`, `home` (Mitte), `park`, `probe` („Fokus tasten“) |
| Kamera | Livebild der Kopfkamera (640 × 480, ca. ein Bild je 1–2 s) | `frame_job` (Rahmen), Zoom, `light`, `exhaust` |
| Auftrag | Aufträge auf dem Pi, Auswahl, Material (eigene Liste) | `material`, `frame_job`, **Laser starten** = `autorun` |
| System → Licht & Abluft | Licht an/aus und 10–100 %, Abluft, Bildschirm-Aus-Zeit | `light` (`on`, `brightness`), `exhaust`, `screen_off` |
| System → Ereignisse | Die letzten 30: Start, Ende, Fehler, Notstopp, Verbindung, Referenz verloren, abgelehnte Aktionen. Roter Punkt am Menü = neue Warnung | – |
| System → Info | Adresse, WLAN, Name, Versionen, Verbindung, Update-Hinweise | `panel_update` |
| immer rechts | **STOPP** (sofort, ohne Rückfrage), Pause/Weiter (nur Warteschlange), Abbruch | `estop`, `queue_pause`, `queue_run`, `abort` |

- **Go vor jedem Fahr- oder Laserauftrag:** Referenzfahrt, Parken, Fokus tasten,
  Rahmen, Laser starten und „Weiter“ (Warteschlange) fragen im Popup mit „Hände
  raus · Deckel zu · Schutzbrille auf“; erst die Bestätigung sendet die Aktion.
  Einzelne Jog-Schritte fragen nicht: der Bediener steht an der Taste, je Schritt
  höchstens 10 mm, der nächste erst nach der Antwort des Pi. Wird die Maschine
  belegt oder geht die Verbindung weg, verschwindet ein offenes Go von selbst.
- **Laser starten** zeigt Datei und Material und geht erst mit gewähltem Material.
  Ist die Kopfhöhe unbekannt, steht das im Popup, die Freigabe bestätigt dann
  auch `clear=1`; `clear` gilt nur, wenn die Frage das wirklich gesagt hat.
- **Material:** dieselbe Wahl wie in Web und App (`PUT /api/workspace`), nur
  Einträge aus `/api/materials`, nur im Leerlauf (prüft `panel.py`). Die Stärke
  setzt die Fahrhöhe; Leistung und Tempo stehen im Auftrag. Reine Startwerte sind
  in der Liste als „Startwert, erst testen“ markiert.
- **Rahmen:** Ist `frame_power_pct` auf dem Pi gesetzt, sagt das Popup, dass der
  Laser dabei glimmt.
- **Bildschirm aus** (Nie, 2, 5, 15, 30 min, Standard 15; gespeichert auf dem Pi
  in `panel.json`): Solange die Maschine arbeitet, belegt ist, der Laser scharf
  ist oder keine Verbindung besteht, bleibt er an, und ein Auftrag von einem
  anderen Gerät weckt ihn. STOPP liegt damit nie hinter einem Weck-Tipper. Die
  Berührung, die ihn weckt, löst sonst nichts aus. Dunkel holt das Panel auch
  kein Kamerabild.
- Das Panel kann **nicht:** Service-Menü (`service_*`), Laser-Regler, roher
  G-Code. `panel.ACTIONS` lässt nur die Aktionen dieser Tabelle durch;
  `tests/test_panel.py` hält die Liste und den Quellcode dagegen fest.
- **Hardware:** Die Hintergrundbeleuchtung hängt am Schaltausgang EXIO2 (nur an/aus,
  `board.c`), `board.c` kennt auch keinen Summer. Darum gibt es weder Helligkeit
  noch Ton in den Einstellungen.
- **Notstopp aktiv:** roter Hinweis mit „Notstopp quittieren“ (`estop_reset`).
- **Keine Verbindung:** Hinweis; STOPP bleibt bedienbar. Das Software-STOPP
  ersetzt den echten Not-Aus nicht.
- Einzelaufträge kennen auf dem Pi kein Pausieren; Pause/Weiter wirken nur auf
  die Warteschlange und sind sonst ausgegraut.

## Protokoll (USB, JSON-Zeilen)

Siehe Kopf von `pi400/marlin/panel.py`. Kurz: Panel → Pi `hello`, `ping`
(jede Sekunde, `cam` 1 = Kamerabildschirm offen), Abfragen `jobs`, `mats`,
`events`, `sys`, und `act`; Pi → Panel `st` (Status alle 0,5–1 s), `res` (Antwort
mit deutschem Text vom Pi), `jobs`, `mats`, `events`, `sys`, `img` (Kopfzeile +
JPEG-Bytes). Der Pi lässt nur die Aktionen in `panel.ACTIONS` und deren Felder
durch. Eine Zeile hat höchstens 8000 Bytes (`panel.LINE_LIMIT`); Listen werden
dafür gekürzt, Auftragsnamen über 95 Bytes nicht angezeigt.

Adresse, WLAN und Pi-Stand liest die Brücke auf dem Pi selbst (Socket,
`iwgetid`, `/proc/net/wireless`, `git log`), weil die API dafür keine Felder hat;
fehlt etwas, zeigt das Panel „–“. Ereignisse leitet sie aus `/api/status` ab und
hält sie im Speicher: Ein Neustart des Dienstes leert die Liste.

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
aus LVGL; lv_font_conv 1.5.2), `--icons` nur für die Symbole. Umlaute und „ “ – −
sind enthalten.

## Vorschau am PC

`sim/build.sh` baut LVGL und `src/ui.c` für Windows/Linux (Compiler: `pip install
ziglang`) und schreibt die Bildschirme mit Beispieldaten nach `sim/out/*.png`.
So lässt sich die Oberfläche ohne Panel prüfen. Das Programm geht auch die Regeln
für Bildschirm-Aus und das Zurücknehmen eines Go durch und schreibt das Ergebnis
auf die Konsole. Ein Stand der Bilder liegt in `preview/`.

## Stand

Gebaut und am PC gerendert, **noch nicht auf dem echten Panel getestet**
(Display-Timing und Touch stammen aus der Waveshare-Demo).
