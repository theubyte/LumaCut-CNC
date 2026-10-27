package de.millione.lumacut.core

import java.util.Locale
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Probe offset: a small cross in a circle is lasered at [mark]; the
 * operator jogs the probe tip over its centre and the head position then
 * gives the offset of the tip from the laser point (machine mm, the Pi's
 * probe_offset_x/y_mm).
 */
object ProbeTarget {
    val mark: Pt get() = Work.center

    fun paths(): List<Poly> {
        val c = mark
        val circle = (0..64).map { k -> val a = 2 * PI * k / 64; Pt(c.x + 2.5 * cos(a), c.y + 2.5 * sin(a)) }
        return listOf(listOf(Pt(c.x - 5, c.y), Pt(c.x + 5, c.y)), listOf(Pt(c.x, c.y - 5), Pt(c.x, c.y + 5)), circle)
    }

    fun job(): String {
        val layer = Layer(name = "Tasterziel", color = 0xFF4FD8B4, mode = LayerMode.LINE, powerPct = 25.0, speed = 1200.0)
        return MarlinWriter("taster-versatz").write(Document("Taster-Versatz", listOf(layer), listOf(Element(layerId = layer.id, kind = "Tasterziel", paths = paths()))))
    }

    /** Head position (machine mm) that puts a tip with [offset] over the mark. */
    fun headFor(offset: Pt): Pt = Work.toMachine(mark) - offset

    /** Offset of the tip (machine mm) when it sits over the mark with the head at [head] (machine mm). */
    fun offset(head: Pt): Pt = Work.toMachine(mark) - head
}

/**
 * Brightness of a camera photo at work positions: through the calibration
 * (lens, position) and the vignetting correction, bilinear between pixels.
 */
class PhotoSampler(private val argb: IntArray, private val w: Int, private val h: Int, private val cal: CameraCalibration, private val head: Pt) {
    private val valid = cal.validPx

    fun inside(p: Pt): Boolean {
        val q = cal.workToPixel(p, head)
        return q.x >= max(1.0, valid.minX) && q.y >= max(1.0, valid.minY) && q.x < min(w - 2.0, valid.maxX - 1) && q.y < min(h - 2.0, valid.maxY - 1)
    }

    /** Luminance 0..255 at work point [p], NaN outside the picture. */
    fun lum(p: Pt): Double {
        if (!inside(p)) return Double.NaN
        val q = cal.workToPixel(p, head)
        val x = q.x - 0.5; val y = q.y - 0.5
        val x0 = floor(x).toInt(); val y0 = floor(y).toInt(); val fx = x - x0; val fy = y - y0
        fun l(i: Int, j: Int): Double {
            val c = argb[j * w + i]
            val v = CameraLight.luminance(c).toDouble()
            val s = cal.shading ?: return v
            return v * (s.at((i + 0.5) / w, (j + 0.5) / h, 0) * 0.299 + s.at((i + 0.5) / w, (j + 0.5) / h, 1) * 0.587 + s.at((i + 0.5) / w, (j + 0.5) / h, 2) * 0.114)
        }
        val top = l(x0, y0) + (l(x0 + 1, y0) - l(x0, y0)) * fx
        val bottom = l(x0, y0 + 1) + (l(x0 + 1, y0 + 1) - l(x0, y0 + 1)) * fx
        return top + (bottom - top) * fy
    }
}

/**
 * Focus ramp: short lines side by side, each lasered with the head a little
 * higher or lower than the current focus ([offsets], mm). The camera
 * measures how wide each line burnt; the narrowest is in focus. Uses the
 * Pi's focus compensation: relative Z moves in the job become an offset on
 * the probed surface (focus_compensation.py), so the test needs no own Z.
 */
object FocusTest {
    const val LENGTH = 14.0
    const val SPACING = 3.0
    const val STEP = 0.5

    /** Offsets from −3 to +3 mm, none closer than 2.2 mm to the surface (the Pi's floor is 2 mm). */
    fun offsets(gapAboveSurface: Double): List<Double> =
        (-6..6).map { it * STEP }.filter { gapAboveSurface + it >= 2.2 }

    /** Work position of line [k] of [n]: vertical, centred around [centre]. */
    fun line(k: Int, n: Int, centre: Pt = Work.center): Pair<Pt, Pt> {
        val x = centre.x + (k - (n - 1) / 2.0) * SPACING
        return Pt(x, centre.y - LENGTH / 2) to Pt(x, centre.y + LENGTH / 2)
    }

    fun bounds(n: Int, centre: Pt = Work.center): Box {
        val (a, _) = line(0, n, centre); val (_, b) = line(n - 1, n, centre)
        return Box(a.x - 2, a.y - 2, b.x + 2, b.y + 2)
    }

