package de.millione.lumacut.core

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Binary picture of a motif on a grid of [pxPerMm] pixels per millimetre.
 * Pixel (0,0) covers the area starting at ([x0], [y0]) mm.
 */
class Mask(val w: Int, val h: Int, val data: BooleanArray, val pxPerMm: Double, val x0: Double = 0.0, val y0: Double = 0.0) {
    init { require(data.size == w * h) { "Ungültige Maske" } }
    operator fun get(x: Int, y: Int) = data[y * w + x]
    val count get() = data.count { it }

    companion object {
        /**
         * Motif mask of a picture: transparent pixels and everything that is connected to the
         * picture edge and close to the edge colour ([tolerance] 0..255 per channel) is background.
         * Holes inside the motif are not background. The result covers [widthMm] x [heightMm].
         */
        fun fromArgb(argb: IntArray, w: Int, h: Int, widthMm: Double, heightMm: Double,
                     pxPerMm: Double = Contour.DEFAULT_PX_PER_MM, tolerance: Int = 40): Mask {
            require(argb.size == w * h && w > 0 && h > 0) { "Ungültige Bilddaten" }
            val bg = background(argb, w, h, tolerance)
            // target grid, capped so the arrays stay small
            val p = min(pxPerMm, min(3000.0 / widthMm, 3000.0 / heightMm))
            val gw = max(1, ceil(widthMm * p).toInt()); val gh = max(1, ceil(heightMm * p).toInt())
            val out = BooleanArray(gw * gh)
            for (gy in 0 until gh) {
                val sy = min(h - 1, ((gy + 0.5) / gh * h).toInt())
                for (gx in 0 until gw) {
                    val sx = min(w - 1, ((gx + 0.5) / gw * w).toInt())
                    out[gy * gw + gx] = !bg[sy * w + sx]
                }
            }
            return Mask(gw, gh, out, gw / widthMm, 0.0, 0.0)
        }

        private fun background(argb: IntArray, w: Int, h: Int, tol: Int): BooleanArray {
            fun a(c: Int) = (c ushr 24) and 0xFF
            fun r(c: Int) = (c ushr 16) and 0xFF
            fun g(c: Int) = (c ushr 8) and 0xFF
            fun b(c: Int) = c and 0xFF
            // edge colour: most frequent (4 bit per channel) among the opaque border pixels
            val bins = HashMap<Int, IntArray>()   // bin -> [count, sumR, sumG, sumB]
            fun border(i: Int) {
                val c = argb[i]
                if (a(c) < 128) return
                val key = ((r(c) shr 4) shl 8) or ((g(c) shr 4) shl 4) or (b(c) shr 4)
                val e = bins.getOrPut(key) { IntArray(4) }
                e[0]++; e[1] += r(c); e[2] += g(c); e[3] += b(c)
            }
            for (x in 0 until w) { border(x); border((h - 1) * w + x) }
            for (y in 1 until h - 1) { border(y * w); border(y * w + w - 1) }
            val top = bins.values.maxByOrNull { it[0] }
            val rr = top?.let { it[1] / it[0] } ?: -1; val rg = top?.let { it[2] / it[0] } ?: -1; val rb = top?.let { it[3] / it[0] } ?: -1
            fun similar(c: Int): Boolean {
                if (a(c) < 128) return true
                if (top == null) return false
                return abs(r(c) - rr) <= tol && abs(g(c) - rg) <= tol && abs(b(c) - rb) <= tol
            }
            val bg = BooleanArray(w * h)
            val queue = IntArray(w * h); var head = 0; var tail = 0
            fun push(i: Int) { if (!bg[i] && similar(argb[i])) { bg[i] = true; queue[tail++] = i } }
            for (x in 0 until w) { push(x); push((h - 1) * w + x) }
            for (y in 0 until h) { push(y * w); push(y * w + w - 1) }
            while (head < tail) {
                val i = queue[head++]; val x = i % w; val y = i / w
                if (x > 0) push(i - 1); if (x < w - 1) push(i + 1)
                if (y > 0) push(i - w); if (y < h - 1) push(i + w)
            }
            return bg
        }
    }

