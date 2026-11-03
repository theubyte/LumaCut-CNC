"""LumaCut Laser-Interface V2: relay + isolated PWM driver on one board.

Run with KiCad's bundled Python (KiCad 10):
  "%LOCALAPPDATA%/Programs/KiCad/10.0/bin/python.exe" build_board.py
Writes laser_interface_v2.kicad_pcb next to this script.

Circuit (see schaltplan.svg):
  J1 PSU +24 V -> F1 (5x20, 2 A T) -> K1 COM; K1 NO -> J2.1 laser red (+24V_SW)
  J1 PSU GND = J2.2 laser black = B.Cu ground plane of the laser side
  J4 SKR FAN1 (+ fixed / - switched by PC6) -> K1 coil, D1 1N4007 across it
  J3 SKR BL_Touch PA1 / GND -> R1 -> U1 optocoupler LED (pins 1/2)
  +24V_SW -> U2 7805 -> +5V -> U1 collector (4); U1 emitter (3) -> J2.3 laser
  yellow PWM, R4 2.2k to GND; R5 + LED1 show +24V_SW.
The SKR side and the laser side share no copper on this board (gap under U1).
"""
import os
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "laser_interface_v2.kicad_pcb")
LIB = os.path.join(os.environ["LOCALAPPDATA"], "Programs/KiCad/10.0/share/kicad/footprints")

W, H = 90.0, 64.0
mm = pcbnew.FromMM


def P(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


board = pcbnew.BOARD()
ds = board.GetDesignSettings()
ds.m_TrackMinWidth = mm(0.2)
ds.m_MinClearance = mm(0.25)

nets = {}


def net(name):
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n
    return nets[name]


def place(ref, value, lib, name, x, y, rot=0, pads=None):
    fp = pcbnew.FootprintLoad(os.path.join(LIB, lib + ".pretty"), name)
    if fp is None:
        raise RuntimeError("footprint missing: %s:%s" % (lib, name))
    fp.SetReference(ref)
    fp.SetValue(value)
    board.Add(fp)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(P(x, y))
    for pad in fp.Pads():
        if pads and pad.GetNumber() in pads:
            pad.SetNet(net(pads[pad.GetNumber()]))
    return fp


# --- placement (mm, origin top left) --------------------------------------
TB = "TerminalBlock_Phoenix"
T2 = "TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal"
T3 = "TerminalBlock_Phoenix_MKDS-1,5-3_1x03_P5.00mm_Horizontal"
# Wire entry is the footprint's +y side: rot 90 faces right (pin 1 at the
# bottom), rot 270 faces left (pin 1 at the top).
place("J1", "Netzteil 24V", TB, T2, 82, 11, 90, {"2": "+24V_IN", "1": "GND"})
place("J2", "Laser", TB, T3, 82, 44, 90, {"3": "+24V_SW", "2": "GND", "1": "PWM"})
# Left edge: SKR connections.
place("J4", "SKR FAN1", TB, T2, 8, 16, 270, {"1": "FAN+", "2": "FAN-"})
place("J3", "SKR BL_Touch", TB, T2, 8, 42, 270, {"1": "PA1", "2": "GND_SKR"})

place("F1", "2A T 5x20", "Fuse",
      "Fuseholder_Clip-5x20mm_Littelfuse_111_Inline_P20.00x5.00mm_D1.05mm_Horizontal",
      52, 6, 0, {"1": "+24V_F", "2": "+24V_IN"})
# G5LE-1: 1 COM, 3 NO, 4 NC, 2/5 coil. rot 90: coil left column, contacts right.
place("K1", "G5LE-1 24VDC", "Relay_THT", "Relay_SPDT_Omron-G5LE-1", 30, 22, 90,
      {"1": "+24V_F", "3": "+24V_SW", "5": "FAN+", "2": "FAN-"})
place("D1", "1N4007", "Diode_THT", "D_DO-41_SOD81_P10.16mm_Horizontal", 24, 16, 270,
      {"1": "FAN+", "2": "FAN-"})

place("U1", "SFH618A / PC817", "Package_DIP", "DIP-4_W7.62mm", 44, 48, 0,
      {"1": "OPTO_A", "2": "GND_SKR", "3": "PWM", "4": "+5V"})
place("R1", "680 (817: 470)", "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
      28, 48, 0, {"1": "PA1", "2": "OPTO_A"})

place("U2", "7805 / 78L05", "Package_TO_SOT_THT", "TO-220-3_Vertical", 54, 38, 0,
      {"1": "+24V_SW", "2": "GND", "3": "+5V"})
place("C1", "100n", "Capacitor_THT", "C_Disc_D5.0mm_W2.5mm_P5.00mm", 54, 33, 0,
      {"1": "+24V_SW", "2": "GND"})
place("C3", "10u 35V", "Capacitor_THT", "CP_Radial_D5.0mm_P2.50mm", 64, 28, 270,
      {"1": "+24V_SW", "2": "GND"})
place("C2", "100n", "Capacitor_THT", "C_Disc_D5.0mm_W2.5mm_P5.00mm", 59.08, 42.5, 270,
      {"1": "+5V", "2": "GND"})
place("R4", "2k2", "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
      70, 50.54, 270, {"1": "PWM", "2": "GND"})
place("R5", "4k7", "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
      68.5, 28, 270, {"1": "+24V_SW", "2": "LED_A"})
place("LED1", "24V an", "LED_THT", "LED_D3.0mm", 65.96, 42, 0, {"1": "GND", "2": "LED_A"})

for i, (x, y) in enumerate([(4, 4), (4, 60), (86, 60), (40, 4)], 1):
    place("H%d" % i, "M3", "MountingHole", "MountingHole_3.2mm_M3", x, y).Reference().SetVisible(False)


# --- tracks -----------------------------------------------------------------
def track(netname, width, pts, layer=pcbnew.F_Cu):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(x1, y1))
        t.SetEnd(P(x2, y2))
        t.SetWidth(mm(width))
        t.SetLayer(layer)
        t.SetNet(net(netname))
        board.Add(t)