    fun job(offsets: List<Double>, powerPct: Double, speed: Double, centre: Pt = Work.center): String {
        require(offsets.isNotEmpty()) { "Keine Fokusstufen" }
        require(powerPct in 1.0..100.0 && speed in Limits.SPEED) { "Leistung oder Tempo ungültig" }
        val s = (powerPct / 100 * 255).roundToInt()
        fun xy(p: Pt) = Work.toMachine(p).let { "X%.3f Y%.3f".format(Locale.ROOT, it.x, it.y) }
        val out = StringBuilder()
        fun line(t: String) { out.append(t).append('\n') }
        line("; LumaCut Fokus-Test – ${offsets.size} Linien, %.0f %% · %.0f mm/min".format(Locale.ROOT, powerPct, speed))
        line("G21"); line("G90"); line("M5 I"); line("M3 I")
        var now = 0.0
        for ((k, off) in offsets.withIndex()) {
            if (abs(off - now) > 1e-9) { line("G91"); line("G0 Z%.3f F600".format(Locale.ROOT, off - now)); line("G90"); now = off }
            line("; Linie ${k + 1}: Fokus %+.1f mm".format(Locale.ROOT, off))
            val (a, b) = line(k, offsets.size, centre)
            val (from, to) = if (k % 2 == 0) a to b else b to a
            line("G0 ${xy(from)}")
            line("G1 ${xy(to)} F${speed.roundToInt()} S$s")
        }
        if (abs(now) > 1e-9) { line("G91"); line("G0 Z%.3f F600".format(Locale.ROOT, -now)); line("G90") }
        line("M5 I"); line("M400")
        return out.toString()
    }

    /** Width (mm, area / depth of the darkness profile) and contrast (0..1) of one line; width NaN when not visible. */
    class LineResult(val offset: Double, val widthMm: Double, val contrast: Double)

    class Result(val lines: List<LineResult>, val bestOffset: Double, val widthAtBest: Double)

    fun evaluate(sampler: PhotoSampler, offsets: List<Double>, centre: Pt = Work.center): Result {
        val step = 0.03
        val lines = offsets.mapIndexed { k, off ->
            val (a, b) = line(k, offsets.size, centre)
            // profile across the line, averaged over its middle part
            val profile = DoubleArray(81); var rows = 0
            for (t in 0..10) {
                val y = a.y + 2 + (b.y - a.y - 4) * t / 10
                val row = DoubleArray(81) { i -> sampler.lum(Pt(a.x + (i - 40) * step, y)) }
                if (row.any { it.isNaN() }) continue
                // centre each row on its darkest point (the line may sit a little off)
                val dark = row.indices.minBy { row[it] }
                val shift = (dark - 40).coerceIn(-25, 25)
                for (i in profile.indices) profile[i] += row[(i + shift).coerceIn(0, 80)]
                rows++
            }
            if (rows < 4) return@mapIndexed LineResult(off, Double.NaN, 0.0)
            for (i in profile.indices) profile[i] /= rows
            val bg = (profile.take(10).average() + profile.takeLast(10).average()) / 2
            val d = profile.map { max(0.0, bg - it) }
            val peak = d.max()
            val contrast = if (bg > 0) peak / bg else 0.0
            val width = if (contrast < 0.06) Double.NaN else d.sum() * step / peak
            LineResult(off, width, contrast)
        }
        val seen = lines.filter { !it.widthMm.isNaN() }
        if (seen.size < 3) throw IllegalStateException("Nur ${seen.size} Linien erkannt – Leistung höher oder Licht prüfen")
        // the width changes only slowly around the focus: a parabola through all lines, not the single narrowest one
        // (camera resolution is about 0.1 mm per pixel, single widths are noisy)
        val fit = parabola(seen.map { it.offset to it.widthMm })
        val best = if (fit != null && fit.first > 1e-6) (-fit.second / (2 * fit.first)).coerceIn(seen.first().offset, seen.last().offset)
                   else CameraFocus.peak(seen.map { it.offset to -it.widthMm })
        return Result(lines, best, seen.minBy { abs(it.offset - best) }.widthMm)
    }

    /** Least squares y = a x² + b x + c; null when it cannot be solved. */
    private fun parabola(pts: List<Pair<Double, Double>>): Triple<Double, Double, Double>? {
        if (pts.size < 3) return null
        fun s(f: (Double, Double) -> Double) = pts.sumOf { (x, y) -> f(x, y) }
        val m = arrayOf(doubleArrayOf(s { x, _ -> x * x * x * x }, s { x, _ -> x * x * x }, s { x, _ -> x * x }),
                        doubleArrayOf(s { x, _ -> x * x * x }, s { x, _ -> x * x }, s { x, _ -> x }),
                        doubleArrayOf(s { x, _ -> x * x }, s { x, _ -> x }, pts.size.toDouble()))
        val r = doubleArrayOf(s { x, y -> x * x * y }, s { x, y -> x * y }, s { _, y -> y })
        fun det(a: Array<DoubleArray>) = a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
        val d = det(m)
        if (abs(d) < 1e-12) return null
        val sol = (0..2).map { k -> det(Array(3) { i -> DoubleArray(3) { j -> if (j == k) r[i] else m[i][j] } }) / d }
        return Triple(sol[0], sol[1], sol[2])
    }
}

/**
 * Engraving test: small filled squares, one per power × speed, with
 * unburnt gaps between them. The camera measures per square how dark it
 * got against the untouched material right next to it, how even it is and
 * whether it darkened its surroundings (smoke, overburn). From that the
 * fastest clean setting for a wanted tone is picked.
 */
