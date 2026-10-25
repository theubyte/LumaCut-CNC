# LumaCut CNC — native Marlin 2.1.2.9 migration (experimental)

> **NOT A LASER-READY RELEASE.** SKR firmware and host application have been
> compiled and regression-tested, **not** electrically verified with this
> machine's LaserTree laser. Laser VCC and PWM must be physically disconnected
> before updating, homing or positioning. An independently wired emergency
> laser cutoff and verified galvanically isolated PWM stage are required.

## Design

- LightBurn 2.2 on Windows → trusted local Wi-Fi → TCP/23 on Raspberry Pi 400
  → dedicated Marlin G-code gateway → USB CDC → BTT SKR Mini MZ v1.0 STM32F103RC.
- Browser Control OS → `http://lumacut.local:8080`, or Pi's actual LAN IP:8080.
  Keep the existing `LUMACUT_KEY` and `/etc/lumacut/lumacut.env`.
- Pi network bridge uses actual **Marlin** responses (`M115`, `M114`, `M119`,
  `ok` / `Error:`), **not** a GRBL emulator. No fake `error:9`, `?`, `$$`.
- Only one G-code command is sent to USB at a time; the Pi forwards the
  **real** acknowledgment. A virtual LightBurn `G28` becomes one atomic
  staged Z-then-XY homing operation with **one** final acknowledgment.
- **Legacy grblHAL files and installed configs remain available** in Git.
  Separate systemd services prevent simultaneous USB and TCP ownership.

## Physical SKR pin ownership

| Function | Port / GPIO | Note |
| --- | --- | --- |
| Laser logic PWM | PA1 | 0–3.3 V logic, Marlin PWM255 S0..255, must isolate from laser-side floating negative |
| Laser 24 V power | FAN1 / PC7 | LOW-SIDE switched negative; active high MOSFET enable |
| Fume extraction | BED / PC9 | M8 flood coolant MOSFET |
| Work LEDs | HE0 / PC8 | M7 mist coolant MOSFET |
| Unassigned auxiliary | FAN0 / PC6 | Reserved/uncontrolled in this first Marlin release |
| Pi data | SKR USB CDC | **Only one** process may open serial device |

**Electrical restriction:** FAN1− is not the PCB's permanent GND; with the
MOSFET off it can float. Directly connecting PA1 PWM to a laser whose GND
is wired to FAN1− can backfeed the MCU or trigger unintended laser emission.
The previous approximately 8 V measurement between PA1 and BED− does not
measure PA1 against true logic ground. Do not attach the laser until
an electrician/electronics-qualified person has verified isolation, grounds,
output polarities, fail-OFF after resets, optical safety, and hardware E-stop.
Software reset `M112` does not replace power cutoff.

## Components and status

- `firmware/marlin/build.py` clones official Marlin **2.1.2.9** and the
  matching SKR MZ V1.0 config, then produces an experimental `firmware.bin`
  and a manifest with `hardware_verified=false`.
- `.github/workflows/marlin.yml` builds the experimental native STM32F103RC
  firmware and runs Python gateway tests separately from old grblHAL CI.
- `pi400/marlin/transport.py`: Pi ↔ SKR native serial protocol, LightBurn
  TCP/23, G-code safety gate and staged Z-first homing.
- `pi400/marlin/web.py`, `pi400/marlin/index.html`: new Pi400 browser OS,
  authenticated web controls, uploads, position, troubleshooting, Wi-Fi.
- `pi400/marlin/lumacut-marlin.service`: dedicated process, conflicts with
  `lumacut.service` to prevent running GRBL and Marlin simultaneously.
- `pi400/marlin/activate.sh`: explicitly verifies actual Marlin M115
  identity before activating. It never flashes the SKR automatically.

### What was verified / not verified

Verified by CI: source compilation, firmware linking, unit tests of
M115 identity, serial ACK, guarding G-code and homing order, web API,
separate systemd unit. Not verified: machine motion orientation, X/Y/Z
steps/mm, mechanical Z screw lead, real limit polarity, USB-CDC sustained
raster throughput, laser PWM amplitude or frequency, FAN1 electrical
behavior, power disconnection timing, spontaneous reconnect and real
LightBurn handshake (requires SKR + Windows testing). The official example
Z 400 steps/mm is a **placeholder**, not calibrated. Do not run
automated homing until checked on actual hardware.

## Marlin firmware deployment

1. Power off laser / physically disconnect both laser VCC and PWM.
   Ensure motors can stop and no hand is near moving mechanism.
2. Back up original grblHAL SKR `firmware.bin` and Pi config,
   photograph wiring, and record baseline X/Y/Z steps/directions and
   endstop polarity. The original firmware has different NVS values;
   do not blindly import old `$$` parameters into Marlin.
