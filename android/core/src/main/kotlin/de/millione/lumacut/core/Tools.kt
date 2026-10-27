package de.millione.lumacut.core

import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/** Align and distribute (like LightBurn's alignment bar). Returns one translation per box. */
object Align {
    enum class Mode(val label: String) { LEFT("Links"), CENTER_X("Mitte"), RIGHT("Rechts"), TOP("Oben"), CENTER_Y("Mitte"), BOTTOM("Unten") }

    /** Moves every box onto the edge / centre line [mode] of [ref]. */
    fun offsets(boxes: List<Box>, mode: Mode, ref: Box): List<Pt> = boxes.map { b ->
        when (mode) {
            Mode.LEFT -> Pt(ref.minX - b.minX, 0.0)
            Mode.CENTER_X -> Pt(ref.center.x - b.center.x, 0.0)
            Mode.RIGHT -> Pt(ref.maxX - b.maxX, 0.0)
            Mode.TOP -> Pt(0.0, ref.minY - b.minY)
            Mode.CENTER_Y -> Pt(0.0, ref.center.y - b.center.y)
            Mode.BOTTOM -> Pt(0.0, ref.maxY - b.maxY)
        }
    }

    /** Equal gaps between the boxes, the outermost two stay where they are. */
    fun distribute(boxes: List<Box>, horizontal: Boolean): List<Pt> {
        if (boxes.size < 3) return boxes.map { Pt(0.0, 0.0) }
        fun lo(b: Box) = if (horizontal) b.minX else b.minY
        fun size(b: Box) = if (horizontal) b.width else b.height
        val order = boxes.indices.sortedBy { lo(boxes[it]) }
        val first = boxes[order.first()]
        val end = order.maxOf { lo(boxes[it]) + size(boxes[it]) }
        val gap = (end - lo(first) - boxes.sumOf(::size)) / (boxes.size - 1)
        val out = Array(boxes.size) { Pt(0.0, 0.0) }
        var at = lo(first)
        for (i in order) {
            val d = at - lo(boxes[i])
            out[i] = if (horizontal) Pt(d, 0.0) else Pt(0.0, d)
            at += size(boxes[i]) + gap
        }
        return out.toList()
    }
}

/** Weld, subtract and intersect of closed shapes, computed on a fine grid (0.1 mm) like a raster trace. */
object Booleans {
    enum class Op(val label: String) { UNION("Verschweißen"), SUBTRACT("Abziehen"), INTERSECT("Schnittmenge") }

    /**
     * [shapes] = the closed paths of each element (even-odd inside one element). UNION joins all, SUBTRACT
     * removes all others from the first, INTERSECT keeps what all have in common. Empty result = nothing left.
     */
    fun apply(shapes: List<List<Poly>>, op: Op, pxPerMm: Double = 10.0): List<Poly> {
        val closed = shapes.map { s -> s.filter { it.size >= 3 } }.filter { it.isNotEmpty() }
        if (closed.size < 2) return closed.flatten()
        val box = boundsOf(closed.flatten()) ?: return emptyList()
        val p = min(pxPerMm, 3000.0 / max(box.width, box.height).coerceAtLeast(1.0))
        val m = 2.0
        val x0 = box.minX - m; val y0 = box.minY - m
        val w = ceil((box.width + 2 * m) * p).toInt() + 1; val h = ceil((box.height + 2 * m) * p).toInt() + 1
        val masks = closed.map { Contour.rasterize(it, x0, y0, w, h, p) }
        val out = BooleanArray(w * h) { i ->
            when (op) {
                Op.UNION -> masks.any { it[i] }
                Op.SUBTRACT -> masks[0][i] && masks.drop(1).none { it[i] }
                Op.INTERSECT -> masks.all { it[i] }
            }
        }
        return Contour.fromMask(Mask(w, h, out, p, x0, y0), 0.0, 0.0, false, 0.05)
    }
}

/** Holding tabs ("Haltestege"): small uncut gaps so cut parts stay in the sheet until taken out. */
object Tabs {
    /** Closed paths get [count] gaps of [widthMm], evenly spread; open or too short paths stay as they are. */
    fun apply(polys: List<Poly>, count: Int, widthMm: Double): List<Poly> = polys.flatMap { poly ->
        val len = poly.length()
        if (!poly.isClosed() || count < 1 || widthMm <= 0 || len < count * widthMm * 3) listOf(poly)
        else {
            // gaps centred at (k + 0.5) * len / count; the cut runs from the end of one gap to the start of the next
            val step = len / count
            (0 until count).map { k ->
                val from = (k + 0.5) * step + widthMm / 2
                val to = (k + 1.5) * step - widthMm / 2
                slice(poly, from, to, len)
            }
        }
    }

