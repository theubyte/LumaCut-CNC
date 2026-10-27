package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Brightness fall-off of the head camera towards the picture edges
 * (vignetting, uneven light), per colour channel on a coarse grid over the
 * photo in normalised coordinates, so it fits every picture size. [gain]
 * holds cols × rows × 3 factors (row by row, R G B) that bring a pixel to
 * the brightness of the picture centre; the outer nodes lie on the picture
 * border.
 */
@Serializable
data class Shading(val cols: Int, val rows: Int, val gain: List<Float>) {
    init { require(cols >= 2 && rows >= 2 && gain.size == cols * rows * 3) { "Ungültige Helligkeitskorrektur" } }

    /** Gain of channel [ch] (0 = R, 1 = G, 2 = B) at photo position u, v (0..1), bilinear between the nodes. */
    fun at(u: Double, v: Double, ch: Int): Double {
        val x = (u * (cols - 1)).coerceIn(0.0, cols - 1.0); val y = (v * (rows - 1)).coerceIn(0.0, rows - 1.0)
        val x0 = min(x.toInt(), cols - 2); val y0 = min(y.toInt(), rows - 2)
        val fx = x - x0; val fy = y - y0
        fun g(i: Int, j: Int) = gain[(j * cols + i) * 3 + ch].toDouble()
        val top = g(x0, y0) + (g(x0 + 1, y0) - g(x0, y0)) * fx
        val bottom = g(x0, y0 + 1) + (g(x0 + 1, y0 + 1) - g(x0, y0 + 1)) * fx
        return top + (bottom - top) * fy
    }

    /** [c] (ARGB) at photo position u, v corrected to centre brightness. */
    fun correct(c: Int, u: Double, v: Double): Int {
        val r = (((c shr 16) and 255) * at(u, v, 0)).roundToInt().coerceIn(0, 255)
        val g = (((c shr 8) and 255) * at(u, v, 1)).roundToInt().coerceIn(0, 255)
        val b = ((c and 255) * at(u, v, 2)).roundToInt().coerceIn(0, 255)
        return (c and 0xFF000000.toInt()) or (r shl 16) or (g shl 8) or b
    }

    companion object {
        /**
         * From photos of a plain white sheet taken at slightly different head
         * positions: each photo divided by its own centre (the camera adjusts
         * its brightness from picture to picture), per cell the median over
         * the photos (marks, dust and fibres differ between them), then a
         * smooth surface (polynomial of degree 4) through the cells, which
         * also reaches the picture border. Factors relative to the centre.
         */
        fun measure(photos: List<IntArray>, w: Int, h: Int, cols: Int = 32): Shading {
            require(photos.isNotEmpty() && photos.all { it.size == w * h }) { "Ungültige Bilddaten" }
            val rows = max(2, (cols * h.toDouble() / w).roundToInt())
            val perPhoto = photos.map { px ->
                val cells = DoubleArray(cols * rows * 3); val n = IntArray(cols * rows)
                var y = 0
                while (y < h) {
                    val j = min(rows - 1, y * rows / h)
                    var x = 0
                    while (x < w) {
                        val k = j * cols + min(cols - 1, x * cols / w)
                        val c = px[y * w + x]
                        cells[k * 3] += ((c shr 16) and 255).toDouble(); cells[k * 3 + 1] += ((c shr 8) and 255).toDouble(); cells[k * 3 + 2] += (c and 255).toDouble()
                        n[k]++
                        x += 2
                    }
                    y += 2
                }
                for (k in n.indices) for (ch in 0..2) cells[k * 3 + ch] /= max(1, n[k])
                val centre = DoubleArray(3) { ch -> centreMean(cells, cols, rows, ch) }
                DoubleArray(cells.size) { cells[it] / max(1.0, centre[it % 3]) }
            }
            val median = DoubleArray(cols * rows * 3) { i -> perPhoto.map { it[i] }.sorted().let { s -> s[s.size / 2] } }
            // surface per channel over u, v in -1..1 (cell centres)
            val us = DoubleArray(cols * rows) { k -> ((k % cols) + 0.5) / cols * 2 - 1 }
            val vs = DoubleArray(cols * rows) { k -> ((k / cols) + 0.5) / rows * 2 - 1 }
            val fits = (0..2).map { ch -> fit(us, vs, DoubleArray(cols * rows) { median[it * 3 + ch] }) }
            val nodes = ArrayList<Float>(cols * rows * 3)
            val centre = DoubleArray(3) { ch -> eval(fits[ch], 0.0, 0.0) }
            for (j in 0 until rows) for (i in 0 until cols) for (ch in 0..2) {
                val v = eval(fits[ch], i.toDouble() / (cols - 1) * 2 - 1, j.toDouble() / (rows - 1) * 2 - 1)
                nodes += (centre[ch] / max(0.05, v)).coerceIn(0.5, 4.0).toFloat()
            }
            return Shading(cols, rows, nodes)
        }

        private const val DEGREE = 4

        private fun terms(u: Double, v: Double): DoubleArray {
            val out = ArrayList<Double>()
            for (a in 0..DEGREE) for (b in 0..DEGREE - a) out += Math.pow(u, a.toDouble()) * Math.pow(v, b.toDouble())
            return out.toDoubleArray()
        }

        private fun eval(c: DoubleArray, u: Double, v: Double): Double = terms(u, v).foldIndexed(0.0) { i, s, t -> s + c[i] * t }

        /** Least squares polynomial through (u, v, z): normal equations, Gaussian elimination with pivoting. */
        private fun fit(u: DoubleArray, v: DoubleArray, z: DoubleArray): DoubleArray {
            val n = terms(0.0, 0.0).size
            val a = Array(n) { DoubleArray(n + 1) }
            for (k in z.indices) {
                val t = terms(u[k], v[k])
                for (r in 0 until n) { for (c in 0 until n) a[r][c] += t[r] * t[c]; a[r][n] += t[r] * z[k] }
            }
            for (col in 0 until n) {
                val p = (col until n).maxBy { abs(a[it][col]) }
                val tmp = a[col]; a[col] = a[p]; a[p] = tmp
                if (abs(a[col][col]) < 1e-12) continue
                for (r in 0 until n) if (r != col) {
                    val f = a[r][col] / a[col][col]
                    for (c in col..n) a[r][c] -= f * a[col][c]
                }
            }
            return DoubleArray(n) { if (abs(a[it][it]) < 1e-12) 0.0 else a[it][n] / a[it][it] }
        }

        /** Mean of channel [ch] over the middle cells (a fifth of the picture each way). */
        private fun centreMean(cells: DoubleArray, cols: Int, rows: Int, ch: Int): Double {
            val i0 = cols * 2 / 5; val i1 = max(i0, cols * 3 / 5 - 1); val j0 = rows * 2 / 5; val j1 = max(j0, rows * 3 / 5 - 1)
            var sum = 0.0; var n = 0
            for (j in j0..j1) for (i in i0..i1) { sum += cells[(j * cols + i) * 3 + ch]; n++ }
            return sum / n
        }
    }
}

