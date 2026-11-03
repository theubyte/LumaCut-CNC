"""Laser-Interface V2 on the owner's 7 x 9 cm perfboard (2.54 mm grid).

Same circuit as build_board.py, but every part sits on a perfboard hole and
the connections are wires: bare wire on the solder side (B.Cu, drawn with a
mask opening so it renders like tinned wire). The board has 32 columns
(A..Z, then A..F again; written here as a'..f') and 26 rows (A..Z).

Run with KiCad's Python:
  "%LOCALAPPDATA%/Programs/KiCad/10.0/bin/python.exe" build_perfboard.py
Prints the wiring list (hole coordinates) and writes lochraster.kicad_pcb.
"""
import os
import string
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "lochraster.kicad_pcb")
LIB = os.path.join(os.environ["LOCALAPPDATA"], "Programs/KiCad/10.0/share/kicad/footprints")
mm = pcbnew.FromMM

BW, BH = 90.0, 70.0
COLS, ROWS, PITCH = 32, 26, 2.54
X0 = (BW - (COLS - 1) * PITCH) / 2
Y0 = (BH - (ROWS - 1) * PITCH) / 2
COL_NAMES = list(string.ascii_uppercase) + [c + "'" for c in "ABCDEF"]
ROW_NAMES = list(string.ascii_uppercase)


def g(c, r):
    return (X0 + c * PITCH, Y0 + r * PITCH)