def pad_xy(ref, num):
    fp = board.FindFootprintByReference(ref)
    for pad in fp.Pads():
        if pad.GetNumber() == num:
            p = pad.GetPosition()
            return (round(pcbnew.ToMM(p.x), 3), round(pcbnew.ToMM(p.y), 3))
    raise KeyError((ref, num))


PWR, COIL, SIG = 2.5, 0.8, 0.5
j1p, j1g = pad_xy("J1", "2"), pad_xy("J1", "1")
j2r, j2b, j2y = pad_xy("J2", "3"), pad_xy("J2", "2"), pad_xy("J2", "1")
j4p, j4n = pad_xy("J4", "1"), pad_xy("J4", "2")
j3a, j3g = pad_xy("J3", "1"), pad_xy("J3", "2")
f_in = max((p for p in [(pad.GetNumber(), pad.GetPosition()) for pad in board.FindFootprintByReference("F1").Pads()]
            if p[0] == "2"), key=lambda p: p[1].x)[1]
f_out = min((p for p in [(pad.GetNumber(), pad.GetPosition()) for pad in board.FindFootprintByReference("F1").Pads()]
             if p[0] == "1"), key=lambda p: p[1].x)[1]
f_in = (pcbnew.ToMM(f_in.x), pcbnew.ToMM(f_in.y))
f_out = (pcbnew.ToMM(f_out.x), pcbnew.ToMM(f_out.y))
com, no = pad_xy("K1", "1"), pad_xy("K1", "3")
c_p, c_n = pad_xy("K1", "5"), pad_xy("K1", "2")
d_k, d_a = pad_xy("D1", "1"), pad_xy("D1", "2")

# Both legs of each fuse clip are one contact; tie them for the DRC.
f1 = sorted((pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y), p.GetNumber())
            for p in board.FindFootprintByReference("F1").Pads())