object EngraveTest {
    data class Spec(
        val powers: List<Double> = listOf(15.0, 25.0, 35.0, 50.0, 70.0),
        val speeds: List<Double> = listOf(1500.0, 2500.0, 3500.0, 4500.0, 6000.0),
        val cellMm: Double = 5.0, val gapMm: Double = 3.0, val intervalMm: Double = 0.1,
        val centre: Pt = Work.center,
    ) {
        init {
            require(powers.size in 2..12 && speeds.size in 1..8) { "2 … 12 Leistungen, 1 … 8 Geschwindigkeiten" }
            require(powers.all { it in 1.0..100.0 } && speeds.all { it in Limits.SPEED }) { "Leistung 1–100 %, Tempo bis %.0f mm/min".format(Limits.SPEED.endInclusive) }
        }
        val pitch get() = cellMm + gapMm

        /** Top-left of the square for power [i] (column) and speed [j] (row). */
        fun cell(i: Int, j: Int): Box {
            val x = centre.x + (i - (powers.size - 1) / 2.0) * pitch - cellMm / 2
            val y = centre.y + (j - (speeds.size - 1) / 2.0) * pitch - cellMm / 2
            return Box(x, y, x + cellMm, y + cellMm)
        }

        fun bounds(): Box = cell(0, 0).union(cell(powers.size - 1, speeds.size - 1)).let { Box(it.minX - gapMm, it.minY - gapMm, it.maxX + gapMm, it.maxY + gapMm) }
    }

    fun job(spec: Spec, motion: MarlinWriter.Motion = MarlinWriter.Motion.FIRMWARE): String {
        val layers = ArrayList<Layer>(); val elements = ArrayList<Element>()
        // slowest first: the hottest squares burn while the plate is still cool
        for ((j, speed) in spec.speeds.withIndex()) for ((i, power) in spec.powers.withIndex()) {
            val layer = Layer(name = "${power.roundToInt()} % · ${speed.roundToInt()} mm/min", color = 0xFF4FD8B4, mode = LayerMode.FILL,
                powerPct = power, speed = speed, intervalMm = spec.intervalMm)
            val b = spec.cell(i, j)
            layers += layer
            elements += Element(layerId = layer.id, kind = "Testfeld", transform = Transform(b.minX, b.minY), paths = listOf(Shapes.rect(spec.cellMm, spec.cellMm)))
        }
        return MarlinWriter("gravur-test", motion).write(Document("Gravur-Test", layers, elements))
    }

    /**
     * One square: [tone] 0 = untouched … 1 = black, [unevenness] spread of
     * the brightness inside, [halo] darkening of the 0.2–0.7 mm ring around it.
     */
    class Field(val power: Double, val speed: Double, val tone: Double, val unevenness: Double, val halo: Double) {
        val clean get() = unevenness < 0.12 && halo < 0.08
        val charred get() = tone > 0.85 || halo >= 0.12
    }

    fun measure(spec: Spec, i: Int, j: Int, sampler: PhotoSampler): Field? {
        val b = spec.cell(i, j)
        fun ring(from: Double, to: Double): List<Double> {
            val out = ArrayList<Double>()
            var y = b.minY - to
            while (y <= b.maxY + to) {
                var x = b.minX - to
                while (x <= b.maxX + to) {
                    val dx = max(b.minX - x, x - b.maxX); val dy = max(b.minY - y, y - b.maxY)
                    val d = max(dx, dy)
                    if (d in from..to) sampler.lum(Pt(x, y)).takeIf { !it.isNaN() }?.let(out::add)
                    x += 0.1
                }
                y += 0.1
            }
            return out
        }
        val inner = ArrayList<Double>()
        val inset = min(0.8, spec.cellMm / 4)
        var y = b.minY + inset
        while (y <= b.maxY - inset) {
            var x = b.minX + inset
            while (x <= b.maxX - inset) { val v = sampler.lum(Pt(x, y)); if (v.isNaN()) return null; inner += v; x += 0.1 }
            y += 0.1
        }
        val far = ring(spec.gapMm * 0.35, spec.gapMm * 0.48).sorted().takeIf { it.size > 20 } ?: return null
        val near = ring(0.2, 0.7).takeIf { it.size > 20 } ?: return null
        val bg = far[far.size * 3 / 4]          // unburnt surroundings (upper quartile: ignores neighbours' smoke)
        if (bg < 20) return null
        val mean = inner.average()
        val sd = kotlin.math.sqrt(inner.sumOf { (it - mean) * (it - mean) } / inner.size)
        return Field(spec.powers[i], spec.speeds[j], (1 - mean / bg).coerceIn(0.0, 1.0), sd / bg, (1 - near.average() / bg).coerceIn(0.0, 1.0))
    }

    enum class Tone(val label: String, val target: Double) { LIGHT("hell", 0.3), MEDIUM("mittel", 0.5), DARK("dunkel", 0.7) }

    /**
     * Fastest clean square within ±0.08 of the tone (then the lower power);
     * without one the clean square closest to the tone; null when nothing is clean.
     */
    fun pick(fields: List<Field>, tone: Tone): Field? {
        val clean = fields.filter { it.clean && !it.charred }
        val near = clean.filter { abs(it.tone - tone.target) <= 0.08 }
        return near.maxWithOrNull(compareBy<Field> { it.speed }.thenBy { -it.power })
            ?: clean.minByOrNull { abs(it.tone - tone.target) }
    }

