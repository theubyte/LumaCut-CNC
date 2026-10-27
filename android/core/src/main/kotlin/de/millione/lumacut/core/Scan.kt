package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/**
 * Camera on the laser head, at the fixed scan height. Either [lens] (dot
 * grid calibration: lens distortion and position in one model) or the
 * older four marks: [photo] are their pixel positions, [relMm] the same
 * marks relative to the head position (work mm) when the photo was taken.
 */
@Serializable
data class CameraCalibration(
    val photoWidth: Int,
    val photoHeight: Int,
    val photo: List<Pt> = emptyList(),
    val relMm: List<Pt> = emptyList(),
    val scanZ: Double = 20.0,
    val lens: Lens? = null,
    /** Camera height above the material surface at which the picture is sharp (automatic calibration). */
    val aboveSurface: Double? = null,
    /** Brightness fall-off towards the picture edges (light calibration), null = not measured. */
    val shading: Shading? = null,
    /** Height from the work laser's glimmer spot (3D), null = not calibrated. */
    val spot: LightModel? = null,
    /** Height from the red measuring line laser (3D), null = not calibrated. */
    val line: LightModel? = null,
) {
    init { require(lens != null || (photo.size == 4 && relMm.size == 4)) { "Vier Kalibrierpunkte nötig" } }

    private val toRel by lazy { Homography.fit(photo, relMm) }
    private val toPhoto by lazy { Homography.fit(relMm, photo) }

    /** Pixel area the model is valid for (the whole photo for four marks). */
    val validPx: Box get() = lens?.valid ?: Box(0.0, 0.0, photoWidth.toDouble(), photoHeight.toDouble())

    /** Work mm seen at photo pixel [p] with the head at [head] (work mm). */
    fun pixelToWork(p: Pt, head: Pt): Pt = (lens?.toRel(p) ?: toRel.map(p)) + head

    fun workToPixel(w: Pt, head: Pt): Pt = lens?.toPixel(w - head) ?: toPhoto.map(w - head)

    /** Outline of [validPx] relative to the head (a wide-angle lens bends the straight image edges). */
    private val outline: List<Pt> by lazy {
        val v = validPx; val n = if (lens == null) 1 else 24
        val corners = listOf(Pt(v.minX, v.minY), Pt(v.maxX, v.minY), Pt(v.maxX, v.maxY), Pt(v.minX, v.maxY))
        (0 until 4).flatMap { e -> val a = corners[e]; val b = corners[(e + 1) % 4]; (0 until n).map { k -> a + (b - a) * (k.toDouble() / n) } }
            .map { pixelToWork(it, Pt(0.0, 0.0)) }
    }

    /** Area the photo covers relative to the head (axis-aligned bounds). */
    fun footprint(): Box = boundsOf(listOf(outline))!!

    /** Largest axis-aligned box fully inside the photo, relative to the head (used for tiling). */
    fun usable(insetFraction: Double = 0.08): Box {
        val f = if (lens == null) footprint() else inscribed()
        val dx = f.width * insetFraction; val dy = f.height * insetFraction
        return Box(f.minX + dx, f.minY + dy, f.maxX - dx, f.maxY - dy)
    }

    /** Box around the image centre, shrunk until its corners lie inside the bent outline. */
    private fun inscribed(): Box {
        val f = footprint(); val c = pixelToWork(validPx.center, Pt(0.0, 0.0))
        val hx = f.width / 2; val hy = f.height / 2
        var t = 1.0
        while (t > 0.05) {
            val box = Box(c.x - hx * t, c.y - hy * t, c.x + hx * t, c.y + hy * t)
            if (listOf(Pt(box.minX, box.minY), Pt(box.maxX, box.minY), Pt(box.maxX, box.maxY), Pt(box.minX, box.maxY)).all { pointInOutline(it, outline) }) return box
            t *= 0.98
        }
        return Box(c.x - 1, c.y - 1, c.x + 1, c.y + 1)
    }

    companion object {
        /** From a calibration photo of a rectangle with known work corners, taken with the head at [head]. */
        fun fromRectangle(photoW: Int, photoH: Int, cornersPx: List<Pt>, cornersWork: List<Pt>, head: Pt, scanZ: Double) =
            CameraCalibration(photoW, photoH, cornersPx, cornersWork.map { it - head }, scanZ)
    }
}

