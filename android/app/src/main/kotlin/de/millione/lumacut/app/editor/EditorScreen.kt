package de.millione.lumacut.app.editor

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.ui.BedMapper
import de.millione.lumacut.app.ui.BtnKind
import de.millione.lumacut.app.ui.Confirm
import de.millione.lumacut.app.ui.ConfirmDialog
import de.millione.lumacut.app.ui.IconBtn
import de.millione.lumacut.app.ui.Lc
import de.millione.lumacut.app.ui.LcButton
import de.millione.lumacut.app.ui.LcCard
import de.millione.lumacut.app.ui.LcIcons
import de.millione.lumacut.app.ui.LcTypography
import de.millione.lumacut.app.ui.NumberField
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.TextInput
import de.millione.lumacut.app.ui.drawBed
import de.millione.lumacut.app.ui.rememberConfirm
import de.millione.lumacut.core.Bed
import de.millione.lumacut.core.Frame
import de.millione.lumacut.core.MaterialTest
import de.millione.lumacut.core.Toolpath
import de.millione.lumacut.core.formatDuration
import de.millione.lumacut.app.machine.canControl
import de.millione.lumacut.app.ui.Banner
import de.millione.lumacut.app.ui.Tile
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.ImageMode
import de.millione.lumacut.core.JobBuildException
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Shapes
import de.millione.lumacut.core.SvgImport
import de.millione.lumacut.core.Transform
import de.millione.lumacut.core.simplify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.roundToInt

