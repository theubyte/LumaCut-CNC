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
import de.millione.lumacut.core.Homography
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Raster
import de.millione.lumacut.core.Work
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

/** Moves geometry so its centre sits in the middle of the work area, scaled down if it does not fit. */
fun placeInWorkArea(polys: List<Poly>, maxW: Double = Work.WIDTH - 10, maxH: Double = Work.HEIGHT - 10): Pair<List<Poly>, Boolean> {
    val b = boundsOf(polys) ?: return polys to false
    val k = minOf(1.0, maxW / maxOf(b.width, 1e-9), maxH / maxOf(b.height, 1e-9))
    val cx = Work.center.x; val cy = Work.center.y
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

    /** Pixel size of the file before any downscaling (for its print size). */
    fun originalSize(context: Context, uri: Uri): Pair<Int, Int>? {
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, o) }
        return if (o.outWidth > 0 && o.outHeight > 0) o.outWidth to o.outHeight else null
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

    /**
     * Resolution stored in the file (PNG pHYs, JPEG JFIF/EXIF) in dots per
     * inch, or null when the file does not say (or claims the 72/96 dpi
     * screen default, which is never a print size).
     */
    fun dpi(context: Context, uri: Uri): Double? = runCatching {
        val head = context.contentResolver.openInputStream(uri)?.use { readHead(it, 64 * 1024) } ?: return null
        val v = pngDpi(head) ?: jpegDpi(head)
        v?.takeIf { it in 100.0..2400.0 && it != 96.0 }
    }.getOrNull()

    private fun pngDpi(b: ByteArray): Double? {
        if (b.size < 33 || b[1] != 'P'.code.toByte() || b[2] != 'N'.code.toByte()) return null
        var i = 8
        while (i + 8 < b.size) {
            val len = u32(b, i); val type = String(b, i + 4, 4, Charsets.US_ASCII)
            if (type == "pHYs" && i + 17 <= b.size) {
                val ppm = u32(b, i + 8).toDouble(); val unit = b[i + 16].toInt()
                return if (unit == 1) ppm * 0.0254 else null
            }
            if (type == "IDAT") return null
            i += 12 + len.toInt()
        }
        return null
    }

    private fun jpegDpi(b: ByteArray): Double? {
        if (b.size < 20 || (b[0].toInt() and 0xFF) != 0xFF || (b[1].toInt() and 0xFF) != 0xD8) return null
        // JFIF APP0: "JFIF", version, units (1 = dpi, 2 = dpcm), Xdensity
        if (String(b, 6, 4, Charsets.US_ASCII) == "JFIF") {
            val units = b[13].toInt(); val x = ((b[14].toInt() and 0xFF) shl 8) or (b[15].toInt() and 0xFF)
            return when (units) { 1 -> x.toDouble(); 2 -> x * 2.54; else -> null }
        }
        return runCatching {
            val exif = android.media.ExifInterface(b.inputStream())
            val x = exif.getAttributeDouble(android.media.ExifInterface.TAG_X_RESOLUTION, 0.0)
            val unit = exif.getAttributeInt(android.media.ExifInterface.TAG_RESOLUTION_UNIT, 2)
            if (x <= 0) null else if (unit == 3) x * 2.54 else x
        }.getOrNull()
    }

    private fun u32(b: ByteArray, i: Int): Long =
        ((b[i].toLong() and 0xFF) shl 24) or ((b[i + 1].toLong() and 0xFF) shl 16) or ((b[i + 2].toLong() and 0xFF) shl 8) or (b[i + 3].toLong() and 0xFF)

    fun toBitmap(r: Raster): Bitmap {
        val g = r.gray()
        val px = IntArray(r.width * r.height) { val v = g[it].toInt() and 0xFF; Color.argb(255, v, v, v) }
        return Bitmap.createBitmap(px, r.width, r.height, Bitmap.Config.ARGB_8888)
    }
}

object CameraRectify {
    /** Photo + four photo points of known work-area positions → work-area image (2 px/mm), as in the editor. */
    fun rectify(photo: Bitmap, photoPoints: List<Pt>, workPoints: List<Pt>): Bitmap {
        val workToPhoto = Homography.fit(workPoints, photoPoints)
        val w = photo.width; val h = photo.height
        val px = IntArray(w * h); photo.getPixels(px, 0, w, 0, 0, w, h)
        val (out, ow, oh) = Homography.rectify(px, w, h, workToPhoto, 2.0)
        return Bitmap.createBitmap(out, ow, oh, Bitmap.Config.ARGB_8888)
    }
}

private fun readHead(input: java.io.InputStream, max: Int): ByteArray {
    val buf = ByteArray(max)
    var n = 0
    while (n < max) { val r = input.read(buf, n, max - n); if (r < 0) break; n += r }
    return buf.copyOf(n)
}
