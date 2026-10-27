package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.random.Random

/** Shapes of the "Formen" tool, drawn into the dragged box. */
enum class ShapeKind(val label: String) { STAR("Stern"), HEART("Herz"), ARROW("Pfeil"), BUBBLE("Sprechblase"), CROSS("Kreuz"), DROP("Tropfen") }

fun ShapeLib.make(kind: ShapeKind, w: Double, h: Double): Poly = fitBox(when (kind) {
    ShapeKind.STAR -> star(5, w, h)
    ShapeKind.HEART -> heart(w, h)
    ShapeKind.ARROW -> listOf(Pt(0.0, h * .3), Pt(w * .6, h * .3), Pt(w * .6, 0.0), Pt(w, h / 2), Pt(w * .6, h), Pt(w * .6, h * .7), Pt(0.0, h * .7), Pt(0.0, h * .3))
    ShapeKind.CROSS -> { val a = w / 3; val b = h / 3
        listOf(Pt(a, 0.0), Pt(2 * a, 0.0), Pt(2 * a, b), Pt(w, b), Pt(w, 2 * b), Pt(2 * a, 2 * b), Pt(2 * a, h), Pt(a, h), Pt(a, 2 * b), Pt(0.0, 2 * b), Pt(0.0, b), Pt(a, b), Pt(a, 0.0)) }
    ShapeKind.BUBBLE -> {
        // rounded box over the upper 78 %, tail at the lower left
        val body = Shapes.rect(w, h * .78, min(w, h * .78) * .25)
        val tail = listOf(Pt(w * .18, h * .7), Pt(w * .12, h), Pt(w * .42, h * .7))
        Booleans.apply(listOf(listOf(body), listOf(tail + tail.first())), Booleans.Op.UNION).maxByOrNull { boundsOf(listOf(it))!!.let { b -> b.width * b.height } } ?: body
    }
    ShapeKind.DROP -> (0..120).map { k ->
        val t = 2 * PI * k / 120
        // teardrop: point at the top
        Pt(w / 2 + w / 2 * sin(t) * sin(t / 2), h - h * (1 + cos(t)) / 2)
    }
}, w, h)

/** [poly] stretched into the box 0..[w] x 0..[h]. */
private fun fitBox(poly: Poly, w: Double, h: Double): Poly {
    val b = boundsOf(listOf(poly)) ?: return poly
    return poly.map { Pt((it.x - b.minX) / maxOf(b.width, 1e-9) * w, (it.y - b.minY) / maxOf(b.height, 1e-9) * h) }
}

/** Smooth curve through tapped points (Catmull–Rom), for the "Kurve" tool. */
object Curves {
    fun catmullRom(points: List<Pt>, closed: Boolean, steps: Int = 12): Poly {
        if (points.size < 3) return if (closed && points.size >= 2) points + points.first() else points
        val p = if (closed) points else listOf(points.first()) + points + listOf(points.last())
        val n = p.size
        val spans = if (closed) n else n - 3
        val out = ArrayList<Pt>()
        for (i in 0 until spans) {
            val p0 = p[(i + n - 1) % n].takeIf { closed } ?: p[i]
            val p1 = if (closed) p[i] else p[i + 1]
            val p2 = if (closed) p[(i + 1) % n] else p[i + 2]
            val p3 = if (closed) p[(i + 2) % n] else p[i + 3]
            for (s in 0 until steps) {
                val t = s.toDouble() / steps; val t2 = t * t; val t3 = t2 * t
                fun c(a: Double, b: Double, cc: Double, d: Double) = 0.5 * (2 * b + (-a + cc) * t + (2 * a - 5 * b + 4 * cc - d) * t2 + (-a + 3 * b - 3 * cc + d) * t3)
                out += Pt(c(p0.x, p1.x, p2.x, p3.x), c(p0.y, p1.y, p2.y, p3.y))
            }
        }
        out += if (closed) out.first() else points.last()
        return out
    }
}