@Composable
fun EditorScreen(editor: EditorViewModel, machine: MachineViewModel) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    val tool by editor.tool.collectAsStateWithLifecycle()
    val originBottom by machine.originBottom.collectAsStateWithLifecycle()
    val canUndo by editor.canUndo.collectAsStateWithLifecycle()
    val canRedo by editor.canRedo.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var confirm by rememberConfirm()
    var textAt by remember { mutableStateOf<Pt?>(null) }
    var sending by remember { mutableStateOf(false) }
    var cameraOpen by remember { mutableStateOf(false) }
    var materialTest by remember { mutableStateOf(false) }
    val machineStatus by machine.status.collectAsStateWithLifecycle()
    val machineOnline by machine.online.collectAsStateWithLifecycle()

    val svgPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch {
            try {
                val bytes = withContext(Dispatchers.IO) { context.contentResolver.openInputStream(uri)?.use { it.readBytes() } } ?: return@launch
                val polys = withContext(Dispatchers.Default) { SvgImport.parse(bytes) }
                val (placed, shrunk) = placeInWorkArea(orientForScreen(polys, originBottom))
                editor.addVector("SVG", placed)
                editor.notify(if (shrunk) "SVG verkleinert, damit es in die Arbeitsfläche passt" else "SVG importiert (${polys.size} Pfade)")
            } catch (e: Exception) { editor.notify(e.message ?: "SVG-Import fehlgeschlagen", true) }
        }
    }
    val imagePicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch {
            val raster = withContext(Dispatchers.Default) { Images.decode(context, uri)?.let { Images.toRaster(it) } }
            if (raster == null) { editor.notify("Bild konnte nicht gelesen werden", true); return@launch }
            val w = 80.0; val h = w * raster.height / raster.width
            val x = (Bed.SAFE + Bed.WIDTH) / 2 - w / 2; val y = (Bed.SAFE + Bed.HEIGHT) / 2 - h / 2
            editor.addElement(Element(layerId = editor.activeLayer.value, kind = "Bild", transform = Transform(x, y),
                raster = raster, imageWidthMm = w, imageHeightMm = h))
            editor.notify("Bild eingefügt: ${raster.width} × ${raster.height} px auf 80 mm Breite")
        }
    }
    val projectSaver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch(Dispatchers.IO) {
            runCatching { context.contentResolver.openOutputStream(uri)?.use { it.write(editor.doc.value.toJson().toByteArray()) } }
                .onSuccess { editor.notify("Projekt gespeichert") }.onFailure { editor.notify("Speichern fehlgeschlagen", true) }
        }
    }
    val projectOpener = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch {
            val text = withContext(Dispatchers.IO) { context.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) } }
            if (text != null) editor.openJson(text)
        }
    }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        // action bar
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            var title by remember(doc.title) { mutableStateOf(doc.title) }
            OutlinedTextField(title, { title = it; editor.rename(it) }, singleLine = true, modifier = Modifier.width(260.dp),
                textStyle = LcTypography.titleMedium, shape = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Lc.accent, unfocusedBorderColor = Lc.line))
            IconBtn(LcIcons.undo, "Rückgängig", editor::undo, enabled = canUndo)
            IconBtn(LcIcons.redo, "Wiederholen", editor::redo, enabled = canRedo)
            IconBtn(LcIcons.copy, "Duplizieren", editor::duplicateSelected, enabled = selected != null)
            IconBtn(LcIcons.trash, "Löschen", editor::deleteSelected, tint = Lc.bad, enabled = selected != null)
            IconBtn(LcIcons.center, "Zentrieren", editor::centerInWorkArea)
            Box(Modifier.width(1.dp).height(36.dp).background(Lc.line))
            IconBtn(LcIcons.svg, "SVG importieren", { svgPicker.launch(arrayOf("image/svg+xml", "*/*")) })
            IconBtn(LcIcons.image, "Bild importieren", { imagePicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) })
            IconBtn(LcIcons.camera, "Kamera-Hintergrund", { cameraOpen = true })
            IconBtn(LcIcons.material, "Materialtest", {
                confirm = Confirm("Materialtest erstellen?", "Das aktuelle Projekt wird durch ein Testraster ersetzt (Rückgängig holt es zurück).", "Weiter") { materialTest = true }
            })
            Box(Modifier.width(1.dp).height(36.dp).background(Lc.line))
            IconBtn(LcIcons.plus, "Neues Projekt", { confirm = Confirm("Neues Projekt?", "Alle Elemente werden entfernt. Ebenen bleiben.", "Neu", danger = true) { editor.newDocument() } })
            IconBtn(LcIcons.folder, "Projekt öffnen", { projectOpener.launch(arrayOf("application/json", "*/*")) })
            IconBtn(LcIcons.save, "Projekt speichern", { projectSaver.launch(PiClient.jobNameFrom(doc.title).removeSuffix(".gcode") + ".lumacut.json") })
            Spacer(Modifier.weight(1f))
            LcButton("An Laser senden", { sending = true }, icon = LcIcons.send, kind = BtnKind.PRIMARY, busy = "upload" in busy,
                     enabled = doc.elements.isNotEmpty())
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            ToolColumn(tool, editor::setTool)
            Box(Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(18.dp)).background(Color(0xFF0B1015)).border(1.dp, Lc.line, RoundedCornerShape(18.dp))) {
                EditorCanvas(editor, originBottom, onText = { textAt = it })
                SmallText(
                    when (tool) {
                        Tool.SELECT -> "Antippen wählt aus · ziehen verschiebt · zwei Finger zoomen und schwenken"
                        Tool.PEN -> "Mit dem Finger zeichnen"
                        Tool.TEXT -> "Antippen, wo der Text beginnen soll"
                        else -> "Ziehen, um ${tool.label.lowercase()} aufzuziehen · zwei Finger zoomen"
                    },
                    Lc.faint, Modifier.align(Alignment.BottomStart).padding(12.dp),
                )
            }
            Inspector(editor, Modifier.width(340.dp).fillMaxHeight())
        }
    }

    textAt?.let { at -> TextDialog(onDismiss = { textAt = null }) { text, size, bold, family ->
        textAt = null
        val raw = TextPaths.build(text, size, bold, family)
        if (raw.isEmpty()) { editor.notify("Kein darstellbarer Text", true); return@TextDialog }
        val oriented = orientForScreen(raw, originBottom)
        val b = de.millione.lumacut.core.boundsOf(oriented)!!
        editor.addVector("Text", oriented.map { p -> p.map { Pt(it.x - b.minX + at.x, it.y - b.minY + at.y) } }, text, size, bold, family)
    } }

    if (sending) SendDialog(
        title = doc.title,
        build = { editor.buildGcode(imageTopAtMaxY = originBottom) },
        onFrame = { tp, mode -> machine.frame(Frame.cutPoints(tp), mode) },
        canFrame = machineStatus.canControl(machineOnline) && machineStatus?.homed == true,
        onDismiss = { sending = false },
    ) { name, gcode ->
        sending = false
        machine.uploadJob(name, gcode)
        editor.jobSent()
    }
    if (materialTest) MaterialTestDialog(onDismiss = { materialTest = false }) { spec ->
        materialTest = false
        val generated = MaterialTest.build(spec) { t, h -> orientForScreen(TextPaths.build(t, h, true, "sans-serif"), originBottom) }
        editor.replaceDocument(generated)
        editor.notify("Materialtest mit ${spec.powerSteps * spec.speedSteps} Feldern erstellt")
    }

    if (cameraOpen) CameraBackgroundDialog(editor, machine, originBottom) { cameraOpen = false }
    ConfirmDialog(confirm) { confirm = null }
}

