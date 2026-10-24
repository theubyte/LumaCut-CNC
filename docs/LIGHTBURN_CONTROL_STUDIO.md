# LumaCut Control Studio – LightBurn, Wi-Fi and first commissioning

Status 24 October 2026. HMI + SKR sources in GitHub `main`; real hardware/laser motion tests required.

## LightBurn GRBL USB profile

The file `lightburn/LumaCut-CNC-USB.lbdev` is a LightBurn `DeviceList`
JSON profile based on a genuine LightBurn .lbdev export. It is an **USB**
profile: GRBL driver, 115200 baud, native ESP32-S3 CDC port on the Waveshare
HMI (not the SKR bootloader USB port). The default static work area
410×400 mm is only a placeholder; enter your measured physical
X/Y travel. Do not infer limits from the original Atomstack sticker.

A **live** profile with the current `$130/$131` sizes and `$30` S-value is
downloadable from the HMI web portal under **WLAN & LightBurn** and from
authenticated GET `/api/lightburn/profile` (browser session API key).

LightBurn: **Devices → Import → LumaCut-CNC-USB.lbdev → Make Default**.
Choose the USB COM port of the HMI (ESP32-S3), not the SKR bootloader
and not a previously installed Atomstack profile.
GRBL (not GRBL-M3), S-Value Max equal to SKR `$30` (usually 1000),
SKR `$32=1` laser mode, mm. The HMI UART-to-SKR bridge is 115200.
LightBurn exports raw G-code; HMI storage accepts .gcode/.nc/.tap/.txt,
or LightBurn may stream directly over the USB CDC.

**Wi-Fi LightBurn**: create a *second* GRBL device manually in LightBurn
for Wi-Fi/TCP/Ethernet, using the router IP of the HMI and **TCP port 23**.
Do not try importing the USB profile as a TCP profile. The HMI's
native serial USB and TCP are mutually exclusive while a session/job
owns the controller. TCP enable is saved in ESP32 NVS and survives reboot;
it no longer silently expires after five minutes. Click **LightBurn TCP
EIN/AUS** from the HMI or the web portal if it should be closed.

The web UI and touchscreen cannot issue competing motion while a
LightBurn host owns the SKR. A TCP disconnect while moving requests GRBL
Feed Hold, *not* a replacement for a hardwired E-Stop.

**If LightBurn does not move**: check selected device is GRBL, correct
COM or correct HMI router IP, port 23, host owner shown "LightBurn",
SKR state `Idle` versus `Alarm`, and the LightBurn Console responses
such as `ok`, `error:...` or `ALARM:...`.
GRBL jobs cannot move in Alarm until a successful homing/unlock and
correct endstop / travel configuration. The HMI does not automatically
discard LightBurn's G-code. Choose GRBL transfer mode "Synchronous"
if serial buffered mode stutters. Ensure serial TX/RX are correctly
crossed between HMI and SKR, with 3.3 V signal levels and common GND.

## QR hotspot & Wi-Fi/router onboarding

The HMI **WLAN/System → Hotspot QR** shows a locally-generated Wi-Fi
QR code with the device-specific WPA2 hotspot name and password. Scan
with the phone camera and open `http://192.168.4.1`. No internet service
is involved in generating this QR code.

In the connected browser, open **WLAN & LightBurn → WLAN suchen**,
pick a 2.4 GHz network, enter its WPA2 password and tap **Verbinden**.
The SSID/password are stored in ESP32 NVS; the ESP32 remains in
AP+STA mode, preserving the hotspot for recovery. The router IP is
shown in the portal/HMI. The independent local HMI access code is
visible in the HMI WLAN page and must be entered once per browser session.
Do not expose the web or raw GRBL TCP port to the public internet.

## Web Control Studio feature set

The responsive 7-tab Control Studio provides:
- status, owner, live XYZ work area and motion position;
- after-homing jog X/Y/Z with 0.1/1/10 mm steps and configured SKR
  25/50/100% axes maxima;
- XYZ home, motor hold and manual release, direction, limit and origin;
- file upload, selection and local execution, pause/resume, framing,
  abort, machine park slots;
- full SKR parameter categories with inline edits and explicit save
  and readback, plus travel X/Y/Z;
- focus Z heights, material rectangle, XY probe-tip offsets,
  pitch and downloadable geometry CSV (NOT a measured height map);
- 2.4 GHz router scan/connect, hotspot QR, TCP toggle and LightBurn
  USB profile download;
- HMI/SKR update check and actions subject to firmware safety gating.

The portal deliberately uses the SAME validated HMI motion and
configuration code (`action()` and the existing script/GRBL readback)
rather than issuing unreviewed commands directly to the serial port.
The basic HMI API key is mandatory for controls and downloads.

## Z20 before X/Y: firmware contract

The new SKR grblHAL **always** homes Z first, performs a system move to
20 mm mechanical Z clearance **before any XY homing**, then homes X/Y.
The SKR move aborts if `$132` does not provide at least 21 mm travel,
or if its saved Z step scale is invalid. It uses the SKR configured
Z max speed rather than a fixed slow rate. This logic is executed
inside grblHAL's `STATE_HOMING`, not as a late HMI macro.
The HMI deliberately does **not** launch another retract after
successful XYZ homing. Update **BOTH** images as a matched pair.

The real mechanical Z travel, endstop release direction, Z steps/mm
`$102`, switch cables and 20 mm free space have not been verified in
this conversation. A compiled binary alone cannot guarantee the
carriage will not collide. Commission with laser power physically
disconnected, observe the first homing cycle continuously and ensure
a reachable physical stop/E-Stop; do not run unsupported unattended
high-energy jobs.

## What has and has not been verified

Source and GitHub CI verify syntax, builds, manifest packaging,
and deterministic tests. They cannot verify: LightBurn communication
with the user's PC and selected COM port; motor step loss, driver heat,
USB signal integrity; mechanical Z movement on the real leadscrew;
the laser PWM and external interlock; safety enclosure, fire protection;
or true material-height mapping. The PC2 limit switch is not a
hardware-validated independent probe signal for automatic G38 scans.
