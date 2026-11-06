"""Reorders a job so the head loses as little time as possible (pure Python).

The Android app writes one layer after the other, rows from top to bottom. On a
motif with separate parts the head crosses the gaps on every row. Here the job is
taken apart and planned again, for the time a run really takes:

* Rows are split where a gap is worth it. Which gaps are worth it depends on the
  speed, so several limits are planned and the fastest one wins.
* Neighbouring rows form strips that run bottom to top. A strip is finished before
  the head moves on, so parts of a motif are done one after the other.
* Strips and lines are ordered by a search: nearest neighbour first, then moving
  pieces of the order (Or-opt) and small random changes, as long as the time budget
  lasts, with the best direction of every piece worked out by dynamic programming.

What never changes:
* Cuts come last, in the order of the file, inner parts before outer ones, so a part
  has not fallen out while something still has to be lasered on it.
* Passes of one layer stay in their order, with their focus steps.
* Every burning line is exactly in the result, with its power and speed; `optimize`
  checks that and returns the file unchanged otherwise. So does a job it cannot read.
* Strips always run towards +Y and are approached from below, so the Y backlash of the
  machine stays out of a fill that is split into several strips.
"""
from __future__ import annotations

import math
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
_LAYER = re.compile(r"^;\s*Ebene\s+(.*)$")
_PASS = re.compile(r"^;\s*Durchgang\s+(\d+)\s*/\s*(\d+)")
APP_HEADER = "; LumaCut App"
CUT_ENERGY = 0.08           # % power per mm/min; above this a line is treated as a cut (marking ~0.03, cutting 0.12+)
Y_TAKE_UP_MM = 1.0
GAP_EXTRAS = (0.1, 10.0, 40.0, None)    # mm beyond two run-ups from which a gap is split; None = never
MIN_RUN_UP_MM = 2.5
LOCAL_SEARCH_MAX_BLOCKS = 12000


@dataclass
class Motion:
    accel: float = 2100.0   # mm/s²
    speed: float = 150.0    # mm/s

    def run_up(self, feed):
        v = feed / 60.0
        return max(MIN_RUN_UP_MM, v * v / (2 * self.accel) * 1.15 + 0.3)

    def rapid(self, dist):
        """Seconds for a rapid of [dist] mm from standstill to standstill."""
        if dist <= 0:
            return 0.0
        v, a = self.speed, self.accel
        if dist >= v * v / a:
            return dist / v + v / a
        return 2.0 * math.sqrt(dist / a)


@dataclass
class Stroke:
    """One burning path with its laser-off run-up and run-out: pts[i] -> pts[i+1] at segs[i] = (feed, power)."""
    pts: list
    segs: list

    def reversed(self):
        return Stroke(self.pts[::-1], self.segs[::-1])

    @property
    def horizontal(self):
        return all(abs(p[1] - self.pts[0][1]) < 1e-9 for p in self.pts)

    @property
    def closed(self):
        return len(self.pts) >= 4 and math.dist(self.pts[0], self.pts[-1]) < 1e-6 and len(set(self.segs)) == 1

    def burns(self):
        return any(s > 0 for _, s in self.segs)


@dataclass
class Section:
    name: str
    passes: list = field(default_factory=lambda: [[]])   # strokes per pass
    raw: list = field(default_factory=list)              # the lines of the file
    start: tuple | None = None                           # head position before the section
    focus_steps: bool = False
    announced_passes: int = 1

    def strokes(self):
        return [s for p in self.passes for s in p]

    @property
    def raster(self):
        return any(s == 0 for st in self.strokes() for _, s in st.segs)

    @property
    def is_cut(self):
        if self.raster:
            return False
        if self.focus_steps or self.announced_passes > 1 or "schneid" in self.name.lower() or "cut" in self.name.lower():
            return True
        return any(s / 2.55 / f >= CUT_ENERGY for st in self.strokes() for f, s in st.segs if f > 0)


class _Unreadable(Exception):
    pass


def _clean(raw):
    return raw.split(";", 1)[0].strip().upper()


