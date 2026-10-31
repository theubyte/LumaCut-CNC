package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

/**
 * Measured surface heights (machine Z of the probe contact) on a regular
 * grid over one area, work-area mm. NaN = not measured (filled by neighbours).
 */
@Serializable
data class HeightMap(val name: String, val x0: Double, val y0: Double, val stepX: Double, val stepY: Double,
                     val cols: Int, val rows: Int, val z: List<Double>) {
    init { require(cols >= 1 && rows >= 1 && z.size == cols * rows) { "Ungültiges Höhenmesh" } }

    val box get() = Box(x0, y0, x0 + stepX * (cols - 1), y0 + stepY * (rows - 1))
    val measured get() = z.filter { !it.isNaN() }
    val min get() = measured.minOrNull() ?: Double.NaN
    val max get() = measured.maxOrNull() ?: Double.NaN

    fun covers(p: Pt, marginMm: Double = 1.0) =
        p.x in box.minX - marginMm..box.maxX + marginMm && p.y in box.minY - marginMm..box.maxY + marginMm

    /** Bilinear surface Z at [p] (clamped to the grid). */
    fun at(p: Pt): Double {
        val fx = if (cols > 1) ((p.x - x0) / stepX).coerceIn(0.0, cols - 1.0) else 0.0
        val fy = if (rows > 1) ((p.y - y0) / stepY).coerceIn(0.0, rows - 1.0) else 0.0
        val c0 = fx.toInt().coerceAtMost(cols - 1); val r0 = fy.toInt().coerceAtMost(rows - 1)
        val c1 = min(c0 + 1, cols - 1); val r1 = min(r0 + 1, rows - 1)
        val tx = fx - c0; val ty = fy - r0
        fun v(c: Int, r: Int) = z[r * cols + c]
        val top = v(c0, r0) * (1 - tx) + v(c1, r0) * tx
        val bottom = v(c0, r1) * (1 - tx) + v(c1, r1) * tx
        return top * (1 - ty) + bottom * ty
    }

    /** Copy with missing points replaced by the mean of measured neighbours (repeated until full). */
    fun filled(): HeightMap {
        val v = z.toMutableList()
        repeat(cols + rows) {
            var missing = false
            for (r in 0 until rows) for (c in 0 until cols) if (v[r * cols + c].isNaN()) {
                val n = listOf(c - 1 to r, c + 1 to r, c to r - 1, c to r + 1)
                    .filter { (cc, rr) -> cc in 0 until cols && rr in 0 until rows }
                    .map { (cc, rr) -> v[rr * cols + cc] }.filter { !it.isNaN() }
                if (n.isNotEmpty()) v[r * cols + c] = n.average() else missing = true
            }
            if (!missing) return copy(z = v)
        }
        return copy(z = v)
    }

    companion object {
        /**
         * Grid over [area] (work mm) with about [spacingMm] between points and
         * [marginMm] from the edges; at least 2 x 2 points unless the area is tiny.
         */
        fun grid(name: String, area: Box, spacingMm: Double, marginMm: Double = 3.0): HeightMap {
            val inner = Box(area.minX + marginMm, area.minY + marginMm, area.maxX - marginMm, area.maxY - marginMm)
            val w = max(0.0, inner.width); val h = max(0.0, inner.height)
            val cols = if (w < 1) 1 else max(2, ceil(w / spacingMm).toInt() + 1)
            val rows = if (h < 1) 1 else max(2, ceil(h / spacingMm).toInt() + 1)
            val cx = if (w < 1) area.center.x else inner.minX; val cy = if (h < 1) area.center.y else inner.minY
            return HeightMap(name, cx, cy, if (cols > 1) w / (cols - 1) else 0.0, if (rows > 1) h / (rows - 1) else 0.0,
                cols, rows, List(cols * rows) { Double.NaN })
        }
    }

    /** Points to probe, serpentine order, in work mm. */
    fun points(): List<Pair<Int, Pt>> = (0 until rows).flatMap { r ->
        val cs = if (r % 2 == 0) 0 until cols else (cols - 1 downTo 0)
        cs.map { c -> (r * cols + c) to Pt(x0 + c * stepX, y0 + r * stepY) }
    }
}

/** All areas of one job. Outside every area the highest measured surface applies (never too low). */
@Serializable
data class HeightMapSet(val maps: List<HeightMap>) {
    val highest get() = maps.flatMap { it.measured }.maxOrNull()
    val lowest get() = maps.flatMap { it.measured }.minOrNull()

    fun surface(p: Pt): Pair<Double, Boolean> {
        val m = maps.filter { it.covers(p) }.minByOrNull { hypot(it.box.center.x - p.x, it.box.center.y - p.y) }
        return if (m != null) m.at(p) to true else (highest ?: throw IllegalStateException("Höhenmesh leer")) to false
    }
}

class FocusReport(val segments: Int, val outsideMm: Double, val minZ: Double, val maxZ: Double, val warnings: List<String>)

