package de.millione.lumacut.core

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class JobBuildException(message: String) : IllegalArgumentException(message)

/**
 * Turns a [Document] into G-code for the LumaCut Pi / Marlin 2.1:
 * - one `M3 I` for the whole job (M3/M5 make Marlin drain its planner);
 * - every G1 carries S0..255 (Marlin resets inline power on G0);
 * - fills and images run bidirectionally with laser-off overscan (G1 S0)
 *   so the head is at speed when burning starts; overscan may enter the
 *   safe zone because S0 never burns, cuts never do;
 * - homing, probing, focus and parking are done by the Pi, not here.
 */
class MarlinWriter(
    private val appVersion: String = "dev",
    /** True when the app shows X0/Y0 bottom-left: the image's top row is then at the largest Y. */
    private val imageTopAtMaxY: Boolean = false,
) {

    private val out = StringBuilder()
    private var at = Pt(0.0, 0.0)

    fun write(doc: Document): String {
        out.setLength(0)
        at = Pt(0.0, 0.0)
        val content = doc.elements.filter { doc.layer(it.layerId)?.output == true }
        if (content.isEmpty()) throw JobBuildException("Nichts zu lasern: keine Elemente auf aktiven Ebenen")
        for (element in content) {
            val box = element.worldBounds() ?: continue
            if (box.minX < Bed.SAFE - 1e-6 || box.minY < Bed.SAFE - 1e-6 || box.maxX > Bed.WIDTH + 1e-6 || box.maxY > Bed.HEIGHT + 1e-6)
                throw JobBuildException("„${element.text ?: element.kind}“ liegt nicht vollständig in der Arbeitsfläche (X/Y ab 30 mm)")
        }
        line("; LumaCut App $appVersion – ${doc.title.replace(Regex("[\\r\\n]"), " ")}")
        line("G21"); line("G90"); line("M5 I"); line("M3 I")
        for (layer in doc.layers.filter { it.output }) {
            val items = content.filter { it.layerId == layer.id }
            if (items.isEmpty()) continue
            line("; Ebene ${layer.name}")
            repeat(layer.passes.coerceIn(1, 50)) { pass ->
                if (layer.passes > 1) line("; Durchgang ${pass + 1}/${layer.passes}")
                for (image in items.filter { it.isImage }) raster(image, layer)
                val vector = items.filter { !it.isImage }.flatMap { it.worldPaths() }
                when (layer.mode) {
                    LayerMode.LINE -> lines(vector, layer)
                    LayerMode.FILL -> fill(vector, layer)
                }
            }
        }
        line("M5 I"); line("M400")
        return out.toString()
    }

    private fun line(text: String) { out.append(text).append('\n') }
    private fun f(v: Double) = "%.3f".format(java.util.Locale.ROOT, v)
    private fun s(pct: Double) = (pct.coerceIn(0.0, 100.0) / 100.0 * 255).roundToInt()
    private fun feed(layer: Layer) = layer.speed.coerceIn(10.0, 9000.0).roundToInt()
    private fun clampX(x: Double) = x.coerceIn(0.0, Bed.WIDTH)

    private fun rapid(p: Pt) {
        if (p.dist(at) > 1e-6) line("G0 X${f(p.x)} Y${f(p.y)}")
        at = p
    }

    private fun burn(p: Pt, power: Int, layer: Layer) {
        line("G1 X${f(p.x)} Y${f(p.y)} F${feed(layer)} S$power")
        at = p
    }

    private fun lines(paths: List<Poly>, layer: Layer) {
        val power = s(layer.powerPct)
        for (path in orderPaths(paths, at)) {
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

    /** One horizontal pass with laser-off run-up and run-out. Runs share direction. */
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
            if (kotlin.math.abs(at.x - run.x0) > 1e-6) burn(Pt(run.x0, y), 0, layer)
            burn(Pt(run.x1, y), run.power, layer)
        }
        if (end != at.x) burn(Pt(end, y), 0, layer)
    }

    /**
     * Images: one row per interval, power from gray (dither/threshold give
     * on/off), equal neighbouring pixels merged into one G1. Rotation of
     * images is not supported; only position and size apply.
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
        val levels = when (element.imageMode) {
            ImageMode.GRAYSCALE -> sampled
            ImageMode.THRESHOLD -> IntArray(sampled.size) { if (sampled[it] < 128) 0 else 255 }
            ImageMode.DITHER -> dither(sampled, cols, rows)
        }
        val maxS = s(layer.powerPct)
        val minS = s(layer.minPowerPct)
        val cell = box.width / cols
        for (r in 0 until rows) {
            val y = if (imageTopAtMaxY) box.maxY - (r + 0.5) * box.height / rows else box.minY + (r + 0.5) * box.height / rows
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

    private fun dither(src: IntArray, w: Int, h: Int): IntArray {
        val v = FloatArray(src.size) { src[it].toFloat() }
        val out = IntArray(src.size)
        for (y in 0 until h) for (x in 0 until w) {
            val i = y * w + x
            val q = if (v[i] < 128f) 0 else 255
            out[i] = q
            val err = v[i] - q
            if (x + 1 < w) v[i + 1] += err * 7 / 16
            if (y + 1 < h) {
                if (x > 0) v[i + w - 1] += err * 3 / 16
                v[i + w] += err * 5 / 16
                if (x + 1 < w) v[i + w + 1] += err * 1 / 16
            }
        }
        return out
    }
}
