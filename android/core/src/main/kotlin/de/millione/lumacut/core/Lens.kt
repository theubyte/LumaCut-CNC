package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sqrt

/**
 * Wide-angle head camera: a plane-to-image homography plus radial lens
 * distortion, in the OpenCV convention (camera matrix fx = fy = [f],
 * principal point [cx]/[cy], dist_coeffs [k1, k2, 0, 0, 0]).
 *
 * [g] (3×3, row-major) maps millimetres relative to the head to undistorted
 * normalised image coordinates; the distortion then bends them outwards or
 * inwards with the distance from the image centre. [valid] is the pixel
 * area the calibration grid covered: outside it the model is extrapolated
 * and the scan does not use it.
 */
@Serializable
data class Lens(
    val cx: Double,
    val cy: Double,
    val f: Double,
    val k1: Double,
    val k2: Double,
    val g: List<Double>,
    val valid: Box,
    val rmsMm: Double = 0.0,
    val maxMm: Double = 0.0,
    val points: Int = 0,
) {
    init { require(g.size == 9) { "Linsenmodell ungültig" } }

    private val inv by lazy { Mat3.inverse(g.toDoubleArray()) }

    /** Image pixel that shows the point [rel] mm away from the head. */
    fun toPixel(rel: Pt): Pt {
        val u = Mat3.apply(g.toDoubleArray(), rel)
        val r2 = u.x * u.x + u.y * u.y
        val d = 1 + k1 * r2 + k2 * r2 * r2
        return Pt(cx + f * u.x * d, cy + f * u.y * d)
    }

    /** Millimetres relative to the head seen at pixel [p]. */
    fun toRel(p: Pt): Pt {
        val qx = (p.x - cx) / f; val qy = (p.y - cy) / f
        val rd = hypot(qx, qy)
        val s = if (rd < 1e-12) 1.0 else undistortRadius(rd) / rd
        return Mat3.apply(inv, Pt(qx * s, qy * s))
    }

    /** Undistorted radius whose distorted radius is [rd] (Newton, starting at rd). */
    internal fun undistortRadius(rd: Double): Double {
        var r = rd
        repeat(30) {
            val r2 = r * r
            val fr = r * (1 + k1 * r2 + k2 * r2 * r2) - rd
            val d = 1 + 3 * k1 * r2 + 5 * k2 * r2 * r2
            if (abs(d) < 1e-9) return r
            val next = r - fr / d
            if (abs(next - r) < 1e-13) return next
            r = next
        }
        return r
    }

    /** True when the distortion is one-to-one over the whole [valid] area (no fold-over at the edges). */
    fun monotonic(): Boolean {
        val corners = listOf(Pt(valid.minX, valid.minY), Pt(valid.maxX, valid.minY), Pt(valid.maxX, valid.maxY), Pt(valid.minX, valid.maxY))
        val rdMax = corners.maxOf { hypot((it.x - cx) / f, (it.y - cy) / f) }
        val ru = undistortRadius(rdMax)
        val r2 = ru * ru
        if (abs(ru * (1 + k1 * r2 + k2 * r2 * r2) - rdMax) > 1e-6) return false
        for (i in 0..60) {
            val r = ru * 1.05 * i / 60; val q = r * r
            if (1 + 3 * k1 * q + 5 * k2 * q * q < 0.15) return false
        }
        return true
    }

    /** OpenCV camera matrix and dist_coeffs (the Pi's camera_calibration.json fields). */
    fun openCv(): Pair<List<List<Double>>, List<Double>> =
        listOf(listOf(f, 0.0, cx), listOf(0.0, f, cy), listOf(0.0, 0.0, 1.0)) to listOf(k1, k2, 0.0, 0.0, 0.0)

    companion object {
        /**
         * Fits the model to pixel positions [px] of points at [rel] mm
         * (relative to the head) in a [w] × [h] photo: linear homography
         * first, then Levenberg–Marquardt with the two radial terms. Points
         * far off the first fit (misdetections) are dropped once.
         */
        fun fit(px: List<Pt>, rel: List<Pt>, w: Int, h: Int, valid: Box = Box(0.0, 0.0, w.toDouble(), h.toDouble())): Lens {
            require(px.size == rel.size) { "Punktlisten passen nicht zusammen" }
            require(px.size >= 20) { "Zu wenige Rasterpunkte erkannt (${px.size}, mindestens 20)" }
            val cx = w / 2.0; val cy = h / 2.0; val f = hypot(w.toDouble(), h.toDouble()) / 2
            var usePx = px; var useRel = rel
            var lens = solve(usePx, useRel, cx, cy, f, valid)
            val err = usePx.indices.map { lens.toPixel(useRel[it]).dist(usePx[it]) }
            val rms = sqrt(err.sumOf { it * it } / err.size)
            val keep = err.indices.filter { err[it] <= max(3 * rms, 1.5) }
            if (keep.size < err.size && keep.size >= 20) {
                usePx = keep.map { usePx[it] }; useRel = keep.map { useRel[it] }
                lens = solve(usePx, useRel, cx, cy, f, valid)
            }
            val mm = usePx.indices.map { lens.toRel(usePx[it]).dist(useRel[it]) }
            return lens.copy(rmsMm = sqrt(mm.sumOf { it * it } / mm.size), maxMm = mm.max(), points = usePx.size)
        }

        private fun solve(px: List<Pt>, rel: List<Pt>, cx: Double, cy: Double, f: Double, valid: Box): Lens {
            // condition the plane coordinates: centroid at 0, mean distance ~1
            val mx = rel.sumOf { it.x } / rel.size; val my = rel.sumOf { it.y } / rel.size
            val s = rel.sumOf { hypot(it.x - mx, it.y - my) } / rel.size
            require(s > 1e-6) { "Rasterpunkte liegen aufeinander" }
            val rn = rel.map { Pt((it.x - mx) / s, (it.y - my) / s) }
            val q = px.map { Pt((it.x - cx) / f, (it.y - cy) / f) }

            // linear start: homography rn -> q, g8 = 1
            val ata = Array(8) { DoubleArray(8) }; val atb = DoubleArray(8)
            for (i in rn.indices) {
                val (x, y) = rn[i]; val (u, v) = q[i]
                for ((row, rhs) in listOf(doubleArrayOf(x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y) to u,
                                          doubleArrayOf(0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y) to v)) {
                    for (a in 0 until 8) { atb[a] += row[a] * rhs; for (b in 0 until 8) ata[a][b] += row[a] * row[b] }
                }
            }
            val theta = Mat3.solve(ata, atb).copyOf(10)       // + k1, k2 = 0

            fun residuals(t: DoubleArray): DoubleArray {
                val out = DoubleArray(2 * rn.size)
                for (i in rn.indices) {
                    val (x, y) = rn[i]
                    val wq = t[6] * x + t[7] * y + 1
                    val ux = (t[0] * x + t[1] * y + t[2]) / wq; val uy = (t[3] * x + t[4] * y + t[5]) / wq
                    val r2 = ux * ux + uy * uy; val d = 1 + t[8] * r2 + t[9] * r2 * r2
                    out[2 * i] = (ux * d - q[i].x) * f; out[2 * i + 1] = (uy * d - q[i].y) * f   // pixels
                }
                return out
            }
            fun cost(r: DoubleArray) = r.sumOf { it * it }

            var r = residuals(theta); var c = cost(r); var lambda = 1e-3
            for (iter in 0 until 100) {
                val n = theta.size
                val jac = Array(n) { k ->
                    val step = 1e-7 * max(1.0, abs(theta[k]))
                    val tp = theta.copyOf().also { it[k] += step }; val tm = theta.copyOf().also { it[k] -= step }
                    val rp = residuals(tp); val rm = residuals(tm)
                    DoubleArray(r.size) { (rp[it] - rm[it]) / (2 * step) }
                }
                val jtj = Array(n) { a -> DoubleArray(n) { b -> var acc = 0.0; for (i in r.indices) acc += jac[a][i] * jac[b][i]; acc } }
                val jtr = DoubleArray(n) { a -> var acc = 0.0; for (i in r.indices) acc += jac[a][i] * r[i]; -acc }
                var improved = false; var converged = false
                while (lambda < 1e9) {
                    val m = Array(n) { a -> DoubleArray(n) { b -> jtj[a][b] + if (a == b) lambda * max(jtj[a][a], 1e-12) else 0.0 } }
                    val delta = runCatching { Mat3.solve(m, jtr) }.getOrNull()
                    if (delta != null) {
                        val cand = DoubleArray(n) { theta[it] + delta[it] }
                        val rc = residuals(cand); val cc = cost(rc)
                        if (cc < c) {
                            converged = c - cc < 1e-10 * max(c, 1e-9)
                            cand.copyInto(theta); r = rc; c = cc; lambda = max(lambda / 4, 1e-12); improved = true
                            break
                        }
                    }
                    lambda *= 8
                }
                if (!improved || converged) break
            }
            // back to plain mm: g = G' · T with T: rel -> rn
            val gp = doubleArrayOf(theta[0], theta[1], theta[2], theta[3], theta[4], theta[5], theta[6], theta[7], 1.0)
            val t = doubleArrayOf(1 / s, 0.0, -mx / s, 0.0, 1 / s, -my / s, 0.0, 0.0, 1.0)
            val g = Mat3.mul(gp, t)
            return Lens(cx, cy, f, theta[8], theta[9], g.map { it / g[8] }, valid)
        }
    }
}

