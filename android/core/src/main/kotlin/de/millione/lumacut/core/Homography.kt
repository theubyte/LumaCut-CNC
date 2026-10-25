package de.millione.lumacut.core

import kotlin.math.abs
import kotlin.math.floor

/**
 * Perspective mapping between a photo of the bed and machine millimetres,
 * from four reference points (e.g. the four corners of the work area).
 */
class Homography private constructor(private val h: DoubleArray) {

    fun map(p: Pt): Pt {
        val w = h[6] * p.x + h[7] * p.y + h[8]
        require(abs(w) > 1e-12) { "Punkt nicht abbildbar" }
        return Pt((h[0] * p.x + h[1] * p.y + h[2]) / w, (h[3] * p.x + h[4] * p.y + h[5]) / w)
    }

    companion object {
        /** Maps [from] onto [to]; both lists must contain four points, no three collinear. */
        fun fit(from: List<Pt>, to: List<Pt>): Homography {
            require(from.size == 4 && to.size == 4) { "Genau vier Referenzpunkte nötig" }
            val a = Array(8) { DoubleArray(9) }
            for (i in 0 until 4) {
                val (x, y) = from[i]; val (u, v) = to[i]
                a[2 * i] = doubleArrayOf(x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, u)
                a[2 * i + 1] = doubleArrayOf(0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, v)
            }
            for (col in 0 until 8) {
                val pivot = (col until 8).maxBy { abs(a[it][col]) }
                require(abs(a[pivot][col]) > 1e-10) { "Referenzpunkte liegen auf einer Linie" }
                val tmp = a[col]; a[col] = a[pivot]; a[pivot] = tmp
                for (r in 0 until 8) if (r != col) {
                    val k = a[r][col] / a[col][col]
                    for (c in col..8) a[r][c] -= k * a[col][c]
                }
            }
            val sol = DoubleArray(9) { if (it < 8) a[it][8] / a[it][it] else 1.0 }
            return Homography(sol)
        }

        /**
         * Rectifies an ARGB photo into a bed image: output pixel (i, j) shows
         * machine point (i + .5, j + .5) / [pxPerMm]. [machineToPhoto] maps mm
         * to photo pixels. Pixels outside the photo stay transparent.
         */
        fun rectify(photo: IntArray, photoW: Int, photoH: Int, machineToPhoto: Homography,
                    pxPerMm: Double = 2.0, bedW: Double = Bed.WIDTH, bedH: Double = Bed.HEIGHT): Triple<IntArray, Int, Int> {
            val w = (bedW * pxPerMm).toInt(); val ht = (bedH * pxPerMm).toInt()
            require(photo.size == photoW * photoH) { "Ungültige Bilddaten" }
            val out = IntArray(w * ht)
            for (j in 0 until ht) for (i in 0 until w) {
                val p = machineToPhoto.map(Pt((i + 0.5) / pxPerMm, (j + 0.5) / pxPerMm))
                val x = p.x - 0.5; val y = p.y - 0.5
                if (x < 0 || y < 0 || x >= photoW - 1 || y >= photoH - 1) continue
                val x0 = floor(x).toInt(); val y0 = floor(y).toInt(); val fx = x - x0; val fy = y - y0
                out[j * w + i] = bilinear(photo[y0 * photoW + x0], photo[y0 * photoW + x0 + 1],
                    photo[(y0 + 1) * photoW + x0], photo[(y0 + 1) * photoW + x0 + 1], fx, fy)
            }
            return Triple(out, w, ht)
        }

        private fun bilinear(c00: Int, c10: Int, c01: Int, c11: Int, fx: Double, fy: Double): Int {
            var result = 0
            for (shift in intArrayOf(24, 16, 8, 0)) {
                fun ch(c: Int) = (c ushr shift) and 0xFF
                val top = ch(c00) + (ch(c10) - ch(c00)) * fx
                val bottom = ch(c01) + (ch(c11) - ch(c01)) * fx
                result = result or ((top + (bottom - top) * fy).toInt().coerceIn(0, 255) shl shift)
            }
            return result
        }
    }
}