@Composable
private fun ToolColumn(tool: Tool, onTool: (Tool) -> Unit) {
    val icons = mapOf(Tool.SELECT to LcIcons.select, Tool.RECT to LcIcons.rect, Tool.ELLIPSE to LcIcons.ellipse,
                      Tool.POLYGON to LcIcons.polygon, Tool.LINE to LcIcons.line, Tool.PEN to LcIcons.pen, Tool.TEXT to LcIcons.text)
    Column(
        Modifier.width(76.dp).fillMaxHeight().clip(RoundedCornerShape(18.dp)).background(Lc.surface).border(1.dp, Lc.line, RoundedCornerShape(18.dp)).padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp), horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        for (t in Tool.entries) {
            val on = t == tool
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(if (on) Lc.accentSoft else Color.Transparent)
                    .clickable { onTool(t) }.padding(vertical = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(icons.getValue(t), t.label, tint = if (on) Lc.accent else Lc.muted, modifier = Modifier.size(24.dp))
                Spacer(Modifier.height(4.dp))
                Text(t.label, style = LcTypography.labelMedium, color = if (on) Lc.accent else Lc.muted, maxLines = 1, overflow = TextOverflow.Clip)
            }
        }
    }
}

/* ---------- canvas ---------- */

@Composable
private fun EditorCanvas(editor: EditorViewModel, originBottom: Boolean, onText: (Pt) -> Unit) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    val tool by editor.tool.collectAsStateWithLifecycle()
    val background by editor.background.collectAsStateWithLifecycle()
    val bgAlpha by editor.backgroundAlpha.collectAsStateWithLifecycle()
    var size by remember { mutableStateOf(IntSize.Zero) }
    var zoom by remember { mutableStateOf(1f) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    var draftStart by remember { mutableStateOf<Pt?>(null) }
    var draftEnd by remember { mutableStateOf<Pt?>(null) }
    val pen = remember { mutableStateListOf<Pt>() }
    val images = remember { HashMap<String, ImageBitmap>() }

    fun mapper() = BedMapper.fit(Size(size.width.toFloat(), size.height.toFloat()), originBottom, zoom = zoom, pan = pan)

    val gestures = Modifier.pointerInput(tool, originBottom) {
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false)
            val start = down.position
            var mode = 0          // 0 undecided, 1 single-finger action, 2 pinch/pan
            var last = start
            var moveKey: String? = null
            val slop = viewConfiguration.touchSlop
            do {
                val event = awaitPointerEvent()
                val pressed = event.changes.filter { it.pressed }
                if (pressed.size >= 2) {
                    if (mode == 1) { draftStart = null; draftEnd = null; pen.clear() }
                    mode = 2
                    val m = mapper()
                    val z = event.calculateZoom(); val p = event.calculatePan(); val c = event.calculateCentroid()
                    val newZoom = (zoom * z).coerceIn(0.6f, 10f); val k = newZoom / zoom
                    val ox2 = c.x - (c.x - m.ox) * k + p.x; val oy2 = c.y - (c.y - m.oy) * k + p.y
                    val base = BedMapper.fit(Size(size.width.toFloat(), size.height.toFloat()), originBottom, zoom = newZoom)
                    zoom = newZoom
                    pan = Offset(ox2 - base.ox, oy2 - base.oy)
                    event.changes.forEach { it.consume() }
                } else if (pressed.size == 1) {
                    val pos = pressed.first().position
                    if (mode == 0 && (pos - start).getDistance() > slop) {
                        mode = 1
                        val m = mapper(); val p0 = m.toBed(start)
                        when (tool) {
                            Tool.SELECT -> {
                                val hit = editor.hit(p0, m.mm(28f).toDouble())
                                if (hit != null) { editor.select(hit.id); moveKey = "drag" + System.nanoTime() } else moveKey = null
                            }
                            Tool.PEN -> { pen.clear(); pen.add(p0) }
                            Tool.TEXT -> {}
                            else -> { draftStart = p0; draftEnd = p0 }
                        }
                    }
                    if (mode == 1) {
                        val m = mapper()
                        when (tool) {
                            Tool.SELECT -> {
                                if (moveKey != null) {
                                    val a = m.toBed(last); val b = m.toBed(pos)
                                    editor.moveSelected(b.x - a.x, b.y - a.y, moveKey!!)
                                } else pan += pos - last
                            }
                            Tool.PEN -> pen.add(m.toBed(pos))
                            Tool.TEXT -> {}
                            else -> draftEnd = m.toBed(pos)
                        }
                        pressed.first().consume()
                    }
                    last = pos
                }
            } while (event.changes.any { it.pressed })
            val m = mapper()
            if (mode == 0) {
                val p = m.toBed(start)
                when (tool) {
                    Tool.SELECT -> editor.select(editor.hit(p, m.mm(28f).toDouble())?.id)
                    Tool.TEXT -> if (Bed.inWorkArea(p.x, p.y)) onText(p) else editor.notify("Text bitte außerhalb der Safezone beginnen", true)
                    else -> {}
                }
            } else if (mode == 1) {
                when (tool) {
                    Tool.PEN -> if (pen.size > 2) editor.addVector("Freihand", listOf(simplify(pen.toList(), 0.15)))
                    Tool.SELECT, Tool.TEXT -> {}
                    else -> {
                        val a = draftStart; val b = draftEnd
                        if (a != null && b != null) shapeFromDrag(tool, a, b)?.let { editor.addVector(tool.label, listOf(it)) }
                    }
                }
                draftStart = null; draftEnd = null; pen.clear()
            }
        }
    }

    Canvas(Modifier.fillMaxSize().onSizeChanged { size = it }.then(gestures)) {
        if (size == IntSize.Zero) return@Canvas
        val m = mapper()
        drawBed(m)
        background?.let { bmp ->
            val a = m.at(Pt(0.0, 0.0)); val b = m.at(Pt(Bed.WIDTH, Bed.HEIGHT))
            drawImage(bmp, dstOffset = IntOffset(minOf(a.x, b.x).roundToInt(), minOf(a.y, b.y).roundToInt()),
                dstSize = IntSize(abs(b.x - a.x).roundToInt(), abs(b.y - a.y).roundToInt()), alpha = bgAlpha)
        }
        for (e in doc.elements) {
            val layer = doc.layer(e.layerId) ?: continue
            val color = Color(layer.color.toInt()).copy(alpha = if (layer.output) 1f else .35f)
            if (e.isImage) {
                val r = e.raster ?: continue
                val img = images.getOrPut(e.id + r.hashCode()) { Images.toBitmap(r).asImageBitmap() }
                val bx = e.worldBounds() ?: continue
                val a = m.at(Pt(bx.minX, bx.minY)); val c = m.at(Pt(bx.maxX, bx.maxY))
                drawImage(img, dstOffset = IntOffset(minOf(a.x, c.x).roundToInt(), minOf(a.y, c.y).roundToInt()),
                    dstSize = IntSize(abs(c.x - a.x).roundToInt().coerceAtLeast(1), abs(c.y - a.y).roundToInt().coerceAtLeast(1)), alpha = .9f)
                continue
            }
            val path = Path().apply {
                fillType = PathFillType.EvenOdd
                for (poly in e.worldPaths()) if (poly.isNotEmpty()) {
                    val p0 = m.at(poly.first()); moveTo(p0.x, p0.y)
                    for (p in poly.drop(1)) { val q = m.at(p); lineTo(q.x, q.y) }
                }
            }
            if (layer.mode == LayerMode.FILL) drawPath(path, color.copy(alpha = color.alpha * .22f))
            drawPath(path, color, style = Stroke(2f, cap = StrokeCap.Round))
        }
        doc.elements.firstOrNull { it.id == selected }?.worldBounds()?.let { b ->
            val a = m.at(Pt(b.minX, b.minY)); val c = m.at(Pt(b.maxX, b.maxY))
            val tl = Offset(minOf(a.x, c.x) - 6, minOf(a.y, c.y) - 6); val sz = Size(abs(c.x - a.x) + 12, abs(c.y - a.y) + 12)
            drawRect(Lc.accent, tl, sz, style = Stroke(2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
            for (corner in listOf(tl, tl + Offset(sz.width, 0f), tl + Offset(0f, sz.height), tl + Offset(sz.width, sz.height)))
                drawCircle(Lc.accent, 7f, corner)
        }
        val a = draftStart; val b = draftEnd
        if (a != null && b != null) shapeFromDrag(tool, a, b)?.let { poly ->
            val path = Path().apply { val p0 = m.at(poly.first()); moveTo(p0.x, p0.y); poly.drop(1).forEach { val q = m.at(it); lineTo(q.x, q.y) } }
            drawPath(path, Lc.accent, style = Stroke(2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 6f))))
        }
        if (pen.size > 1) {
            val path = Path().apply { val p0 = m.at(pen.first()); moveTo(p0.x, p0.y); pen.drop(1).forEach { val q = m.at(it); lineTo(q.x, q.y) } }
            drawPath(path, Lc.accent, style = Stroke(2.5f, cap = StrokeCap.Round))
        }
    }
}