/** Engraved and cut parts of a generated piece, in mm with the piece's top-left at (0, 0). */
class Parts(val engrave: List<Poly>, val cut: List<Poly>, val marks: List<Poly> = emptyList(), val labels: List<Pair<Pt, String>> = emptyList()) {
    fun bounds(): Box? = boundsOf(engrave + cut + marks)
    /** The same parts moved so the overall top-left is at (0, 0). */
    fun normalized(): Parts {
        val b = bounds() ?: return this
        fun mv(l: List<Poly>) = l.map { p -> p.map { Pt(it.x - b.minX, it.y - b.minY) } }
        return Parts(mv(engrave), mv(cut), mv(marks), labels.map { (q, s) -> Pt(q.x - b.minX, q.y - b.minY) to s })
    }
}

enum class TagStyle(val label: String) { KEYCHAIN("Anhänger (Kontur)"), PLATE("Schild"), HEART("Herz"), ROUND("Rund") }

/** Generators for personalised pieces: name tags, emblems, frames, rulers, puzzles. */
object Personalize {
    private fun move(l: List<Poly>, dx: Double, dy: Double) = l.map { p -> p.map { Pt(it.x + dx, it.y + dy) } }
    private fun circle(cx: Double, cy: Double, d: Double) = move(listOf(Shapes.ellipse(d, d)), cx - d / 2, cy - d / 2).first()

    /** Scales [paths] about their top-left so their height is [h]. */
    fun fitHeight(paths: List<Poly>, h: Double): List<Poly> {
        val b = boundsOf(paths) ?: return paths
        val k = h / max(b.height, 1e-9)
        return paths.map { p -> p.map { Pt(b.minX + (it.x - b.minX) * k, b.minY + (it.y - b.minY) * k) } }
    }

    /** Name tag around [text] (engraved); outline and optional hole of [holeMm] are cut. */
    fun tag(text: List<Poly>, style: TagStyle, holeMm: Double?): Parts {
        val tb = boundsOf(text) ?: return Parts(emptyList(), emptyList())
        val hole = holeMm?.takeIf { it > 0 }
        val parts = when (style) {
            TagStyle.KEYCHAIN -> {
                val m = max(3.0, tb.height * 0.3)
                var outline = Contour.fromPolys(text, m, outerOnly = true)
                val cut = ArrayList<Poly>()
                if (hole != null) {
                    val ring = hole + 6.0
                    val cx = tb.minX - m - ring / 2 + 2.0; val cy = tb.center.y
                    outline = Booleans.apply(listOf(outline, listOf(circle(cx, cy, ring))), Booleans.Op.UNION)
                    cut += circle(cx, cy, hole)
                }
                Parts(text, outline + cut)
            }
            TagStyle.PLATE -> {
                val pad = max(4.0, tb.height * 0.4)
                val extra = if (hole != null) hole + 4.0 else 0.0
                val w = tb.width + 2 * pad + extra; val h = tb.height + 2 * pad
                val x0 = tb.minX - pad - extra; val y0 = tb.minY - pad
                val cut = arrayListOf(move(listOf(Shapes.rect(w, h, min(w, h) * 0.25)), x0, y0).first())
                if (hole != null) cut += circle(x0 + pad / 2 + hole / 2 + 1.0, tb.center.y, hole)
                Parts(text, cut)
            }
            TagStyle.HEART -> {
                val w = max(tb.width * 1.55, tb.height * 3.0); val h = w * 0.9
                val x0 = tb.center.x - w / 2; val y0 = tb.center.y - h * 0.42
                val cut = arrayListOf(move(listOf(ShapeLib.heart(w, h)), x0, y0).first())
                if (hole != null) cut += circle(x0 + w * 0.27, y0 + h * 0.2, hole)
                Parts(text, cut)
            }
            TagStyle.ROUND -> {
                val d = max(tb.width + 2 * max(5.0, tb.height * 0.5), tb.height * 3.0) + if (hole != null) hole * 2 else 0.0
                val cut = arrayListOf(circle(tb.center.x, tb.center.y, d))
                if (hole != null) cut += circle(tb.center.x, tb.center.y - d / 2 + hole, hole)
                Parts(text, cut)
            }
        }
        return parts.normalized()
    }

