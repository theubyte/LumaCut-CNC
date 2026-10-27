package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Lasered dot grid for the head-camera calibration: 17 × 13 dots, 12 mm
 * apart, centred in the work area. The centre dot is big, the dot right of
 * it and the one two rows below it are medium: from those three the
 * detection knows which dot is which, also when the camera is turned or
 * mirrored. One photo of it gives the lens distortion, the scale, the
 * rotation and the camera offset at once.
 */
object DotGrid {
    const val HALF_COLS = 8
    const val HALF_ROWS = 6
    const val PITCH = 12.0
    const val R_DOT = 1.2
    const val R_MID = 2.0
    const val R_BIG = 3.0

    /** Shift of the grid from the work-area centre (0 in the app; a calibration run that shares one plate with other tests moves it). */
    var offset: Pt = Pt(0.0, 0.0)

    val center: Pt get() = Work.center + offset

    fun position(i: Int, j: Int) = Pt(center.x + i * PITCH, center.y + j * PITCH)

    fun radius(i: Int, j: Int) = when {
        i == 0 && j == 0 -> R_BIG
        (i == 1 && j == 0) || (i == 0 && j == 2) -> R_MID
        else -> R_DOT
    }

    /** Area of the grid in work mm (with the dots' radius). */
    fun bounds() = Box(center.x - HALF_COLS * PITCH - R_BIG, center.y - HALF_ROWS * PITCH - R_BIG,
                       center.x + HALF_COLS * PITCH + R_BIG, center.y + HALF_ROWS * PITCH + R_BIG)

    /**
     * A dot as one open spiral from the rim inwards, [pitch] apart, ending
     * at [hole] radius. No tight turns in the middle: there the head would
     * brake while the laser keeps its power, and the wood chars and sparks.
     * The burn spreads enough to close the small centre.
     */
    fun dot(c: Pt, r: Double, pitch: Double = 0.25, hole: Double = 0.45): Poly {
        val out = ArrayList<Pt>()
        var a = 0.0; var rr = r
        out += Pt(c.x + r, c.y)
        while (rr > hole) {
            a += 0.25 / rr                              // ~0.25 mm segments, constant speed
            rr = r - pitch * a / (2 * PI)
            out += Pt(c.x + rr * cos(a), c.y + rr * sin(a))
        }
        return out
    }

    /** All dots, row by row in a serpentine (short travel). */
    fun paths(): List<Poly> = (-HALF_ROWS..HALF_ROWS).flatMap { j ->
        val cols = (-HALF_COLS..HALF_COLS).let { if ((j + HALF_ROWS) % 2 == 0) it.toList() else it.reversed() }
        cols.map { i -> dot(position(i, j), radius(i, j)) }
    }

    /** Laser power for the grid, chosen by the operator: 20 % first, more when the camera finds too few dots. */
    const val POWER_MIN = 20.0
    const val POWER_MAX = 60.0

    /** G-code for the grid: low power and fast, light brown dots are enough for the camera. */
    fun job(powerPct: Double = POWER_MIN): String {
        require(powerPct in POWER_MIN..POWER_MAX) { "Leistung für das Punktraster: 20–60 %" }
        val layer = Layer(name = "Punktraster", color = 0xFF4FD8B4, mode = LayerMode.LINE, powerPct = powerPct, speed = 1800.0)
        val e = Element(layerId = layer.id, kind = "Punktraster", paths = paths())
        return MarlinWriter("kamera-punktraster").write(Document("Kamera-Punktraster", listOf(layer), listOf(e)))
    }

    /* ---------- detection ---------- */

    class Blob(val x: Double, val y: Double, val area: Int)

