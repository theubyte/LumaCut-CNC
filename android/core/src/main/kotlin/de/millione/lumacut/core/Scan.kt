package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max

/**
 * Camera on the laser head, at the fixed scan height. [photo] are pixel
 * positions of four marks, [relMm] the same marks relative to the head
 * position (work mm) when the calibration photo was taken.
 */
@Serializable
data class CameraCalibration(
    val photoWidth: Int,
    val photoHeight: Int,
    val photo: List<Pt>,
    val relMm: List<Pt>,
    val scanZ: Double = 20.0,
) {
    init { require(photo.size == 4 && relMm.size == 4) { "Vier Kalibrierpunkte nötig" } }

    private val toRel by lazy { Homography.fit(photo, relMm) }
    private val toPhoto by lazy { Homography.fit(relMm, photo) }

    /** Work mm seen at photo pixel [p] with the head at [head] (work mm). */
    fun pixelToWork(p: Pt, head: Pt): Pt = toRel.map(p) + head

    fun workToPixel(w: Pt, head: Pt): Pt = toPhoto.map(w - head)

    /** Area the photo covers relative to the head (axis-aligned bounds of the 4 image corners). */
    fun footprint(): Box = boundsOf(listOf(listOf(
        Pt(0.0, 0.0), Pt(photoWidth.toDouble(), 0.0), Pt(photoWidth.toDouble(), photoHeight.toDouble()), Pt(0.0, photoHeight.toDouble()),
    ).map(toRel::map)))!!

    /** Largest axis-aligned box fully inside the photo, relative to the head (used for tiling). */
    fun usable(insetFraction: Double = 0.08): Box {
        val f = footprint()
        val dx = f.width * insetFraction; val dy = f.height * insetFraction
        return Box(f.minX + dx, f.minY + dy, f.maxX - dx, f.maxY - dy)
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
     * the whole work area with [overlap] (0..0.5). Head positions are kept
     * in the machine travel; strips the camera cannot reach are reported.
     */
    fun plan(cal: CameraCalibration, overlap: Double = 0.25): TilePlan {
        val u = cal.usable()
        val stepX = u.width * (1 - overlap.coerceIn(0.0, 0.5))
        val stepY = u.height * (1 - overlap.coerceIn(0.0, 0.5))
        require(stepX > 1 && stepY > 1) { "Kamera-Kalibrierung unplausibel (Bildausschnitt zu klein)" }
        val cols = max(1, ceil((Work.WIDTH - u.width) / stepX).toInt() + 1)
        val rows = max(1, ceil((Work.HEIGHT - u.height) / stepY).toInt() + 1)
        // Head travel in work mm (machine 0..390 / 0..370, X reversed) (laser off, may cross the safe zone like parking).
        val minHx = Work.fromMachine(Bed.WIDTH, 0.0).x; val maxHx = Work.fromMachine(0.0, 0.0).x   // machine X is reversed
        val minHy = Work.fromMachine(0.0, 0.0).y; val maxHy = Work.fromMachine(0.0, Bed.HEIGHT).y
        val heads = ArrayList<Pt>()
        val missing = mutableListOf<String>()
        for (r in 0 until rows) {
            val ty = if (rows == 1) 0.0 else (Work.HEIGHT - u.height) * r / (rows - 1)
            val order = if (r % 2 == 0) 0 until cols else (cols - 1 downTo 0)
            for (c in order) {
                val tx = if (cols == 1) 0.0 else (Work.WIDTH - u.width) * c / (cols - 1)
                // head so that the usable box's top-left lands at (tx, ty)
                val hx = (tx - u.minX).coerceIn(minHx, maxHx)
                val hy = (ty - u.minY).coerceIn(minHy, maxHy)
                heads += Pt(hx, hy)
            }
        }
        val cover = heads.map { Box(it.x + u.minX, it.y + u.minY, it.x + u.maxX, it.y + u.maxY) }
        if (cover.minOf { it.minX } > 0.5) missing += "linker Rand (%.0f mm)".format(cover.minOf { it.minX })
        if (cover.minOf { it.minY } > 0.5) missing += "oberer Rand (%.0f mm)".format(cover.minOf { it.minY })
        if (cover.maxOf { it.maxX } < Work.WIDTH - 0.5) missing += "rechter Rand (%.0f mm)".format(Work.WIDTH - cover.maxOf { it.maxX })
        if (cover.maxOf { it.maxY } < Work.HEIGHT - 0.5) missing += "unterer Rand (%.0f mm)".format(Work.HEIGHT - cover.maxOf { it.maxY })
        return TilePlan(heads, missing)
    }

    class Tile(val argb: IntArray, val width: Int, val height: Int, val head: Pt)

    /**
     * Mosaic of the work area at [pxPerMm]: each output pixel comes from the
     * tile whose usable centre is closest (least lens distortion), sampled
     * bilinearly. Uncovered pixels stay transparent. Row 0 = work Y 0.
     */
    fun mosaic(tiles: List<Tile>, cal: CameraCalibration, pxPerMm: Double = 2.0): Triple<IntArray, Int, Int> {
        val w = (Work.WIDTH * pxPerMm).toInt(); val h = (Work.HEIGHT * pxPerMm).toInt()
        val out = IntArray(w * h)
        val u = cal.usable(0.0)
        val centres = tiles.map { it.head + u.center }
        for (j in 0 until h) {
            val wy = (j + 0.5) / pxPerMm
            for (i in 0 until w) {
                val wx = (i + 0.5) / pxPerMm
                var best = -1; var bestD = Double.MAX_VALUE
                for (t in tiles.indices) {
                    val c = centres[t]
                    val d = (c.x - wx) * (c.x - wx) + (c.y - wy) * (c.y - wy)
                    if (d < bestD) { bestD = d; best = t }
                }
                if (best < 0) continue
                val tile = tiles[best]
                val p = cal.workToPixel(Pt(wx, wy), tile.head)
                val x = p.x - 0.5; val y = p.y - 0.5
                if (x < 0 || y < 0 || x >= tile.width - 1 || y >= tile.height - 1) continue
                val x0 = floor(x).toInt(); val y0 = floor(y).toInt()
                out[j * w + i] = sample(tile, x0, y0, x - x0, y - y0)
            }
        }
        return Triple(out, w, h)
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