/** Small 3×3 / n×n helpers for the lens fit. */
internal object Mat3 {
    fun apply(m: DoubleArray, p: Pt): Pt {
        val w = m[6] * p.x + m[7] * p.y + m[8]
        require(abs(w) > 1e-15) { "Punkt nicht abbildbar" }
        return Pt((m[0] * p.x + m[1] * p.y + m[2]) / w, (m[3] * p.x + m[4] * p.y + m[5]) / w)
    }

    fun mul(a: DoubleArray, b: DoubleArray) = DoubleArray(9) { i ->
        val r = i / 3; val c = i % 3
        a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c]
    }

    fun inverse(m: DoubleArray): DoubleArray {
        val a = m[0]; val b = m[1]; val c = m[2]; val d = m[3]; val e = m[4]; val f = m[5]; val g = m[6]; val h = m[7]; val i = m[8]
        val det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        require(abs(det) > 1e-18) { "Abbildung nicht umkehrbar" }
        return doubleArrayOf(
            (e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
            (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
            (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det,
        )
    }

    /** Solves a·x = b (Gaussian elimination with partial pivoting); [a] and [b] are not changed. */
    fun solve(a: Array<DoubleArray>, b: DoubleArray): DoubleArray {
        val n = b.size
        val m = Array(n) { r -> DoubleArray(n + 1) { c -> if (c < n) a[r][c] else b[r] } }
        for (col in 0 until n) {
            val p = (col until n).maxBy { abs(m[it][col]) }
            require(abs(m[p][col]) > 1e-14) { "Gleichungssystem singulär" }
            val tmp = m[col]; m[col] = m[p]; m[p] = tmp
            for (r in 0 until n) if (r != col) {
                val k = m[r][col] / m[col][col]
                if (k != 0.0) for (c in col..n) m[r][c] -= k * m[col][c]
            }
        }
        return DoubleArray(n) { m[it][n] / m[it][it] }
    }
}
