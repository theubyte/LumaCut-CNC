package de.millione.lumacut.core

import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Finding the sharp height of the head camera: its lens is focused by hand
 * once, so the Pi moves Z until the picture is sharpest.
 */
object CameraFocus {
    /**
     * Sharpness of the middle 60 % of a picture: mean squared Laplacian on
     * every second pixel, divided by the squared mean brightness so that
     * the camera's own exposure changes do not count.
     */
    fun sharpness(argb: IntArray, w: Int, h: Int): Double {
        require(argb.size == w * h) { "Ungültige Bilddaten" }
        fun g(x: Int, y: Int): Double { val c = argb[y * w + x]; return (((c shr 16) and 255) * 0.299 + ((c shr 8) and 255) * 0.587 + (c and 255) * 0.114) }
        val x0 = (w * 0.2).toInt().coerceAtLeast(2); val x1 = (w * 0.8).toInt().coerceAtMost(w - 3)
        val y0 = (h * 0.2).toInt().coerceAtLeast(2); val y1 = (h * 0.8).toInt().coerceAtMost(h - 3)
        var sum = 0.0; var bright = 0.0; var n = 0
        var y = y0
        while (y <= y1) {
            var x = x0
            while (x <= x1) {
                val c = g(x, y)
                val lap = 4 * c - g(x - 2, y) - g(x + 2, y) - g(x, y - 2) - g(x, y + 2)
                sum += lap * lap; bright += c; n++
                x += 2
            }
            y += 2
        }
        if (n == 0) return 0.0
        val mean = bright / n
        return sum / n / (mean * mean + 1.0)
    }

    /** Z jog steps the Pi accepts (±10, ±1, ±0.1 mm) that add up to [delta] (rounded to 0.1 mm). */
    fun jogSteps(delta: Double): List<Double> {
        var tenths = (delta * 10).roundToInt()
        val out = ArrayList<Double>()
        for (unit in intArrayOf(100, 10, 1)) {
            while (abs(tenths) >= unit) {
                val s = if (tenths > 0) unit else -unit
                out += s / 10.0; tenths -= s
            }
        }
        return out
    }

    /**
     * Height of the sharpest picture from measured (z, sharpness) pairs:
     * the best sample, refined by a parabola through it and its neighbours.
     */
    fun peak(samples: List<Pair<Double, Double>>): Double {
        require(samples.isNotEmpty()) { "Keine Schärfewerte" }
        val s = samples.sortedBy { it.first }
        val i = s.indices.maxBy { s[it].second }
        if (i == 0 || i == s.size - 1) return s[i].first
        val (za, a) = s[i - 1]; val (zb, b) = s[i]; val (zc, c) = s[i + 1]
        val denom = (za - zb) * (za - zc) * (zb - zc)
        if (abs(denom) < 1e-12) return zb
        val p = (zc * (b - a) + zb * (a - c) + za * (c - b)) / denom
        val q = (zc * zc * (a - b) + zb * zb * (c - a) + za * za * (b - c)) / denom
        if (p >= 0) return zb
        return (-q / (2 * p)).coerceIn(za, zc)
    }

    /** True when the best sample lies at the end of the searched range (lens set for a height out of reach). */
    fun atEdge(samples: List<Pair<Double, Double>>): Boolean {
        val s = samples.sortedBy { it.first }
        val i = s.indices.maxBy { s[it].second }
        return i == 0 || i == s.size - 1
    }
}