    /**
     * Dark round spots in an ARGB photo: pixels clearly darker than their
     * surroundings (local mean over a window of 1/12 of the image width),
     * grouped, centre weighted by darkness. Spots cut by the image border,
     * long streaks (grain, edges) and specks are dropped.
     */
    fun detect(argb: IntArray, w: Int, h: Int): List<Blob> {
        require(argb.size == w * h) { "Ungültige Bilddaten" }
        val lum = IntArray(w * h) { val c = argb[it]; (((c shr 16) and 255) * 299 + ((c shr 8) and 255) * 587 + (c and 255) * 114) / 1000 }
        val stride = w + 1
        val integ = LongArray(stride * (h + 1))
        for (y in 0 until h) {
            var row = 0L
            for (x in 0 until w) { row += lum[y * w + x]; integ[(y + 1) * stride + x + 1] = integ[y * stride + x + 1] + row }
        }
        val r = max(8, w / 24)
        val weight = IntArray(w * h)
        for (y in 0 until h) {
            val y0 = max(0, y - r); val y1 = min(h, y + r + 1)
            for (x in 0 until w) {
                val x0 = max(0, x - r); val x1 = min(w, x + r + 1)
                val sum = integ[y1 * stride + x1] - integ[y0 * stride + x1] - integ[y1 * stride + x0] + integ[y0 * stride + x0]
                val mean = sum.toDouble() / ((x1 - x0) * (y1 - y0))
                val l = lum[y * w + x]
                if (l < mean * 0.82 - 4) weight[y * w + x] = (mean - l).roundToInt().coerceAtLeast(1)
            }
        }
        val seen = BooleanArray(w * h)
        val stack = IntArray(w * h)
        val blobs = ArrayList<Blob>()
        val maxArea = w * h / 150
        for (start in 0 until w * h) {
            if (weight[start] == 0 || seen[start]) continue
            var top = 0; stack[top++] = start; seen[start] = true
            var count = 0; var sw = 0.0; var sx = 0.0; var sy = 0.0
            var minX = w; var maxX = -1; var minY = h; var maxY = -1
            while (top > 0) {
                val p = stack[--top]; val px = p % w; val py = p / w
                val wt = weight[p].toDouble()
                count++; sw += wt; sx += wt * (px + 0.5); sy += wt * (py + 0.5)
                if (px < minX) minX = px; if (px > maxX) maxX = px; if (py < minY) minY = py; if (py > maxY) maxY = py
                for (dy in -1..1) for (dx in -1..1) {
                    val nx = px + dx; val ny = py + dy
                    if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue
                    val q = ny * w + nx
                    if (!seen[q] && weight[q] > 0) { seen[q] = true; stack[top++] = q }
                }
            }
            val bw = maxX - minX + 1; val bh = maxY - minY + 1
            if (count < 12 || count > maxArea || bw < 4 || bh < 4) continue
            if (minX == 0 || minY == 0 || maxX == w - 1 || maxY == h - 1) continue
            if (max(bw, bh) > 2.5 * min(bw, bh)) continue
            if (count < 0.45 * bw * bh) continue
            blobs += Blob(sx / sw, sy / sw, count)
        }
        return blobs
    }

    /**
     * Grid index (i, j) → pixel for the blobs belonging to the grid. Starts
     * at the big centre dot, takes the directions from the two medium dots
     * and walks from dot to dot, each step predicted from the last one (so
     * the bending of a wide-angle lens is followed).
     */
    /** The big centre dot and the two direction dots as pixel vectors (e1 = one pitch right, e2 = one pitch down). */
    private class Markers(val big: Blob, val e1: Pt, val e2: Pt, val spacing: Double)

    private fun markers(blobs: List<Blob>): Markers {
        require(blobs.size >= 20) { "Zu wenige Punkte im Bild (${blobs.size}) – Raster ganz im Bild? Licht?" }
        val median = blobs.map { it.area }.sorted()[blobs.size / 2].toDouble()
        val spacing = blobs.map { b -> blobs.filter { it !== b }.minOf { hypot(it.x - b.x, it.y - b.y) } }.sorted()[blobs.size / 2]
        val big = blobs.maxBy { it.area }
        // a wide-angle lens magnifies the centre: measure the spacing at the big dot itself
        val step = blobs.filter { it !== big }.map { hypot(it.x - big.x, it.y - big.y) }.sorted().take(4).let { it[it.size / 2] }
        fun d(b: Blob) = hypot(b.x - big.x, b.y - big.y) / step
        val near = blobs.filter { it !== big && d(it) < 2.5 }.map { it.area }.sorted()
        val local = if (near.size >= 8) near[near.size / 2].toDouble() else median
        require(big.area > 4.0 * local) { "Großen Mittelpunkt nicht gefunden – Raster-Mitte ins Bild fahren" }
        val mids = blobs.filter { it !== big && it.area > 1.7 * local && it.area < 4.4 * local }
        val right = mids.filter { d(it) in 0.6..1.5 }.minByOrNull { abs(d(it) - 1) }
        val down = mids.filter { d(it) in 1.5..2.6 }.minByOrNull { abs(d(it) - 2) }
        require(right != null && down != null) { "Richtungspunkte neben der Mitte nicht gefunden – Bild schärfer stellen oder Licht prüfen" }
        return Markers(big, Pt(right.x - big.x, right.y - big.y), Pt((down.x - big.x) / 2, (down.y - big.y) / 2), spacing)
    }

    /**
     * Where the image centre looks, in work mm relative to the grid centre
     * (rough, from the dots next to the centre), or null when the centre
     * dot is not in the picture. Moving the head by minus this value brings
     * the grid centre into the middle of the picture.
     */
    fun locate(argb: IntArray, w: Int, h: Int): Pt? {
        val m = runCatching { markers(detect(argb, w, h)) }.getOrNull() ?: return null
        val vx = w / 2.0 - m.big.x; val vy = h / 2.0 - m.big.y
        val det = m.e1.x * m.e2.y - m.e2.x * m.e1.y
        if (abs(det) < 1e-9) return null
        val a = (vx * m.e2.y - m.e2.x * vy) / det
        val b = (m.e1.x * vy - vx * m.e1.y) / det
        return Pt(a * PITCH, b * PITCH)
    }