/** World polygon for a drag from [a] to [b]. */
private fun shapeFromDrag(tool: Tool, a: Pt, b: Pt): Poly? {
    val x = minOf(a.x, b.x); val y = minOf(a.y, b.y); val w = abs(b.x - a.x); val h = abs(b.y - a.y)
    if (tool == Tool.LINE) return if (a.dist(b) < 0.5) null else listOf(a, b)
    if (w < 0.5 || h < 0.5) return null
    val local = when (tool) {
        Tool.RECT -> Shapes.rect(w, h)
        Tool.ELLIPSE -> Shapes.ellipse(w, h)
        Tool.POLYGON -> Shapes.polygon(6, w, h)
        else -> return null
    }
    return local.map { Pt(it.x + x, it.y + y) }
}

/* ---------- inspector ---------- */

@Composable
private fun Inspector(editor: EditorViewModel, modifier: Modifier) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val selectedId by editor.selected.collectAsStateWithLifecycle()
    val active by editor.activeLayer.collectAsStateWithLifecycle()
    val materials by editor.materials.collectAsStateWithLifecycle()
    val background by editor.background.collectAsStateWithLifecycle()
    val bgAlpha by editor.backgroundAlpha.collectAsStateWithLifecycle()
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val sel = doc.elements.firstOrNull { it.id == selectedId }
        if (sel != null) SelectionCard(editor, sel)
        LcCard(padding = 16.dp) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Ebenen", style = LcTypography.titleLarge, modifier = Modifier.weight(1f))
                IconBtn(LcIcons.plus, "Ebene hinzufügen", editor::addLayer)
            }
            Spacer(Modifier.height(10.dp))
            SmallText(if (sel != null) "Antippen legt die Auswahl auf die Ebene." else "Neue Formen landen auf der aktiven Ebene. Reihenfolge = Bearbeitungsreihenfolge.")
            Spacer(Modifier.height(10.dp))
            for (layer in doc.layers) LayerRow(editor, layer, layer.id == (sel?.layerId ?: active), materials, doc.elements.count { it.layerId == layer.id })
        }
        if (background != null) LcCard(padding = 16.dp) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Kamera-Hintergrund", style = LcTypography.titleMedium, modifier = Modifier.weight(1f))
                IconBtn(LcIcons.trash, "Hintergrund entfernen", { editor.setBackground(null) }, tint = Lc.bad)
            }
            Slider(bgAlpha, editor::setBackgroundAlpha, colors = SliderDefaults.colors(thumbColor = Lc.accent, activeTrackColor = Lc.accent))
            SmallText("Deckkraft ${(bgAlpha * 100).toInt()} %")
        }
    }
}

