package de.millione.lumacut.app.editor

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.ui.Banner
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.Contour
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.ImageAdjust
import de.millione.lumacut.core.ImageMode
import de.millione.lumacut.core.ImageTools
import de.millione.lumacut.core.Mask
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.QrCode
import de.millione.lumacut.core.Work
import de.millione.lumacut.core.boundsOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
private fun SliderRow(label: String, value: Float, range: ClosedFloatingPointRange<Float>, unit: String, onChange: (Float) -> Unit) {
    Column {
        Row {
            Text(label, style = LcTypography.bodyMedium, modifier = Modifier.weight(1f))
            Text("%.1f %s".format(value, unit), style = LcTypography.bodyMedium, color = Lc.muted)
        }
        Slider(value, onChange, valueRange = range, colors = SliderDefaults.colors(thumbColor = Lc.accent, activeTrackColor = Lc.accent))
    }
}

/* ---------- contour / sticker / offset ---------- */

private enum class ContourMode { EDGE, STICKER, OFFSET }

/** Motif mask of a picture element at [ppm] pixels per millimetre (origin = top-left of its box). */
private fun imageMask(e: Element, ppm: Double, tolerance: Int): Pair<Mask, Box>? {
    val raster = e.raster ?: return null
    val box = e.worldBounds() ?: return null
    val gray = raster.gray()
    val argb = IntArray(raster.width * raster.height) { val g = gray[it].toInt() and 0xFF; (0xFF shl 24) or (g shl 16) or (g shl 8) or g }
    return Mask.fromArgb(argb, raster.width, raster.height, box.width, box.height, ppm, tolerance) to box
}

/**
 * Cut outline for the selection: around a picture ("am Rand entlang" or sticker with margin), or an
 * offset outline (outwards / inwards) of vector shapes and text. The outline lands on the cutting layer.
 */
@Composable
fun ContourDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    val sel = doc.elements.filter { it.id in selected }
    val image = sel.singleOrNull()?.takeIf { it.isImage }
    val scope = rememberCoroutineScope()
    var mode by remember { mutableStateOf(if (image != null) ContourMode.STICKER else ContourMode.OFFSET) }
    var distance by remember { mutableStateOf(3f) }
    var inset by remember { mutableStateOf(true) }
    var tolerance by remember { mutableStateOf(40f) }
    var join by remember { mutableStateOf(false) }
    var offset by remember { mutableStateOf(2f) }
    var outlineOnly by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf<List<Poly>?>(null) }
    var working by remember { mutableStateOf(true) }

    fun compute(ppm: Double): List<Poly> {
        if (image != null) {
            val (mask, box) = imageMask(image, ppm, tolerance.toInt()) ?: return emptyList()
            val polys = if (mode == ContourMode.EDGE) Contour.edge(mask, if (inset) 0.2 else 0.0) else Contour.sticker(mask, distance.toDouble(), join)
            return polys.map { poly -> poly.map { Pt(it.x + box.minX, it.y + box.minY) } }
        }
        return Contour.fromPolys(sel.flatMap { it.worldPaths() }, offset.toDouble(), ppm)
    }

    LaunchedEffect(mode, distance, inset, tolerance, join, offset) {
        delay(200)
        working = true
        preview = try { withContext(Dispatchers.Default) { compute(3.0) } } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { null }
        working = false
    }

    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text(if (image != null) "Kontur zum Ausschneiden" else "Umriss", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (image != null) {
                    Segmented(listOf(ContourMode.STICKER to "Sticker (Rand außen)", ContourMode.EDGE to "Am Rand entlang"), mode, { mode = it })
                    if (mode == ContourMode.STICKER) {
                        SliderRow("Abstand nach außen", distance, 1f..10f, "mm") { distance = it }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(join, { join = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk))
                            SmallText("Teile zu einer Kontur verbinden")
                        }
                    } else Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(inset, { inset = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk))
                        SmallText("0,2 mm nach innen (Schnitt nimmt nichts vom Motiv)")
                    }
                    SliderRow("Hintergrund-Toleranz", tolerance, 5f..120f, "") { tolerance = it }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(outlineOnly, { outlineOnly = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk))
                        SmallText("Nur Kontur (Bild entfernen)")
                    }
                } else {
                    SliderRow("Abstand (− = nach innen)", offset, -10f..10f, "mm") { offset = it }
                }
                ContourPreview(sel, preview, working)
                if (!working && preview.isNullOrEmpty()) Banner("Keine Kontur gefunden – Toleranz oder Abstand ändern.", Lc.warn)
                SmallText("Die Kontur liegt auf der Ebene „Schneiden“ und wird zuletzt gelasert. Sie bleibt im Arbeitsbereich.", Lc.faint)
            }
        },
        confirmButton = {
            LcButton("Übernehmen", {
                scope.launch {
                    val polys = withContext(Dispatchers.Default) { compute(Contour.DEFAULT_PX_PER_MM) }
                    if (polys.isEmpty()) editor.notify("Keine Kontur gefunden – Toleranz oder Abstand ändern.", true)
                    else if (image != null) editor.addContour(image, polys, outlineOnly)
                    else editor.addContour(null, polys, false)
                    onDismiss()
                }
            }, kind = BtnKind.PRIMARY, enabled = !working && !preview.isNullOrEmpty())
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

@Composable
private fun ContourPreview(source: List<Element>, contour: List<Poly>?, working: Boolean) {
    val bitmap = remember(source.firstOrNull()?.id) {
        source.singleOrNull()?.takeIf { it.isImage }?.raster?.let { Images.toBitmap(it).asImageBitmap() }
    }
    Canvas(Modifier.fillMaxWidth().height(220.dp).clip(RoundedCornerShape(16.dp)).background(Lc.sheet).border(1.dp, Lc.line, RoundedCornerShape(16.dp))) {
        val src = source.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) } ?: return@Canvas
        val view = boundsOf(contour.orEmpty())?.union(src) ?: src
        val pad = 14f
        val k = minOf((size.width - 2 * pad) / view.width.toFloat(), (size.height - 2 * pad) / view.height.toFloat())
        val ox = (size.width - view.width.toFloat() * k) / 2; val oy = (size.height - view.height.toFloat() * k) / 2
        fun at(p: Pt) = Offset(ox + (p.x - view.minX).toFloat() * k, oy + (p.y - view.minY).toFloat() * k)
        if (bitmap != null) {
            val a = at(Pt(src.minX, src.minY))
            drawImage(bitmap, dstOffset = IntOffset(a.x.toInt(), a.y.toInt()), dstSize = IntSize((src.width * k).toInt(), (src.height * k).toInt()))
        } else {
            for (e in source) for (poly in e.worldPaths()) {
                val path = Path()
                poly.forEachIndexed { i, p -> val o = at(p); if (i == 0) path.moveTo(o.x, o.y) else path.lineTo(o.x, o.y) }
                drawPath(path, Lc.muted, style = Stroke(1.5f))
            }
        }
        for (poly in contour.orEmpty()) {
            val path = Path()
            poly.forEachIndexed { i, p -> val o = at(p); if (i == 0) path.moveTo(o.x, o.y) else path.lineTo(o.x, o.y) }
            drawPath(path, Lc.cut, style = Stroke(2.5f))
        }
        if (working) drawRect(Color(0x66000000))
    }
}

