package de.millione.lumacut.app.editor

import android.graphics.Bitmap
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
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
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.FileProvider
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.MarlinWriter
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Shapes
import de.millione.lumacut.core.Transform
import de.millione.lumacut.core.boundsOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.math.min
import kotlin.math.roundToInt

private val labelPaint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
    textSize = 34f; typeface = android.graphics.Typeface.DEFAULT_BOLD
}

@Composable
fun CameraBackgroundDialog(editor: EditorViewModel, machine: MachineViewModel, originBottom: Boolean, onClose: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var x0 by remember { mutableStateOf("60") }; var y0 by remember { mutableStateOf("50") }
    var x1 by remember { mutableStateOf("360") }; var y1 by remember { mutableStateOf("350") }
    var photo by remember { mutableStateOf<Bitmap?>(null) }
    val markers = remember { mutableStateListOf<Offset>() }   // in photo pixels
    var working by remember { mutableStateOf(false) }
    val photoFile = remember { File(context.cacheDir, "camera").apply { mkdirs() }.resolve("bed.jpg") }
    val photoUri = remember { FileProvider.getUriForFile(context, context.packageName + ".files", photoFile) }

    fun reference(): List<Pt>? {
        val a = x0.toDoubleOrNull(); val b = y0.toDoubleOrNull(); val c = x1.toDoubleOrNull(); val d = y1.toDoubleOrNull()
        if (a == null || b == null || c == null || d == null || c - a < 50 || d - b < 50) return null
        return listOf(Pt(a, b), Pt(c, b), Pt(c, d), Pt(a, d))
    }

    fun usePhoto(bmp: Bitmap?) {
        if (bmp == null) { editor.notify("Foto konnte nicht geladen werden", true); return }
        photo = bmp
        markers.clear()
        val w = bmp.width.toFloat(); val h = bmp.height.toFloat()
        markers.addAll(listOf(Offset(w * .2f, h * .2f), Offset(w * .8f, h * .2f), Offset(w * .8f, h * .8f), Offset(w * .2f, h * .8f)))
    }

    val take = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) scope.launch { usePhoto(withContext(Dispatchers.IO) { loadUpright(photoFile) }) }
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? ->
        if (uri != null) scope.launch { usePhoto(withContext(Dispatchers.IO) { Images.decode(context, uri, 2400) }) }
    }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Row(Modifier.fillMaxSize().background(Lc.bg).padding(20.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            LcCard(Modifier.width(360.dp).fillMaxHeight()) {
                Text("Kamera-Hintergrund", style = LcTypography.headlineSmall)
                Spacer(Modifier.height(8.dp))
                SmallText("1. Kalibrier-Rechteck lasern (einmalig, z. B. auf die Opferplatte).\n2. Arbeitsfläche möglichst senkrecht von oben fotografieren.\n3. Die vier Marker auf die nummerierten Ecken ziehen.\n4. Übernehmen – das Foto liegt maßgenau unter dem Editor.")
                Spacer(Modifier.height(14.dp))
                Text("Rechteck (Maschinen-mm)", style = LcTypography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("X1", x0, { x0 = it }, Modifier.weight(1f)); NumberField("Y1", y0, { y0 = it }, Modifier.weight(1f))
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("X2", x1, { x1 = it }, Modifier.weight(1f)); NumberField("Y2", y1, { y1 = it }, Modifier.weight(1f))
                }
                Spacer(Modifier.height(10.dp))
                LcButton("Kalibrier-Rechteck an Laser senden", {
                    val ref = reference() ?: run { editor.notify("Rechteck mindestens 50 × 50 mm, X/Y ab 30", true); return@LcButton }
                    machine.uploadJob("kamera-kalibrierung.gcode", calibrationJob(ref, originBottom, imageTopAtMaxY = originBottom))
                    editor.notify("Kalibrier-Rechteck gesendet: unter Aufträge starten")
                }, Modifier.fillMaxWidth(), LcIcons.send)
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LcButton("Foto", { take.launch(photoUri) }, Modifier.weight(1f), LcIcons.camera, BtnKind.PRIMARY)
                    LcButton("Galerie", { pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, Modifier.weight(1f), LcIcons.image)
                }
                Spacer(Modifier.weight(1f))
                LcButton("Übernehmen", {
                    val p = photo ?: return@LcButton
                    val ref = reference() ?: run { editor.notify("Rechteck-Werte prüfen", true); return@LcButton }
                    working = true
                    scope.launch {
                        try {
                            val bmp = withContext(Dispatchers.Default) {
                                CameraRectify.rectify(p, markers.map { Pt(it.x.toDouble(), it.y.toDouble()) }, ref, originBottom)
                            }
                            editor.setBackground(bmp); editor.notify("Kamera-Hintergrund übernommen"); onClose()
                        } catch (e: Exception) { editor.notify(e.message ?: "Entzerren fehlgeschlagen", true) }
                        finally { working = false }
                    }
                }, Modifier.fillMaxWidth(), LcIcons.check, BtnKind.PRIMARY, busy = working, enabled = photo != null, big = true)
                Spacer(Modifier.height(8.dp))
                LcButton("Schließen", onClose, Modifier.fillMaxWidth(), kind = BtnKind.GHOST)
            }
            Box(Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(18.dp)).background(Color(0xFF0B1015)), contentAlignment = Alignment.Center) {
                val p = photo
                if (p == null) SmallText("Noch kein Foto")
                else MarkerCanvas(p, markers)
            }
        }
    }
}