    /** The part of closed [poly] between arc lengths [from] and [to] (may wrap past the start). */
    private fun slice(poly: Poly, from: Double, to: Double, len: Double): Poly {
        val out = ArrayList<Pt>()
        fun at(s0: Double): Pt {
            var s = s0 % len
            for ((a, b) in poly.zipWithNext()) {
                val d = a.dist(b)
                if (s <= d && d > 0) return Pt(a.x + (b.x - a.x) * s / d, a.y + (b.y - a.y) * s / d)
                s -= d
            }
            return poly.last()
        }
        out += at(from)
        // vertices strictly between from and to, walking forwards (twice round covers the wrap)
        var s = 0.0
        val verts = ArrayList<Pair<Double, Pt>>()
        for ((a, b) in poly.zipWithNext()) { s += a.dist(b); verts += s to b }
        for (lap in 0..1) for ((sv, v) in verts) {
            val t = sv + lap * len
            if (t > from && t < to) out += v
        }
        out += at(to)
        return out
    }
}

/** Space-saving arrangement: boxes shelf-packed plate after plate. */
object Nest {
    /** Plate index and translation per box; null = larger than a plate (or more than [maxPlates] plates needed). */
    fun place(boxes: List<Box>, w: Double = Work.WIDTH, h: Double = Work.HEIGHT, maxPlates: Int = 20): List<Pair<Int, Pt>?> {
        val out = arrayOfNulls<Pair<Int, Pt>>(boxes.size)
        var rest = boxes.indices.filter { boxes[it].width <= w - 2 && boxes[it].height <= h - 2 }
        var plate = 0
        while (rest.isNotEmpty() && plate < maxPlates) {
            val packed = ImportLayout.shelf(rest.map { boxes[it] }, w, h)
            rest.forEachIndexed { k, i -> packed[k]?.let { out[i] = plate to it } }
            rest = rest.filterIndexed { k, _ -> packed[k] == null }
            plate++
        }
        return out.toList()
    }
}

/**
 * Finger-jointed box (like the box makers of xTool / LightBurn / boxes.py). Outer size [w] x [d] x [h] mm,
 * material [t] mm, fingers about [finger] mm wide. Without [closed] the top stays open.
 */
data class BoxSpec(val w: Double, val d: Double, val h: Double, val t: Double, val finger: Double, val closed: Boolean = false)

object BoxMaker {
    /** Panels as closed polylines (origin top-left of each panel), with names. */
    fun panels(s: BoxSpec): List<Pair<String, Poly>> {
        require(s.t > 0 && s.finger > 0 && min(s.w, min(s.d, s.h)) > 4 * s.t) { "Box zu klein für diese Materialstärke" }
        // Edge kinds: A = fingers at the ends (outer line), B = notches at the ends (inset by t), F = flat.
        val bottom = panel(s.w, s.d, s.t, s.finger, "AAAA")
        val top = if (s.closed) "B" else "F"
        // front/back: top, right, bottom, left (clockwise from the top edge)
        val front = panel(s.w, s.h, s.t, s.finger, top + "A" + "B" + "A")
        val side = panel(s.d, s.h, s.t, s.finger, top + "B" + "B" + "B")
        val list = arrayListOf("Boden" to bottom, "Vorne" to front, "Hinten" to front, "Links" to side, "Rechts" to side)
        if (s.closed) list += "Deckel" to bottom
        return list
    }

    /** Odd number of segments, each about [finger] long (at least 3 when the edge is long enough). */
    fun segments(len: Double, finger: Double): Int {
        var n = floor(len / finger).toInt()
        if (n % 2 == 0) n -= 1
        return max(1, n)
    }

    /**
     * Rectangle [w] x [h] walked clockwise (top, right, bottom, left in y-down coordinates); [kinds] = edge kind
     * per edge. Segment i of an A edge lies on the outline for even i, inset by [t] for odd i; B is the reverse.
     */
    private fun panel(w: Double, h: Double, t: Double, finger: Double, kinds: String): Poly {
        val corners = listOf(Pt(0.0, 0.0), Pt(w, 0.0), Pt(w, h), Pt(0.0, h))
        val dirs = listOf(Pt(1.0, 0.0), Pt(0.0, 1.0), Pt(-1.0, 0.0), Pt(0.0, -1.0))   // along each edge
        val normals = listOf(Pt(0.0, 1.0), Pt(-1.0, 0.0), Pt(0.0, -1.0), Pt(1.0, 0.0)) // inwards
        val lengths = listOf(w, h, w, h)
        val offsets = (0..3).map { e ->
            when (kinds[e]) {
                'F' -> listOf(0.0)
                else -> { val n = segments(lengths[e], finger); List(n) { i -> if ((i % 2 == 0) == (kinds[e] == 'A')) 0.0 else t } }
            }
        }
        val out = ArrayList<Pt>()
        for (e in 0..3) {
            val p = corners[e]; val u = dirs[e]; val v = normals[e]
            val d = offsets[e]; val prevLast = offsets[(e + 3) % 4].last()
            fun pt(a: Double, off: Double) = Pt(p.x + u.x * a + v.x * off, p.y + u.y * a + v.y * off)
            out += pt(prevLast, d.first())                    // corner: previous edge's inset runs along this edge
            val seg = lengths[e] / d.size
            for (k in 1 until d.size) { out += pt(seg * k, d[k - 1]); out += pt(seg * k, d[k]) }
        }
        out += out.first()
        return out.filterIndexed { i, q -> i == 0 || q.dist(out[i - 1]) > 1e-9 }
    }
}