    /** Head positions (work mm) whose usable camera area together show every square with its surroundings. */
    fun photos(spec: Spec, cal: CameraCalibration): List<Pt> = CameraCover.heads(spec.bounds(), cal)
}

/** Head positions for photos of a test area. */
object CameraCover {
    /** Head positions (work mm) whose usable camera areas (25 % overlap) together cover [area]. */
    fun heads(area: Box, cal: CameraCalibration): List<Pt> {
        val u = cal.usable(0.1)
        val cols = max(1, ceil((area.width - u.width) / (u.width * 0.75)).toInt() + 1)
        val rows = max(1, ceil((area.height - u.height) / (u.height * 0.75)).toInt() + 1)
        return (0 until rows).flatMap { r -> (0 until cols).map { c ->
            val tx = if (cols == 1) area.center.x - u.width / 2 else area.minX + (area.width - u.width) * c / (cols - 1)
            val ty = if (rows == 1) area.center.y - u.height / 2 else area.minY + (area.height - u.height) * r / (rows - 1)
            Pt(tx - u.minX, ty - u.minY)
        } }
    }
}

/**
 * Motion calibration: how hard and how fast the gantry can move without
 * losing a step. First a reference mark per level is lasered (an "L" of two
 * lines). Then, level by level, the Pi drives laser-off stress moves at a
 * rising acceleration and speed, and the laser draws a check "L" 1 mm
 * beside the reference. A lost step moves every later check mark; the
 * camera measures the line spacing, so a level fails when its check mark
 * moved more than [TOLERANCE] against the previous one. Glyph 0 gets its
 * check mark without stress: the baseline (repeatability, backlash).
 */
object MotionTest {
    data class Level(val accel: Double, val speed: Double)

    val LEVELS = listOf(Level(1000.0, 150.0), Level(2000.0, 200.0), Level(3000.0, 250.0),
                        Level(4500.0, 300.0), Level(6000.0, 350.0), Level(8000.0, 400.0))
    const val ARM = 6.0
    const val GAP = 1.0
    const val PITCH = 10.0
    const val PER_ROW = 4
    const val TOLERANCE = 0.1

    /** Top-left corner of glyph [k] of [n] (glyph 0 = baseline, glyph k = level k-1). */
    fun origin(k: Int, n: Int, centre: Pt = Work.center): Pt {
        val rows = (n + PER_ROW - 1) / PER_ROW
        val col = k % PER_ROW; val row = k / PER_ROW
        return Pt(centre.x + (col - (PER_ROW - 1) / 2.0) * PITCH - ARM / 2, centre.y + (row - (rows - 1) / 2.0) * PITCH - ARM / 2)
    }

    fun bounds(n: Int, centre: Pt = Work.center): Box =
        (0 until n).map { origin(it, n, centre) }.let { o -> Box(o.minOf { it.x } - 2, o.minOf { it.y } - 2, o.maxOf { it.x } + ARM + 2, o.maxOf { it.y } + ARM + 2) }

    /** Reference "L": vertical line at x, horizontal line at y, corner top-left. */
    fun reference(k: Int, n: Int, centre: Pt = Work.center): List<Poly> {
        val o = origin(k, n, centre)
        return listOf(listOf(o, Pt(o.x, o.y + ARM)), listOf(o, Pt(o.x + ARM, o.y)))
    }

    /** Check "L" [GAP] mm right of and below the reference. */
    fun check(k: Int, n: Int, centre: Pt = Work.center): List<Poly> {
        val o = origin(k, n, centre) + Pt(GAP, GAP)
        return listOf(listOf(o, Pt(o.x, o.y + ARM - GAP)), listOf(o, Pt(o.x + ARM - GAP, o.y)))
    }

    /**
     * The lines of [paths], each started from 2 mm before its start in −X
     * and −Y: every line is approached from the same side, so the backlash
     * of the belts (about 0.1 mm) is the same for reference and check marks
     * and does not look like a lost step. [motion] is not needed (no fills).
     */
    @Suppress("UNUSED_PARAMETER")
    fun job(title: String, paths: List<Poly>, motion: MarlinWriter.Motion = MarlinWriter.Motion.FIRMWARE): String {
        val s = (25.0 / 100 * 255).roundToInt()
        fun xy(p: Pt) = Work.toMachine(p).let { "X%.3f Y%.3f".format(Locale.ROOT, it.x, it.y) }
        val out = StringBuilder("; LumaCut $title\nG21\nG90\nM5 I\nM3 I\n")
        for (path in paths) {
            val start = path.first()
            out.append("G0 ${xy(start - Pt(2.0, 2.0))}\nG0 ${xy(start)}\n")
            for (q in path.drop(1)) out.append("G1 ${xy(q)} F1200 S$s\n")
        }
        out.append("M5 I\nM400\n")
        return out.toString()
    }

    /** Check minus reference spacing, minus [GAP] (mm): how far the check mark moved; NaN when a line is not found. */
    class Shift(val dx: Double, val dy: Double) {
        val found get() = !dx.isNaN() && !dy.isNaN()
    }