    /** Every enclosed hole becomes part of the motif ("outer contour only"). */
    fun filled(): Mask {
        val outside = BooleanArray(w * h)
        val queue = IntArray(w * h); var head = 0; var tail = 0
        fun push(i: Int) { if (!outside[i] && !data[i]) { outside[i] = true; queue[tail++] = i } }
        for (x in 0 until w) { push(x); push((h - 1) * w + x) }
        for (y in 0 until h) { push(y * w); push(y * w + w - 1) }
        while (head < tail) {
            val i = queue[head++]; val x = i % w; val y = i / w
            if (x > 0) push(i - 1); if (x < w - 1) push(i + 1)
            if (y > 0) push(i - w); if (y < h - 1) push(i + w)
        }
        return Mask(w, h, BooleanArray(w * h) { !outside[it] }, pxPerMm, x0, y0)
    }

    /** Drops separate specks smaller than [minAreaMm2]. */
    fun withoutSpecks(minAreaMm2: Double): Mask {
        val minPx = (minAreaMm2 * pxPerMm * pxPerMm).toInt()
        if (minPx <= 1) return this
        val seen = BooleanArray(w * h); val keep = BooleanArray(w * h)
        val queue = IntArray(w * h)
        for (start in 0 until w * h) {
            if (!data[start] || seen[start]) continue
            var head = 0; var tail = 0
            queue[tail++] = start; seen[start] = true
            while (head < tail) {
                val i = queue[head++]; val x = i % w; val y = i / w
                fun go(j: Int) { if (data[j] && !seen[j]) { seen[j] = true; queue[tail++] = j } }
                if (x > 0) go(i - 1); if (x < w - 1) go(i + 1)
                if (y > 0) go(i - w); if (y < h - 1) go(i + w)
            }
            if (tail >= minPx) for (k in 0 until tail) keep[queue[k]] = true
        }
        return Mask(w, h, keep, pxPerMm, x0, y0)
    }
}

/**
 * Outlines of motifs: cut lines around a picture or around vectors, optionally offset (outwards
 * for a sticker, inwards for a margin). Works on a raster: signed distance field of the mask,
 * marching squares at the wanted distance, light smoothing, Douglas–Peucker. Output is polylines only.
 */
object Contour {
    const val DEFAULT_PX_PER_MM = 6.0
    const val SIMPLIFY_MM = 0.05

    /**
     * Closed outlines of [mask] moved by [offsetMm] (positive = outwards). Gaps up to about 2 * [closeGapMm]
     * between parts are closed first. With [outerOnly] holes are ignored.
     */
    fun fromMask(mask: Mask, offsetMm: Double, closeGapMm: Double = 0.0, outerOnly: Boolean = true,
                 minAreaMm2: Double = 1.0): List<Poly> {
        val base = if (outerOnly) mask.filled() else mask
        if (base.count == 0) return emptyList()
        val p = base.pxPerMm
        val gap = max(0.0, closeGapMm)
        val pad = ceil((max(offsetMm, 0.0) + gap) * p).toInt() + 4
        var field = sdf(base, pad)
        var pw = base.w + 2 * pad; var ph = base.h + 2 * pad
        var iso = offsetMm * p
        if (gap > 0) {
            // closing: grow by offset + gap, then shrink by gap; the second field is of the grown shape
            val grown = BooleanArray(pw * ph) { field[it] <= (offsetMm + gap) * p }
            var gm = Mask(pw, ph, grown, p)
            if (outerOnly) gm = gm.filled()
            field = sdf(gm, 4); pw += 8; ph += 8
            iso = -gap * p
            val loops = trace(field, pw, ph, iso.toFloat())
            return finish(loops, base, pad + 4, p, outerOnly, minAreaMm2)
        }
        return finish(trace(field, pw, ph, iso.toFloat()), base, pad, p, outerOnly, minAreaMm2)
    }

