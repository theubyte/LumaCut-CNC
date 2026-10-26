package de.millione.lumacut.app.editor

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.FileKind
import de.millione.lumacut.core.FileKinds
import de.millione.lumacut.core.ImportFormats
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Transform
import de.millione.lumacut.core.Work
import de.millione.lumacut.core.boundsOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.max
import kotlin.math.min

private const val SUPPORTED = "SVG, DXF, xTool (.xcs), LightBurn (.lbrn), HPGL, PDF/Illustrator, Bilder, LumaCut-Projekt"

/** One entry point for every file: the type is recognised from the content, not from the name. */
suspend fun importFile(context: Context, uri: Uri, editor: EditorViewModel) {
    val bytes = withContext(Dispatchers.IO) { runCatching { context.contentResolver.openInputStream(uri)?.use { it.readBytes() } }.getOrNull() }
    if (bytes == null || bytes.isEmpty()) { editor.notify("Die Datei lässt sich nicht lesen – bitte noch einmal auswählen.", true); return }
    try {
        when (val kind = FileKinds.detect(bytes)) {
            FileKind.IMAGE -> importImage(context, uri, editor)
            FileKind.PDF -> importPdf(context, uri, editor)
            FileKind.PROJECT -> editor.openJson(String(bytes, Charsets.UTF_8))
            FileKind.UNKNOWN -> editor.notify("Dieses Format kenne ich nicht. Unterstützt: $SUPPORTED.", true)
            else -> importVector(kind, bytes, editor)
        }
    } catch (e: kotlinx.coroutines.CancellationException) {
        throw e
    } catch (e: Exception) {
        editor.notify(e.message ?: "Import fehlgeschlagen", true)
    }
}

private suspend fun importImage(context: Context, uri: Uri, editor: EditorViewModel) {
    val (bitmap, original, dpi) = withContext(Dispatchers.Default) {
        Triple(Images.decode(context, uri), Images.originalSize(context, uri), Images.dpi(context, uri))
    }
    if (bitmap == null) { editor.notify("Dieses Bildformat kann das Tablet nicht lesen – als PNG oder JPG speichern.", true); return }
    // With a resolution in the file the picture keeps its print size; otherwise 80 mm wide.
    val width = if (dpi != null && original != null) original.first / dpi * 25.4 else 80.0
    placeBitmap(editor, bitmap, width, if (dpi != null) "%.0f dpi aus der Datei".format(dpi) else null)
}

private suspend fun importPdf(context: Context, uri: Uri, editor: EditorViewModel) {
    val page = withContext(Dispatchers.IO) {
        val fd = context.contentResolver.openFileDescriptor(uri, "r") ?: return@withContext null
        try {
            val renderer = PdfRenderer(fd)
            try {
                if (renderer.pageCount == 0) return@withContext null
                val p = renderer.openPage(0)
                try {
                    val k = min(2000f / max(p.width, p.height), 8f)
                    val bmp = Bitmap.createBitmap(max(1, (p.width * k).toInt()), max(1, (p.height * k).toInt()), Bitmap.Config.ARGB_8888)
                    bmp.eraseColor(Color.WHITE)
                    p.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                    bmp to p.width / 72.0 * 25.4
                } finally { p.close() }
            } finally { renderer.close() }
        } catch (e: Exception) {
            null
        } finally { fd.close() }
    }
    if (page == null) { editor.notify("Das PDF lässt sich nicht lesen (verschlüsselt oder beschädigt). Als Bild oder SVG exportieren.", true); return }
    placeBitmap(editor, page.first, page.second, "erste Seite")
}

private suspend fun importVector(kind: FileKind, bytes: ByteArray, editor: EditorViewModel) {
    val result = withContext(Dispatchers.Default) { ImportFormats.parseVector(kind, bytes) }
    var all: Box? = boundsOf(result.polys)
    for (img in result.images) all = img.box.union(all)
    val box = all ?: run { editor.notify("Nichts Lasertaugliches gefunden.", true); return }
    // one common transform: centred in the work area, scaled down when too big
    val k = minOf(1.0, (Work.WIDTH - 10) / max(box.width, 1e-9), (Work.HEIGHT - 10) / max(box.height, 1e-9))
    val cx = Work.center.x; val cy = Work.center.y
    fun map(p: Pt) = Pt(cx + (p.x - box.center.x) * k, cy + (p.y - box.center.y) * k)
    if (result.polys.isNotEmpty()) editor.addVector(kind.label, result.polys.map { poly -> poly.map(::map) })
    var pictures = 0
    for (img in result.images) {
        val bmp = withContext(Dispatchers.Default) { BitmapFactory.decodeByteArray(img.bytes, 0, img.bytes.size) } ?: continue
        val a = map(Pt(img.box.minX, img.box.minY)); val b = map(Pt(img.box.maxX, img.box.maxY))
        val raster = withContext(Dispatchers.Default) { Images.toRaster(bmp) }
        editor.addElement(Element(layerId = editor.layerIdByName("Gravieren"), kind = "Bild", transform = Transform(a.x, a.y),
            raster = raster, imageWidthMm = b.x - a.x, imageHeightMm = b.y - a.y))
        pictures++
    }
    val parts = buildList {
        if (result.polys.isNotEmpty()) add("${result.polys.size} Pfade")
        if (pictures > 0) add("$pictures Bild" + if (pictures > 1) "er" else "")
    }
    val shrink = if (k < 1.0) " · verkleinert, damit es in den Arbeitsbereich passt" else ""
    editor.notify("${kind.label} importiert: ${parts.joinToString(", ")}$shrink" + (result.skippedSentence()?.let { ". $it" } ?: ""))
}

/** Puts a picture, [widthMm] wide (scaled down to fit), in the middle of the work area on the engraving layer. */
private suspend fun placeBitmap(editor: EditorViewModel, bitmap: Bitmap, widthMm: Double, note: String?) {
    val raster = withContext(Dispatchers.Default) { Images.toRaster(bitmap) }
    var w = widthMm
    var h = w * raster.height / raster.width
    val k = minOf(1.0, (Work.WIDTH - 10) / w, (Work.HEIGHT - 10) / h)
    w *= k; h *= k
    editor.addElement(Element(layerId = editor.layerIdByName("Gravieren"), kind = "Bild",
        transform = Transform(Work.center.x - w / 2, Work.center.y - h / 2), raster = raster, imageWidthMm = w, imageHeightMm = h))
    editor.notify("Bild eingefügt: %.0f × %.0f mm".format(w, h) + (note?.let { " ($it)" } ?: ""))
}