    fun measure(sampler: PhotoSampler, k: Int, n: Int, centre: Pt = Work.center): Shift {
        val o = origin(k, n, centre)
        // across the vertical lines (X), averaged down the part where both exist, and the same for Y
        val dx = lineSpacing(GAP) { s -> (0..10).map { t -> sampler.lum(Pt(o.x + s, o.y + GAP + 1 + (ARM - GAP - 2) * t / 10)) } }
        val dy = lineSpacing(GAP) { s -> (0..10).map { t -> sampler.lum(Pt(o.x + GAP + 1 + (ARM - GAP - 2) * t / 10, o.y + s)) } }
        return Shift(dx - GAP, dy - GAP)
    }

    /**
     * Index of the last level that held (−1: not even the first), from the
     * shifts of glyphs 0 … n (glyph 0 = baseline without stress).
     */
    fun lastGood(shifts: List<Shift>): Int {
        var last = -1
        for (k in 1 until shifts.size) {
            val a = shifts[k - 1]; val b = shifts[k]
            if (!a.found || !b.found) break
            if (abs(b.dx - a.dx) > TOLERANCE || abs(b.dy - a.dy) > TOLERANCE) break
            last = k - 1
        }
        return last
    }

    /** Limits to keep: 70 % of the acceleration and 80 % of the speed of the last level that held. */
    fun recommend(level: Level) = MarlinWriter.Motion((level.accel * 0.7 / 100).roundToInt() * 100.0, (level.speed * 0.8 / 10).roundToInt() * 10.0)
}

/**
 * Distance between two parallel dark lines about [gap] mm apart, from a
 * profile across both; [at] gives the samples at offset s (mm) from where
 * the first line should be. The lines are searched in a wide window (±1.5
 * mm), so a camera that sees everything shifted a little (registration
 * of camera and laser) does not mix them up. NaN unless two clear lines
 * are seen.
 */
internal fun lineSpacing(gap: Double, at: (Double) -> List<Double>): Double {
    val step = 0.02
    val offs = (-75..((gap + 1.5) / step).toInt()).map { it * step }
    val prof = offs.map { s -> at(s).filter { !it.isNaN() }.takeIf { it.size >= 6 }?.average() ?: return Double.NaN }
    val bg = prof.sorted().let { it[it.size * 4 / 5] }
    if (bg <= 0) return Double.NaN
    val d = prof.map { max(0.0, bg - it) }
    val half = (0.15 / step).toInt()
    val peaks = d.indices.filter { i -> d[i] > 0.08 * bg && (maxOf(0, i - half)..minOf(d.lastIndex, i + half)).all { d[it] <= d[i] } }
        .sortedByDescending { d[it] }
    val first = peaks.firstOrNull() ?: return Double.NaN
    val second = peaks.firstOrNull { abs(offs[it] - offs[first]) >= gap * 0.4 } ?: return Double.NaN
    fun centre(i: Int): Double {
        var sw = 0.0; var sx = 0.0
        for (j in maxOf(0, i - 15)..minOf(d.lastIndex, i + 15)) { val v = d[j] - d[i] / 2; if (v > 0) { sw += v; sx += v * offs[j] } }
        return sx / sw
    }
    return abs(centre(second) - centre(first))
}

/**
 * Grey-scale curve: one row of squares at the same speed with rising
 * power. The camera measures how dark each got; inverted, that is the
 * share of power a picture needs for each grey ([Layer.toneCurve]), so
 * photos come out with the tones of the original instead of too dark.
 */
object ToneTest {
    data class Spec(val maxPower: Double, val speed: Double, val steps: Int = 10, val intervalMm: Double = 0.1, val centre: Pt = Work.center) {
        init { require(maxPower in 5.0..100.0 && speed in Limits.SPEED && steps in 4..12) { "Ungültiger Graustufen-Test" } }
        val fields get() = EngraveTest.Spec(powers = (1..steps).map { maxPower * it / steps }, speeds = listOf(speed),
            cellMm = 5.0, gapMm = 3.0, intervalMm = intervalMm, centre = centre)
    }

    fun job(spec: Spec, motion: MarlinWriter.Motion = MarlinWriter.Motion.FIRMWARE) = EngraveTest.job(spec.fields, motion)

    /**
     * Curve (11 shares of the power for darkness 0, 0.1 … 1) from the tones
     * measured at power share (i + 1) / steps; a darker field than the next
     * one (noise) is evened out first.
     */
    fun curve(tones: List<Double>): List<Double> {
        require(tones.isNotEmpty()) { "Keine Messwerte" }
        val mono = tones.runningReduce { a, b -> max(a, b) }
        val top = mono.last()
        require(top >= 0.05) { "Auch mit der höchsten Leistung kaum Farbe – höhere Leistung oder langsamer testen" }
        val shares = listOf(0.0) + tones.indices.map { (it + 1).toDouble() / tones.size }
        val rel = listOf(0.0) + mono.map { it / top }
        return (0..10).map { k ->
            val want = k / 10.0
            val i = (1 until rel.size).firstOrNull { rel[it] >= want - 1e-9 } ?: (rel.size - 1)
            val span = rel[i] - rel[i - 1]
            if (span < 1e-9) shares[i] else shares[i - 1] + (shares[i] - shares[i - 1]) * (want - rel[i - 1]) / span
        }
    }
}