class TilePlan(val heads: List<Pt>, val uncovered: List<String>)

object Scan {
    /**
     * Serpentine head positions (work mm) so the usable camera area covers
     * [area] (default: the whole work area, clipped to it) with [overlap]
     * (0..0.5). An area smaller than one picture gets one picture centred
     * on it. Head positions are kept in the machine travel; strips of the
     * area the camera cannot reach are reported.
     */
    fun plan(cal: CameraCalibration, area: Box = Box(0.0, 0.0, Work.WIDTH, Work.HEIGHT), overlap: Double = 0.25): TilePlan {
        val a = Box(area.minX.coerceIn(0.0, Work.WIDTH), area.minY.coerceIn(0.0, Work.HEIGHT), area.maxX.coerceIn(0.0, Work.WIDTH), area.maxY.coerceIn(0.0, Work.HEIGHT))
        require(a.width > 0.5 && a.height > 0.5) { "Scanbereich liegt nicht im Arbeitsbereich" }
        val u = cal.usable()
        val stepX = u.width * (1 - overlap.coerceIn(0.0, 0.5))
        val stepY = u.height * (1 - overlap.coerceIn(0.0, 0.5))
        require(stepX > 1 && stepY > 1) { "Kamera-Kalibrierung unplausibel (Bildausschnitt zu klein)" }
        val cols = max(1, ceil((a.width - u.width) / stepX).toInt() + 1)
        val rows = max(1, ceil((a.height - u.height) / stepY).toInt() + 1)
        // Head travel in work mm (machine 0..390 / 0..370, X reversed) (laser off, may cross the safe zone like parking).
        val minHx = Work.fromMachine(Bed.WIDTH, 0.0).x; val maxHx = Work.fromMachine(0.0, 0.0).x   // machine X is reversed
        val minHy = Work.fromMachine(0.0, 0.0).y; val maxHy = Work.fromMachine(0.0, Bed.HEIGHT).y
        val heads = ArrayList<Pt>()
        val missing = mutableListOf<String>()
        for (r in 0 until rows) {
            val ty = if (rows == 1) a.center.y - u.height / 2 else a.minY + (a.height - u.height) * r / (rows - 1)
            val order = if (r % 2 == 0) 0 until cols else (cols - 1 downTo 0)
            for (c in order) {
                val tx = if (cols == 1) a.center.x - u.width / 2 else a.minX + (a.width - u.width) * c / (cols - 1)
                // head so that the usable box's top-left lands at (tx, ty)
                val hx = (tx - u.minX).coerceIn(minHx, maxHx)
                val hy = (ty - u.minY).coerceIn(minHy, maxHy)
                heads += Pt(hx, hy)
            }
        }
        val cover = heads.map { Box(it.x + u.minX, it.y + u.minY, it.x + u.maxX, it.y + u.maxY) }
        if (cover.minOf { it.minX } > a.minX + 0.5) missing += "linker Rand (%.0f mm)".format(cover.minOf { it.minX } - a.minX)
        if (cover.minOf { it.minY } > a.minY + 0.5) missing += "oberer Rand (%.0f mm)".format(cover.minOf { it.minY } - a.minY)
        if (cover.maxOf { it.maxX } < a.maxX - 0.5) missing += "rechter Rand (%.0f mm)".format(a.maxX - cover.maxOf { it.maxX })
        if (cover.maxOf { it.maxY } < a.maxY - 0.5) missing += "unterer Rand (%.0f mm)".format(a.maxY - cover.maxOf { it.maxY })
        return TilePlan(heads, missing)
    }

