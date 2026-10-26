package de.millione.lumacut.core

import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class JobBuildException(message: String) : IllegalArgumentException(message)

/**
 * Turns a [Document] (work-area mm) into G-code for the LumaCut Pi / Marlin 2.1.
 * Same rules as the Windows app (lumacut_canvas/gcode.py):
 * - one `M3 I` for the whole job, every G1 carries F and S0..255;
 * - output coordinates are machine_x = 390 - x, machine_y = 30 + y (see [Work]); nothing, not even a
 *   laser-off overscan, ever leaves the work area (the safe zone is never entered);
 * - layers with zStep lower the focus between passes with
 *   `G91 / G0 Z-… F600 / G90` and return to focus height afterwards;
 * - fills and images run bidirectionally with laser-off run-up (G1 S0);
 * - homing, probing, focus and parking are done by the Pi.
 */
class MarlinWriter(private val appVersion: String = "dev") {

    private val out = StringBuilder()
    // Last commanded point in work coordinates. Unknown at the start: the head
    // can be anywhere (parked, after probing), so the first move is always a rapid.
    private var at: Pt? = null

    fun write(doc: Document): String {
        out.setLength(0)
        at = null
        val active = doc.layers.filter { it.output && it.visible }.map { it.id }.toSet()
        val content = doc.elements.filter { it.layerId in active }
        if (content.isEmpty()) throw JobBuildException("Nichts zu lasern: keine Elemente auf sichtbaren Ebenen")
        for (element in content) {
            val box = element.worldBounds() ?: continue
            if (!Work.contains(box)) throw JobBuildException("„${element.text ?: element.kind}“ ragt über die Arbeitsfläche hinaus")
            if (element.isImage && abs(element.transform.rotation) > 1e-6)
                throw JobBuildException("Gedrehte Bilder werden noch nicht unterstützt – Drehung auf 0° setzen")
        }
        for (layer in doc.layers.filter { it.id in active }) {
            if (layer.powerPct !in Limits.POWER || layer.speed !in Limits.SPEED || layer.passes !in Limits.PASSES)
                throw JobBuildException("Ungültige Werte auf Ebene „${layer.name}“")
            if (layer.zStepMm !in Limits.Z_STEP || layer.focusDropMm > Limits.MAX_FOCUS_DROP_MM + 1e-6)
                throw JobBuildException("Fokus-Absenkung zu groß auf „${layer.name}“ (%.2f mm > %.0f mm)".format(Locale.GERMANY, layer.focusDropMm, Limits.MAX_FOCUS_DROP_MM))
        }
        line("; LumaCut App $appVersion – ${doc.title.replace(Regex("[\\r\\n]"), " ")}")
        line("G21"); line("G90"); line("M5 I"); line("M3 I")
        for (layer in doc.layers.filter { it.id in active }) {
            val items = content.filter { it.layerId == layer.id }
            if (items.isEmpty()) continue
            line("; Ebene ${layer.name}")
            for (pass in 0 until layer.passes) {
                if (pass > 0 && layer.zStepMm > 0) { line("G91"); line("G0 Z%.3f F600".format(Locale.ROOT, -layer.zStepMm)); line("G90") }
                if (layer.passes > 1) line("; Durchgang ${pass + 1}/${layer.passes}")
                for (image in items.filter { it.isImage }) raster(image, layer)
                val vector = items.filter { !it.isImage }.flatMap { it.worldPaths() }
                when (layer.mode) {
                    LayerMode.LINE -> lines(vector, layer)
                    LayerMode.FILL -> fill(vector, layer)
                }
            }
            if (layer.zStepMm > 0 && layer.focusDropMm > 0) {   // back to focus height
                line("G91"); line("G0 Z%.3f F600".format(Locale.ROOT, layer.focusDropMm)); line("G90")
            }
        }
        line("M5 I"); line("M400")
        return out.toString()
    }

    private fun line(text: String) { out.append(text).append('\n') }
    private fun xy(p: Pt): String {
        val m = Work.toMachine(Pt(p.x.coerceIn(0.0, Work.WIDTH), p.y.coerceIn(0.0, Work.HEIGHT)))
        return "X%.3f Y%.3f".format(Locale.ROOT, m.x, m.y)
    }
    private fun s(pct: Double) = (pct.coerceIn(0.0, 100.0) / 100.0 * 255).roundToInt()
    private fun feed(layer: Layer) = layer.speed.coerceIn(Limits.SPEED).roundToInt()
    private fun clampX(x: Double) = x.coerceIn(0.0, Work.WIDTH)