/**
 * Backlash: two lines 1 mm apart, the first approached from one side, the
 * second from the other. Play in belts or pulleys shifts the second; the
 * camera measures the spacing. Three pairs per axis, averaged.
 */
object BacklashTest {
    const val LEN = 8.0
    const val GAP = 1.0
    const val RUN = 5.0

    /** (axis, origin) of the pairs: lines across X first, then across Y. */
    fun pairs(centre: Pt = Work.center): List<Pair<Char, Pt>> =
        (0..2).map { 'X' to Pt(centre.x - 20 + it * 6.0, centre.y - LEN / 2) } + (0..2).map { 'Y' to Pt(centre.x + 6, centre.y - 8 + it * 6.0) }

    fun bounds(centre: Pt = Work.center): Box {
        val ps = pairs(centre).flatMap { (a, o) -> if (a == 'X') listOf(o - Pt(RUN, 0.0), o + Pt(GAP + RUN, LEN)) else listOf(o - Pt(0.0, RUN), o + Pt(LEN, GAP + RUN)) }
        return Box(ps.minOf { it.x } - 2, ps.minOf { it.y } - 2, ps.maxOf { it.x } + 2, ps.maxOf { it.y } + 2)
    }

    fun job(powerPct: Double = 25.0, speed: Double = 1200.0, centre: Pt = Work.center): String {
        val s = (powerPct / 100 * 255).roundToInt()
        fun xy(p: Pt) = Work.toMachine(p).let { "X%.3f Y%.3f".format(Locale.ROOT, it.x, it.y) }
        val f = speed.roundToInt()
        val out = StringBuilder("; LumaCut Umkehrspiel-Test\nG21\nG90\nM5 I\nM3 I\n")
        for ((axis, o) in pairs(centre)) {
            val along = if (axis == 'X') Pt(0.0, LEN) else Pt(LEN, 0.0)
            val across = if (axis == 'X') Pt(1.0, 0.0) else Pt(0.0, 1.0)
            // first line: approached from the low side; second: from the high side
            out.append("G0 ${xy(o - across * RUN)}\nG0 ${xy(o)}\nG1 ${xy(o + along)} F$f S$s\n")
            val b = o + across * GAP
            out.append("G0 ${xy(b + across * RUN)}\nG0 ${xy(b)}\nG1 ${xy(b + along)} F$f S$s\n")
        }
        out.append("M5 I\nM400\n")
        return out.toString()
    }

    /** Spacing minus [GAP] of one pair (mm, signed); NaN when not seen. */
    fun measure(sampler: PhotoSampler, axis: Char, o: Pt): Double {
        val across = if (axis == 'X') Pt(1.0, 0.0) else Pt(0.0, 1.0)
        val along = if (axis == 'X') Pt(0.0, 1.0) else Pt(1.0, 0.0)
        return lineSpacing(GAP) { s -> (0..10).map { t -> sampler.lum(o + across * s + along * (1.5 + (LEN - 3) * t / 10)) } } - GAP
    }

    /** Backlash per axis: |mean| of its pairs, NaN without measurements. */
    fun result(values: List<Pair<Char, Double>>): Map<Char, Double> = listOf('X', 'Y').associateWith { a ->
        values.filter { it.first == a && !it.second.isNaN() }.map { it.second }.takeIf { it.isNotEmpty() }?.let { abs(it.average()) } ?: Double.NaN
    }
}

/**
 * Guided cut test: small squares cut with rising passes (rows) and speeds
 * (columns). The operator presses them out and taps in the app which ones
 * fell through; the fastest one that did, with some reserve, becomes the
 * cutting setting of the material. A small engraved arrow at the top left
 * shows the orientation.
 */
object CutTest {
    data class Spec(
        val powerPct: Double = 100.0,
        val speeds: List<Double> = listOf(150.0, 250.0, 350.0, 450.0, 600.0),
        val passes: List<Int> = listOf(1, 2, 3),
        val thicknessMm: Double = 3.0,
        val cellMm: Double = 8.0, val gapMm: Double = 4.0,
        val centre: Pt = Work.center,
    ) {
        init {
            require(powerPct in 1.0..100.0 && speeds.size in 2..6 && passes.size in 1..4) { "Ungültiger Schnitt-Test" }
            require(speeds.all { it in 30.0..Limits.SPEED.endInclusive } && passes.all { it in 1..10 }) { "Tempo oder Durchgänge ungültig" }
        }
        /** Focus drop per pass: following the cut into the material, at most 3 mm in total. */
        val zStep: Double get() { val p = passes.max(); return if (p <= 1) 0.0 else minOf(thicknessMm / p, Limits.MAX_FOCUS_DROP_MM / (p - 1), 1.0) }

        /** Square for speed [i] (column) and passes [j] (row). */
        fun cell(i: Int, j: Int): Box {
            val pitch = cellMm + gapMm
            val x = centre.x + (i - (speeds.size - 1) / 2.0) * pitch - cellMm / 2
            val y = centre.y + (j - (passes.size - 1) / 2.0) * pitch - cellMm / 2
            return Box(x, y, x + cellMm, y + cellMm)
        }
    }

