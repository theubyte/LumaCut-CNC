package de.millione.lumacut.app.editor

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.Typeface
import android.net.Uri
import de.millione.lumacut.core.Bed
import de.millione.lumacut.core.Homography
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Raster
import de.millione.lumacut.core.boundsOf
import de.millione.lumacut.core.simplify
import kotlin.math.max
import kotlin.math.roundToInt

object Fonts {
    val families = listOf("sans-serif" to "Sans", "serif" to "Serif", "monospace" to "Mono",
                          "sans-serif-condensed" to "Schmal", "cursive" to "Schreibschrift")
}

/** Text outlines from the Android font engine, flattened to polylines in mm (y down, origin top-left). */
object TextPaths {
    private const val SIZE = 200f   // render large, then scale: keeps curves smooth

    fun build(text: String, heightMm: Double, bold: Boolean, family: String): List<Poly> {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = SIZE
            typeface = Typeface.create(family, if (bold) Typeface.BOLD else Typeface.NORMAL)
        }
        val k = heightMm / SIZE
        val lines = text.lines()
        val spacing = paint.fontSpacing
        val out = ArrayList<Poly>()
        for ((i, line) in lines.withIndex()) {
            if (line.isBlank()) continue
            val path = Path()
            paint.getTextPath(line, 0, line.length, 0f, i * spacing, path)
            val pm = PathMeasure(path, false)
            val pos = FloatArray(2)
            do {
                val len = pm.length
                if (len <= 0f) continue
                val n = max(4, (len / 1.2f).toInt())
                val poly = ArrayList<Pt>(n + 2)
                for (s in 0..n) {
                    pm.getPosTan(len * s / n, pos, null)
                    poly += Pt(pos[0] * k, pos[1] * k)
                }
                if (pm.isClosed && poly.first() != poly.last()) poly += poly.first()
                out += simplify(poly, 0.02)
            } while (pm.nextContour())
        }
        return out
    }
}

/** Puts imported geometry the way it looks on screen: with X0/Y0 bottom-left the y axis is flipped. */
fun orientForScreen(polys: List<Poly>, originBottom: Boolean): List<Poly> {
    if (!originBottom) return polys
    val b = boundsOf(polys) ?: return polys
    return polys.map { poly -> poly.map { Pt(it.x, b.maxY - (it.y - b.minY)) } }
}

/** Moves geometry so its centre sits in the middle of the work area, scaled down if it does not fit. */
fun placeInWorkArea(polys: List<Poly>, maxW: Double = Bed.WIDTH - Bed.SAFE - 10, maxH: Double = Bed.HEIGHT - Bed.SAFE - 10): Pair<List<Poly>, Boolean> {
    val b = boundsOf(polys) ?: return polys to false
    val k = minOf(1.0, maxW / maxOf(b.width, 1e-9), maxH / maxOf(b.height, 1e-9))
    val cx = (Bed.SAFE + Bed.WIDTH) / 2; val cy = (Bed.SAFE + Bed.HEIGHT) / 2
    return polys.map { poly -> poly.map { Pt(cx + (it.x - b.center.x) * k, cy + (it.y - b.center.y) * k) } } to (k < 1.0)
}

object Images {
    /** Decodes [uri] with at most [maxSide] px on the long side. */
    fun decode(context: Context, uri: Uri, maxSide: Int = 1400): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0) return null
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / sample > maxSide * 2) sample *= 2
        val bmp = context.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: return null
        val scale = minOf(1.0, maxSide.toDouble() / max(bmp.width, bmp.height))
        return if (scale < 1.0) Bitmap.createScaledBitmap(bmp, (bmp.width * scale).roundToInt(), (bmp.height * scale).roundToInt(), true) else bmp
    }

    /** Luminance with transparency treated as white (= laser off). */
    fun toRaster(bmp: Bitmap, maxSide: Int = 1000): Raster {
        val scale = minOf(1.0, maxSide.toDouble() / max(bmp.width, bmp.height))
        val src = if (scale < 1.0) Bitmap.createScaledBitmap(bmp, max(1, (bmp.width * scale).roundToInt()), max(1, (bmp.height * scale).roundToInt()), true) else bmp
        val w = src.width; val h = src.height
        val px = IntArray(w * h); src.getPixels(px, 0, w, 0, 0, w, h)
        val gray = ByteArray(w * h) { i ->
            val c = px[i]; val a = Color.alpha(c) / 255.0
            val l = 0.2126 * Color.red(c) + 0.7152 * Color.green(c) + 0.0722 * Color.blue(c)
            (l * a + 255 * (1 - a)).roundToInt().coerceIn(0, 255).toByte()
        }
        return Raster.of(w, h, gray)
    }

    fun toBitmap(r: Raster): Bitmap {
        val g = r.gray()
        val px = IntArray(r.width * r.height) { val v = g[it].toInt() and 0xFF; Color.argb(255, v, v, v) }
        return Bitmap.createBitmap(px, r.width, r.height, Bitmap.Config.ARGB_8888)
    }
}

object CameraRectify {
    /** Photo + four photo points of known machine positions → bed image (2 px/mm), drawn as in the editor. */
    fun rectify(photo: Bitmap, photoPoints: List<Pt>, machinePoints: List<Pt>, originBottom: Boolean): Bitmap {
        val machineToPhoto = Homography.fit(machinePoints, photoPoints)
        val w = photo.width; val h = photo.height
        val px = IntArray(w * h); photo.getPixels(px, 0, w, 0, 0, w, h)
        val (out, ow, oh) = Homography.rectify(px, w, h, machineToPhoto, 2.0)
        val bmp = Bitmap.createBitmap(out, ow, oh, Bitmap.Config.ARGB_8888)
        if (!originBottom) return bmp
        val m = android.graphics.Matrix().apply { preScale(1f, -1f) }
        return Bitmap.createBitmap(bmp, 0, 0, ow, oh, m, false)
    }
}
