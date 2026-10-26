package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sin

class DxfException(message: String) : IllegalArgumentException(message)

/**
 * ASCII DXF to polylines in millimetres, Y pointing down like the work area.
 * Supports LINE, LWPOLYLINE and POLYLINE (with bulge arcs), CIRCLE, ARC,
 * ELLIPSE, SPLINE and INSERT of blocks (position, scale, rotation, nested).
 * Units from $INSUNITS (none = mm). Text, hatches and dimensions are skipped.
 */
object DxfImport {
    private const val SEG_MM = 0.25
    private const val MAX_POINTS = 400_000

    private class Entity(val type: String, val codes: List<Pair<Int, String>>) {
        fun d(code: Int, default: Double = 0.0) = codes.firstOrNull { it.first == code }?.second?.trim()?.toDoubleOrNull() ?: default
        fun i(code: Int, default: Int = 0) = codes.firstOrNull { it.first == code }?.second?.trim()?.toIntOrNull() ?: default
        fun s(code: Int) = codes.firstOrNull { it.first == code }?.second?.trim()
        fun all(code: Int) = codes.filter { it.first == code }.mapNotNull { it.second.trim().toDoubleOrNull() }
    }

    fun parse(bytes: ByteArray): List<Poly> {
        val text = bytes.toString(Charsets.UTF_8).ifEmpty { throw DxfException("Leere Datei") }
        if (text.startsWith("AutoCAD Binary DXF")) throw DxfException("Binäres DXF wird nicht unterstützt – als ASCII-DXF speichern")
        val lines = text.lines()
        val pairs = ArrayList<Pair<Int, String>>(lines.size / 2)
        var k = 0
        while (k + 1 < lines.size) {
            val code = lines[k].trim().toIntOrNull() ?: throw DxfException("Keine gültige DXF-Datei")
            pairs += code to lines[k + 1]
            k += 2
        }
        var units = 1.0
        val blocks = HashMap<String, MutableList<Entity>>()
        val entities = ArrayList<Entity>()
        var section = ""
        var i = 0
        var currentBlock: MutableList<Entity>? = null
        while (i < pairs.size) {
            val (code, value) = pairs[i]
            val v = value.trim()
            if (code == 0 && v == "SECTION") { section = pairs.getOrNull(i + 1)?.second?.trim() ?: ""; i += 2; continue }
            if (code == 0 && v == "ENDSEC") { section = ""; i++; continue }
            if (section == "HEADER" && code == 9 && v == "\$INSUNITS") {
                units = when (pairs.getOrNull(i + 1)?.second?.trim()?.toIntOrNull()) { 1 -> 25.4; 5 -> 10.0; 6 -> 1000.0; 2 -> 304.8; else -> 1.0 }
                i += 2; continue
            }
            if (code == 0 && (section == "ENTITIES" || section == "BLOCKS")) {
                // collect one entity: all pairs until the next code 0
                var j = i + 1
                val body = ArrayList<Pair<Int, String>>()
                while (j < pairs.size && pairs[j].first != 0) { body += pairs[j]; j++ }
                val e = Entity(v, body)
                when {
                    section == "BLOCKS" && v == "BLOCK" -> { currentBlock = ArrayList<Entity>().also { blocks[e.s(2) ?: ""] = it } }
                    section == "BLOCKS" && v == "ENDBLK" -> currentBlock = null
                    section == "BLOCKS" -> currentBlock?.add(e)
                    else -> entities += e
                }
                i = j; continue
            }
            i++
        }
        val out = ArrayList<Poly>()
        emit(entities, Matrix(), blocks, out, depth = 0)
        if (out.isEmpty()) throw DxfException("Keine unterstützten Zeichnungselemente gefunden")
        if (out.sumOf { it.size } > MAX_POINTS) throw DxfException("DXF zu komplex")
        val scaled = out.map { poly -> poly.map { Pt(it.x * units, it.y * units) } }
        // DXF Y points up; the work area Y points down.
        val b = boundsOf(scaled)!!
        return scaled.map { poly -> poly.map { Pt(it.x - b.minX, b.maxY - it.y) } }
    }

