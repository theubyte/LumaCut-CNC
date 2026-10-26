# LumaCut CNC

Eigene Laser-Steuerung für die LumaCut-Maschine: Raspberry Pi 400 als Steuerrechner, BTT SKR Mini MZ V1.0 mit Marlin 2.1.2.9 als Bewegungs- und Lasercontroller, dazu eigene Software: **LumaCut für Android** (Tablet-App) und **LumaCut Studio** (Windows). Ziel ist, LightBurn vollständig abzulösen.

```
 LumaCut Android (Tablet) · Studio (Win)  Browser
            │  HTTP :8080 (Pi-API)           │
            ▼                                ▼
 ┌────────────────── Raspberry Pi 400 ──────────────────┐
 │ pi400/marlin: Web-UI + API, Sicherheitsregeln,       │
 │ Homing/Abtasten/Fokus/Park, Jobausführung,           │
 │ Firmware-Update des SKR        (TCP :23 für LightBurn,│
 │                                 nur Übergangsphase)   │
 └───────────────────────┬──────────────────────────────┘
                         │ USB (eine Zeile, ein "ok")
                         ▼
        BTT SKR Mini MZ V1.0 · Marlin 2.1.2.9 (firmware/marlin)
        X/Y/Z-Motoren · Endschalter · Z-Taster · Laser PWM · Licht · Abluft
```

**Der Pi ist die einzige Stelle, die die Maschine kennt.** Safezone, Homing-Reihenfolge, Z-Untergrenze, Fokus und Laser-Freigaben werden dort durchgesetzt, egal ob ein Befehl aus Studio, dem Browser oder LightBurn kommt.

## Verbindliche Abläufe

- Homing: **X/Y zuerst**, dann Z, dann Rückzug auf 20 mm (einstellbar).
- 30-mm-Safezone in L-Form (X < 30 oder Y < 30) bleibt werkstückfrei; Schnitte nur bei X ≥ 30 und Y ≥ 30. Parkpunkt X0/Y0.
- Werkstückoberfläche per G30 mit dem Z-Taster; Fokus standardmäßig 7 mm über dem Material.
- Laser: PA1 PWM, Marlin `M3 I` (Inline-Modus), S 0–255. Licht `M7` (HE0/PC8), Abluft `M8` (BED/PC9).
- Motor-Melodien nach erfolgreichem Homing und nach Jobende.
- Ein-Klick-Ablauf: Homing → Abtasten → Fokus → Auftrag → Park.

## Repository

| Pfad | Inhalt |
|---|---|
| `pi400/marlin/` | Pi-Dienst: `transport.py` (USB-Protokoll, Sicherheitsregeln, Homing/G30/Park), `web.py` + `index.html` (Web-UI/API), `firmware_flash.py` (SKR-Update über USB), `smart_cam.py` (Motivgrenzen) |
| `pi400/install.sh`, `update.sh`, `recover.sh` | Erstinstallation, nächtliches Auto-Update, Wiederherstellung |
| `firmware/marlin/build.py` | Reproduzierbarer Marlin-Build mit allen LumaCut-Anpassungen |
| `android/` | **LumaCut für Android** (Tablet-App, Kotlin/Compose): Werkstatt, Aufträge mit Vorschau, Editor, Kamera, Material |
| `software/lumacut-studio/` | LumaCut Studio (Tauri 2, Windows) |
| `tests/` | Python-Tests für Pi-Dienst und Firmware-Update (ohne Hardware) |
| `docs/` | Maschine, Pi-Betrieb, Firmware, Entwicklung, Studio-Plan |

## Dokumentation

- [docs/MASCHINE.md](docs/MASCHINE.md) – Hardware, Belegung, Koordinaten, Kalibrierwerte
- [docs/PI_BETRIEB.md](docs/PI_BETRIEB.md) – Installation, Updates, Bedienung, API, Fehlersuche
- [docs/PI_STATUS_UND_OFFENE_PUNKTE.md](docs/PI_STATUS_UND_OFFENE_PUNKTE.md) – Was der Pi-Dienst kann, Pi für Rahmen/Parken aktualisieren, offene Punkte
- [docs/FIRMWARE.md](docs/FIRMWARE.md) – Marlin-Build, Flashen über den Pi, Marlin-Besonderheiten
- [docs/ANDROID_APP.md](docs/ANDROID_APP.md) – Tablet-App: Bereiche, Aufbau, APK bauen und installieren
- [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md) – Tests, CI, Arbeitsweise, Stolperfallen
- [docs/LUMACUT_STUDIO_PLAN_2026-10-25.md](docs/LUMACUT_STUDIO_PLAN_2026-10-25.md) – Ziel und Fahrplan für Studio
- [CHANGELOG.md](CHANGELOG.md) – Was wann warum geändert wurde

## Schnellstart

```bash
# Pi neu aufsetzen (Raspberry Pi OS 64-bit)
git clone https://github.com/theubyte/LumaCut-CNC.git
sudo bash LumaCut-CNC/pi400/install.sh
```

Web-UI danach unter `http://lumacut.local:8080`. Weitere Updates holt sich der Pi jede Nacht selbst von `main`.

## Arbeitsweise

Alles läuft auf `main`. Jede Commit-Message erklärt **was** geändert wurde und **warum**. Hardware-Befunde (Logs, Messwerte, Marlin-Quelltextstellen) gehören in die Commit-Message oder die Doku, damit die Entscheidung später nachvollziehbar bleibt.

> Sicherheit: Die Software-Sperren ersetzen keinen Hardware-Not-Aus und keine Laserschutzmaßnahmen. Laser nie unbeaufsichtigt betreiben.