/* ---------- photo engraving ---------- */

/** Brightness, contrast, sharpness, invert and the dithering method, with a live preview of what gets lasered. */
@Composable
fun ImageAdjustDialog(editor: EditorViewModel, e: Element, onDismiss: () -> Unit) {
    var mode by remember { mutableStateOf(e.imageMode) }
    var brightness by remember { mutableStateOf(e.adjust.brightness.toFloat()) }
    var contrast by remember { mutableStateOf(e.adjust.contrast.toFloat()) }
    var sharpen by remember { mutableStateOf(e.adjust.sharpen.toFloat()) }
    var invert by remember { mutableStateOf(e.adjust.invert) }
    var preview by remember { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    val raster = e.raster

    LaunchedEffect(mode, brightness, contrast, sharpen, invert) {
        if (raster == null) return@LaunchedEffect
        delay(120)
        preview = withContext(Dispatchers.Default) {
            val gray = raster.gray()
            val k = maxOf(1, raster.width / 320)
            val w = raster.width / k; val h = raster.height / k
            val small = IntArray(w * h) { gray[(it / w * k) * raster.width + (it % w) * k].toInt() and 0xFF }
            val levels = ImageTools.binarize(ImageTools.adjust(small, w, h, ImageAdjust(brightness.toInt(), contrast.toInt(), sharpen.toInt(), invert)), w, h, mode)
            val px = IntArray(w * h) { val g = levels[it]; (0xFF shl 24) or (g shl 16) or (g shl 8) or g }
            android.graphics.Bitmap.createBitmap(px, w, h, android.graphics.Bitmap.Config.ARGB_8888).asImageBitmap()
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Bild anpassen", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                preview?.let { Image(it, null, Modifier.fillMaxWidth().height(200.dp).clip(RoundedCornerShape(12.dp)).background(Color.White), contentScale = ContentScale.Fit) }
                Segmented(listOf(ImageMode.GRAYSCALE to "Graustufen", ImageMode.DITHER to "Floyd-Steinberg", ImageMode.THRESHOLD to "S/W"), mode, { mode = it })
                Segmented(listOf(ImageMode.DITHER_JARVIS to "Jarvis", ImageMode.DITHER_STUCKI to "Stucki"), mode, { mode = it })
                SliderRow("Helligkeit", brightness, -100f..100f, "") { brightness = it }
                SliderRow("Kontrast", contrast, -100f..100f, "") { contrast = it }
                SliderRow("Schärfe", sharpen, 0f..100f, "") { sharpen = it }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(invert, { invert = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk))
                    SmallText("Invertieren (hell wird gelasert)")
                }
            }
        },
        confirmButton = {
            LcButton("Übernehmen", {
                editor.updateElement(e.id) { it.copy(imageMode = mode, adjust = ImageAdjust(brightness.toInt(), contrast.toInt(), sharpen.toInt(), invert)) }
                onDismiss()
            }, kind = BtnKind.PRIMARY)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

/* ---------- QR code ---------- */

@Composable
fun QrDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var text by remember { mutableStateOf("https://") }
    var module by remember { mutableStateOf("1.0") }
    val mod = module.replace(',', '.').toDoubleOrNull()
    val code = remember(text) { runCatching { QrCode.encode(text) } }
    val qr = code.getOrNull()
    val sizeMm = if (qr != null && mod != null) qr.size * mod else null
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("QR-Code", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                TextInput("Text oder Adresse", text, { text = it }, Modifier.fillMaxWidth())
                NumberField("Kantenlänge eines Punktes", module, { module = it }, Modifier.fillMaxWidth(), "mm")
                code.exceptionOrNull()?.let { Banner(it.message ?: "Kein QR-Code möglich", Lc.bad) }
                if (qr != null && sizeMm != null) SmallText("%d × %d Punkte = %.1f × %.1f mm".format(qr.size, qr.size, sizeMm, sizeMm))
                if (mod != null && mod < QrCode.MIN_MODULE_MM) Banner("Punkte unter %.1f mm lassen sich oft nicht mehr lesen – größer wählen.".format(QrCode.MIN_MODULE_MM))
                if (sizeMm != null && (sizeMm > Work.WIDTH || sizeMm > Work.HEIGHT)) Banner("Zu groß für den Arbeitsbereich.", Lc.bad)
                SmallText("Beim Gravieren einen hellen Rand von mindestens 4 Punkten um den Code lassen. Gelasert werden die dunklen Punkte.", Lc.faint)
            }
        },
        confirmButton = {
            LcButton("Einfügen", {
                if (qr != null && mod != null) { editor.addShape("QR-Code", qr.toPolys(mod), "Gravieren"); onDismiss() }
            }, kind = BtnKind.PRIMARY, enabled = qr != null && mod != null && mod in 0.2..10.0 && (sizeMm ?: 1e9) <= Work.HEIGHT)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

/* ---------- grid copies ---------- */

@Composable
fun GridDialog(editor: EditorViewModel, onDismiss: () -> Unit) {
    var nx by remember { mutableStateOf("3") }
    var ny by remember { mutableStateOf("2") }
    var gapX by remember { mutableStateOf("5") }
    var gapY by remember { mutableStateOf("5") }
    fun d(s: String) = s.replace(',', '.').toDoubleOrNull()
    val valid = nx.toIntOrNull()?.let { it in 1..50 } == true && ny.toIntOrNull()?.let { it in 1..50 } == true &&
        d(gapX)?.let { it in 0.0..200.0 } == true && d(gapY)?.let { it in 0.0..200.0 } == true
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Vervielfältigen", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Anzahl nach rechts", nx, { nx = it }, Modifier.weight(1f))
                    NumberField("Anzahl nach unten", ny, { ny = it }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Abstand rechts", gapX, { gapX = it }, Modifier.weight(1f), "mm")
                    NumberField("Abstand unten", gapY, { gapY = it }, Modifier.weight(1f), "mm")
                }
                SmallText("Kopien, die nicht mehr in den Arbeitsbereich passen, werden weggelassen und gemeldet.", Lc.faint)
            }
        },
        confirmButton = {
            LcButton("Vervielfältigen", {
                val skipped = editor.duplicateGrid(nx.toInt(), ny.toInt(), d(gapX)!!, d(gapY)!!)
                editor.notify(if (skipped > 0) "$skipped Kopien passen nicht in den Arbeitsbereich und fehlen" else "Kopien angelegt", skipped > 0)
                onDismiss()
            }, kind = BtnKind.PRIMARY, enabled = valid)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

/* ---------- import that does not fit ---------- */

/** Vector imports keep their size: when parts do not fit even when arranged, the operator decides. */
@Composable
fun ImportFitDialog(p: PendingImport, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Passt nicht in den Arbeitsbereich", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${p.kindLabel}: ${p.total - p.fitting} von ${p.total} Teilen sind auch nebeneinander angeordnet zu groß für 360 × 340 mm.", style = LcTypography.bodyLarge)
                SmallText("Funktionsteile (Steckmaße, Flex-Muster) sollten nicht verkleinert werden.")
                LcButton("Nur Teile nehmen, die passen (${p.fitting})", { p.onFitting(); onDismiss() }, Modifier.fillMaxWidth(), enabled = p.fitting > 0)
                p.onPlates?.let { onPlates ->
                    LcButton("Auf ${p.plates} Platten verteilen (Originalgröße)", { onPlates(); onDismiss() }, Modifier.fillMaxWidth(), kind = BtnKind.PRIMARY)
                }
                LcButton("Verkleinern auf ${p.shrinkPercent} %", { p.onShrink(); onDismiss() }, Modifier.fillMaxWidth())
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}