    private fun emit(list: List<Entity>, m: Matrix, blocks: Map<String, List<Entity>>, out: MutableList<Poly>, depth: Int) {
        if (depth > 8) return
        var idx = 0
        while (idx < list.size) {
            val e = list[idx]
            val local: List<Poly> = when (e.type) {
                "LINE" -> listOf(listOf(Pt(e.d(10), e.d(20)), Pt(e.d(11), e.d(21))))
                "LWPOLYLINE" -> {
                    val pts = ArrayList<Pair<Pt, Double>>()
                    var cur: Pt? = null; var bulge = 0.0; var x: Double? = null
                    for ((code, value) in e.codes) when (code) {
                        10 -> { cur?.let { pts += it to bulge }; x = value.trim().toDouble(); bulge = 0.0; cur = null }
                        20 -> cur = Pt(x ?: 0.0, value.trim().toDouble())
                        42 -> bulge = value.trim().toDouble()
                    }
                    cur?.let { pts += it to bulge }
                    listOf(bulgePath(pts, closed = (e.i(70) and 1) == 1))
                }
                "POLYLINE" -> {
                    val pts = ArrayList<Pair<Pt, Double>>()
                    var j = idx + 1
                    while (j < list.size && list[j].type == "VERTEX") { pts += Pt(list[j].d(10), list[j].d(20)) to list[j].d(42); j++ }
                    if (j < list.size && list[j].type == "SEQEND") j++
                    idx = j - 1
                    listOf(bulgePath(pts, closed = (e.i(70) and 1) == 1))
                }
                "CIRCLE" -> listOf(arc(Pt(e.d(10), e.d(20)), e.d(40), 0.0, 2 * PI))
                "ARC" -> {
                    val a0 = Math.toRadians(e.d(50)); var a1 = Math.toRadians(e.d(51))
                    if (a1 <= a0) a1 += 2 * PI
                    listOf(arc(Pt(e.d(10), e.d(20)), e.d(40), a0, a1))
                }
                "ELLIPSE" -> {
                    val c = Pt(e.d(10), e.d(20)); val major = Pt(e.d(11), e.d(21)); val ratio = e.d(40, 1.0)
                    var t0 = e.d(41, 0.0); var t1 = e.d(42, 2 * PI)
                    if (t1 <= t0) t1 += 2 * PI
                    val a = hypot(major.x, major.y); val rot = kotlin.math.atan2(major.y, major.x)
                    val n = max(24, ceil((t1 - t0) * a / SEG_MM).toInt()).coerceAtMost(2000)
                    listOf((0..n).map { s ->
                        val t = t0 + (t1 - t0) * s / n
                        val ex = a * cos(t); val ey = a * ratio * sin(t)
                        Pt(c.x + ex * cos(rot) - ey * sin(rot), c.y + ex * sin(rot) + ey * cos(rot))
                    })
                }
                "SPLINE" -> listOf(spline(e))
                "INSERT" -> {
                    val block = blocks[e.s(2) ?: ""]
                    if (block != null) {
                        val r = Math.toRadians(e.d(50))
                        val sx = e.d(41, 1.0); val sy = e.d(42, 1.0)
                        val t = m * Matrix(e = e.d(10), f = e.d(20)) * Matrix(cos(r), sin(r), -sin(r), cos(r)) * Matrix(a = sx, d = sy)
                        emit(block, t, blocks, out, depth + 1)
                    }
                    emptyList()
                }
                else -> emptyList()
            }
            local.filter { it.size >= 2 }.forEach { poly -> out += poly.map(m::apply) }
            idx++
        }
    }

    /** Polyline with bulge arcs (bulge = tan(angle / 4), positive counter-clockwise). */
    private fun bulgePath(pts: List<Pair<Pt, Double>>, closed: Boolean): Poly {
        if (pts.isEmpty()) return emptyList()
        val out = arrayListOf(pts.first().first)
        val count = if (closed) pts.size else pts.size - 1
        for (k in 0 until count) {
            val (p0, bulge) = pts[k]
            val p1 = pts[(k + 1) % pts.size].first
            if (abs(bulge) < 1e-9) { out += p1; continue }
            val theta = 4 * atan(bulge)
            val chord = p0.dist(p1)
            val r = chord / (2 * sin(abs(theta) / 2))
            val mid = Pt((p0.x + p1.x) / 2, (p0.y + p1.y) / 2)
            val h = r * cos(theta / 2)
            val nx = -(p1.y - p0.y) / chord; val ny = (p1.x - p0.x) / chord
            val sgn = if (bulge > 0) 1 else -1
            val c = Pt(mid.x + nx * h * sgn, mid.y + ny * h * sgn)
            val a0 = kotlin.math.atan2(p0.y - c.y, p0.x - c.x)
            val n = max(4, ceil(abs(theta) * r / SEG_MM).toInt()).coerceAtMost(720)
            for (s in 1..n) {
                val a = a0 + theta * s / n
                out += if (s == n) p1 else Pt(c.x + r * cos(a), c.y + r * sin(a))
            }
        }
        if (closed && out.first() != out.last()) out += out.first()
        return out
    }

    private fun arc(c: Pt, r: Double, a0: Double, a1: Double): Poly {
        val n = max(12, ceil((a1 - a0) * r / SEG_MM).toInt()).coerceAtMost(2000)
        return (0..n).map { s -> val a = a0 + (a1 - a0) * s / n; Pt(c.x + r * cos(a), c.y + r * sin(a)) }
    }

    /** B-spline (de Boor) from control points and knots; fit points as fallback. */
    private fun spline(e: Entity): Poly {
        val degree = e.i(71, 3)
        val knots = e.all(40)
        val cx = e.all(10); val cy = e.all(20)
        val ctrl = cx.zip(cy).map { Pt(it.first, it.second) }
        if (ctrl.size < 2 || knots.size != ctrl.size + degree + 1) {
            val fx = e.all(11); val fy = e.all(21)
            return fx.zip(fy).map { Pt(it.first, it.second) }.ifEmpty { ctrl }
        }
        val t0 = knots[degree]; val t1 = knots[ctrl.size]
        val approx = ctrl.zipWithNext().sumOf { (a, b) -> a.dist(b) }
        val n = max(16, ceil(approx / SEG_MM).toInt()).coerceAtMost(4000)
        return (0..n).map { s ->
            val t = if (s == n) t1 - 1e-9 * (t1 - t0) else t0 + (t1 - t0) * s / n
            var span = degree
            while (span < ctrl.size - 1 && t >= knots[span + 1]) span++
            val d = Array(degree + 1) { j -> ctrl[span - degree + j] }
            for (r in 1..degree) for (j in degree downTo r) {
                val i = span - degree + j
                val denom = knots[i + degree - r + 1] - knots[i]
                val alpha = if (denom == 0.0) 0.0 else (t - knots[i]) / denom
                d[j] = Pt((1 - alpha) * d[j - 1].x + alpha * d[j].x, (1 - alpha) * d[j - 1].y + alpha * d[j].y)
            }
            d[degree]
        }
    }
}