def _parse(lines):
    """(leading lines, sections, trailing lines). Raises _Unreadable for anything but the app's own format."""
    head, tail, sections = [], [], []
    section = None
    x = y = None
    feed = None
    stroke = None
    in_steps = False

    def flush():
        nonlocal stroke
        if stroke is not None and stroke.segs and section is not None:
            section.passes[-1].append(stroke)
        stroke = None

    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        m = _LAYER.match(text)
        if m:
            flush()
            section = Section(m.group(1).strip(), start=None if x is None else (x, y))
            sections.append(section)
            section.raw.append(raw)
            continue
        if section is None:
            line = _clean(text)
            if line and line not in ("G21", "G90", "M5 I", "M3 I") and not text.startswith(";"):
                raise _Unreadable("Vor der ersten Ebene: " + text)
            head.append(raw)
            continue
        m = _PASS.match(text)
        if m:
            flush()
            section.raw.append(raw)
            section.announced_passes = int(m.group(2))
            if section.strokes() or int(m.group(1)) > 1:
                section.passes.append([])
            continue
        if text.startswith(";"):
            section.raw.append(raw)
            continue
        line = _clean(text)
        if line == "G91":
            flush()
            in_steps = True
            section.focus_steps = True
            section.raw.append(raw)
            continue
        if line == "G90":
            in_steps = False
            section.raw.append(raw)
            continue
        if in_steps:
            if not re.match(r"^G0?0?\s+Z[-+0-9.]+(\s+F[0-9.]+)?$", line):
                raise _Unreadable("Unbekannte relative Zeile: " + text)
            section.raw.append(raw)
            continue
        if line in ("M5 I", "M400"):
            flush()
            tail.append(raw)
            continue
        if tail:
            raise _Unreadable("Nach dem Ende: " + text)
        words = {k: float(v) for k, v in _WORD.findall(line)}
        if line.startswith("G0 ") or line.startswith("G00 "):
            if "Z" in words or "X" not in words or "Y" not in words or "S" in words:
                raise _Unreadable("Eilfahrt: " + text)
            flush()
            x, y = words["X"], words["Y"]
            stroke = Stroke([(x, y)], [])
        elif line.startswith("G1 ") or line.startswith("G01 "):
            if "Z" in words or "X" not in words or "Y" not in words or "S" not in words:
                raise _Unreadable("Laserzeile: " + text)
            if x is None:
                raise _Unreadable("Laserzeile ohne Startpunkt: " + text)
            feed = words.get("F", feed)
            if feed is None or feed <= 0:
                raise _Unreadable("Laserzeile ohne Tempo: " + text)
            if stroke is None:
                stroke = Stroke([(x, y)], [])
            x, y = words["X"], words["Y"]
            stroke.pts.append((x, y))
            stroke.segs.append((feed, words["S"]))
        else:
            raise _Unreadable("Unbekannte Zeile: " + text)
        section.raw.append(raw)
    flush()
    if not sections:
        raise _Unreadable("Keine Ebenen")
    return head, sections, tail


def _split_row(stroke, motion, extra):
    """Splits a raster row at laser-off gaps longer than two run-ups + [extra]. [extra] None: the row stays whole."""
    if extra is None or not stroke.horizontal:
        return [stroke]
    out = []
    pts, segs = [stroke.pts[0]], []
    n = len(stroke.segs)
    for i, seg in enumerate(stroke.segs):
        a, b = stroke.pts[i], stroke.pts[i + 1]
        length = abs(b[0] - a[0])
        over = motion.run_up(seg[0])
        if seg[1] == 0 and 0 < i < n - 1 and length > 2 * over + extra:
            step = over if b[0] > a[0] else -over
            pts.append((a[0] + step, a[1]))
            segs.append(seg)
            out.append(Stroke(pts, segs))
            pts, segs = [(b[0] - step, b[1]), b], [seg]
        else:
            pts.append(b)
            segs.append(seg)
    out.append(Stroke(pts, segs))
    return out


@dataclass
class Block:
    """Something the head does in one go. variants[k] = (entry, exit, strokes in order)."""
    variants: list
    takes_up_y: bool = False