def P(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def hole_name(c, r):
    return "%s%s" % (COL_NAMES[c], ROW_NAMES[r])


board = pcbnew.BOARD()
nets = {}


def net(name):
    if name not in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        nets[name] = n
    return nets[name]


def place(ref, value, lib, name, c, r, rot=0, pads=None, snap=True):
    fp = pcbnew.FootprintLoad(os.path.join(LIB, lib + ".pretty"), name)
    fp.SetReference(ref)
    fp.SetValue(value)
    board.Add(fp)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(P(*g(c, r)))
    for pad in fp.Pads():
        if pads and pad.GetNumber() in pads:
            pad.SetNet(net(pads[pad.GetNumber()]))
        if snap:
            # 5.00 mm terminal / fuse-clip pitch -> nearest 2.54 mm hole.
            x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
            cc, rr = round((x - X0) / PITCH), round((y - Y0) / PITCH)
            pad.SetPosition(P(*g(cc, rr)))
    return fp


TB = "TerminalBlock_Phoenix"
T2 = "TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal"
T3 = "TerminalBlock_Phoenix_MKDS-1,5-3_1x03_P5.00mm_Horizontal"
R = ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
RV = ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical")    # standing
# Right edge (wire entry outwards): rot 90, pin 1 at the bottom.
place("J1", "Netzteil", TB, T2, 29, 4, 90, {"2": "+24V_IN", "1": "GND"})
place("J2", "Laser", TB, T3, 29, 17, 90, {"3": "+24V_SW", "2": "GND", "1": "PWM"})
# Left edge: rot 270, pin 1 at the top.
place("J4", "SKR FAN1", TB, T2, 2, 5, 270, {"1": "FAN+", "2": "FAN-"})
place("J3", "SKR BL_Touch", TB, T2, 2, 17, 270, {"1": "PA1", "2": "GND_SKR"})
place("F1", "2A T", "Fuse",
      "Fuseholder_Clip-5x20mm_Littelfuse_111_Inline_P20.00x5.00mm_D1.05mm_Horizontal",
      15, 2, 0, {"1": "+24V_F", "2": "+24V_IN"})
# The G5LE pins are off the 2.54 grid (6 / 14.2 mm): drill these 5 holes.
place("K1", "G5LE-1 24VDC", "Relay_THT", "Relay_SPDT_Omron-G5LE-1", 8, 8, 90,
      {"1": "+24V_F", "3": "+24V_SW", "5": "FAN+", "2": "FAN-"}, snap=False)
place("D1", "1N4007", "Diode_THT", "D_DO-41_SOD81_P10.16mm_Horizontal", 6, 5, 270,
      {"1": "FAN+", "2": "FAN-"})
place("U1", "SFH618A/PC817", "Package_DIP", "DIP-4_W7.62mm", 12, 18, 0,
      {"1": "OPTO_A", "2": "GND_SKR", "3": "PWM", "4": "+5V"})
place("R1", "680", *R, 6, 18, 0, {"1": "PA1", "2": "OPTO_A"})
# LM317T from the owner's gas-heating board instead of a 7805 (03.11.):
# pin 1 ADJ, 2 OUT (also the tab!), 3 IN. Turned round: IN left, ADJ right,
# tab towards row Z. 1.25 V x (1 + 680/220) = 5.1 V.
place("U2", "LM317T", "Package_TO_SOT_THT", "TO-220-3_Vertical", 20, 16, 180,
      {"1": "ADJ", "2": "+5V", "3": "+24V_SW"})
place("R6", "220", *RV, 19, 18, 0, {"1": "+5V", "2": "ADJ"})
place("R7", "680", *RV, 20, 19, 270, {"1": "ADJ", "2": "GND"})
place("C1", "100n", "Capacitor_THT", "C_Disc_D5.0mm_W2.5mm_P5.00mm", 21, 14, 270,
      {"1": "+24V_SW", "2": "GND"})
place("C3", "10u", "Capacitor_THT", "CP_Radial_D5.0mm_P2.50mm", 23, 14, 270,
      {"1": "+24V_SW", "2": "GND"})
place("C2", "100n", "Capacitor_THT", "C_Disc_D5.0mm_W2.5mm_P5.00mm", 17, 18, 270,
      {"1": "+5V", "2": "GND"})
place("R4", "2k2", *R, 24, 23, 90, {"1": "PWM", "2": "GND"})
place("R5", "4k7", *R, 26, 14, 270, {"1": "+24V_SW", "2": "LED_A"})
place("LED1", "LED", "LED_THT", "LED_D3.0mm", 27, 19, 180, {"1": "GND", "2": "LED_A"})


def pad_at(ref, num):
    fp = board.FindFootprintByReference(ref)
    p = [p for p in fp.Pads() if p.GetNumber() == num]
    return (pcbnew.ToMM(p[0].GetPosition().x), pcbnew.ToMM(p[0].GetPosition().y))


# --- wires: (net, width, [grid points or (ref, pad)], layer) ----------------
WIRES = [
    ("+24V_IN", 1.4, [(23, 2), (29, 2)], "dick"),
    ("+24V_F", 1.4, [("K1", "1"), (12, 8), (12, 3), (15, 3), (15, 2)], "dick, isoliert"),
    ("+24V_SW", 1.4, [("K1", "3"), (14, 10), (14, 13), (29, 13)], "dick"),
    ("GND", 1.4, [(29, 4), (30, 4), (30, 15), (29, 15)], "dick"),
    ("GND", 0.8, [(29, 15), (28, 15), (28, 20), (17, 20)], ""),
    ("+24V_SW", 0.8, [(18, 13), (18, 16)], ""),
    ("+24V_SW", 0.8, [(21, 13), (21, 14)], ""),
    ("+24V_SW", 0.8, [(23, 13), (23, 14)], ""),
    ("+24V_SW", 0.8, [(26, 13), (26, 14)], ""),
    ("GND", 0.8, [(21, 16), (21, 20)], ""),
    ("GND", 0.8, [(23, 15), (23, 20)], ""),
    ("GND", 0.8, [(24, 19), (24, 20)], ""),
    ("GND", 0.8, [(27, 19), (27, 20)], ""),
    ("LED_A", 0.8, [(26, 18), (26, 19)], ""),
    ("+5V", 0.8, [(19, 16), (19, 18), (15, 18)], ""),
    ("ADJ", 0.8, [(20, 16), (20, 19)], ""),
    ("PWM", 0.8, [(15, 19), (15, 23), (29, 23), (29, 17)], ""),
    ("FAN+", 0.8, [(2, 5), (8, 5), ("K1", "5")], ""),
    ("FAN-", 0.8, [(2, 7), (4, 7), (4, 11), (8, 11), ("K1", "2")], ""),
    ("FAN-", 0.8, [(6, 9), (6, 11)], ""),
    ("PA1", 0.8, [(2, 17), (4, 17), (4, 18), (6, 18)], ""),
    ("OPTO_A", 0.8, [(10, 18), (12, 18)], ""),
    ("GND_SKR", 0.8, [(2, 19), (12, 19)], ""),
]


def xy(p):
    return pad_at(*p) if isinstance(p[0], str) else g(*p)


def name(p):
    if isinstance(p[0], str):
        return "%s-Pin%s" % p
    return hole_name(*p)


used = set()
for netname, width, pts, note in WIRES:
    for a, b in zip(pts, pts[1:]):
        (x1, y1), (x2, y2) = xy(a), xy(b)
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(x1, y1))
        t.SetEnd(P(x2, y2))
        t.SetWidth(mm(width))
        t.SetLayer(pcbnew.B_Cu)
        t.SetNet(net(netname))
        board.Add(t)
        # Mask opening over the wire: renders as tinned wire.
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(x1, y1))
        s.SetEnd(P(x2, y2))
        s.SetWidth(mm(width + 0.3))
        s.SetLayer(pcbnew.B_Mask)
        board.Add(s)