    /**
     * Round emblem of [diameter] mm: [initials] large in the middle, optional [top] text along the upper and [bottom]
     * text along the lower edge (flat text, any size). Outer circle cut, two rings marked.
     */
    fun emblem(initials: List<Poly>, top: List<Poly>?, bottom: List<Poly>?, diameter: Double): Parts {
        val r = diameter / 2
        val c = Pt(r, r)
        val arcs = top != null || bottom != null
        val mid = fitHeight(initials, diameter * if (arcs) 0.28 else 0.42)
        val mb = boundsOf(mid)
        val engrave = ArrayList<Poly>()
        if (mb != null) {
            val k = min(1.0, (if (arcs) diameter * 0.55 else diameter * 0.7) / mb.width)   // keep inside the inner ring
            engrave += mid.map { p -> p.map { Pt(c.x + (it.x - mb.center.x) * k, c.y + (it.y - mb.center.y) * k) } }
        }
        val band = diameter * 0.09
        fun arc(text: List<Poly>?, upper: Boolean) {
            val t = text?.let { fitHeight(it, band) } ?: return
            val b = boundsOf(t) ?: return
            val r0 = if (upper) diameter * 0.335 else diameter * 0.425
            val maxLen = PI * r0 * 0.85
            val flat = if (b.width > maxLen) t.map { p -> p.map { Pt(b.minX + (it.x - b.minX) * maxLen / b.width, b.maxY - (b.maxY - it.y) * maxLen / b.width) } } else t
            val bent = ArcText.bend(flat, if (upper) r0 else -r0)
            engrave += if (upper) move(bent, c.x, c.y - r0) else move(bent, c.x, c.y + r0)
        }
        arc(top, true); arc(bottom, false)
        val marks = arrayListOf(circle(c.x, c.y, diameter - 6.0))
        if (arcs) marks += circle(c.x, c.y, diameter * 0.62)
        return Parts(engrave, listOf(circle(c.x, c.y, diameter)), marks)
    }

    enum class FrameStyle(val label: String) { SIMPLE("Rechteck"), ROUNDED("Abgerundet"), DOUBLE("Doppelt"), OVAL("Oval"), DASHED("Gestrichelt") }

    /** Frame [marginMm] around [box] (work mm). */
    fun frame(box: Box, style: FrameStyle, marginMm: Double): List<Poly> {
        val x = box.minX - marginMm; val y = box.minY - marginMm
        val w = box.width + 2 * marginMm; val h = box.height + 2 * marginMm
        fun rect(dx: Double, r: Double) = move(listOf(Shapes.rect(w + 2 * dx, h + 2 * dx, r)), x - dx, y - dx).first()
        return when (style) {
            FrameStyle.SIMPLE -> listOf(rect(0.0, 0.0))
            FrameStyle.ROUNDED -> listOf(rect(0.0, min(w, h) * 0.12))
            FrameStyle.DOUBLE -> listOf(rect(0.0, 0.0), rect(2.5, 0.0))
            FrameStyle.OVAL -> {
                // an ellipse through the corners of the box (plus margin) encloses it: axes * sqrt(2)
                val ew = (box.width * 1.4142) + 2 * marginMm; val eh = (box.height * 1.4142) + 2 * marginMm
                move(listOf(Shapes.ellipse(ew, eh)), box.center.x - ew / 2, box.center.y - eh / 2)
            }
            FrameStyle.DASHED -> dashes(rect(0.0, 0.0), 4.0, 2.5)
        }
    }