@Composable
private fun MarkerCanvas(photo: Bitmap, markers: MutableList<Offset>) {
    val image = remember(photo) { photo.asImageBitmap() }
    var size by remember { mutableStateOf(IntSize.Zero) }
    fun scale() = min(size.width / photo.width.toFloat(), size.height / photo.height.toFloat())
    fun origin() = Offset((size.width - photo.width * scale()) / 2, (size.height - photo.height * scale()) / 2)
    var dragging by remember { mutableStateOf(-1) }
    Canvas(
        Modifier.fillMaxSize()
            .onSizeChanged { size = it }
            .pointerInput(photo) {
                detectDragGestures(
                    onDragStart = { o ->
                        val k = scale(); val org = origin()
                        dragging = markers.indices.minByOrNull { (org + markers[it] * k - o).getDistance() }
                            ?.takeIf { (org + markers[it] * k - o).getDistance() < 90f } ?: -1
                    },
                    onDragEnd = { dragging = -1 },
                ) { change, drag ->
                    if (dragging >= 0) {
                        change.consume()
                        val k = scale()
                        val n = markers[dragging] + drag / k
                        markers[dragging] = Offset(n.x.coerceIn(0f, photo.width.toFloat()), n.y.coerceIn(0f, photo.height.toFloat()))
                    }
                }
            }
    ) {
        if (size == IntSize.Zero) return@Canvas
        val k = scale(); val org = origin()
        drawImage(image, dstOffset = IntOffset(org.x.roundToInt(), org.y.roundToInt()),
            dstSize = IntSize((photo.width * k).roundToInt(), (photo.height * k).roundToInt()))
        if (markers.size == 4) {
            val pts = markers.map { org + it * k }
            val path = Path().apply { moveTo(pts[0].x, pts[0].y); pts.drop(1).forEach { lineTo(it.x, it.y) }; close() }
            drawPath(path, Lc.accent, style = Stroke(3f))
            labelPaint.color = Color.White.toArgb()
            pts.forEachIndexed { i, p ->
                drawCircle(Lc.accent.copy(alpha = .25f), 40f, p)
                drawCircle(Lc.accent, 40f, p, style = Stroke(3f))
                drawLine(Lc.accent, p - Offset(16f, 0f), p + Offset(16f, 0f), 2f)
                drawLine(Lc.accent, p - Offset(0f, 16f), p + Offset(0f, 16f), 2f)
                drawContext.canvas.nativeCanvas.drawText("${i + 1}", p.x + 44f, p.y - 30f, labelPaint)
            }
        }
    }
}

/** Upright bitmap from a camera JPEG, honouring the EXIF orientation. */
private fun loadUpright(file: File): Bitmap? {
    val opts = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
    android.graphics.BitmapFactory.decodeFile(file.path, opts)
    var sample = 1
    while (maxOf(opts.outWidth, opts.outHeight) / sample > 2400) sample *= 2
    val bmp = android.graphics.BitmapFactory.decodeFile(file.path, android.graphics.BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
    val deg = when (ExifInterface(file.path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
        ExifInterface.ORIENTATION_ROTATE_90 -> 90f; ExifInterface.ORIENTATION_ROTATE_180 -> 180f; ExifInterface.ORIENTATION_ROTATE_270 -> 270f; else -> 0f
    }
    return if (deg == 0f) bmp else Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(deg) }, true)
}

/** Rectangle with numbered corners and crosses, engraved lightly for the camera calibration. */
private fun calibrationJob(ref: List<Pt>, originBottom: Boolean, imageTopAtMaxY: Boolean): String {
    val layer = Layer(name = "Kalibrierung", color = 0xFF4FD8B4, mode = LayerMode.LINE, powerPct = 30.0, speed = 1500.0)
    val elements = mutableListOf<Element>()
    elements += Element(layerId = layer.id, kind = "Rahmen", paths = listOf(ref + ref.first()))
    ref.forEachIndexed { i, c ->
        elements += Element(layerId = layer.id, kind = "Kreuz", paths = listOf(
            listOf(Pt(c.x - 6, c.y), Pt(c.x + 6, c.y)), listOf(Pt(c.x, c.y - 6), Pt(c.x, c.y + 6))))
        val glyphs = orientForScreen(TextPaths.build("${i + 1}", 8.0, true, "sans-serif"), originBottom)
        val b = boundsOf(glyphs) ?: return@forEachIndexed
        val inward = Pt(if (i == 0 || i == 3) c.x + 4 else c.x - 4 - b.width, if (i < 2) c.y + 4 else c.y - 4 - b.height)
        elements += Element(layerId = layer.id, kind = "Nummer", transform = Transform(inward.x - b.minX, inward.y - b.minY), paths = glyphs)
    }
    return MarlinWriter("kalibrierung", imageTopAtMaxY).write(Document("Kamera-Kalibrierung", listOf(layer), elements))
}