/** Helpers for the light calibration (white balance on a white sheet). */
object CameraLight {
    /**
     * Colour cast of the middle of a picture of a white sheet: ln(R / B) of
     * the bright pixels (> half the brightest ones, so marks and shadows do
     * not count). 0 = neutral, > 0 = too warm (red), < 0 = too cold (blue).
     */
    fun tint(argb: IntArray, w: Int, h: Int): Double {
        require(argb.size == w * h) { "Ungültige Bilddaten" }
        var r = 0.0; var b = 0.0
        val lum = ArrayList<Int>()
        val x0 = w / 4; val x1 = w * 3 / 4; val y0 = h / 4; val y1 = h * 3 / 4
        for (y in y0 until y1 step 3) for (x in x0 until x1 step 3) { val c = argb[y * w + x]; lum += luminance(c) }
        val bright = lum.sorted().let { it[it.size * 9 / 10] } / 2
        for (y in y0 until y1 step 3) for (x in x0 until x1 step 3) {
            val c = argb[y * w + x]
            if (luminance(c) < bright) continue
            r += ((c shr 16) and 255) + 1; b += (c and 255) + 1
        }
        if (r == 0.0 || b == 0.0) throw IllegalStateException("Bild zu dunkel – Licht an, weißes Blatt unter der Kamera?")
        return ln(r / b)
    }

    /** Mean luminance of the middle half (0..255): plausibility of the white sheet. */
    fun brightness(argb: IntArray, w: Int, h: Int): Double {
        var sum = 0.0; var n = 0
        for (y in h / 4 until h * 3 / 4 step 4) for (x in w / 4 until w * 3 / 4 step 4) { sum += luminance(argb[y * w + x]); n++ }
        return sum / max(1, n)
    }

    /**
     * White balance (Kelvin) at which [tintAt] is 0: both ends of [range]
     * first, then halving. The cast falls or rises steadily with the
     * setting; when it does not change sign in the range the end with the
     * smaller cast is taken.
     */
    suspend fun whiteBalance(range: IntRange, steps: Int = 6, tintAt: suspend (Int) -> Double): Int {
        var lo = range.first; var hi = range.last
        var tLo = tintAt(lo); var tHi = tintAt(hi)
        if (tLo * tHi > 0) return if (abs(tLo) < abs(tHi)) lo else hi
        repeat(steps) {
            val mid = (lo + hi) / 2
            if (hi - lo < 50) return@repeat
            val t = tintAt(mid)
            if (t * tLo > 0) { lo = mid; tLo = t } else { hi = mid; tHi = t }
        }
        // linear between the last two
        val k = if (tHi == tLo) 0.5 else -tLo / (tHi - tLo)
        return (lo + (hi - lo) * k.coerceIn(0.0, 1.0)).roundToInt()
    }

    fun luminance(c: Int) = (((c shr 16) and 255) * 299 + ((c shr 8) and 255) * 587 + (c and 255) * 114) / 1000
}