    /** One plan over several separate [areas] (marked workpieces): their pictures one after another. */
    fun plan(cal: CameraCalibration, areas: List<Box>, overlap: Double = 0.25): TilePlan {
        require(areas.isNotEmpty()) { "Kein Scanbereich" }
        val plans = areas.map { plan(cal, it, overlap) }
        return TilePlan(plans.flatMap { it.heads }.distinct(), plans.flatMap { it.uncovered }.distinct())
    }

    class Tile(val argb: IntArray, val width: Int, val height: Int, val head: Pt)

    /**
     * Mosaic of the work area at [pxPerMm], built tile by tile so only one
     * photo is in memory at a time. Every tile is first corrected for the
     * vignetting ([CameraCalibration.shading]), then brought to the
     * brightness and colour the mosaic already shows where they overlap
     * (the camera adjusts its brightness for every picture), and blended in
     * with a weight that falls to 0 at its edges, so no seam stays visible.
     * Sampled bilinearly; uncovered pixels stay transparent (or keep the
     * earlier scan given as base). Row 0 = work Y 0.
     */
    class Mosaic(private val cal: CameraCalibration, private val pxPerMm: Double, base: IntArray? = null) {
        val width = (Work.WIDTH * pxPerMm).toInt()
        val height = (Work.HEIGHT * pxPerMm).toInt()
        /** Starts from [base] (an earlier scan of the same size): only the newly photographed parts change. */
        val pixels = base?.takeIf { it.size == width * height }?.copyOf() ?: IntArray(width * height)
        private val weight = FloatArray(width * height)
        private val reach = cal.footprint()
        private val valid = cal.validPx

        /** Gain per channel (R, G, B) the last tile was multiplied with to match the mosaic. */
        var lastGain = doubleArrayOf(1.0, 1.0, 1.0); private set

        fun add(tile: Tile) {
            val i0 = max(0, floor((tile.head.x + reach.minX) * pxPerMm).toInt()); val i1 = min(width - 1, ceil((tile.head.x + reach.maxX) * pxPerMm).toInt())
            val j0 = max(0, floor((tile.head.y + reach.minY) * pxPerMm).toInt()); val j1 = min(height - 1, ceil((tile.head.y + reach.maxY) * pxPerMm).toInt())
            val minX = max(0.0, valid.minX); val minY = max(0.0, valid.minY)
            val maxX = min(tile.width - 1.0, valid.maxX - 1); val maxY = min(tile.height - 1.0, valid.maxY - 1)
            val halfW = (maxX - minX) / 2; val halfH = (maxY - minY) / 2
            if (halfW <= 0 || halfH <= 0 || i1 < i0 || j1 < j0) return
            // 1. project: mosaic pixel, corrected colour and edge weight for every pixel the tile shows
            val cap = (i1 - i0 + 1) * (j1 - j0 + 1)
            val idx = IntArray(cap); val col = IntArray(cap); val wt = FloatArray(cap)
            var n = 0
            for (j in j0..j1) {
                val wy = (j + 0.5) / pxPerMm
                for (i in i0..i1) {
                    val p = cal.workToPixel(Pt((i + 0.5) / pxPerMm, wy), tile.head)
                    val x = p.x - 0.5; val y = p.y - 0.5
                    if (x < minX || y < minY || x >= maxX || y >= maxY) continue
                    val x0 = floor(x).toInt(); val y0 = floor(y).toInt()
                    var c = sample(tile, x0, y0, x - x0, y - y0)
                    cal.shading?.let { c = it.correct(c, p.x / tile.width, p.y / tile.height) }
                    val e = min(min(x - minX, maxX - x) / halfW, min(y - minY, maxY - y) / halfH).coerceIn(0.0, 1.0)
                    idx[n] = j * width + i; col[n] = c; wt[n] = (e * e + 1e-4).toFloat()
                    n++
                }
            }
            // 2. gain per channel from the overlap with what is already there (clipped and dark pixels left out)
            val sumTile = DoubleArray(3); val sumMosaic = DoubleArray(3); var shared = 0
            for (q in 0 until n) {
                val k = idx[q]
                if (weight[k] < 0.05f || wt[q] < 0.05f) continue
                val a = col[q]; val b = pixels[k]
                if (CameraLight.luminance(a) !in 15..240 || CameraLight.luminance(b) !in 15..240) continue
                for (ch in 0..2) { val sh = 16 - 8 * ch; sumTile[ch] += (a shr sh) and 255; sumMosaic[ch] += (b shr sh) and 255 }
                shared++
            }
            val gain = DoubleArray(3) { ch -> if (shared < 200 || sumTile[ch] <= 0) 1.0 else (sumMosaic[ch] / sumTile[ch]).coerceIn(0.7, 1.4) }
            lastGain = gain
            // 3. blend: running weighted mean, so a pixel ends up as the weighted mean of all tiles showing it
            for (q in 0 until n) {
                val k = idx[q]; val w = wt[q]; val total = weight[k] + w
                val f = w / total
                val a = col[q]; val old = pixels[k]
                var out = 0xFF000000.toInt()
                for (ch in 0..2) {
                    val sh = 16 - 8 * ch
                    val v = ((a shr sh) and 255) * gain[ch]
                    val blended = if (weight[k] == 0f) v else ((old shr sh) and 255) + (v - ((old shr sh) and 255)) * f
                    out = out or ((blended + 0.5).toInt().coerceIn(0, 255) shl sh)
                }
                pixels[k] = out
                weight[k] = total
            }
        }
    }