    private fun rapid(p: Pt) {
        val last = at
        if (last == null || p.dist(last) > 1e-6) line("G0 ${xy(p)}")
        at = p
    }

    private fun burn(p: Pt, power: Int, layer: Layer) {
        line("G1 ${xy(p)} F${feed(layer)} S$power")
        at = p
    }

    private fun lines(paths: List<Poly>, layer: Layer) {
        val power = s(layer.powerPct)
        for (path in orderForCutting(paths, at ?: Pt(0.0, 0.0))) {
            rapid(path.first())
            for (p in path.drop(1)) burn(p, power, layer)
        }
    }

    private fun fill(paths: List<Poly>, layer: Layer) {
        val closed = paths.filter { it.isClosed() }
        if (closed.isEmpty()) return
        val power = s(layer.powerPct)
        for (seg in hatch(closed, layer.intervalMm.coerceIn(0.03, 2.0))) {
            scanLine(seg.first().y, listOf(Run(seg.first().x, seg.last().x, power)), layer)
        }
    }

    private class Run(val x0: Double, val x1: Double, val power: Int)

    /** One horizontal pass with laser-off run-up and run-out, kept inside the work area. */
    private fun scanLine(y: Double, runs: List<Run>, layer: Layer) {
        if (runs.isEmpty()) return
        val forward = runs.first().x1 >= runs.first().x0
        val dir = if (forward) 1.0 else -1.0
        val over = layer.overscanMm.coerceIn(0.0, 10.0)
        val start = clampX(runs.first().x0 - dir * over)
        val end = clampX(runs.last().x1 + dir * over)
        rapid(Pt(start, y))
        if (start != runs.first().x0) burn(Pt(runs.first().x0, y), 0, layer)
        for (run in runs) {
            if (abs(at!!.x - run.x0) > 1e-6) burn(Pt(run.x0, y), 0, layer)
            burn(Pt(run.x1, y), run.power, layer)
        }
        if (end != at!!.x) burn(Pt(end, y), 0, layer)
    }

    /**
     * Images: one row per interval, power from gray (dither/threshold give
     * on/off), equal neighbouring pixels merged into one G1. Row 0 of the
     * picture is the top on screen (machine Y 30), column 0 the left on screen
     * (large machine X); the picture is not mirrored.
     */
    private fun raster(element: Element, layer: Layer) {
        val raster = element.raster ?: return
        val gray = raster.gray()
        val box = element.worldBounds() ?: return
        val interval = layer.intervalMm.coerceIn(0.03, 2.0)
        val rows = max(1, (box.height / interval).toInt())
        val cols = max(1, (box.width / interval).toInt())
        val sampled = IntArray(rows * cols) { i ->
            val r = i / cols; val c = i % cols
            val px = min(raster.width - 1, ((c + 0.5) * raster.width / cols).toInt())
            val py = min(raster.height - 1, ((r + 0.5) * raster.height / rows).toInt())
            gray[py * raster.width + px].toInt() and 0xFF
        }
        val levels = ImageTools.binarize(ImageTools.adjust(sampled, cols, rows, element.adjust), cols, rows, element.imageMode)
        val maxS = s(layer.powerPct)
        val minS = s(layer.minPowerPct)
        val cell = box.width / cols
        for (r in 0 until rows) {
            val y = box.minY + (r + 0.5) * box.height / rows
            val runs = ArrayList<Run>()
            var c = 0
            while (c < cols) {
                val level = levels[r * cols + c]
                var e = c + 1
                while (e < cols && levels[r * cols + e] == level) e++
                val power = if (level >= 250) 0 else (minS + (maxS - minS) * (255 - level) / 255.0).roundToInt()
                runs += Run(box.minX + c * cell, box.minX + e * cell, power)
                c = e
            }
            val first = runs.indexOfFirst { it.power > 0 }
            if (first < 0) continue
            val last = runs.indexOfLast { it.power > 0 }
            val row = runs.subList(first, last + 1)
            val ordered = if (r % 2 == 0) row else row.reversed().map { Run(it.x1, it.x0, it.power) }
            scanLine(y, ordered, layer)
        }
    }
}