3. Open the latest successful **LumaCut Marlin Experimental** GitHub
   Actions run and download its **Marlin EXPRIMENTAL** artifact.
   Verify the manifest's model, `hardware_verified=false` and SHA256.
   The compile image is *experimental*; do not flash it until you've
   confirmed the SKR Mini MZ V1.0 bootloader accepts this image format.
   Use the board's supported FAT32 microSD `firmware.bin` method if
   its original bootloader is intact; otherwise use a verified
   recovery/flash programmer. The Pi USB firmware updater does not
   implement SKR bootloader flashing.
4. **Update Pi sources while grblHAL remains active**, with LightBurn
   fully disconnected, using the proven `pi400/update.sh` HTTPS
   updater from the current GitHub `main`. Before reflash ensure
   `/opt/lumacut/pi400/marlin/web.py` exists. The old grblHAL Pi
   service will not control the new Marlin SKR.
5. After independently flashing the Marlin firmware, run on Pi:
   `sudo bash /opt/lumacut/pi400/marlin/activate.sh --laser-disconnected`.
   The installer stops the old GRBL service, opens USB to get real
   `M115`, accepts only an identifiable **LumaCut CNC Marlin** SKR,
   then starts `lumacut-marlin.service` on HTTP/8080 and TCP/23.
   For diagnostics run `sudo journalctl -u lumacut-marlin.service -n 80 --no-pager`
   and `sudo systemctl status lumacut-marlin.service`.
6. Open `http://lumacut.local:8080` or the actual Pi LAN address.
   Check `M115`, `M119`, `M114`; preserve disabled mechanical
   software commissioning until every physical switch/direction checked.
7. When all checks pass **without connected laser**, enable mechanics
   in the dedicated Web UI. The Pi then permits guarded Z-first homing.
   `G28 Z` first, +Z clearance (20 mm default), `G28 X Y`,
   `M400`, `M114`; any error aborts further motion. Perform this
   ONLY if positive Z truly moves the head away from the workpiece.

## LightBurn 2.2 manual device settings (do not import the old GRBL .lbdev)

Create **Custom GCode** device via **Devices → Create Manually**,
**Ethernet/Wi-Fi TCP**, Pi address `lumacut.local` / actual IP,
**port 23**, **GCode Flavor Marlin**. Select dimensions from
mechanically measured X/Y travel (present sample 390 x 370 mm), correct
origin and Z setup. In Device Settings → **Custom GCode**:

| Field | Initial expected template |
| --- | --- |
| Home | `G28` (gateway expands Z-first only after hardware commissioning) |
| GCode Flavor | `Marlin` |
| Get Position | `M114` |
| Get Status | `M114` |
| User Start Script | `G21\nG90\nM5 I\nM8\nM3 I` |
| User End Script | `M5 I\nM9` |
| Cut Move | `G1 [X]{x} [Y]{y} F{speed} S{power}` |
| Raster Move | `G1 [X]{x} [Y]{y} F{speed} S{power}` |
| Rapid Move | `G0 [X]{x} [Y]{y}` |
| Tool On | `M3 I` |
| Tool Off | `M5 I` |
| Air On/Off | `M8` / `M9` |
| Max S-value | **255**, not old 1000 |
| Comments | Suppress if incompatible with other emitted firmware commands |
| Get configuration on connect | OFF (Marlin is not GRBL) |
| G53 | OFF until machine positions validated |

**Mandatory:** enable LightBurn's *Emit S Value With Every G1 Command*
when available. In Marlin continuous inline `M3 I`, `G0` blanks
power to zero; the first `G1` after each `G0` requires an explicit
`S` to produce a cut. Check LightBurn's **Save GCode** output before
any real engraving. Manually edit other unnecessary templates to avoid
unsupported GRBL `?`, `$H`, `$$`, `G54`, `G53`, `M106` and
`M3 S...` commands. Abort/pause/resume over Wi-Fi must be bench
validated before trusting them during a cut. Current TCP gateway
recognizes `M112` emergency parser command, but **physical E-stop
is mandatory**.

This sample works at the **G-code syntax level only** (do not use with
the optical head connected until electrically cleared):

```gcode
G21
G90
M5 I
M8
M3 I
G0 X10 Y10
G1 X50 S180 F1500
G0 X10 Y60
G1 X50 S120 F1500
M5 I
M9
```

LightBurn Custom GCode documentation:
https://docs.lightburnsoftware.com/2.2/Reference/DeviceSettings/CustomGCode/
Marlin inline laser documentation:
https://marlinfw.org/docs/features/laser_spindle.html

## Rollback

To return fully to grblHAL, first power off and disconnect the laser,
then restore the previous SKR grblHAL firmware. After its original
identity is verified again, stop/disable
`lumacut-marlin.service` and reenable the old
`lumacut.service`. **Do not** restart the legacy GRBL bridge with
Marlin still flashed: its `$I` and `?` startup messages are invalid
for Marlin. The two different web apps share only the authorized
`LUMACUT_KEY`, not unsafe machine calibration.