    /** Outlines of closed vector shapes, offset by [offsetMm] (even-odd fill, holes kept unless [outerOnly]). */
    fun fromPolys(polys: List<Poly>, offsetMm: Double, pxPerMm: Double = 8.0, outerOnly: Boolean = false): List<Poly> {
        val closed = polys.filter { it.size >= 3 }
        val box = boundsOf(closed) ?: return emptyList()
        val p = min(pxPerMm, 3000.0 / max(box.width, box.height).coerceAtLeast(1.0))
        val m = 2.0
        val x0 = box.minX - m; val y0 = box.minY - m
        val w = ceil((box.width + 2 * m) * p).toInt() + 1; val h = ceil((box.height + 2 * m) * p).toInt() + 1
        val rows = Array(h) { ArrayList<Double>() }
        for (poly in closed) {
            val pts = if (poly.isClosed()) poly else poly + poly.first()
            for ((a, b) in pts.zipWithNext()) {
                if (a.y == b.y) continue
                val ja = ceil((min(a.y, b.y) - y0) * p - 0.5).toInt().coerceAtLeast(0)
                val jb = floor((max(a.y, b.y) - y0) * p - 0.5).toInt().coerceAtMost(h - 1)
                for (j in ja..jb) {
                    val y = y0 + (j + 0.5) / p
                    if ((a.y <= y && b.y > y) || (b.y <= y && a.y > y)) rows[j].add(a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y))
                }
            }
        }
        val data = BooleanArray(w * h)
        for (j in 0 until h) {
            val xs = rows[j]; xs.sort()
            var k = 0
            while (k + 1 < xs.size) {
                val i0 = ceil((xs[k] - x0) * p - 0.5).toInt().coerceAtLeast(0)
                val i1 = floor((xs[k + 1] - x0) * p - 0.5).toInt().coerceAtMost(w - 1)
                for (i in i0..i1) data[j * w + i] = true
                k += 2
            }
        }
        return fromMask(Mask(w, h, data, p, x0, y0), offsetMm, 0.0, outerOnly, 0.0)
    }

    /** Sticker: the outline [offsetMm] outside the motif with rounded corners and small gaps between parts closed. */
    fun sticker(mask: Mask, offsetMm: Double, join: Boolean = false): List<Poly> =
        fromMask(mask.withoutSpecks(0.5), offsetMm, if (join) 8.0 else 2.0, true)

    /** Hugs the edge ([insetMm] pulls the line inwards, e.g. 0.2). */
    fun edge(mask: Mask, insetMm: Double = 0.0): List<Poly> =
        fromMask(mask.withoutSpecks(0.5), -max(0.0, insetMm), 0.0, true)

    /** Signed distance in pixels, negative inside the mask; [pad] background pixels around. */
    private fun sdf(m: Mask, pad: Int): FloatArray {
        val w = m.w + 2 * pad; val h = m.h + 2 * pad
        val fg = BooleanArray(w * h)
        for (y in 0 until m.h) for (x in 0 until m.w) fg[(y + pad) * w + x + pad] = m.data[y * m.w + x]
        val toFg = edt(fg, w, h)
        val toBg = edt(BooleanArray(w * h) { !fg[it] }, w, h)
        return FloatArray(w * h) { if (fg[it]) -toBg[it] else toFg[it] }
    }

    /** Euclidean distance to the nearest true pixel (Felzenszwalb–Huttenlocher). */
    private fun edt(feature: BooleanArray, w: Int, h: Int): FloatArray {
        val inf = 1e10
        val sq = DoubleArray(w * h) { if (feature[it]) 0.0 else inf }
        val n = max(w, h)
        val f = DoubleArray(n); val d = DoubleArray(n); val v = IntArray(n); val z = DoubleArray(n + 1)
        val far = 1e20
        fun line(len: Int) {
            var k = 0; v[0] = 0; z[0] = -far; z[1] = far
            for (q in 1 until len) {
                var s = ((f[q] + q.toDouble() * q) - (f[v[k]] + v[k].toDouble() * v[k])) / (2.0 * q - 2.0 * v[k])
                while (s <= z[k]) {
                    k--
                    s = ((f[q] + q.toDouble() * q) - (f[v[k]] + v[k].toDouble() * v[k])) / (2.0 * q - 2.0 * v[k])
                }
                k++; v[k] = q; z[k] = s; z[k + 1] = far
            }
            k = 0
            for (q in 0 until len) {
                while (z[k + 1] < q) k++
                d[q] = (q - v[k]).toDouble() * (q - v[k]) + f[v[k]]
            }
        }
        for (x in 0 until w) {
            for (y in 0 until h) f[y] = sq[y * w + x]
            line(h)
            for (y in 0 until h) sq[y * w + x] = d[y]
        }
        for (y in 0 until h) {
            for (x in 0 until w) f[x] = sq[y * w + x]
            line(w)
            for (x in 0 until w) sq[y * w + x] = d[x]
        }
        return FloatArray(w * h) { sqrt(min(sq[it], inf)).toFloat() }
    }

    private class Seg(val k0: Long, val k1: Long, val x0: Double, val y0: Double, val x1: Double, val y1: Double)

    /** Marching squares: closed loops (grid coordinates) where the field crosses [iso]; inside = below. */
    private fun trace(f: FloatArray, w: Int, h: Int, iso: Float): List<List<Pt>> {
        val segs = ArrayList<Seg>()
        fun hk(x: Int, y: Int) = (y.toLong() * w + x) * 2
        fun vk(x: Int, y: Int) = (y.toLong() * w + x) * 2 + 1
        for (j in 0 until h - 1) for (i in 0 until w - 1) {
            val a = f[j * w + i]; val b = f[j * w + i + 1]; val c = f[(j + 1) * w + i + 1]; val d = f[(j + 1) * w + i]
            val ia = a < iso; val ib = b < iso; val ic = c < iso; val id = d < iso
            val code = (if (ia) 1 else 0) or (if (ib) 2 else 0) or (if (ic) 4 else 0) or (if (id) 8 else 0)
            if (code == 0 || code == 15) continue
            // crossing points: T, R, B, L
            fun t(p: Float, q: Float) = ((iso - p) / (q - p)).toDouble()
            fun point(e: Char): Triple<Long, Double, Double> = when (e) {
                'T' -> Triple(hk(i, j), i + t(a, b), j.toDouble())
                'B' -> Triple(hk(i, j + 1), i + t(d, c), (j + 1).toDouble())
                'L' -> Triple(vk(i, j), i.toDouble(), j + t(a, d))
                else -> Triple(vk(i + 1, j), (i + 1).toDouble(), j + t(b, c))
            }
            fun seg(from: Char, to: Char) {
                val s = point(from); val e = point(to)
                segs += Seg(s.first, e.first, s.second, s.third, e.second, e.third)
            }
            val centreInside = (a + b + c + d) / 4 < iso
            when (code) {
                1 -> seg('T', 'L'); 2 -> seg('R', 'T'); 4 -> seg('B', 'R'); 8 -> seg('L', 'B')
                3 -> seg('R', 'L'); 6 -> seg('B', 'T'); 12 -> seg('L', 'R'); 9 -> seg('T', 'B')
                7 -> seg('B', 'L'); 11 -> seg('R', 'B'); 13 -> seg('T', 'R'); 14 -> seg('L', 'T')
                5 -> if (centreInside) { seg('T', 'R'); seg('B', 'L') } else { seg('T', 'L'); seg('B', 'R') }
                10 -> if (centreInside) { seg('L', 'T'); seg('R', 'B') } else { seg('R', 'T'); seg('L', 'B') }
            }
        }
        val byStart = HashMap<Long, Int>(segs.size * 2)
        for ((i, s) in segs.withIndex()) byStart[s.k0] = i
        val used = BooleanArray(segs.size)
        val loops = ArrayList<List<Pt>>()
        for (first in segs.indices) {
            if (used[first]) continue
            val pts = ArrayList<Pt>()
            var cur = first
            while (!used[cur]) {
                used[cur] = true
                pts += Pt(segs[cur].x0, segs[cur].y0)
                cur = byStart[segs[cur].k1] ?: break
            }
            if (pts.size >= 3) { pts += pts.first(); loops += pts }
        }
        return loops
    }

    private fun area(poly: Poly): Double {
        var s = 0.0
        for ((a, b) in poly.zipWithNext()) s += a.x * b.y - b.x * a.y
        return s / 2
    }

    private fun finish(loops: List<List<Pt>>, base: Mask, padPx: Int, p: Double, outerOnly: Boolean, minAreaMm2: Double): List<Poly> {
        fun toMm(g: Pt) = Pt(base.x0 + (g.x - padPx + 0.5) / p, base.y0 + (g.y - padPx + 0.5) / p)
        val out = ArrayList<Poly>()
        for (loop in loops) {
            var pts = loop.dropLast(1)
            repeat(1) {   // one light smoothing pass takes the pixel stairs out
                val n = pts.size
                pts = List(n) { i -> val a = pts[(i + n - 1) % n]; val b = pts[i]; val c = pts[(i + 1) % n]; Pt(0.25 * a.x + 0.5 * b.x + 0.25 * c.x, 0.25 * a.y + 0.5 * b.y + 0.25 * c.y) }
            }
            val mm = (pts + pts.first()).map(::toMm)
            val s = simplify(mm, SIMPLIFY_MM)
            if (s.size >= 4 && abs(area(s)) >= minAreaMm2) out += if (s.first().dist(s.last()) < 1e-9) s else s + s.first()
        }
        if (!outerOnly || out.isEmpty()) return out
        val sign = area(out.maxByOrNull { abs(area(it)) }!!) > 0
        return out.filter { (area(it) > 0) == sign }
    }
}