def _strips(rows, pitch):
    """Rows of one layer to strips: rows on top of each other that overlap in X, each strip bottom to top."""
    rows = sorted(rows, key=lambda s: (s.pts[0][1], min(p[0] for p in s.pts)))
    open_strips = []
    strips = []
    for row in rows:
        y = row.pts[0][1]
        lo, hi = min(p[0] for p in row.pts), max(p[0] for p in row.pts)
        best, best_overlap = None, 0.0
        for strip in open_strips:
            if y - strip["y"] > 1.6 * pitch or y - strip["y"] < 1e-6:
                continue
            overlap = min(hi, strip["hi"]) - max(lo, strip["lo"])
            if overlap > best_overlap:
                best, best_overlap = strip, overlap
        if best is None:
            best = {"rows": []}
            open_strips.append(best)
            strips.append(best)
        best["rows"].append(row)
        best.update(y=y, lo=lo, hi=hi)
        open_strips = [s for s in open_strips if y - s["y"] <= 1.6 * pitch]
    return [s["rows"] for s in strips]


def _strip_block(rows):
    def run(first_left):
        out = []
        left = first_left
        for row in rows:
            forward = row.pts[-1][0] >= row.pts[0][0]
            out.append(row if forward == left else row.reversed())
            left = not left
        return out
    variants = []
    for first_left in (True, False):
        strokes = run(first_left)
        variants.append((strokes[0].pts[0], strokes[-1].pts[-1], strokes))
    return Block(variants, takes_up_y=True)


def _line_block(stroke):
    back = stroke.reversed()
    return Block([(stroke.pts[0], stroke.pts[-1], [stroke]), (back.pts[0], back.pts[-1], [back])])