@Composable
private fun SelectionCard(editor: EditorViewModel, e: Element) {
    val b = e.worldBounds() ?: return
    LcCard(padding = 16.dp, accent = Lc.accent) {
        Text(e.text?.let { "Text: $it" } ?: e.kind, style = LcTypography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(12.dp))
        var keep by remember { mutableStateOf(true) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Num("X", b.minX, Modifier.weight(1f)) { editor.placeSelected(it, null) }
            Num("Y", b.minY, Modifier.weight(1f)) { editor.placeSelected(null, it) }
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val local = editor.localSize(e)
            Num("Breite", local?.first?.times(e.transform.scaleX) ?: b.width, Modifier.weight(1f)) { editor.resizeSelected(it, null, keep) }
            Num("Höhe", local?.second?.times(e.transform.scaleY) ?: b.height, Modifier.weight(1f)) { editor.resizeSelected(null, it, keep) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(keep, { keep = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk))
            SmallText("Seitenverhältnis beibehalten")
        }
        if (!e.isImage) {
            Num("Drehung", e.transform.rotation, Modifier.fillMaxWidth(), suffix = "°") { editor.rotateSelected(it) }
        } else {
            Spacer(Modifier.height(4.dp))
            Segmented(listOf(ImageMode.GRAYSCALE to "Graustufen", ImageMode.DITHER to "Dither", ImageMode.THRESHOLD to "S/W"), e.imageMode,
                { mode -> editor.updateElement(e.id) { it.copy(imageMode = mode) } })
            Spacer(Modifier.height(6.dp))
            SmallText("Bilder werden zeilenweise graviert; Zeilenabstand und Leistung kommen von der Ebene.")
        }
        val outside = b.minX < Bed.SAFE || b.minY < Bed.SAFE || b.maxX > Bed.WIDTH || b.maxY > Bed.HEIGHT
        if (outside) { Spacer(Modifier.height(8.dp)); SmallText("Liegt nicht vollständig in der Arbeitsfläche (ab X/Y 30 mm).", Lc.warn) }
    }
}

/** Numeric field that commits valid numbers as you type. */
@Composable
private fun Num(label: String, value: Double, modifier: Modifier, suffix: String = "mm", onValue: (Double) -> Unit) {
    fun fmt(v: Double) = "%.1f".format(java.util.Locale.ROOT, v)
    var text by remember { mutableStateOf(fmt(value)) }
    var focused by remember { mutableStateOf(false) }
    // Follow outside changes (dragging, undo) but never overwrite what is being typed.
    LaunchedEffect(value) { if (!focused) text = fmt(value) }
    NumberField(label, text, { t -> text = t; t.toDoubleOrNull()?.let(onValue) },
        modifier.onFocusChanged { focused = it.isFocused }, suffix)
}

@Composable
private fun LayerRow(editor: EditorViewModel, layer: Layer, active: Boolean, materials: List<de.millione.lumacut.core.Material>, count: Int) {
    var open by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(14.dp))
            .background(if (active) Lc.surface3 else Lc.surface2)
            .border(1.dp, if (active) Color(layer.color.toInt()).copy(alpha = .7f) else Lc.line, RoundedCornerShape(14.dp))
    ) {
        Row(Modifier.fillMaxWidth().clickable { editor.setActiveLayer(layer.id) }.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(14.dp).clip(CircleShape).background(Color(layer.color.toInt())))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(layer.name, style = LcTypography.titleMedium, maxLines = 1)
                SmallText("${if (layer.mode == LayerMode.FILL) "Füllen" else "Linie"} · ${layer.powerPct.roundToInt()} % · ${layer.speed.roundToInt()} mm/min${if (layer.passes > 1) " · ${layer.passes}×" else ""} · $count")
            }
            IconBtn(if (layer.output) LcIcons.eye else LcIcons.eyeOff, "Ausgabe", { editor.updateLayer(layer.id) { it.copy(output = !it.output) } },
                    tint = if (layer.output) Lc.text else Lc.faint)
            Spacer(Modifier.width(6.dp))
            IconBtn(if (open) LcIcons.up else LcIcons.down, "Einstellungen", { open = !open })
        }
        if (open) Column(Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            TextInput("Name", layer.name, { n -> editor.updateLayer(layer.id, "name") { it.copy(name = n) } }, Modifier.fillMaxWidth())
            Segmented(listOf(LayerMode.LINE to "Linie / Schneiden", LayerMode.FILL to "Füllen / Gravieren"), layer.mode,
                { m -> editor.updateLayer(layer.id) { it.copy(mode = m) } })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Num("Leistung", layer.powerPct, Modifier.weight(1f), "%") { v -> editor.updateLayer(layer.id, "power") { it.copy(powerPct = v.coerceIn(0.0, 100.0)) } }
                Num("Tempo", layer.speed, Modifier.weight(1f), "mm/min") { v -> editor.updateLayer(layer.id, "speed") { it.copy(speed = v.coerceIn(10.0, 9000.0)) } }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Num("Durchgänge", layer.passes.toDouble(), Modifier.weight(1f), "×") { v -> editor.updateLayer(layer.id, "passes") { it.copy(passes = v.toInt().coerceIn(1, 50)) } }
                Num("Zeilenabstand", layer.intervalMm, Modifier.weight(1f)) { v -> editor.updateLayer(layer.id, "interval") { it.copy(intervalMm = v.coerceIn(0.03, 2.0)) } }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Num("Min. Leistung (Bild)", layer.minPowerPct, Modifier.weight(1f), "%") { v -> editor.updateLayer(layer.id, "minpower") { it.copy(minPowerPct = v.coerceIn(0.0, 100.0)) } }
                Num("Überlauf", layer.overscanMm, Modifier.weight(1f)) { v -> editor.updateLayer(layer.id, "overscan") { it.copy(overscanMm = v.coerceIn(0.0, 10.0)) } }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Box {
                    LcButton("Material …", { menu = true }, icon = LcIcons.material)
                    DropdownMenu(menu, { menu = false }, containerColor = Lc.surface2) {
                        for (m in materials) DropdownMenuItem(
                            text = { Text("${m.name} ${m.thicknessMm} mm · ${m.process}") },
                            onClick = { menu = false; editor.applyMaterial(layer.id, m) })
                    }
                }
                IconBtn(LcIcons.up, "Nach oben", { editor.moveLayer(layer.id, true) })
                IconBtn(LcIcons.down, "Nach unten", { editor.moveLayer(layer.id, false) })
                IconBtn(LcIcons.trash, "Ebene löschen", { editor.deleteLayer(layer.id) }, tint = Lc.bad)
            }
        }
    }
}