    fun job(spec: Spec, motion: MarlinWriter.Motion = MarlinWriter.Motion.FIRMWARE): String {
        val mark = Layer(name = "Markierung", color = 0xFFEEF3F8, mode = LayerMode.LINE, powerPct = 20.0, speed = 1500.0)
        val first = spec.cell(0, 0)
        val arrow = listOf(Pt(first.minX, first.minY - 4), Pt(first.minX + 3, first.minY - 4), Pt(first.minX + 2, first.minY - 5), Pt(first.minX + 3, first.minY - 4), Pt(first.minX + 2, first.minY - 3))
        val layers = arrayListOf(mark); val elements = arrayListOf(Element(layerId = mark.id, kind = "Markierung", paths = listOf(arrow)))
        for ((j, p) in spec.passes.withIndex()) for ((i, s) in spec.speeds.withIndex()) {
            val layer = Layer(name = "${spec.powerPct.roundToInt()} % · ${s.roundToInt()} mm/min · ${p}×", color = 0xFFFF8A5C, mode = LayerMode.LINE,
                powerPct = spec.powerPct, speed = s, passes = p, zStepMm = if (p > 1) spec.zStep else 0.0)
            val b = spec.cell(i, j)
            layers += layer
            elements += Element(layerId = layer.id, kind = "Schnittfeld", transform = Transform(b.minX, b.minY), paths = listOf(Shapes.rect(spec.cellMm, spec.cellMm)))
        }
        return MarlinWriter("schnitt-test", motion).write(Document("Schnitt-Test", layers, elements))
    }

    /** Setting to keep: [reserve] true when a slower square that also fell through backs it up. */
    class Pick(val speed: Double, val passes: Int, val powerPct: Double, val zStep: Double, val reserve: Boolean, val inconsistent: Boolean)

    /**
     * From the squares that fell through ([through]: column, row): the
     * quickest (passes / speed); taken is the next slower one that also fell
     * through (≥ 15 % more time), so material variation does not leave
     * parts hanging. [Pick.inconsistent] when a slower square with the same
     * passes did not fall through although a faster one did (check the marks).
     */
    fun pick(spec: Spec, through: Set<Pair<Int, Int>>): Pick? {
        if (through.isEmpty()) return null
        fun cost(c: Pair<Int, Int>) = spec.passes[c.second] / spec.speeds[c.first]
        val best = through.minBy(::cost)
        val safe = through.filter { cost(it) >= cost(best) * 1.15 }.minByOrNull(::cost)
        val chosen = safe ?: best
        val inconsistent = through.any { (i, j) -> (0 until i).any { k -> (k to j) !in through } }
        val p = spec.passes[chosen.second]
        return Pick(spec.speeds[chosen.first], p, spec.powerPct, if (p > 1) spec.zStep else 0.0, safe != null, inconsistent)
    }
}

/**
 * Ringing test: after a sharp 90° corner the axis that stopped hard may
 * swing on for a moment; the long straight line drawn right after it then
 * waves sideways, fading out. Per moved axis and speed one "leg": a short
 * lead across, the corner, then [Spec.length] mm straight. The camera
 * follows the line centre and measures how far it swings ([Leg.amplitude])
 * and how long one wave is, which gives the swing frequency (input
 * shaping). Lines along X show the Y axis swinging and vice versa.
 */
object RingingTest {
    data class Spec(
        val speeds: List<Double> = listOf(1500.0, 3000.0, 4500.0),
        val length: Double = 30.0, val lead: Double = 4.0, val pitch: Double = 5.0,
        val powerPct: Double = 20.0, val centre: Pt = Work.center,
    ) {
        init { require(speeds.size in 1..6 && speeds.all { it in 300.0..Limits.SPEED.endInclusive } && powerPct in 1.0..100.0) { "Ungültiger Schwing-Test" } }
    }

    /** One line: moving along [axis] at [speed] (mm/min), the corner at [corner], the line towards +axis. */
    data class Leg(val axis: Char, val speed: Double, val corner: Pt) {
        val dir get() = if (axis == 'X') Pt(1.0, 0.0) else Pt(0.0, 1.0)
        val across get() = if (axis == 'X') Pt(0.0, 1.0) else Pt(1.0, 0.0)
    }

    fun legs(spec: Spec): List<Leg> {
        val n = spec.speeds.size
        val blockH = (n - 1) * spec.pitch
        val left = spec.centre.x - spec.length - spec.lead - 3
        val top = spec.centre.y - spec.length / 2
        val xs = spec.speeds.mapIndexed { i, s -> Leg('X', s, Pt(left + spec.lead, top + spec.lead + i * spec.pitch)) }
        val ys = spec.speeds.mapIndexed { i, s -> Leg('Y', s, Pt(spec.centre.x + 3 + spec.lead + i * spec.pitch, top + spec.lead + blockH + 6)) }
        return xs + ys
    }

    fun bounds(spec: Spec): Box {
        val pts = legs(spec).flatMap { l -> listOf(l.corner - l.across * spec.lead, l.corner + l.dir * spec.length) }
        return Box(pts.minOf { it.x } - 2, pts.minOf { it.y } - 2, pts.maxOf { it.x } + 2, pts.maxOf { it.y } + 2)
    }