/**
 * Adds per-segment focus height from a [HeightMapSet] to a LumaCut job
 * (machine mm), like the Windows app's apply_focus_compensation:
 * Z = surface + focusGap − tipOffset, never below surface + 2 mm; burning
 * lines split into ≤ [maxSegMm] pieces; relative per-pass focus drops
 * (G91 / G0 Z-… / G90) become an offset on the mesh Z; rapids go up first
 * and lower at the target; arcs and absolute Z are refused.
 */
object FocusCompensation {
    private val WORD = Regex("([A-Z])\\s*([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))")

    fun apply(gcode: String, maps: HeightMapSet, focusGapMm: Double, tipOffsetMm: Double, maxSegMm: Double = 2.0): Pair<String, FocusReport> {
        val gap = focusGapMm - tipOffsetMm
        require(gap >= 2.0) { "Fokus läge näher als 2 mm am Werkstück" }
        val out = StringBuilder()
        var x = 0.0; var y = 0.0; var relative = false
        var drop = 0.0; var pendingDrop = false
        var lastZ = Double.NaN; var segments = 0; var outside = 0.0
        var minZ = Double.MAX_VALUE; var maxZ = -Double.MAX_VALUE
        val warnings = mutableListOf<String>()
        fun f(v: Double) = "%.3f".format(Locale.ROOT, v)
        fun zAt(px: Double, py: Double, length: Double): Double {
            val (s, inside) = maps.surface(Work.fromMachine(px, py))
            if (!inside) outside += length
            val z = s + gap - drop
            if (z < s + 2.0 - 1e-9) throw IllegalArgumentException("Fokus-Absenkung führt unter Oberfläche + 2 mm")
            minZ = min(minZ, z); maxZ = max(maxZ, z)
            return z
        }
        for (raw in gcode.lines()) {
            val line = raw.substringBefore(';').trim().uppercase()
            if (line.isEmpty()) { if (raw.isNotBlank()) out.append(raw).append('\n'); continue }
            if (line == "G91") { relative = true; continue }
            if (line == "G90") { relative = false; if (pendingDrop) pendingDrop = false; continue }
            val words = WORD.findAll(line).associate { it.groupValues[1][0] to it.groupValues[2].toDouble() }
            val g = Regex("^G0*(\\d+)").find(line)?.groupValues?.get(1)?.toInt()
            if (g == 2 || g == 3) throw IllegalArgumentException("Bögen (G2/G3) werden für die Fokuskorrektur nicht unterstützt")
            if (relative) {
                // only the per-pass focus drop blocks of MarlinWriter are allowed here
                if (g == 0 && words.keys - 'G' == setOf('Z', 'F')) { drop -= words.getValue('Z'); pendingDrop = true; continue }
                throw IllegalArgumentException("Relative Bewegungen außer Fokus-Absenkung nicht unterstützt")
            }
            if ((g == 0 || g == 1) && words.containsKey('Z')) throw IllegalArgumentException("Auftrag enthält bereits Z-Werte")
            if (g == 0 && (words.containsKey('X') || words.containsKey('Y'))) {
                val nx = words['X'] ?: x; val ny = words['Y'] ?: y
                val zTarget = zAt(nx, ny, 0.0)
                val safe = if (lastZ.isNaN()) zTarget else max(lastZ, zTarget)
                if (!lastZ.isNaN() && safe > lastZ + 1e-6) out.append("G0 Z${f(safe)} F600\n")
                out.append("G0 X${f(nx)} Y${f(ny)}").append(words['F']?.let { " F${it.toInt()}" } ?: "").append('\n')
                if (zTarget < safe - 1e-6 || lastZ.isNaN()) out.append("G0 Z${f(zTarget)} F600\n")
                lastZ = zTarget; x = nx; y = ny
                continue
            }
            if (g == 1 && (words.containsKey('X') || words.containsKey('Y'))) {
                val nx = words['X'] ?: x; val ny = words['Y'] ?: y
                val len = hypot(nx - x, ny - y)
                val n = max(1, ceil(len / maxSegMm).toInt())
                val tail = buildString {
                    words['F']?.let { append(" F${it.toInt()}") }
                    words['S']?.let { append(" S${it.toInt()}") }
                }
                for (k in 1..n) {
                    val px = x + (nx - x) * k / n; val py = y + (ny - y) * k / n
                    val z = zAt(px, py, len / n)
                    out.append("G1 X${f(px)} Y${f(py)} Z${f(z)}$tail\n")
                    lastZ = z; segments++
                }
                x = nx; y = ny
                continue
            }
            out.append(raw.trim()).append('\n')
        }
        if (outside > 0.5) warnings += "%.0f mm Laserweg liegen außerhalb der abgetasteten Bereiche – dort gilt die höchste gemessene Oberfläche".format(Locale.GERMANY, outside)
        return out.toString() to FocusReport(segments, outside, if (segments > 0) minZ else Double.NaN, if (segments > 0) maxZ else Double.NaN, warnings)
    }
}
