# LumaCut CNC: FAN1-LASER / Pi400 USB experimental integration

**Status:** source changes and automated tests only. Not released for powered laser use.
Firmware version must report `[BOARD:LumaCut SKR Mini MZ v1.0 FAN1-LASER EXPERIMENTAL]`.
The Pi refuses motion and LightBurn on the old SKR board identifier, because
the old image switches the **wrong** power output. This is intentional.

## Desired machine contract

| Function | Board output | STM32 |
|---|---|---|
| Laser TTL/PWM | PT-DET logic signal | PA1 / hardware PWM |
| Laser 24 V power switch | FAN1 + / FAN1 - low-side MOSFET | PC7 / spindle enable |
| Exhaust 24 V | BED + / BED - low-side MOSFET | PC9 / coolant M8 |
| Cabinet LEDs 24 V | HE0 + / HE0 - low-side MOSFET | PC8 / coolant M7 |
| Unused auxiliary | FAN0 + / FAN0 - low-side MOSFET | PC6 / $LCIO |
| Pi ↔ SKR communication | USB CDC | PA11/PA12 |

**CRITICAL:** FAN1− is a switched negative terminal and is **not** a permanent
logic ground. Wiring PA1 directly to the laser PWM input when laser ground
is supplied by FAN1− can produce reverse powering, unexpected laser emission,
or STM32 destruction. A separate suitably rated and verified **galvanically
isolated PWM stage** with its secondary referenced to the laser side and
an independent normally-off laser power interlock are mandatory before real
laser operation. Do **not** simply move three wires to FAN1 and PA1.
The former reading of 8 V was made between PA1 and the switched BED−;
that is not a valid PA1-to-board-ground voltage measurement. Test PA1
against fixed SKR logic GND, with the laser fully disconnected.

Do not attach the laser until output polarities, MOSFET off-state, default
states during USB disconnect/reset, real PWM amplitude, laser input threshold,
isolation, thermal management, and the independent E-stop/interlock have been
verified. Use a dummy load and a scope/differential measurement as appropriate.

## LightBurn communication

Use Pi400's TCP port 23; only ONE client can hold the connection at a time.
A second probing client while LightBurn is still connected may get
`error:9` followed by a socket close; this does not prove the primary
session is broken. Close LightBurn fully before isolated TCP diagnostics.

The Pi bridge blocks unsafe powered M3 laser commands and requires
live grblHAL `$32=1` laser mode. Prefer an imported updated
`lightburn/LumaCut-CNC-USB.lbdev` machine profile:
`M4 S0` for laser standby; `G0` moves between paths; `M4` permits PWM
only while traversing feed-controlled burn moves (grblHAL laser mode).
Use `M5` to stop. Do not run arbitrary unverified G-code.

USB disappearance is a real defect separate from TCP ownership. Verify a
quality direct USB data cable, stable SKR power and Pi power, and dmesg.

## Local G-code jobs

The Pi preflights complete G-code before starting; files with powered M3
are refused rather than drawing unwanted positioning lines. Existing files
using `M3 S500` must be regenerated for dynamic-power `M4` laser mode.
Before a job the Pi sends `M5`; after the job it sends `M5`; M2/M30
end codes are handled by the Pi to avoid an unnecessary unacknowledged
program-end transition. On a detected job error Pi requests a controller
soft-reset. None of this replaces a **hardware** emergency power cutoff.

## Update order

1. Download machine backup (`$$`, `$I`, configurations), disconnect
   laser power and PWM, and close LightBurn.
2. Verify GitHub Actions has passed for the exact **same commit**.
3. Extract the **SKR-USB** artifact and follow the *verified* SKR Mini MZ
   firmware loader procedure. Do not attempt Pi-serial flashing: no confirmed
   automatic SKR USB bootloader path is implemented.
4. Check `$I` from SKR using direct USB serial. It MUST contain
   `FAN1-LASER`; confirm `$32=1` via `$$` before test jobs.
5. Only then update Pi software: `sudo bash /opt/lumacut/pi400/update.sh`.
   Inspect service logs and health: `sudo journalctl -u lumacut -n 70 --no-pager`.
6. Reimport the new LightBurn device profile. Prove `?` status and `ok`
   replies using one TCP client. Test non-laser motion only.
7. Verify independent E-stop, laser disable, dummy-load switching,
   low-side isolation, PWM voltage and frequency, and post-reset off state.
8. Real laser operation remains **prohibited** without those measurements.

The Pi daily update timer updates Pi sources only; it cannot auto-flash SKR.
An old/other SKR firmware after the new Pi update will show *not ready* and
must not be bypassed by renaming identity strings or disabling checks.
