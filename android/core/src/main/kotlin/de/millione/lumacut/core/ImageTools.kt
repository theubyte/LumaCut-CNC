package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlin.math.roundToInt

/** Corrections for photo engraving; all 0 / false = untouched picture. */
@Serializable
data class ImageAdjust(val brightness: Int = 0, val contrast: Int = 0, val sharpen: Int = 0, val invert: Boolean = false) {
    val isDefault get() = brightness == 0 && contrast == 0 && sharpen == 0 && !invert
}

object ImageTools {
    /** Gray values 0..255 (0 = black = full power) after sharpen, contrast, brightness and invert. */
    fun adjust(gray: IntArray, w: Int, h: Int, a: ImageAdjust): IntArray {
        if (a.isDefault) return gray
        var v = gray
        if (a.sharpen > 0) v = sharpen(v, w, h, a.sharpen / 100.0)
        val factor = (100 + a.contrast.coerceIn(-100, 100)) / 100.0
        val shift = a.brightness.coerceIn(-100, 100) * 2.55
        return IntArray(v.size) { i ->
            var x = (v[i] - 128) * factor + 128 + shift
            x = x.coerceIn(0.0, 255.0)
            (if (a.invert) 255 - x else x).roundToInt().coerceIn(0, 255)
        }
    }

    /** Unsharp mask with a 3x3 box blur; [amount] 0..1 (up to 2x the detail). */
    fun sharpen(src: IntArray, w: Int, h: Int, amount: Double): IntArray {
        val out = IntArray(src.size)
        for (y in 0 until h) for (x in 0 until w) {
            var sum = 0; var n = 0
            for (dy in -1..1) for (dx in -1..1) {
                val xx = x + dx; val yy = y + dy
                if (xx in 0 until w && yy in 0 until h) { sum += src[yy * w + xx]; n++ }
            }
            val blur = sum.toDouble() / n
            out[y * w + x] = (src[y * w + x] + (src[y * w + x] - blur) * amount * 2).roundToInt().coerceIn(0, 255)
        }
        return out
    }

    /** Error-diffusion kernels: (dx, dy, weight) and the divisor. */
    private class Kernel(val taps: List<Triple<Int, Int, Int>>, val div: Int)

    private val FLOYD = Kernel(listOf(Triple(1, 0, 7), Triple(-1, 1, 3), Triple(0, 1, 5), Triple(1, 1, 1)), 16)
    private val JARVIS = Kernel(listOf(
        Triple(1, 0, 7), Triple(2, 0, 5),
        Triple(-2, 1, 3), Triple(-1, 1, 5), Triple(0, 1, 7), Triple(1, 1, 5), Triple(2, 1, 3),
        Triple(-2, 2, 1), Triple(-1, 2, 3), Triple(0, 2, 5), Triple(1, 2, 3), Triple(2, 2, 1)), 48)
    private val STUCKI = Kernel(listOf(
        Triple(1, 0, 8), Triple(2, 0, 4),
        Triple(-2, 1, 2), Triple(-1, 1, 4), Triple(0, 1, 8), Triple(1, 1, 4), Triple(2, 1, 2),
        Triple(-2, 2, 1), Triple(-1, 2, 2), Triple(0, 2, 4), Triple(1, 2, 2), Triple(2, 2, 1)), 42)

    /** Black/white (0/255) from gray values by threshold or error diffusion. */
    fun binarize(src: IntArray, w: Int, h: Int, mode: ImageMode): IntArray = when (mode) {
        ImageMode.GRAYSCALE -> src
        ImageMode.THRESHOLD -> IntArray(src.size) { if (src[it] < 128) 0 else 255 }
        ImageMode.DITHER -> diffuse(src, w, h, FLOYD)
        ImageMode.DITHER_JARVIS -> diffuse(src, w, h, JARVIS)
        ImageMode.DITHER_STUCKI -> diffuse(src, w, h, STUCKI)
    }

    private fun diffuse(src: IntArray, w: Int, h: Int, k: Kernel): IntArray {
        val v = FloatArray(src.size) { src[it].toFloat() }
        val out = IntArray(src.size)
        for (y in 0 until h) for (x in 0 until w) {
            val i = y * w + x
            val q = if (v[i] < 128f) 0 else 255
            out[i] = q
            val err = v[i] - q
            for ((dx, dy, wt) in k.taps) {
                val xx = x + dx; val yy = y + dy
                if (xx in 0 until w && yy < h) v[yy * w + xx] += err * wt / k.div
            }
        }
        return out
    }
}