    /**
     * Grid index (i, j) → pixel for the blobs belonging to the grid. Starts
     * at the big centre dot, takes the directions from the two medium dots
     * and walks from dot to dot, each step predicted from the last one (so
     * the bending of a wide-angle lens is followed).
     */
    fun index(blobs: List<Blob>): Map<Pair<Int, Int>, Pt> {
        val mk = markers(blobs)
        val big = mk.big; val spacing = mk.spacing
        val cell = spacing
        val buckets = HashMap<Long, MutableList<Int>>()
        fun key(gx: Int, gy: Int) = (gx.toLong() shl 32) xor (gy.toLong() and 0xFFFFFFFFL)
        blobs.forEachIndexed { k, b -> buckets.getOrPut(key((b.x / cell).toInt(), (b.y / cell).toInt())) { mutableListOf() } += k }
        fun nearest(p: Pt, maxD: Double): Int? {
            var best: Int? = null; var bestD = maxD
            val cx = (p.x / cell).toInt(); val cy = (p.y / cell).toInt()
            for (gy in cy - 1..cy + 1) for (gx in cx - 1..cx + 1) {
                val list = buckets[key(gx, gy)] ?: continue
                for (k in list) { val dd = hypot(blobs[k].x - p.x, blobs[k].y - p.y); if (dd < bestD) { bestD = dd; best = k } }
            }
            return best
        }

        val bigK = blobs.indexOf(big)
        val found = HashMap<Pair<Int, Int>, Pt>()
        val used = HashSet<Int>()
        val e1 = mk.e1
        val e2 = mk.e2
        class Node(val i: Int, val j: Int, val p: Pt, val e1: Pt, val e2: Pt)
        val queue = ArrayDeque<Node>()
        found[0 to 0] = Pt(big.x, big.y); used += bigK
        queue += Node(0, 0, Pt(big.x, big.y), e1, e2)
        while (queue.isNotEmpty()) {
            val n = queue.removeFirst()
            for ((di, dj) in listOf(1 to 0, -1 to 0, 0 to 1, 0 to -1)) {
                val i = n.i + di; val j = n.j + dj
                if (abs(i) > HALF_COLS || abs(j) > HALF_ROWS || (i to j) in found) continue
                val pred = n.p + n.e1 * di.toDouble() + n.e2 * dj.toDouble()
                val step = if (di != 0) hypot(n.e1.x, n.e1.y) else hypot(n.e2.x, n.e2.y)
                val k = nearest(pred, 0.3 * step) ?: continue
                if (k in used) continue
                val q = Pt(blobs[k].x, blobs[k].y)
                used += k; found[i to j] = q
                val ne1 = if (di != 0) (q - n.p) * di.toDouble() else n.e1
                val ne2 = if (dj != 0) (q - n.p) * dj.toDouble() else n.e2
                queue += Node(i, j, q, ne1, ne2)
            }
        }
        return found
    }

    class Result(val calibration: CameraCalibration, val points: List<Pt>, val lens: Lens)

    /**
     * Calibration from one photo of the grid taken with the head at [head]
     * (work mm) and Z at [scanZ]. Throws with a German message when the
     * grid is not found or the fit is implausible.
     */
    fun calibrate(argb: IntArray, w: Int, h: Int, head: Pt, scanZ: Double): Result {
        val found = index(detect(argb, w, h))
        require(found.size >= 20) { "Nur ${found.size} Rasterpunkte zugeordnet – Raster ganz ins Bild, scharf stellen" }
        val keys = found.keys.toList()
        val px = keys.map { found.getValue(it) }
        val rel = keys.map { (i, j) -> position(i, j) - head }
        val spacingPx = keys.mapNotNull { (i, j) -> found[i + 1 to j]?.dist(found.getValue(i to j)) }.average()
        val b = boundsOf(listOf(px))!!
        val m = spacingPx / 2
        val valid = Box(max(0.0, b.minX - m), max(0.0, b.minY - m), min(w.toDouble(), b.maxX + m), min(h.toDouble(), b.maxY + m))
        val lens = Lens.fit(px, rel, w, h, valid)
        require(lens.monotonic()) { "Linsenmodell kippt am Rand – Raster mittiger ins Bild und erneut versuchen" }
        require(lens.rmsMm < 0.6) { "Rasterpunkte passen schlecht zusammen (%.2f mm) – Bild unscharf oder verwackelt?".format(lens.rmsMm) }
        return Result(CameraCalibration(w, h, scanZ = scanZ, lens = lens), px, lens)
    }
}