def _pitch(strokes):
    ys = sorted({s.pts[0][1] for s in strokes if s.horizontal})
    diffs = sorted(b - a for a, b in zip(ys, ys[1:]) if b - a > 1e-6)
    return diffs[len(diffs) // 2] if diffs else 0.1


def _blocks(group, motion, extra):
    """[(section name irrelevant) strokes grouped by section] -> blocks for one free group."""
    blocks = []
    for strokes in group:
        rows, others = [], []
        for s in strokes:
            if s.horizontal and any(power == 0 for _, power in s.segs):
                rows += _split_row(s, motion, extra)
            else:
                others.append(s)
        if rows:
            blocks += [_strip_block(r) for r in _strips(rows, _pitch(rows))]
        blocks += [_line_block(s) for s in others]
    return blocks


class _Grid:
    """Buckets of block indices by entry point, to find near blocks without looking at all of them."""

    def __init__(self, blocks, cell=25.0):
        self.cell = cell
        self.cells = {}
        for i, b in enumerate(blocks):
            for entry, _, _ in b.variants:
                self.cells.setdefault(self._key(entry), set()).add(i)

    def _key(self, p):
        return int(p[0] // self.cell), int(p[1] // self.cell)

    def remove(self, i, blocks):
        for entry, _, _ in blocks[i].variants:
            bucket = self.cells.get(self._key(entry))
            if bucket is not None:
                bucket.discard(i)
                if not bucket:
                    del self.cells[self._key(entry)]

    def near(self, p, want=1):
        """Blocks in growing rings around [p]; at least [want] when that many exist."""
        cx, cy = self._key(p)
        found = set()
        ring = 0
        limit = 40
        while ring <= limit:
            for gx in range(cx - ring, cx + ring + 1):
                for gy in range(cy - ring, cy + ring + 1):
                    if max(abs(gx - cx), abs(gy - cy)) == ring:
                        found |= self.cells.get((gx, gy), set())
            if len(found) >= want:
                return found
            ring += 1
        return set().union(*self.cells.values()) if self.cells else set()


def _greedy(blocks, start, motion):
    grid = _Grid(blocks)
    tour = []
    at = start
    left = len(blocks)
    while left:
        best, best_cost = None, math.inf
        for i in grid.near(at):
            for entry, _, _ in blocks[i].variants:
                d = math.dist(at, entry)
                if d < best_cost:
                    best, best_cost = i, d
        tour.append(best)
        grid.remove(best, blocks)
        at = min(((math.dist(at, entry), out) for entry, out, _ in blocks[best].variants), key=lambda t: t[0])[1]
        left -= 1
    return tour


def _directions(tour, blocks, start, end, motion):
    """Best variant of every block for this order (dynamic programming). (cost of all rapids, variants)."""
    state = [(0.0, start, None)]
    back = []
    for i in tour:
        row, pointers = [], []
        for entry, out, _ in blocks[i].variants:
            options = [(cost + motion.rapid(math.dist(at, entry)), k) for k, (cost, at, _) in enumerate(state)]
            cost, k = min(options)
            row.append((cost, out, k))
            pointers.append(k)
        state = row
        back.append(pointers)
    options = [(cost + motion.rapid(math.dist(at, end)), k) for k, (cost, at, _) in enumerate(state)]
    total, k = min(options)
    chosen = [0] * len(tour)
    for j in range(len(tour) - 1, -1, -1):
        chosen[j] = k
        k = back[j][k]
    return total, chosen


def _rapid_cost(tour, blocks, start, end, motion):
    return _directions(tour, blocks, start, end, motion)[0]


def _improve(tour, blocks, start, end, motion, deadline, rng):
    """Or-opt with random restarts: take up to 3 blocks out, put them where the rapids get shortest."""
    n = len(tour)
    if n < 3 or n > LOCAL_SEARCH_MAX_BLOCKS:
        return tour, _rapid_cost(tour, blocks, start, end, motion)
    centre = [_centre(b) for b in blocks]

    def link(a, b):
        return motion.rapid(math.dist(centre[a], centre[b]))

    def sweep(order):
        """One pass of relocations on the rough cost (centre to centre); cheap enough for the Pi."""
        changed = False
        by_cell = {}
        for b in order:
            by_cell.setdefault((int(centre[b][0] // 30), int(centre[b][1] // 30)), []).append(b)
        pos = {b: i for i, b in enumerate(order)}
        i = 0
        while i < len(order) and time.monotonic() < deadline:
            for length in (1, 2, 3):
                if i + length > len(order):
                    break
                seg = order[i:i + length]
                before = order[i - 1] if i > 0 else None
                after = order[i + length] if i + length < len(order) else None
                removed = ((link(before, seg[0]) if before is not None else 0.0)
                           + (link(seg[-1], after) if after is not None else 0.0)
                           - (link(before, after) if before is not None and after is not None else 0.0))
                if removed <= 1e-6:
                    continue
                cx, cy = int(centre[seg[0]][0] // 30), int(centre[seg[0]][1] // 30)
                candidates = [c for gx in (cx - 1, cx, cx + 1) for gy in (cy - 1, cy, cy + 1) for c in by_cell.get((gx, gy), ())]
                best, best_gain = None, 1e-6
                for c in candidates:
                    j = pos.get(c)
                    if j is None or i - 1 <= j < i + length:
                        continue
                    nxt = order[j + 1] if j + 1 < len(order) else None
                    added = (link(c, seg[0]) + (link(seg[-1], nxt) - link(c, nxt) if nxt is not None else 0.0))
                    gain = removed - added
                    if gain > best_gain:
                        best, best_gain = j, gain
                if best is not None:
                    rest = order[:i] + order[i + length:]
                    at = best + 1 if best < i else best + 1 - length
                    order[:] = rest[:at] + seg + rest[at:]
                    pos = {b: k for k, b in enumerate(order)}
                    changed = True
                    break
            i += 1
        return changed

    best = list(tour)
    best_cost = _rapid_cost(best, blocks, start, end, motion)
    current = list(best)
    while time.monotonic() < deadline:
        for _ in range(6):
            if not sweep(current) or time.monotonic() >= deadline:
                break
        cost = _rapid_cost(current, blocks, start, end, motion)
        if cost < best_cost - 1e-6:
            best, best_cost = list(current), cost
        current = list(best)
        for _ in range(max(1, n // 40)):            # a small random change, then repair it again
            i = rng.randrange(n)
            length = min(rng.randint(1, 3), n - i)
            seg = current[i:i + length]
            del current[i:i + length]
            j = rng.randrange(len(current) + 1)
            current[j:j] = seg
    return best, best_cost


def _centre(block):
    xs = [p[0] for entry, out, _ in block.variants for p in (entry, out)]
    ys = [p[1] for entry, out, _ in block.variants for p in (entry, out)]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _emit_stroke(stroke, out):
    out.append("G0 X%.3f Y%.3f" % stroke.pts[0])
    feed = None
    for p, (f, s) in zip(stroke.pts[1:], stroke.segs):
        out.append("G1 X%.3f Y%.3f F%g S%g" % (p[0], p[1], f, s))
        feed = f
    return feed


def _rotated(stroke, near):
    """A closed line starting at its vertex closest to [near]; same path."""
    if not stroke.closed:
        return stroke
    pts = stroke.pts[:-1]
    k = min(range(len(pts)), key=lambda i: math.dist(pts[i], near))
    return Stroke(pts[k:] + pts[:k] + [pts[k]], stroke.segs)


def _emit_group(tour, chosen, blocks, at, out):
    """Writes the blocks; returns the head position afterwards."""
    for i, k in zip(tour, chosen):
        block = blocks[i]
        entry, _, strokes = block.variants[k]
        if block.takes_up_y and at is not None and at[1] > entry[1] + 1e-6 and entry[1] - Y_TAKE_UP_MM >= 0:
            out.append("G0 X%.3f Y%.3f" % (entry[0], entry[1] - Y_TAKE_UP_MM))
        for stroke in strokes:
            if not block.takes_up_y and at is not None:
                stroke = _rotated(stroke, at)
            _emit_stroke(stroke, out)
            at = stroke.pts[-1]
    return at


def _burn_set(lines):
    """Every powered line as (from, to, power, feed), direction ignored; what must survive any reordering."""
    burns = Counter()
    x = y = None
    feed = None
    for raw in lines:
        line = _clean(raw)
        words = {k: float(v) for k, v in _WORD.findall(line)}
        if line.startswith(("G0 ", "G1 ", "G00 ", "G01 ")) and "X" in words and "Y" in words:
            feed = words.get("F", feed)
            nx, ny = round(words["X"], 3), round(words["Y"], 3)
            if line.startswith(("G1 ", "G01 ")) and words.get("S", 0) > 0:
                a, b = sorted(((x, y), (nx, ny)))
                burns[(a, b, words["S"], feed)] += 1
            x, y = nx, ny
    return burns


def _extent(lines):
    xs, ys = [], []
    for raw in lines:
        line = _clean(raw)
        if line.startswith(("G0 ", "G1 ", "G00 ", "G01 ")):
            words = {k: float(v) for k, v in _WORD.findall(line)}
            if "X" in words:
                xs.append(words["X"])
            if "Y" in words:
                ys.append(words["Y"])
    return (min(xs), max(xs), min(ys), max(ys)) if xs and ys else None


def estimate_seconds(lines, motion, default_feed=1500.0):
    """Rough run time of a job (no compensation for firmware details): for comparing, not to the second."""
    total = 0.0
    x = y = z = None
    run = None      # (length, speed, entry speed, ux, uy)
    feed = default_feed

    def trapezoid(d, v, a, v0, v1):
        v = max(1e-6, v)
        d_up = max(0.0, v * v - v0 * v0) / (2 * a)
        d_down = max(0.0, v * v - v1 * v1) / (2 * a)
        if d_up + d_down <= d:
            return (v - v0) / a + (d - d_up - d_down) / v + (v - v1) / a
        peak = math.sqrt(max(0.0, a * d + (v0 * v0 + v1 * v1) / 2))
        return max(0.0, peak - v0) / a + max(0.0, peak - v1) / a

    def close(v_out):
        nonlocal total, run
        if run is not None:
            total += trapezoid(run[0], run[1], motion.accel, run[2], min(v_out, run[1]))
        run = None

    for raw in lines:
        line = _clean(raw)
        if not line.startswith(("G0 ", "G1 ", "G00 ", "G01 ")):
            continue
        words = {k: float(v) for k, v in _WORD.findall(line)}
        rapid = line.startswith(("G0 ", "G00 "))
        if not rapid and "F" in words:
            feed = words["F"]
        nx, ny, nz = words.get("X", x), words.get("Y", y), words.get("Z", z)
        if "X" not in words and "Y" not in words:       # Z alone: stops, moves at 10 mm/s
            close(0.0)
            if z is not None and nz is not None:
                total += abs(nz - z) / 10.0 + 0.02
            z = nz
            continue
        if x is None:
            x, y, z = nx, ny, nz
            continue
        d = math.hypot(nx - x, ny - y)
        if d > 0:
            v = min(motion.speed, 150.0 if rapid else feed / 60.0)
            if nz is not None and z is not None and abs(nz - z) > 0:
                v = min(v, d / (abs(nz - z) / 9.0))
            ux, uy = (nx - x) / d, (ny - y) / d
            if run is not None and abs(run[1] - v) < 1e-6 and ux * run[3] + uy * run[4] > 0.999:
                run = (run[0] + d, v, run[2], ux, uy)
            else:
                turn = 0.0 if run is None else max(0.0, ux * run[3] + uy * run[4])
                v_join = min(v, run[1] if run else v) * turn
                close(v_join)
                run = (d, v, v_join, ux, uy)
        x, y, z = nx, ny, nz
    close(0.0)
    return total


def _plan(groups, start, end, motion, deadline, rng, should_stop):
    """Plans the free groups one after the other within the budget. Returns (lines, head position)."""
    out = []
    at = start
    for k, group in enumerate(groups):
        if should_stop is not None and should_stop():
            raise RuntimeError("Abgebrochen")
        # every limit for splitting rows gets a quick plan, the best one gets the rest of the time
        share = deadline if k == len(groups) - 1 else time.monotonic() + (deadline - time.monotonic()) / (len(groups) - k)
        best = None
        for extra in GAP_EXTRAS:
            blocks = _blocks(group, motion, extra)
            if not blocks:
                continue
            tour = _greedy(blocks, at, motion)
            cost, chosen = _directions(tour, blocks, at, end, motion)
            lines = []
            _emit_group(tour, chosen, blocks, at, lines)
            seconds = estimate_seconds(_with_start(at, lines), motion)
            if best is None or seconds < best[0]:
                best = (seconds, blocks, tour)
        if best is None:
            continue
        _, blocks, tour = best
        tour, _ = _improve(tour, blocks, at, end, motion, share, rng)
        _, chosen = _directions(tour, blocks, at, end, motion)
        at = _emit_group(tour, chosen, blocks, at, out)
    return out, at


def _with_start(at, lines):
    return (["G0 X%.3f Y%.3f" % at] if at is not None else []) + lines


def optimize(lines, motion=None, *, budget_s=4.0, start=(0.0, 0.0), end=(0.0, 0.0), should_stop=None, seed=1):
    """(lines, report). Unreadable or not faster: the lines as they came, with the reason in the report."""
    motion = motion or Motion()
    lines = list(lines)
    began = time.monotonic()
    report = {"applied": False, "reason": "", "before_s": None, "after_s": None, "seconds": 0.0, "blocks": 0}
    if not any(l.startswith(APP_HEADER) for l in lines[:5]):
        report["reason"] = "kein App-Auftrag"
        return lines, report
    if any("LUMACUT-CAPTURE" in l for l in lines):
        report["reason"] = "Messauftrag"
        return lines, report
    try:
        head, sections, tail = _parse(lines)
    except _Unreadable as exc:
        report["reason"] = str(exc)
        return lines, report

    free, later_groups, fixed, cuts = [], [], [], []
    for s in sections:
        if s.is_cut:
            cuts.append(s)
        elif s.focus_steps:
            fixed.append(s)
        elif len([p for p in s.passes if p]) > 1:
            later_groups += [[p] for p in s.passes if p]
        else:
            free.append(s.strokes())
    groups = ([free] if free else []) + later_groups
    body, at = _plan(groups, tuple(start), tuple(end), motion, began + budget_s, random.Random(seed), should_stop)
    for s in fixed + cuts:
        if s.start is not None:
            body.append("G0 X%.3f Y%.3f" % s.start)
        body += [l for l in s.raw if not l.lstrip().startswith(";")]
    result = head + body + tail

    report["seconds"] = round(time.monotonic() - began, 2)
    report["before_s"] = round(estimate_seconds(lines, motion), 1)
    report["after_s"] = round(estimate_seconds(result, motion), 1)
    if _burn_set(lines) != _burn_set(result):
        report["reason"] = "Prüfung: Laserbahnen weichen ab"
        return lines, report
    before, after = _extent(lines), _extent(result)
    if before and after and (after[0] < before[0] - 1e-3 or after[1] > before[1] + 1e-3
                             or after[2] < before[2] - Y_TAKE_UP_MM - 1e-3 or after[3] > before[3] + 1e-3):
        report["reason"] = "Prüfung: Fahrten außerhalb des Auftrags"
        return lines, report
    if report["after_s"] >= report["before_s"]:
        report["reason"] = "Nicht schneller als die Datei"
        return lines, report
    report["applied"] = True
    return result, report