track("+24V_F", PWR, [f1[0][:2], f1[1][:2]])
track("+24V_IN", PWR, [f1[2][:2], f1[3][:2]])
# Power path: J1+ -> fuse -> COM (on B.Cu, under the relay) -> NO -> laser red.
track("+24V_IN", PWR, [j1p, (j1p[0] - 4, j1p[1]), f_in])
track("+24V_F", PWR, [f_out, (f_out[0], com[1]), com], pcbnew.B_Cu)
track("+24V_SW", PWR, [no, (71, no[1]), (71, j2r[1]), j2r])
# Ground: J1- to J2- also as a wide track (the plane carries it too).
track("GND", PWR, [j1g, (j1g[0] - 4, j1g[1]), (j1g[0] - 4, j2b[1]), j2b], pcbnew.B_Cu)
# Coil: J4+ -> coil (D1 cathode on the way); J4- -> coil other end (D1 anode).
track("FAN+", COIL, [j4p, (d_k[0], j4p[1]), d_k, (c_p[0], d_k[1]), c_p])
track("FAN-", COIL, [j4n, (14, j4n[1]), (14, c_n[1]), c_n])
track("FAN-", COIL, [d_a, (d_a[0], c_n[1])])
# Regulator input branch and caps.
u2i, u2g, u2o = pad_xy("U2", "1"), pad_xy("U2", "2"), pad_xy("U2", "3")
track("+24V_SW", 1.0, [(u2i[0], no[1]), u2i])
r5a, r5b = pad_xy("R5", "1"), pad_xy("R5", "2")
led_a = pad_xy("LED1", "2")
track("LED_A", SIG, [r5b, (r5b[0], led_a[1]), led_a])
# +5V: regulator out -> C2 -> optocoupler collector.
u1 = {n: pad_xy("U1", n) for n in "1234"}
track("+5V", 0.8, [u2o, (u2o[0], 45), (u1["4"][0], 45), u1["4"]])
# PWM: emitter -> R4 -> laser yellow.
track("PWM", 0.8, [u1["3"], (71, u1["3"][1]), (71, j2y[1]), j2y])
# SKR side.
r1a, r1b = pad_xy("R1", "1"), pad_xy("R1", "2")
track("PA1", SIG, [j3a, (20, j3a[1]), (20, r1a[1]), r1a])
track("OPTO_A", SIG, [r1b, u1["1"]])
track("GND_SKR", SIG, [j3g, (14, j3g[1]), (14, 53), (40, 53), (40, u1["2"][1]), u1["2"]])

# --- ground plane (laser side, bottom) -------------------------------------
zone = pcbnew.ZONE(board)
zone.SetLayer(pcbnew.B_Cu)
zone.SetNet(net("GND"))
zone.SetLocalClearance(mm(0.5))
zone.SetMinThickness(mm(0.3))
zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
outline = zone.Outline()
outline.NewOutline()
for x, y in [(56, 10), (89, 10), (89, 63), (56, 63)]:
    outline.Append(mm(x), mm(y))
board.Add(zone)

# --- outline, texts ----------------------------------------------------------
for (x1, y1), (x2, y2) in [((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))]:
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(P(x1, y1))
    s.SetEnd(P(x2, y2))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    board.Add(s)


def text(s, x, y, size=1.2, rot=0, layer=pcbnew.F_SilkS, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(P(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(size * (0.2 if bold else 0.15)))
    t.SetTextAngleDegrees(rot)
    board.Add(t)


text("LumaCut Laser-IF V2", 24, 60.5, 1.6, bold=True)
text("NETZTEIL 24V", 82, 16.5, 1.0)
text("+24V", 74.6, 3.2, 0.9)
text("GND", 74.8, 11, 0.9)
text("LASER", 82, 49.5, 1.0)
text("+24V", 74.6, 31.4, 0.9)
text("GND", 74.8, 39, 0.9)
text("PWM", 74.6, 42.3, 0.9)
text("SKR FAN1 (Spule)", 9, 10.3, 1.0)
text("+", 16, 14.3, 1.0)
text("-", 16.5, 22.8, 1.0)
text("SKR BL_TOUCH (PWM)", 10, 36.6, 1.0)
text("PA1", 16, 40.3, 0.9)
text("GND", 16, 48.8, 0.9)
text("IN GND OUT", 56.5, 40.9, 0.8)
text("2A T", 62, 9.5, 1.0)
text("Trennung", 47.8, 55, 0.8)
# Terminal labels replace the J references; keep the other references clear.
for ref in ("J1", "J2", "J3", "J4"):
    board.FindFootprintByReference(ref).Reference().SetVisible(False)
for ref, x, y, rot in (("C3", 60.6, 25.6, 0), ("D1", 21.4, 21, 90), ("U2", 48.6, 37.5, 90),
                       ("LED1", 65.2, 45.6, 0), ("R5", 66.4, 33, 90), ("K1", 38, 22, 0)):
    f = board.FindFootprintByReference(ref).Reference()
    f.SetPosition(P(x, y))
    f.SetTextAngleDegrees(rot)

pcbnew.ZONE_FILLER(board).Fill(board.Zones())
board.Save(OUT)
print("saved", OUT)
for ref in ["J1", "J2", "J3", "J4", "F1", "K1", "U1", "U2"]:
    fp = board.FindFootprintByReference(ref)
    print(ref, sorted((p.GetNumber(), round(pcbnew.ToMM(p.GetPosition().x), 2), round(pcbnew.ToMM(p.GetPosition().y), 2)) for p in fp.Pads()))
