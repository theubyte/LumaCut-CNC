package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.sin

/** Text on a curve: bends flat text outlines (mm, y down) along a circle. */
object ArcText {
    /**
     * [radiusMm] > 0: text on top of a circle, letters pointing outwards (reads left to right).
     * [radiusMm] < 0: text along the bottom of the circle, letters pointing to the centre.
     * The baseline (bottom of [paths]) follows the circle; the middle of the text is at the circle's
     * top / bottom. Arc length of the baseline equals the flat length. Result is not moved.
     */
    fun bend(paths: List<Poly>, radiusMm: Double): List<Poly> {
        require(abs(radiusMm) >= 1.0) { "Radius mindestens 1 mm" }
        val box = boundsOf(paths) ?: return paths
        val r0 = abs(radiusMm)
        val cx = box.center.x; val base = box.maxY
        return paths.map { poly ->
            poly.map { p ->
                val theta = (p.x - cx) / r0
                val above = base - p.y
                if (radiusMm > 0) {
                    val r = r0 + above
                    Pt(r * sin(theta), r0 - r * cos(theta))        // circle top at y = 0, centre at (0, r0)
                } else {
                    val r = max(0.01, r0 - above)
                    Pt(r * sin(theta), r * cos(theta) - r0)        // circle bottom at y = 0, centre at (0, -r0)
                }
            }
        }
    }
}

/** Copies of a motif in a grid, for series parts. */
object Arrange {
    /** Offsets of all copies except the original: [nx] x [ny] pieces of [piece] with [gapX]/[gapY] between them. */
    fun gridOffsets(piece: Box, nx: Int, ny: Int, gapX: Double, gapY: Double): List<Pt> {
        require(nx in 1..50 && ny in 1..50) { "Höchstens 50 Stück je Richtung" }
        val out = ArrayList<Pt>()
        for (j in 0 until ny) for (i in 0 until nx) {
            if (i == 0 && j == 0) continue
            out += Pt(i * (piece.width + gapX), j * (piece.height + gapY))
        }
        return out
    }

    /** Offsets whose moved [piece] stays inside the work area; the rest is reported by the caller. */
    fun inside(piece: Box, offsets: List<Pt>) = offsets.filter {
        Work.contains(Box(piece.minX + it.x, piece.minY + it.y, piece.maxX + it.x, piece.maxY + it.y))
    }
}

/** Ready-made outlines, origin at the top-left of their box. Closed polylines only. */
object ShapeLib {
    fun heart(w: Double, h: Double): Poly {
        val n = 120
        // classic parametric heart, scaled into the box
        val raw = (0..n).map { k ->
            val t = 2 * PI * k / n
            Pt(16 * sin(t).let { it * it * it }, -(13 * cos(t) - 5 * cos(2 * t) - 2 * cos(3 * t) - cos(4 * t)))
        }
        val b = boundsOf(listOf(raw))!!
        return raw.map { Pt((it.x - b.minX) / b.width * w, (it.y - b.minY) / b.height * h) }
    }

    fun star(points: Int, w: Double, h: Double, innerRatio: Double = 0.45): Poly {
        val n = points.coerceIn(3, 24)
        val raw = (0..2 * n).map { k ->
            val a = -PI / 2 + PI * k / n
            val r = if (k % 2 == 0) 1.0 else innerRatio.coerceIn(0.1, 0.9)
            Pt(r * cos(a), r * sin(a))
        }
        val b = boundsOf(listOf(raw))!!
        return raw.map { Pt((it.x - b.minX) / b.width * w, (it.y - b.minY) / b.height * h) }
    }

    /** Pendant: rounded outline plus a hole near the top edge, as two closed polylines (outline, hole). */
    fun pendant(w: Double, h: Double, holeDiameter: Double = 4.0): List<Poly> {
        val outline = Shapes.rect(w, h, minOf(w, h) * 0.25)
        val hole = Shapes.ellipse(holeDiameter, holeDiameter).map { Pt(it.x + (w - holeDiameter) / 2, it.y + holeDiameter * 0.8) }
        return listOf(outline, hole)
    }
}