    fun mosaic(tiles: List<Tile>, cal: CameraCalibration, pxPerMm: Double = 2.0): Triple<IntArray, Int, Int> {
        val m = Mosaic(cal, pxPerMm)
        tiles.forEach(m::add)
        return Triple(m.pixels, m.width, m.height)
    }

    private fun sample(t: Tile, x0: Int, y0: Int, fx: Double, fy: Double): Int {
        val c00 = t.argb[y0 * t.width + x0]; val c10 = t.argb[y0 * t.width + x0 + 1]
        val c01 = t.argb[(y0 + 1) * t.width + x0]; val c11 = t.argb[(y0 + 1) * t.width + x0 + 1]
        var r = 0
        for (shift in intArrayOf(24, 16, 8, 0)) {
            fun ch(c: Int) = (c ushr shift) and 0xFF
            val top = ch(c00) + (ch(c10) - ch(c00)) * fx
            val bottom = ch(c01) + (ch(c11) - ch(c01)) * fx
            r = r or ((top + (bottom - top) * fy).toInt().coerceIn(0, 255) shl shift)
        }
        return r
    }

    /**
     * True when the switch can probe work point [p] directly: the Pi moves
     * the head by the switch offset ([probeOffset] = tip minus laser point)
     * and keeps it in X10..380 / Y10..360 (Marlin PROBING_MARGIN; the laser
     * is off, so the head may enter the safezone). Points in the edge strip
     * the switch never reaches are probed by the Pi up to 40 mm beside them.
     */
    fun reachable(p: Pt, probeOffset: Pt): Boolean {
        val head = Work.toMachine(p) - probeOffset
        return head.x in PROBE_HEAD_MIN..PROBE_HEAD_MAX_X && head.y in PROBE_HEAD_MIN..PROBE_HEAD_MAX_Y
    }

    private const val PROBE_HEAD_MIN = 10.0
    private const val PROBE_HEAD_MAX_X = 380.0
    private const val PROBE_HEAD_MAX_Y = 360.0
}

/** Point-in-polygon (even-odd) for a closed outline given without repeating the first point. */
internal fun pointInOutline(p: Pt, poly: List<Pt>): Boolean {
    var c = false
    var j = poly.size - 1
    for (i in poly.indices) {
        val a = poly[i]; val b = poly[j]
        if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) c = !c
        j = i
    }
    return c
}
