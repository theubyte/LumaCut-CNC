package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Height without touching (3D): a light on the head – the work laser at a
 * glimmer of power or a red measuring line laser – falls on the surface,
 * the camera beside it sees it from the side. Camera and light move
 * together, so where the light shows in the picture depends only on the
 * distance between head and surface. The model holds that once measured
 * over a flat plate ([d]: distances; per [keys] entry the picture positions
 * [u]/[v] at those distances; a spot has one key, a line one per sampled
 * column). Measuring goes backwards: picture position → distance.
 */
@Serializable
data class LightModel(val kind: String, val keys: List<Int>, val d: List<Double>, val u: List<List<Double>>, val v: List<List<Double>>,
                      val power: Int = 0) {
    init { require(d.size >= 2 && keys.size == u.size && keys.size == v.size && u.all { it.size == d.size } && v.all { it.size == d.size }) { "Ungültiges Lichtmodell" } }

    /** Picture position of key [k] at distance [dist] (linear between the measured distances, extended at the ends). */
    fun predict(k: Int, dist: Double): Pt {
        val i = (1 until d.size).firstOrNull { dist <= d[it] } ?: (d.size - 1)
        val t = (dist - d[i - 1]) / (d[i] - d[i - 1])
        return Pt(u[k][i - 1] + (u[k][i] - u[k][i - 1]) * t, v[k][i - 1] + (v[k][i] - v[k][i - 1]) * t)
    }

    /** Distance for picture position [p] of key [k] and how far [p] lies beside the calibrated track (px); null when too far. */
    fun distance(k: Int, p: Pt, maxOffPx: Double = 6.0): Pair<Double, Double>? {
        val span = d.last() - d.first()
        var best: Pair<Double, Double>? = null
        var x = d.first() - span * 0.3
        while (x <= d.last() + span * 0.3) {
            val off = predict(k, x).dist(p)
            if (best == null || off < best.second) best = x to off
            x += 0.02
        }
        return best?.takeIf { it.second <= maxOffPx }
    }

    /** Index of the key nearest to picture column [col] (line models). */
    fun keyFor(col: Int): Int = keys.indices.minBy { abs(keys[it] - col) }

    companion object {
        /** From (distance, picture position) pairs per key; several pictures per distance are averaged. */
        fun fit(kind: String, keys: List<Int>, samples: List<Pair<Double, List<Pt?>>>, power: Int = 0): LightModel {
            val ds = samples.map { it.first }.distinct().sorted()
            require(ds.size >= 2) { "Mindestens zwei Höhen nötig" }
            val us = keys.indices.map { MutableList(ds.size) { Double.NaN } }
            val vs = keys.indices.map { MutableList(ds.size) { Double.NaN } }
            for ((j, dist) in ds.withIndex()) for (k in keys.indices) {
                val seen = samples.filter { it.first == dist }.mapNotNull { it.second.getOrNull(k) }
                if (seen.isNotEmpty()) { us[k][j] = seen.map { it.x }.average(); vs[k][j] = seen.map { it.y }.average() }
            }
            // keys seen at every distance only
            val good = keys.indices.filter { k -> us[k].none { it.isNaN() } }
            require(good.isNotEmpty()) { "Licht in den Kalibrierbildern nicht gefunden" }
            return LightModel(kind, good.map { keys[it] }, ds, good.map { us[it] }, good.map { vs[it] }, power)
        }
    }
}

/** Finding the light in a picture. */
object LightFinder {
    class Spot(val px: Pt, val strength: Double, val pixels: Int)