# --- perfboard holes (all free grid positions) -------------------------------
occupied = set()
relay_pins = [pad_at("K1", n) for n in "12345"]
for fp in board.GetFootprints():
    for pad in fp.Pads():
        x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
        occupied.add((round((x - X0) / PITCH), round((y - Y0) / PITCH)))
perf = pcbnew.FOOTPRINT(board)
perf.SetReference("LOCH")
perf.Reference().SetVisible(False)
perf.Value().SetVisible(False)
board.Add(perf)
for c in range(COLS):
    for r in range(ROWS):
        x, y = g(c, r)
        if (c, r) in occupied or any((x - px) ** 2 + (y - py) ** 2 < 2.4 ** 2 for px, py in relay_pins):
            continue
        pad = pcbnew.PAD(perf)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.VECTOR2I(mm(1.7), mm(1.7)))
        pad.SetDrillSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
        pad.SetLayerSet(pad.PTHMask())
        pad.SetPosition(P(x, y))
        perf.Add(pad)

# --- outline, corner holes, coordinate letters ------------------------------
for (x1, y1), (x2, y2) in [((0, 0), (BW, 0)), ((BW, 0), (BW, BH)), ((BW, BH), (0, BH)), ((0, BH), (0, 0))]:
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(P(x1, y1))
    s.SetEnd(P(x2, y2))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    board.Add(s)
for x, y in [(2, 2), (BW - 2, 2), (2, BH - 2), (BW - 2, BH - 2)]:
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_CIRCLE)
    s.SetCenter(P(x, y))
    s.SetEnd(P(x + 1, y))
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetWidth(mm(0.1))
    board.Add(s)


def text(s, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(P(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(size * 0.15))
    t.SetTextAngleDegrees(rot)
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    board.Add(t)


for layer in (pcbnew.F_SilkS, pcbnew.B_SilkS):
    for c in range(COLS):
        text(COL_NAMES[c][0] + ("'" if c >= 26 else ""), g(c, 0)[0], Y0 - 2.0, 0.9, layer)
    for r in range(ROWS):
        text(ROW_NAMES[r], X0 - 2.3, g(0, r)[1], 0.9, layer)
        text(ROW_NAMES[r], X0 + (COLS - 1) * PITCH + 2.3, g(0, r)[1], 0.9, layer)

text("LumaCut Laser-IF V2 Lochraster", g(10, 25)[0], BH - 1.2, 1.0)

board.Save(OUT)
print("saved", OUT)
print("\nBAUTEILE (Pin -> Loch):")
for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
    if fp.GetReference() == "LOCH":
        continue
    holes = []
    for pad in sorted(fp.Pads(), key=lambda p: p.GetNumber()):
        x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
        c, r = (x - X0) / PITCH, (y - Y0) / PITCH
        on = abs(c - round(c)) < 0.05 and abs(r - round(r)) < 0.05
        holes.append("%s:%s%s" % (pad.GetNumber(), hole_name(round(c), round(r)), "" if on else "~"))
    print("  %-5s %-14s %s" % (fp.GetReference(), fp.GetValue(), " ".join(holes)))
print("\nDRAEHTE (Loetseite):")
for netname, width, pts, note in WIRES:
    print("  %-8s %s%s" % (netname, " -> ".join(name(p) for p in pts), ("  [%s]" % note) if note else ""))