    /** G-code written directly: the direction of every line must stay as planned (no reordering). */
    fun job(spec: Spec): String {
        val s = (spec.powerPct / 100 * 255).roundToInt()
        fun xy(p: Pt) = Work.toMachine(p).let { "X%.3f Y%.3f".format(Locale.ROOT, it.x, it.y) }
        val out = StringBuilder()
        fun line(t: String) { out.append(t).append('\n') }
        line("; LumaCut Schwing-Test – ${spec.speeds.size} Tempi je Achse")
        line("G21"); line("G90"); line("M5 I"); line("M3 I")
        for (l in legs(spec)) {
            line("; Achse ${l.axis}, %.0f mm/min".format(Locale.ROOT, l.speed))
            line("G0 ${xy(l.corner - l.across * spec.lead)}")
            line("G1 ${xy(l.corner)} F${l.speed.roundToInt()} S$s")
            line("G1 ${xy(l.corner + l.dir * spec.length)} F${l.speed.roundToInt()} S$s")
        }
        line("M5 I"); line("M400")
        return out.toString()
    }

    /** [amplitude] largest swing (mm) in the first 12 mm after the corner, [noise] wobble of the settled rest, [wavelength] mm or NaN. */
    class Result(val leg: Leg, val amplitude: Double, val noise: Double, val wavelength: Double) {
        /** The axis that swings: the one that stopped at the corner. */
        val swingingAxis get() = if (leg.axis == 'X') 'Y' else 'X'
        val frequency get() = if (wavelength.isNaN() || wavelength <= 0) Double.NaN else leg.speed / 60 / wavelength
        val found get() = !amplitude.isNaN()
        val rings get() = found && amplitude > 0.05 && amplitude > 3 * noise
    }

    fun measure(sampler: PhotoSampler, spec: Spec, leg: Leg): Result {
        val step = 0.1
        val ts = generateSequence(0.4) { it + step }.takeWhile { it <= spec.length - 0.6 }.toList()
        // where the line really is across (camera and laser may be registered a little apart): wide search in the settled part
        val wide = (-75..75).map { it * 0.02 }
        val found = listOf(0.6, 0.75, 0.9).map { k -> val base = leg.corner + leg.dir * (spec.length * k)
            val prof = wide.map { o -> sampler.lum(base + leg.across * o) }
            if (prof.any { it.isNaN() }) Double.NaN else wide[prof.indices.minBy { prof[it] }] }.filter { !it.isNaN() }
        if (found.isEmpty()) return Result(leg, Double.NaN, Double.NaN, Double.NaN)
        val shift = found.sorted()[found.size / 2]
        val offs = (-20..20).map { shift + it * 0.04 }
        val dev = ts.map { t ->
            val base = leg.corner + leg.dir * t
            val prof = offs.map { o -> sampler.lum(base + leg.across * o) }
            if (prof.any { it.isNaN() }) return Result(leg, Double.NaN, Double.NaN, Double.NaN)
            val bg = (prof.take(5).average() + prof.takeLast(5).average()) / 2
            val d = prof.map { max(0.0, bg - it) }
            val peak = d.max()
            if (peak < bg * 0.08) Double.NaN
            else { var sw = 0.0; var sx = 0.0; for (i in d.indices) { val v = d[i] - peak / 2; if (v > 0) { sw += v; sx += v * offs[i] } }; sx / sw }
        }
        val good = ts.indices.filter { !dev[it].isNaN() }
        if (good.size < ts.size * 0.7) return Result(leg, Double.NaN, Double.NaN, Double.NaN)
        // the settled second half gives the straight line (the camera may see it a little tilted)
        val tail = good.filter { ts[it] > spec.length * 0.5 }
        val mt = tail.map { ts[it] }.average(); val md = tail.map { dev[it] }.average()
        val slope = tail.sumOf { (ts[it] - mt) * (dev[it] - md) } / tail.sumOf { (ts[it] - mt) * (ts[it] - mt) }.coerceAtLeast(1e-9)
        val res = ts.indices.map { if (dev[it].isNaN()) Double.NaN else dev[it] - (md + slope * (ts[it] - mt)) }
        val noise = kotlin.math.sqrt(tail.map { res[it] * res[it] }.average())
        val head = ts.indices.filter { ts[it] <= 12.0 && !res[it].isNaN() }
        val amplitude = head.maxOf { abs(res[it]) }
        // wavelength: first peak of the autocorrelation of the swing (robust while it fades out)
        val r = head.map { res[it] }
        val energy = r.sumOf { it * it }
        val ac = (0..r.size / 2).map { k -> if (energy <= 0) 0.0 else (0 until r.size - k).sumOf { r[it] * r[it + k] } / energy }
        val firstNeg = ac.indexOfFirst { it < 0 }
        val peak = if (firstNeg < 0) -1 else (firstNeg until ac.size - 1).firstOrNull { ac[it] >= ac[it - 1] && ac[it] >= ac[it + 1] && ac[it] > 0.1 } ?: -1
        val wavelength = if (peak <= 0) Double.NaN else {
            val a0 = ac[peak - 1]; val a1 = ac[peak]; val a2 = ac[peak + 1]
            val d = a0 - 2 * a1 + a2
            (peak + if (abs(d) < 1e-12) 0.0 else 0.5 * (a0 - a2) / d) * step
        }
        return Result(leg, amplitude, noise, wavelength)
    }
}
