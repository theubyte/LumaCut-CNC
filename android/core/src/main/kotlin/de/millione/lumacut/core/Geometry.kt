package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/** Machine bed in mm. Origin top-left as seen on the tablet, Y grows downwards. */
object Bed {
    const val WIDTH = 390.0
    const val HEIGHT = 370.0
    /** L-shaped home band: X < 30 or Y < 30 stays free of material and cuts. */
    const val SAFE = 30.0

    fun inWorkArea(x: Double, y: Double) = x >= SAFE && y >= SAFE && x <= WIDTH && y <= HEIGHT
}

@Serializable
data class Pt(val x: Double, val y: Double) {
    operator fun plus(o: Pt) = Pt(x + o.x, y + o.y)
    operator fun minus(o: Pt) = Pt(x - o.x, y - o.y)
    operator fun times(k: Double) = Pt(x * k, y * k)
    fun dist(o: Pt) = hypot(x - o.x, y - o.y)
}

/** A polyline; closed shapes repeat the first point at the end. */
typealias Poly = List<Pt>

fun Poly.length(): Double = zipWithNext().sumOf { (a, b) -> a.dist(b) }
fun Poly.isClosed(eps: Double = 1e-6) = size > 2 && first().dist(last()) < eps

data class Box(val minX: Double, val minY: Double, val maxX: Double, val maxY: Double) {
    val width get() = maxX - minX
    val height get() = maxY - minY
    val center get() = Pt((minX + maxX) / 2, (minY + maxY) / 2)
    fun union(o: Box?) = if (o == null) this else Box(min(minX, o.minX), min(minY, o.minY), max(maxX, o.maxX), max(maxY, o.maxY))
    fun contains(p: Pt) = p.x in minX..maxX && p.y in minY..maxY
}

fun boundsOf(polys: Iterable<Poly>): Box? {
    var box: Box? = null
    for (poly in polys) for (p in poly) {
        val b = Box(p.x, p.y, p.x, p.y)
        box = b.union(box)
    }
    return box
}

/** 2D affine transform: scale, rotate (degrees, around origin), translate. */
@Serializable
data class Transform(val x: Double = 0.0, val y: Double = 0.0, val scaleX: Double = 1.0,
                     val scaleY: Double = 1.0, val rotation: Double = 0.0) {
    fun apply(p: Pt): Pt {
        val sx = p.x * scaleX
        val sy = p.y * scaleY
        val r = Math.toRadians(rotation)
        val c = cos(r)
        val s = sin(r)
        return Pt(sx * c - sy * s + x, sx * s + sy * c + y)
    }
}

/**
 * Horizontal hatch lines inside closed polygons (even-odd rule), for filled
 * engraving. Returns segments in alternating direction (boustrophedon) so
 * the head never travels back across the whole width.
 */
fun hatch(polys: List<Poly>, spacing: Double): List<Poly> {
    require(spacing > 0.01) { "Zeilenabstand zu klein" }
    val closed = polys.filter { it.size >= 3 }
    val box = boundsOf(closed) ?: return emptyList()
    val result = mutableListOf<Poly>()
    var y = box.minY + spacing / 2
    var row = 0
    while (y <= box.maxY) {
        val xs = mutableListOf<Double>()
        for (poly in closed) {
            val pts = if (poly.isClosed()) poly else poly + poly.first()
            for ((a, b) in pts.zipWithNext()) {
                if ((a.y <= y && b.y > y) || (b.y <= y && a.y > y)) {
                    xs += a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y)
                }
            }
        }
        xs.sort()
        val pairs = xs.chunked(2).filter { it.size == 2 && it[1] - it[0] > 1e-6 }
        val ordered = if (row % 2 == 0) pairs else pairs.reversed()
        for (pair in ordered) {
            result += if (row % 2 == 0) listOf(Pt(pair[0], y), Pt(pair[1], y)) else listOf(Pt(pair[1], y), Pt(pair[0], y))
        }
        y += spacing
        row++
    }
    return result
}

/**
 * Greedy nearest-neighbour order for open paths (each may be reversed),
 * closed paths start where they are. Cuts travel time noticeably.
 */
fun orderPaths(paths: List<Poly>, start: Pt = Pt(0.0, 0.0)): List<Poly> {
    val left = paths.filter { it.size >= 2 }.toMutableList()
    val out = ArrayList<Poly>(left.size)
    var at = start
    while (left.isNotEmpty()) {
        var best = 0
        var bestDist = Double.MAX_VALUE
        var reverse = false
        for ((i, p) in left.withIndex()) {
            val d0 = at.dist(p.first())
            if (d0 < bestDist) { bestDist = d0; best = i; reverse = false }
            if (!p.isClosed()) {
                val d1 = at.dist(p.last())
                if (d1 < bestDist) { bestDist = d1; best = i; reverse = true }
            }
        }
        val chosen = left.removeAt(best).let { if (reverse) it.reversed() else it }
        out += chosen
        at = chosen.last()
    }
    return out
}

/** Polygon approximations of primitives (mm). */
object Shapes {
    fun rect(w: Double, h: Double, radius: Double = 0.0): Poly {
        if (radius <= 0) return listOf(Pt(0.0, 0.0), Pt(w, 0.0), Pt(w, h), Pt(0.0, h), Pt(0.0, 0.0))
        val r = min(radius, min(w, h) / 2)
        val out = mutableListOf<Pt>()
        fun arc(cx: Double, cy: Double, from: Double) {
            for (k in 0..8) {
                val a = Math.toRadians(from + 90.0 * k / 8)
                out += Pt(cx + r * cos(a), cy + r * sin(a))
            }
        }
        arc(w - r, r, 270.0); arc(w - r, h - r, 0.0); arc(r, h - r, 90.0); arc(r, r, 180.0)
        out += out.first()
        return out
    }

    fun ellipse(w: Double, h: Double, segmentMm: Double = 0.4): Poly {
        val rx = w / 2
        val ry = h / 2
        val n = max(24, (Math.PI * (rx + ry) / segmentMm).toInt())
        return (0..n).map { k ->
            val a = 2 * Math.PI * k / n
            Pt(rx + rx * cos(a), ry + ry * sin(a))
        }
    }

    fun polygon(sides: Int, w: Double, h: Double): Poly {
        val n = sides.coerceIn(3, 64)
        return (0..n).map { k ->
            val a = -Math.PI / 2 + 2 * Math.PI * k / n
            Pt(w / 2 + w / 2 * cos(a), h / 2 + h / 2 * sin(a))
        }
    }
}

/** Douglas–Peucker simplification for freehand strokes and dense imports. */
fun simplify(points: Poly, tolerance: Double): Poly {
    if (points.size < 3) return points
    val keep = BooleanArray(points.size)
    keep[0] = true; keep[points.size - 1] = true
    fun rec(a: Int, b: Int) {
        var maxD = 0.0
        var idx = -1
        val pa = points[a]
        val pb = points[b]
        val len = pa.dist(pb)
        for (i in a + 1 until b) {
            val p = points[i]
            val d = if (len < 1e-12) p.dist(pa)
            else kotlin.math.abs((pb.x - pa.x) * (pa.y - p.y) - (pa.x - p.x) * (pb.y - pa.y)) / len
            if (d > maxD) { maxD = d; idx = i }
        }
        if (idx >= 0 && maxD > tolerance) { keep[idx] = true; rec(a, idx); rec(idx, b) }
    }
    rec(0, points.size - 1)
    return points.filterIndexed { i, _ -> keep[i] }
}