    /**
     * The work laser's blue spot: pixels much bluer than red and green or
     * blown out to white; the strongest compact blob (3 … 3000 px), searched
     * within [radius] px of [near] when given. Null when there is none.
     */
    fun spot(argb: IntArray, w: Int, h: Int, near: Pt? = null, radius: Double = 250.0): Spot? {
        require(argb.size == w * h) { "Ungültige Bilddaten" }
        val x0 = near?.let { max(0, (it.x - radius).toInt()) } ?: 0; val x1 = near?.let { min(w - 1, (it.x + radius).toInt()) } ?: (w - 1)
        val y0 = near?.let { max(0, (it.y - radius).toInt()) } ?: 0; val y1 = near?.let { min(h - 1, (it.y + radius).toInt()) } ?: (h - 1)
        val bw = x1 - x0 + 1; val bh = y1 - y0 + 1
        if (bw <= 0 || bh <= 0) return null
        val score = FloatArray(bw * bh)
        for (y in y0..y1) for (x in x0..x1) {
            val c = argb[y * w + x]
            val r = (c shr 16) and 255; val g = (c shr 8) and 255; val b = c and 255
            val lum = (r * 299 + g * 587 + b * 114) / 1000
            score[(y - y0) * bw + (x - x0)] = (b - (r + g) / 2f - 25f).coerceAtLeast(0f) + ((lum - 235) * 3f).coerceAtLeast(0f)
        }
        val peak = score.max()
        if (peak < 45f) return null
        val thr = max(30f, peak * 0.35f)
        val seen = BooleanArray(score.size)
        var best: Spot? = null; var bestSum = 0.0
        val stack = IntArray(score.size)
        for (start in score.indices) {
            if (seen[start] || score[start] < thr) continue
            var n = 0; var top = 0; stack[top++] = start; seen[start] = true
            var sw = 0.0; var sx = 0.0; var sy = 0.0; var mx = 0f
            while (top > 0) {
                val i = stack[--top]; n++
                val s = score[i]; sw += s; sx += s * (i % bw); sy += s * (i / bw); mx = max(mx, s)
                val ix = i % bw; val iy = i / bw
                for ((dx, dy) in arrayOf(1 to 0, -1 to 0, 0 to 1, 0 to -1)) {
                    val nx = ix + dx; val ny = iy + dy
                    if (nx < 0 || ny < 0 || nx >= bw || ny >= bh) continue
                    val j = ny * bw + nx
                    if (!seen[j] && score[j] >= thr) { seen[j] = true; stack[top++] = j }
                }
            }
            if (n !in 3..3000) continue
            if (sw > bestSum) { bestSum = sw; best = Spot(Pt(x0 + sx / sw + 0.5, y0 + sy / sw + 0.5), mx.toDouble(), n) }
        }
        return best
    }

    /**
     * The red measuring line: per sampled column [cols], the row where the
     * picture with the line on is much redder than the one with it off,
     * centred on the brightest part. Null for columns without the line.
     */
    fun line(on: IntArray, off: IntArray, w: Int, h: Int, cols: List<Int>): List<Pt?> {
        require(on.size == w * h && off.size == w * h) { "Ungültige Bilddaten" }
        return cols.map { col ->
            if (col !in 0 until w) return@map null
            val diff = DoubleArray(h) { y -> (((on[y * w + col] shr 16) and 255) - ((off[y * w + col] shr 16) and 255)).toDouble() }
            val peak = diff.indices.maxBy { diff[it] }
            if (diff[peak] < 25) return@map null
            var sw = 0.0; var sy = 0.0
            for (y in max(0, peak - 4)..min(h - 1, peak + 4)) { val v = diff[y] - diff[peak] / 2; if (v > 0) { sw += v; sy += v * y } }
            Pt(col + 0.5, sy / sw + 0.5)
        }
    }
}

/**
 * Measuring with the work laser at a glimmer of power. The Pi fires only
 * while moving, so every measurement is a short slow line; a capture line
 * in the job makes the Pi take the picture while it runs (Pi
 * "; LUMACUT-CAPTURE"). Jobs set their own absolute Z: the Pi then does
 * not lower to the focus height on its own, which over a taller object
 * could touch it.
 */
object SpotMeasure {
    const val FEED = 120.0
    const val LENGTH = 12.0
    /** Glimmer powers tried by the power test: S 1 … 13 of 255 (0.4 … 5 %). */
    val TEST_POWERS = (1..13).toList()
    /** Head distances above the plate for the calibration, mm. */
    val CAL_DISTANCES = listOf(8.0, 11.0, 14.0, 17.0, 20.0, 23.0)
    /** Head distance above the probed surface while measuring: everything up to 12 mm higher stays in range. */
    const val MEASURE_DISTANCE = 20.0

    private fun xy(p: Pt) = Work.toMachine(p).let { "X%.3f Y%.3f".format(Locale.ROOT, it.x, it.y) }

    private fun header(title: String) = StringBuilder().apply {
        append("; LumaCut $title\n"); append("G21\nG90\nM5 I\nM3 I\n")
    }

    private fun StringBuilder.measureLine(start: Pt, s: Int, id: String, w: Int, h: Int, delayMs: Int = 1500) {
        append("G0 ${xy(start)}\n"); append("M400\n")
        append("G1 ${xy(start + Pt(LENGTH, 0.0))} F${FEED.roundToInt()} S$s\n")
        append("; LUMACUT-CAPTURE id=$id w=$w h=$h delay=$delayMs\n")
    }

    /** Line [k] of the power test, rows [pitch] mm apart from [origin]. */
    fun powerLine(origin: Pt, k: Int, pitch: Double = 3.0) = origin + Pt(0.0, k * pitch)

    fun powerTestJob(origin: Pt, surfaceZ: Double, w: Int, h: Int, powers: List<Int> = TEST_POWERS): String = header("Laserpunkt-Leistungstest").apply {
        append("G0 Z%.3f F600\n".format(Locale.ROOT, surfaceZ + MEASURE_DISTANCE))
        for ((k, s) in powers.withIndex()) measureLine(powerLine(origin, k), s, "spotpow-$k", w, h)
        append("M5 I\nM400\n")
    }.toString()

