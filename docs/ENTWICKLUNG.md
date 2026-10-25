# Entwicklung

## Tests

```bash
# Pi-Dienst und Firmware-Update (Python 3.11+, keine Hardware nötig)
python -m pip install Flask pyserial
LUMACUT_DATA=$(mktemp -d) python -m unittest discover -s tests -v

# LumaCut Studio (Node 18+)
cd software/lumacut-studio && npm install && npm run test:unit && npm run test:ui
```

Was die Tests abdecken:
- `tests/test_marlin_gateway.py`: Sicherheitsregeln (Safezone, Z-Untergrenze, Laserfreigabe), Homing, G30-Auswertung, LightBurn-Präambel, ein Ein-Klick-Lauf gegen einen simulierten Marlin.
- `tests/test_firmware_flash.py`: Marlin-Binärprotokoll gegen ein Gerätemodell nach `binary_stream.h`, kompletter Update-Ablauf, Fehlerfälle.
- `tests/test_marlin_usb_detect.py`, `test_pi_update_script.py`, `test_smart_cam.py`: Port-Erkennung, Installer, Updater, Motivgrenzen.
- `software/lumacut-studio/*.test.mjs`: Geometrie, Planer, Marlin-Postprozessor, Kamera-Kalibrierung. `ui-smoke.mjs` testet die ausgelieferte Oberfläche in Chrome/Edge.

Unter Windows Python mit `PYTHONUTF8=1` starten (Umlaute in Quelltexten).

## CI (GitHub Actions)

| Workflow | Auslöser | Prüft |
|---|---|---|
| `ci.yml` | `pi400/`, `tests/`, `firmware/marlin/` | alle Python-Tests, Kompilierung, `bash -n` der Skripte |
| `marlin.yml` | `firmware/marlin/` | baut die SKR-Firmware, legt `firmware.bin` als Artefakt ab |
| `lumacut-studio-windows.yml` | `software/lumacut-studio/` | Node-Tests, UI-Smoke-Test, Windows-Installer (NSIS) |

## Firmware lokal bauen (Windows)

Lange Pfade brechen den Marlin-Clone ab. Bewährt:

```bash
export PLATFORMIO_CORE_DIR=A:/mfw/pio TMP=A:/mfw/tmp TEMP=A:/mfw/tmp
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.longpaths GIT_CONFIG_VALUE_0=true
python firmware/marlin/build.py --output A:/mfw/dist --cache-dir A:/mfw/up
```

Der erste Lauf lädt Marlin und die STM32-Toolchain (einige Minuten), danach dauert ein Build etwa 35 s.

## Zugriff auf den Pi

- SSH mit Schlüssel als `lumacut@192.168.2.89`. Passwörter gehören nicht ins Repository.
- `/opt/lumacut` gehört `lumacut`, Git geht also ohne sudo. Für einen Dienst-Neustart braucht es sudo, oder eine eng begrenzte sudoers-Regel nur für `systemctl restart lumacut-marlin.service`.
- Deploy ohne GitHub-Zugang siehe [PI_BETRIEB.md](PI_BETRIEB.md#updates).

## Regeln für Änderungen

- Alles auf `main`. Commit-Message mit **Was** und **Warum**. Hardware-Belege (Logzeilen, Messwerte, Marlin-Quelltextstelle) mit hineinschreiben.
- Sicherheitslogik gehört auf den Pi (`transport.py`), nicht in Studio. Studio fragt nur Aktionen an.
- Nie eine Datei komplett aus einer älteren Kopie neu schreiben, ohne mit dem aktuellen Stand zu vergleichen. Am 25.10.2026 ging so `safe_home()` verloren und Homing war tot.
- Neue Marlin-Annahmen am Quelltext 2.1.2.9 prüfen (`Marlin/src/…`), nicht raten.
- Pfad `pi400/marlin/` und die Dienstnamen nicht umbenennen. Der nächtliche Updater auf dem Pi verlässt sich darauf.

## Bekannte offene Punkte

- Rastergravur über Marlin: Der Pi sendet eine Zeile und wartet auf das `ok`. Für feine Graustufen ist das vermutlich zu langsam. Messen, dann mehrere Zeilen gleichzeitig senden (`ADVANCED_OK`) und gleiche Pixel zusammenfassen.
- Graustufen und Overscan fehlen im Studio-Raster (bisher schwarz/weiß).
- Kamera auf dem Pi (Aufnahme, Kachel-Scan, Zusammensetzen) fehlt.
- Y-Ausrichtung Studio (Y nach unten) ↔ Maschine an einem Testmotiv prüfen.
- Web-API ohne Zugangsschutz: Vor der Tablet-App eine Gerätekopplung einbauen.