/* ---------- dialogs ---------- */

@Composable
private fun TextDialog(onDismiss: () -> Unit, onOk: (String, Double, Boolean, String) -> Unit) {
    var text by remember { mutableStateOf("LumaCut") }
    var size by remember { mutableStateOf("15") }
    var bold by remember { mutableStateOf(true) }
    var family by remember { mutableStateOf("sans-serif") }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Text einfügen", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(text, { text = it }, label = { Text("Text (mehrzeilig möglich)") }, modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp), colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Lc.accent))
                NumberField("Schriftgröße", size, { size = it }, Modifier.fillMaxWidth(), "mm")
                Segmented(Fonts.families, family, { family = it })
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(bold, { bold = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk)); Text("Fett")
                }
            }
        },
        confirmButton = { LcButton("Einfügen", { size.toDoubleOrNull()?.takeIf { it in 1.0..300.0 }?.let { onOk(text, it, bold, family) } }, kind = BtnKind.PRIMARY, enabled = text.isNotBlank()) },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

@Composable
private fun SendDialog(
    title: String,
    build: suspend () -> String,
    onFrame: (Toolpath, Frame.Mode) -> Unit,
    canFrame: Boolean,
    onDismiss: () -> Unit,
    onSend: (String, String) -> Unit,
) {
    var name by remember { mutableStateOf(PiClient.jobNameFrom(title).removeSuffix(".gcode")) }
    var gcode by remember { mutableStateOf<String?>(null) }
    var toolpath by remember { mutableStateOf<Toolpath?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    // Build and check the job before it leaves the tablet: time, size, warnings.
    LaunchedEffect(Unit) {
        try {
            val g = build()
            toolpath = withContext(Dispatchers.Default) { Toolpath.parse(g) }
            gcode = g
        } catch (e: Exception) { error = e.message ?: "Auftrag nicht erzeugbar" }
    }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("An Laser senden", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                TextInput("Auftragsname", name, { name = it }, Modifier.fillMaxWidth())
                val tp = toolpath
                val failure = error
                when {
                    failure != null -> Banner(failure, Lc.bad)
                    tp == null -> SmallText("Auftrag wird erzeugt …")
                    else -> {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Tile("Dauer (ca.)", formatDuration(tp.stats.seconds), Modifier.weight(1f))
                            Tile("Laserweg", "%.2f m".format(tp.stats.cutMm / 1000), Modifier.weight(1f))
                        }
                        Tile("Größe", tp.bounds?.let { "%.1f × %.1f mm".format(it.width, it.height) } ?: "—", Modifier.fillMaxWidth())
                        tp.stats.warnings.forEach { Banner(it) }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            LcButton("Rahmen", { onFrame(tp, Frame.Mode.BOX) }, Modifier.weight(1f), LcIcons.rect, enabled = canFrame)
                            LcButton("Gummiband", { onFrame(tp, Frame.Mode.HULL) }, Modifier.weight(1f), LcIcons.polygon, enabled = canFrame)
                        }
                        SmallText(if (canFrame) "Rahmen fährt den Umriss mit ausgeschaltetem Laser ab." else "Rahmen fahren: Maschine erst referenzieren.")
                    }
                }
            }
        },
        confirmButton = {
            LcButton("Senden", { gcode?.let { onSend(PiClient.jobNameFrom(name), it) } }, icon = LcIcons.send, kind = BtnKind.PRIMARY,
                enabled = name.isNotBlank() && gcode != null)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}

