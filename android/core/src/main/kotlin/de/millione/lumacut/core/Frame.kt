package de.millione.lumacut.core

import java.util.Locale

/** Outline the Pi traces with the laser off (op=frame), so the operator sees where the job will burn. */
object Frame {
    enum class Mode(val api: String, val label: String) { BOX("box", "Rechteck"), HULL("hull", "Gummiband") }

    /**
     * Laser-off program accepted by the Pi's frame_program(): only G21/G90/M5 I and
     * absolute G0 moves. [points] are machine mm (e.g. from [cutPoints]); the outline is
     * kept inside the work area, never in the safe zone.
     */
    fun program(points: List<Pt>, mode: Mode, feed: Int = 3000): String {
        require(points.isNotEmpty()) { "Kein Motiv für den Rahmen" }
        val outline = when (mode) {
            Mode.BOX -> boundsOf(listOf(points))!!.let { b ->
                listOf(Pt(b.minX, b.minY), Pt(b.maxX, b.minY), Pt(b.maxX, b.maxY), Pt(b.minX, b.maxY))
            }
            Mode.HULL -> convexHull(points)
        }
        val f = feed.coerceIn(300, 9000)
        val out = StringBuilder("G21\nG90\nM5 I\n")
        for (p in outline + outline.first()) {
            val x = p.x.coerceIn(Bed.SAFE, Bed.WIDTH); val y = p.y.coerceIn(Bed.SAFE, Bed.HEIGHT)
            out.append(String.format(Locale.ROOT, "G0 X%.3f Y%.3f F%d\n", x, y, f))
        }
        return out.toString()
    }

    /** Points the laser actually burns in a toolpath (machine mm). */
    fun cutPoints(tp: Toolpath): List<Pt> = tp.segments.filter { it.cut }.flatMap {
        listOf(Pt(it.x0.toDouble(), it.y0.toDouble()), Pt(it.x1.toDouble(), it.y1.toDouble()))
    }

    /** Andrew's monotone chain, counter-clockwise, without repeated end point. */
    fun convexHull(points: List<Pt>): List<Pt> {
        val pts = points.distinct().sortedWith(compareBy({ it.x }, { it.y }))
        if (pts.size < 3) return pts
        fun cross(o: Pt, a: Pt, b: Pt) = (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
        val lower = ArrayList<Pt>()
        for (p in pts) { while (lower.size >= 2 && cross(lower[lower.size - 2], lower.last(), p) <= 0) lower.removeAt(lower.size - 1); lower += p }
        val upper = ArrayList<Pt>()
        for (p in pts.asReversed()) { while (upper.size >= 2 && cross(upper[upper.size - 2], upper.last(), p) <= 0) upper.removeAt(upper.size - 1); upper += p }
        return lower.dropLast(1) + upper.dropLast(1)
    }
}

/**
 * Power × speed test grid like LightBurn's material test: one layer per cell
 * (its own power and speed), labels on a light extra layer. [label] turns
 * text into outlines (the app uses the Android font engine).
 */
object MaterialTest {
    data class Spec(
        val powerFrom: Double = 20.0, val powerTo: Double = 100.0, val powerSteps: Int = 5,
        val speedFrom: Double = 300.0, val speedTo: Double = 3000.0, val speedSteps: Int = 5,
        val mode: LayerMode = LayerMode.FILL, val cellMm: Double = 10.0, val gapMm: Double = 4.0,
        val passes: Int = 1, val intervalMm: Double = 0.1,
        val originX: Double = 10.0, val originY: Double = 10.0,
    )

    private val palette = listOf(0xFF4FD8B4, 0xFF6CB6FF, 0xFFFFB45C, 0xFFB98CFF, 0xFFFF8AD8, 0xFF9BE15D)

    fun steps(from: Double, to: Double, n: Int): List<Double> =
        if (n <= 1) listOf(from) else (0 until n).map { from + (to - from) * it / (n - 1) }

    fun build(spec: Spec, label: (String, Double) -> List<Poly>): Document {
        require(spec.powerSteps in 1..10 && spec.speedSteps in 1..10) { "Höchstens 10 × 10 Felder" }
        require(spec.powerFrom in 0.0..100.0 && spec.powerTo in 0.0..100.0) { "Leistung 0–100 %" }
        require(spec.speedFrom in 10.0..6000.0 && spec.speedTo in 10.0..6000.0) { "Tempo 10–6000 mm/min" }
        val powers = steps(spec.powerFrom, spec.powerTo, spec.powerSteps)
        val speeds = steps(spec.speedFrom, spec.speedTo, spec.speedSteps)
        val labelH = 3.0
        val left = spec.originX + 14.0           // room for speed labels
        val top = spec.originY + labelH + 3.0     // room for power labels
        val pitch = spec.cellMm + spec.gapMm
        val text = Layer(name = "Beschriftung", color = 0xFFEEF3F8, mode = LayerMode.LINE, powerPct = 20.0, speed = 1500.0)
        val layers = mutableListOf<Layer>()
        val elements = mutableListOf<Element>()
        fun place(t: String, x: Double, y: Double) {
            val g = label(t, labelH)
            val b = boundsOf(g) ?: return
            elements += Element(layerId = text.id, kind = "Beschriftung", text = t,
                transform = Transform(x, y), paths = g.map { p -> p.map { Pt(it.x - b.minX, it.y - b.minY) } })
        }
        powers.forEachIndexed { i, p -> place("${p.toInt()}%", left + i * pitch, spec.originY) }
        speeds.forEachIndexed { j, s -> place("${s.toInt()}", spec.originX, top + j * pitch + spec.cellMm / 2 - labelH / 2) }
        for ((j, s) in speeds.withIndex()) for ((i, p) in powers.withIndex()) {
            val layer = Layer(name = "${p.toInt()} % · ${s.toInt()} mm/min", color = palette[(i + j) % palette.size],
                mode = spec.mode, powerPct = p, speed = s, passes = spec.passes, intervalMm = spec.intervalMm)
            layers += layer
            elements += Element(layerId = layer.id, kind = "Testfeld", transform = Transform(left + i * pitch, top + j * pitch),
                paths = listOf(Shapes.rect(spec.cellMm, spec.cellMm)))
        }
        // Labels first: they burn lightly before the test fields.
        return Document(title = "Materialtest", layers = listOf(text) + layers, elements = elements)
    }
}
