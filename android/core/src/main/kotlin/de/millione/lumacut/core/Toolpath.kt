package de.millione.lumacut.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sin

/** One straight piece of the toolpath as the machine executes it. */
class Segment(val x0: Float, val y0: Float, val x1: Float, val y1: Float,
              val power: Int, val cut: Boolean, val line: Int)

class ToolpathStats(val cutMm: Double, val travelMm: Double, val seconds: Double,
                    val maxPower: Int, val warnings: List<String>)

class Toolpath(val segments: List<Segment>, val bounds: Box?, val stats: ToolpathStats, val lineCount: Int) {
    /** Estimated remaining seconds when the machine has sent [line] of [lineCount]. */
    fun remainingSeconds(line: Int): Double =
        if (lineCount <= 0) 0.0 else stats.seconds * (1.0 - line.toDouble() / lineCount).coerceIn(0.0, 1.0)

    companion object {
        private const val TRAVEL_FEED = 9000.0   // the Pi adds F9000 to XY rapids without F
        // Speeding up and slowing down costs about v/a extra wherever the head
        // stops or turns sharply (> 60°); grey-scale power changes along a
        // straight line cost nothing. Atomstack board: $120 = 1000 mm/s².
        private const val ACCEL = 1000.0
        private const val ARC_MM = 0.5
        private val WORD = Regex("([A-Z])\\s*([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))")

        /**
         * Marlin 2.1 inline laser semantics: M3 I arms, M5 disarms, G0 forces
         * power 0, G1/G2/G3 use their S or the last S since the previous G0.
         */
        fun parse(text: String): Toolpath {
            val lines = text.lines()
            val segments = ArrayList<Segment>()
            var x = 0.0; var y = 0.0; var absolute = true; var scale = 1.0
            var feed = 1000.0; var power = 0; var armed = false
            var cutMm = 0.0; var travelMm = 0.0; var seconds = 0.0; var maxPower = 0; var cuts = 0
            var unpowered = 0
            var dirX = 0.0; var dirY = 0.0
            var box: Box? = null
            for ((index, raw) in lines.withIndex()) {
                val line = raw.replace(Regex("\\([^)]*\\)"), "").substringBefore(';').trim().uppercase()
                if (line.isEmpty()) continue
                if (line.startsWith("M3") && Regex("\\bI\\b").containsMatchIn(line)) { armed = true; continue }
                if (line.startsWith("M5")) { armed = false; power = 0; continue }
                val gs = ArrayList<Int>()
                val w = HashMap<Char, Double>()
                for (m in WORD.findAll(line)) {
                    val letter = m.groupValues[1][0]
                    val value = m.groupValues[2].toDouble()
                    if (letter == 'G') gs += value.toInt() else if (letter != 'M') w[letter] = value
                }
                if (20 in gs) scale = 25.4
                if (21 in gs) scale = 1.0
                if (90 in gs) absolute = true
                if (91 in gs) absolute = false
                val motion = gs.firstOrNull { it in 0..3 } ?: continue
                w['F']?.let { feed = it * scale }
                val nx = w['X']?.let { if (absolute) it * scale else x + it * scale } ?: x
                val ny = w['Y']?.let { if (absolute) it * scale else y + it * scale } ?: y
                val rapid = motion == 0
                if (rapid) power = 0
                else if (w.containsKey('S')) power = w.getValue('S').toInt().coerceIn(0, 255)
                else if (armed && power == 0) unpowered++
                val cut = !rapid && armed && power > 0
                val points = if ((motion == 2 || motion == 3) && (w.containsKey('I') || w.containsKey('J')))
                    arc(x, y, nx, ny, (w['I'] ?: 0.0) * scale, (w['J'] ?: 0.0) * scale, motion == 2)
                else listOf(Pt(nx, ny))
                val speed = if (rapid && !w.containsKey('F')) TRAVEL_FEED else feed
                var px = x; var py = y
                for (p in points) {
                    val len = hypot(p.x - px, p.y - py)
                    if (len > 0) {
                        segments += Segment(px.toFloat(), py.toFloat(), p.x.toFloat(), p.y.toFloat(), if (cut) power else 0, cut, index + 1)
                        if (cut) {
                            cutMm += len; cuts++; maxPower = max(maxPower, power)
                            box = Box(minOf(px, p.x), minOf(py, p.y), maxOf(px, p.x), maxOf(py, p.y)).union(box)
                        } else travelMm += len
                        seconds += len / max(speed, 1.0) * 60
                        val ux = (p.x - px) / len; val uy = (p.y - py) / len
                        if (ux * dirX + uy * dirY < 0.5) seconds += speed / 60.0 / ACCEL
                        dirX = ux; dirY = uy
                    }
                    px = p.x; py = p.y
                }
                x = nx; y = ny
            }
            val warnings = mutableListOf<String>()
            if (unpowered > 0) warnings += "$unpowered Laserfahrten nach Leerfahrt ohne S-Wert: Marlin lasert dort mit 0"
            val b = box
            if (b == null) warnings += "Keine Laserbewegung gefunden"
            else if (b.minX < 0.0 || b.minY < 0.0 || b.maxX > Bed.WIDTH || b.maxY > Bed.HEIGHT || Bed.touchesPark(b))
                warnings += "Motiv berührt die Park-Ecke oder liegt außerhalb der Arbeitsfläche"
            return Toolpath(segments, b, ToolpathStats(cutMm, travelMm, seconds, maxPower, warnings), lines.size)
        }

        private fun arc(x0: Double, y0: Double, x1: Double, y1: Double, i: Double, j: Double, cw: Boolean): List<Pt> {
            val cx = x0 + i; val cy = y0 + j; val r = hypot(i, j)
            var a0 = atan2(y0 - cy, x0 - cx); var a1 = atan2(y1 - cy, x1 - cx)
            if (cw) { if (a1 >= a0) a1 -= 2 * PI } else if (a1 <= a0) a1 += 2 * PI
            val n = max(2, ceil(abs(a1 - a0) * r / ARC_MM).toInt())
            return (1..n).map { k ->
                if (k == n) Pt(x1, y1) else {
                    val a = a0 + (a1 - a0) * k / n
                    Pt(cx + r * cos(a), cy + r * sin(a))
                }
            }
        }
    }
}

fun formatDuration(seconds: Double): String {
    val s = max(0.0, seconds).toLong()
    val h = s / 3600; val m = (s % 3600) / 60; val r = s % 60
    return when {
        h > 0 -> "%d h %02d min".format(h, m)
        m > 0 -> "%d min %02d s".format(m, r)
        else -> "$r s"
    }
}
