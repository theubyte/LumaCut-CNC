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
        val best = CameraFocus.peak(seen.map { it.offset to -it.widthMm })
        val nearest = seen.minBy { abs(it.offset - best) }
        return Result(lines, best, nearest.widthMm)
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
            require(powers.size in 2..8 && speeds.size in 2..8) { "2 … 8 Stufen je Richtung" }
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

    fun job(title: String, paths: List<Poly>, motion: MarlinWriter.Motion = MarlinWriter.Motion.FIRMWARE): String {
        val layer = Layer(name = title, color = 0xFF4FD8B4, mode = LayerMode.LINE, powerPct = 25.0, speed = 1200.0)
        return MarlinWriter("bewegungstest", motion).write(Document(title, listOf(layer), listOf(Element(layerId = layer.id, kind = title, paths = paths))))
    }

    /** Check minus reference spacing, minus [GAP] (mm): how far the check mark moved; NaN when a line is not found. */
    class Shift(val dx: Double, val dy: Double) {
        val found get() = !dx.isNaN() && !dy.isNaN()
    }

    fun measure(sampler: PhotoSampler, k: Int, n: Int, centre: Pt = Work.center): Shift {
        val o = origin(k, n, centre)
        // across the vertical lines (X), averaged down the part where both exist, and the same for Y
        val dx = spacing { s -> (0..10).map { t -> sampler.lum(Pt(o.x + s, o.y + GAP + 1 + (ARM - GAP - 2) * t / 10)) } }
        val dy = spacing { s -> (0..10).map { t -> sampler.lum(Pt(o.x + GAP + 1 + (ARM - GAP - 2) * t / 10, o.y + s)) } }
        return Shift(dx - GAP, dy - GAP)
    }

    /** Distance between the dark line near 0 and the one near [GAP] in a profile; [at] gives samples at offset s (mm). */
    private fun spacing(at: (Double) -> List<Double>): Double {
        val step = 0.02
        val offs = (-30..80).map { it * step }                 // -0.6 … +1.6 mm
        val prof = offs.map { s -> at(s).filter { !it.isNaN() }.takeIf { it.size >= 6 }?.average() ?: return Double.NaN }
        val bg = prof.sorted().let { it[it.size * 4 / 5] }
        fun centre(from: Double, to: Double): Double {
            val idx = offs.indices.filter { offs[it] in from..to }
            val d = idx.map { max(0.0, bg - prof[it]) }
            val peak = d.max()
            if (bg <= 0 || peak / bg < 0.08) return Double.NaN
            var sw = 0.0; var sx = 0.0
            for ((m, i) in idx.withIndex()) { val v = d[m] - peak / 2; if (v > 0) { sw += v; sx += v * offs[i] } }
            return sx / sw
        }
        return centre(GAP - 0.5, GAP + 0.55) - centre(-0.55, 0.5)
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