    /** Pieces of [dash] mm with [gap] mm between them along [poly]. */
    fun dashes(poly: Poly, dash: Double, gap: Double): List<Poly> {
        val out = ArrayList<Poly>()
        var cur = ArrayList<Pt>()
        var s = 0.0; var on = true; var left = dash
        cur += poly.first()
        for ((a, b) in poly.zipWithNext()) {
            var from = a; var segLeft = a.dist(b)
            while (segLeft > 1e-9) {
                val step = min(segLeft, left)
                val k = step / a.dist(b)
                val to = Pt(from.x + (b.x - a.x) * k, from.y + (b.y - a.y) * k)
                if (on) cur += to
                from = to; segLeft -= step; left -= step; s += step
                if (left <= 1e-9) {
                    if (on && cur.size > 1) out += cur
                    on = !on; left = if (on) dash else gap
                    cur = ArrayList<Pt>().also { it += from }
                }
            }
        }
        if (on && cur.size > 1) out += cur
        return out
    }

    /** Ruler [lengthMm] long and [widthMm] wide: outline (cut), mm/5 mm/cm ticks (marked) and positions for the cm numbers. */
    fun ruler(lengthMm: Int, widthMm: Double, holeMm: Double?): Parts {
        val x0 = 5.0
        val w = lengthMm + 2 * x0 + if (holeMm != null) holeMm + 4 else 0.0
        val cut = arrayListOf(Shapes.rect(w, widthMm, 2.0))
        if (holeMm != null) cut += circle(w - x0 / 2 - holeMm / 2 - 1.0, widthMm / 2, holeMm)
        val marks = ArrayList<Poly>(); val labels = ArrayList<Pair<Pt, String>>()
        for (i in 0..lengthMm) {
            val len = when { i % 10 == 0 -> widthMm * 0.42; i % 5 == 0 -> widthMm * 0.3; else -> widthMm * 0.18 }
            marks += listOf(Pt(x0 + i, 0.0), Pt(x0 + i, len))
            if (i % 10 == 0) labels += Pt(x0 + i, widthMm * 0.42 + 1.5) to (i / 10).toString()
        }
        return Parts(emptyList(), cut, marks, labels)
    }

    /** Jigsaw puzzle [w] x [h] mm with [cols] x [rows] pieces: outline plus the inner cut lines with knobs. */
    fun puzzle(w: Double, h: Double, cols: Int, rows: Int, seed: Int = 7): List<Poly> {
        val rnd = Random(seed)
        // knob along a unit edge: u along, v sideways (scaled by the shorter side of the piece)
        val profile = listOf(0.0 to 0.0, 0.34 to 0.0, 0.40 to 0.02, 0.38 to 0.10, 0.35 to 0.18, 0.40 to 0.25, 0.50 to 0.27,
            0.60 to 0.25, 0.65 to 0.18, 0.62 to 0.10, 0.60 to 0.02, 0.66 to 0.0, 1.0 to 0.0)
        val cw = w / cols; val ch = h / rows; val knob = min(cw, ch)
        fun edge(a: Pt, b: Pt): Poly {
            val sign = if (rnd.nextBoolean()) 1.0 else -1.0
            val dx = b.x - a.x; val dy = b.y - a.y
            val nx = -dy / a.dist(b); val ny = dx / a.dist(b)
            val pts = profile.map { (u, v) -> Pt(a.x + dx * u + nx * v * knob * sign, a.y + dy * u + ny * v * knob * sign) }
            return Curves.catmullRom(pts, false, 8)
        }
        val out = arrayListOf(Shapes.rect(w, h))
        for (i in 1 until cols) {
            val line = ArrayList<Pt>()
            for (j in 0 until rows) { val e = edge(Pt(i * cw, j * ch), Pt(i * cw, (j + 1) * ch)); line += if (line.isEmpty()) e else e.drop(1) }
            out += line
        }
        for (j in 1 until rows) {
            val line = ArrayList<Pt>()
            for (i in 0 until cols) { val e = edge(Pt(i * cw, j * ch), Pt((i + 1) * cw, j * ch)); line += if (line.isEmpty()) e else e.drop(1) }
            out += line
        }
        return out
    }
}