@Composable
private fun MaterialTestDialog(onDismiss: () -> Unit, onCreate: (MaterialTest.Spec) -> Unit) {
    var pFrom by remember { mutableStateOf("20") }
    var pTo by remember { mutableStateOf("100") }
    var pSteps by remember { mutableStateOf("5") }
    var sFrom by remember { mutableStateOf("300") }
    var sTo by remember { mutableStateOf("3000") }
    var sSteps by remember { mutableStateOf("5") }
    var mode by remember { mutableStateOf(LayerMode.FILL) }
    var cell by remember { mutableStateOf("10") }
    var interval by remember { mutableStateOf("0.1") }
    val spec = runCatching {
        MaterialTest.Spec(
            powerFrom = pFrom.toDouble(), powerTo = pTo.toDouble(), powerSteps = pSteps.toInt(),
            speedFrom = sFrom.toDouble(), speedTo = sTo.toDouble(), speedSteps = sSteps.toInt(),
            mode = mode, cellMm = cell.toDouble().coerceIn(3.0, 40.0), intervalMm = interval.toDouble().coerceIn(0.03, 2.0),
        )
    }.getOrNull()
    val valid = spec != null && spec.powerSteps in 1..10 && spec.speedSteps in 1..10 &&
        spec.powerFrom in 0.0..100.0 && spec.powerTo in 0.0..100.0 && spec.speedFrom in 10.0..9000.0 && spec.speedTo in 10.0..9000.0
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Materialtest", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SmallText("Raster aus Leistung (Spalten) × Tempo (Zeilen). Jedes Feld bekommt eine eigene Ebene, die Beschriftung wird leicht graviert.")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Leistung von", pFrom, { pFrom = it }, Modifier.weight(1f), "%")
                    NumberField("bis", pTo, { pTo = it }, Modifier.weight(1f), "%")
                    NumberField("Stufen", pSteps, { pSteps = it }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Tempo von", sFrom, { sFrom = it }, Modifier.weight(1f))
                    NumberField("bis", sTo, { sTo = it }, Modifier.weight(1f))
                    NumberField("Stufen", sSteps, { sSteps = it }, Modifier.weight(1f))
                }
                Segmented(listOf(LayerMode.FILL to "Gravieren", LayerMode.LINE to "Schneiden"), mode, { mode = it })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    NumberField("Feldgröße", cell, { cell = it }, Modifier.weight(1f), "mm")
                    NumberField("Zeilenabstand", interval, { interval = it }, Modifier.weight(1f), "mm")
                }
            }
        },
        confirmButton = {
            LcButton("Erstellen", { if (valid) spec?.let(onCreate) }, kind = BtnKind.PRIMARY, enabled = valid)
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen", color = Lc.muted) } },
    )
}