    fun calibrationJob(origin: Pt, surfaceZ: Double, power: Int, w: Int, h: Int, distances: List<Double> = CAL_DISTANCES): String = header("Laserpunkt-Kalibrierung").apply {
        for ((k, dist) in distances.withIndex()) {
            append("G0 Z%.3f F600\n".format(Locale.ROOT, surfaceZ + dist))
            measureLine(origin + Pt(0.0, k * 2.0), power, "spotcal-$k", w, h)
        }
        append("M5 I\nM400\n")
    }.toString()

    /** One short line through every point (centred on it). */
    fun measureJob(points: List<Pt>, headZ: Double, power: Int, w: Int, h: Int): String = header("Laserpunkt-Höhenmessung").apply {
        append("G0 Z%.3f F600\n".format(Locale.ROOT, headZ))
        for ((k, p) in points.withIndex()) measureLine(p - Pt(LENGTH / 2, 0.0), power, "spotmes-$k", w, h, delayMs = 2200)
        append("M5 I\nM400\n")
    }.toString()

    /** Power test result: the spot seen (A), a mark left (B). */
    class PowerStep(val s: Int, val seen: Boolean, val strength: Double, val mark: Double)

    /** Lowest power the camera sees reliably while every power up to it left no mark; null when there is none. */
    fun pickPower(steps: List<PowerStep>): Int? {
        val sorted = steps.sortedBy { it.s }
        for ((i, st) in sorted.withIndex()) {
            if (sorted.take(i + 1).any { it.mark >= 0.05 }) return null
            // seen here and at the next step (not a lucky flicker)
            if (st.seen && sorted.getOrNull(i + 1)?.seen != false) return st.s
        }
        return null
    }

    /** How dark the test line at [start] got against the material beside it (0 = nothing). */
    fun markOf(sampler: PhotoSampler, start: Pt): Double {
        val along = (1..10).map { start.x + LENGTH * it / 11.0 }
        val on = along.mapNotNull { x -> sampler.lum(Pt(x, start.y)).takeIf { !it.isNaN() } }
        val beside = along.flatMap { x -> listOf(sampler.lum(Pt(x, start.y - 1.0)), sampler.lum(Pt(x, start.y + 1.0))) }.filter { !it.isNaN() }
        if (on.size < 5 || beside.size < 10) return Double.NaN
        val bg = beside.sorted()[beside.size / 2]
        return ((bg - on.sorted()[on.size / 2]) / bg).coerceAtLeast(0.0)
    }
}

/** Measuring line laser: on/off pictures at each head position, heights per picture column. */
object LineMeasure {
    /** Columns sampled across the picture. */
    fun columns(w: Int, step: Int = 16): List<Int> = (step / 2 until w step step).toList()

    /**
     * Heights from one on/off picture pair: per column the distance from
     * the model, surface = [headZ] − distance, placed at the work point the
     * camera sees there (good enough for a collision and focus map).
     */
    fun points(model: LightModel, on: IntArray, off: IntArray, w: Int, h: Int, cal: CameraCalibration, head: Pt, headZ: Double): List<Triple<Double, Double, Double>> {
        val found = LightFinder.line(on, off, w, h, model.keys)
        return found.mapIndexedNotNull { k, p ->
            p ?: return@mapIndexedNotNull null
            val (dist, _) = model.distance(k, p) ?: return@mapIndexedNotNull null
            val wp = cal.pixelToWork(p, head)
            Triple(wp.x, wp.y, headZ - dist)
        }
    }

    /** Height grid ([step] mm) from measured points: per cell the highest point (never too low for collisions). */
    fun grid(name: String, pts: List<Triple<Double, Double, Double>>, step: Double = 2.0): HeightMap? {
        if (pts.isEmpty()) return null
        val x0 = pts.minOf { it.first }; val y0 = pts.minOf { it.second }
        val cols = ((pts.maxOf { it.first } - x0) / step).toInt() + 1; val rows = ((pts.maxOf { it.second } - y0) / step).toInt() + 1
        if (cols * rows > 200_000) return null
        val z = MutableList(cols * rows) { Double.NaN }
        for ((x, y, hz) in pts) {
            val i = ((x - x0) / step).roundToInt().coerceIn(0, cols - 1); val j = ((y - y0) / step).roundToInt().coerceIn(0, rows - 1)
            val k = j * cols + i
            if (z[k].isNaN() || hz > z[k]) z[k] = hz
        }
        return HeightMap(name, x0, y0, step, step, cols, rows, z).filled()
    }
}
