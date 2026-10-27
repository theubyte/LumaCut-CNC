package de.millione.lumacut.app.editor

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.material3.HorizontalDivider
import de.millione.lumacut.app.ui.BarBtn
import de.millione.lumacut.core.Booleans
import de.millione.lumacut.core.make
import de.millione.lumacut.core.ShapeKind
import de.millione.lumacut.core.Curves
import de.millione.lumacut.app.ui.BarDivider
import de.millione.lumacut.app.ui.BarTextField
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.canControl
import de.millione.lumacut.app.ui.Banner
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
import de.millione.lumacut.app.ui.Tile
import de.millione.lumacut.app.ui.WorkMapper
import de.millione.lumacut.app.ui.drawHead
import de.millione.lumacut.app.ui.drawWorkArea
import de.millione.lumacut.app.ui.rememberConfirm
import de.millione.lumacut.core.Box as WBox
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.DxfImport
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.Frame
import de.millione.lumacut.core.ImageMode
import de.millione.lumacut.core.ShapeLib
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.MeasureEval
import de.millione.lumacut.core.SnapHit
import de.millione.lumacut.core.Limits
import de.millione.lumacut.core.MaterialTest
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Shapes
import de.millione.lumacut.core.SvgImport
import de.millione.lumacut.core.Toolpath
import de.millione.lumacut.core.Transform
import de.millione.lumacut.core.Work
import de.millione.lumacut.core.formatDuration
import de.millione.lumacut.core.simplify
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.roundToInt

@Composable
fun EditorScreen(editor: EditorViewModel, machine: MachineViewModel, onNext: () -> Unit, onScan: () -> Unit) {
    var contourOpen by remember { mutableStateOf(false) }
    var adjustOpen by remember { mutableStateOf(false) }
    var qrOpen by remember { mutableStateOf(false) }
    var gridOpen by remember { mutableStateOf(false) }
    var toolsMenu by remember { mutableStateOf(false) }
    var tabsOpen by remember { mutableStateOf(false) }
    var circleOpen by remember { mutableStateOf(false) }
    var boxOpen by remember { mutableStateOf(false) }
    var personalMenu by remember { mutableStateOf(false) }
    var personal by remember { mutableStateOf<String?>(null) }
    var shapesMenu by remember { mutableStateOf(false) }
    val doc by editor.doc.collectAsStateWithLifecycle()
    val project by editor.project.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    val tool by editor.tool.collectAsStateWithLifecycle()
    val multi by editor.multi.collectAsStateWithLifecycle()
    val measureMode by editor.measureMode.collectAsStateWithLifecycle()
    val measurePoints by editor.pendingPoints.collectAsStateWithLifecycle()
    val measureFirst by editor.pendingElement.collectAsStateWithLifecycle()
    val heights by editor.heights.collectAsStateWithLifecycle()
    val canUndo by editor.canUndo.collectAsStateWithLifecycle()
    val canRedo by editor.canRedo.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var confirm by rememberConfirm()
    var textAt by remember { mutableStateOf<Pt?>(null) }
    var moreMenu by remember { mutableStateOf(false) }
    var cameraOpen by remember { mutableStateOf(false) }
    var materialTest by remember { mutableStateOf(false) }
    val machineStatus by machine.status.collectAsStateWithLifecycle()
    val machineOnline by machine.online.collectAsStateWithLifecycle()
    val ws: de.millione.lumacut.app.workspace.WorkspaceViewModel = androidx.lifecycle.viewmodel.compose.viewModel()

    val importPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch { importFile(context, uri, editor) }
    }
    val projectSaver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch(Dispatchers.IO) {
            runCatching { context.contentResolver.openOutputStream(uri)?.use { it.write(editor.projectJson().toByteArray()) } }
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

    // One compact bar, so the work area keeps as much height as possible (the tablet is height-limited).
    var panelOpen by rememberSaveable { mutableStateOf(true) }
    Column(Modifier.fillMaxSize().padding(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                var title by remember(doc.title) { mutableStateOf(doc.title) }
                BarTextField(title, { title = it; editor.rename(it) }, Modifier.width(180.dp))
                BarBtn(LcIcons.undo, null, editor::undo, enabled = canUndo, description = "Rückgängig")
                BarBtn(LcIcons.redo, null, editor::redo, enabled = canRedo, description = "Wiederholen")
                BarDivider()
                BarBtn(LcIcons.copy, null, editor::duplicateSelected, enabled = selected.isNotEmpty(), description = "Duplizieren")
                BarBtn(LcIcons.trash, null, editor::deleteSelected, tint = Lc.bad, enabled = selected.isNotEmpty(), description = "Löschen")
                BarBtn(LcIcons.center, null, editor::centerInWorkArea, description = "Zentrieren")
                BarDivider()
                BarBtn(LcIcons.upload, "Importieren", { importPicker.launch(arrayOf("*/*")) })
                Box {
                    BarBtn(LcIcons.plus, "Einfügen", { shapesMenu = true }, menu = true)
                    DropdownMenu(shapesMenu, { shapesMenu = false }, containerColor = Lc.surface2) {
                        @Composable fun shape(label: String, kind: String, paths: () -> List<List<Pt>>) =
                            DropdownMenuItem(text = { Text(label) }, onClick = { shapesMenu = false; editor.addShape(kind, paths(), "Schneiden") })
                        shape("Herz", "Herz") { listOf(ShapeLib.heart(60.0, 54.0)) }
                        shape("Stern", "Stern") { listOf(ShapeLib.star(5, 60.0, 57.0)) }
                        shape("Abgerundetes Rechteck", "Rechteck") { listOf(Shapes.rect(60.0, 40.0, 8.0)) }
                        shape("Anhänger mit Loch", "Anhänger") { ShapeLib.pendant(50.0, 30.0, 4.0) }
                        HorizontalDivider(color = Lc.line)
                        DropdownMenuItem(text = { Text("QR-Code …") }, onClick = { shapesMenu = false; qrOpen = true })
                    }
                }
                BarBtn(LcIcons.polygon, "Kontur", { contourOpen = true }, enabled = selected.isNotEmpty())
                Box {
                    BarBtn(LcIcons.heart, "Personalisieren", { personalMenu = true }, menu = true)
                    DropdownMenu(personalMenu, { personalMenu = false }, containerColor = Lc.surface2) {
                        for ((key, label) in listOf("tags" to "Namensschilder & Anhänger …", "emblem" to "Monogramm-Emblem …",
                                "frame" to "Rahmen …", "ruler" to "Lineal …", "puzzle" to "Puzzle …"))
                            DropdownMenuItem(text = { Text(label) }, onClick = { personalMenu = false; personal = key })
                    }
                }
                Box {
                    BarBtn(LcIcons.tools, "Werkzeuge", { toolsMenu = true }, menu = true)
                    DropdownMenu(toolsMenu, { toolsMenu = false }, containerColor = Lc.surface2) {
                        @Composable fun item(label: String, enabled: Boolean = true, action: () -> Unit) =
                            DropdownMenuItem(text = { Text(label) }, enabled = enabled, onClick = { toolsMenu = false; action() })
                        val shapes = doc.elements.count { it.id in selected && !it.isImage }
                        for (op in Booleans.Op.entries) item(op.label + when (op) {
                            Booleans.Op.UNION -> " (vereinen)"; Booleans.Op.SUBTRACT -> " (unterste minus Rest)"; Booleans.Op.INTERSECT -> " (nur Überlappung)"
                        }, shapes >= 2) { editor.booleanSelected(op) }
                        HorizontalDivider(color = Lc.line)
                        item("Waagrecht spiegeln", selected.isNotEmpty()) { editor.mirrorSelected(true) }
                        item("Senkrecht spiegeln", selected.isNotEmpty()) { editor.mirrorSelected(false) }
                        item("Haltestege …", shapes >= 1) { tabsOpen = true }
                        HorizontalDivider(color = Lc.line)
                        item("Vervielfältigen (Raster) …", selected.isNotEmpty()) { gridOpen = true }
                        item("Kreisanordnung …", selected.isNotEmpty()) { circleOpen = true }
                        item(if (selected.isEmpty()) "Platte platzsparend anordnen" else "Auswahl platzsparend anordnen", doc.elements.isNotEmpty()) { editor.nestSelected() }
                        HorizontalDivider(color = Lc.line)
                        item("Box mit Fingerzinken …") { boxOpen = true }
                    }
                }
                de.millione.lumacut.app.workspace.ScanMenu(machine, editor, ws, onSetup = onScan) { open ->
                    BarBtn(LcIcons.camera, "Scannen", open, menu = true, description = "Scannen: Bereiche, Motiv oder ganzer Arbeitsplatz")
                }
                Box {
                    BarBtn(null, "Mehr", { moreMenu = true }, menu = true)
                    DropdownMenu(moreMenu, { moreMenu = false }, containerColor = Lc.surface2) {
                        @Composable fun item(label: String, enabled: Boolean = true, action: () -> Unit) =
                            DropdownMenuItem(text = { Text(label) }, enabled = enabled, onClick = { moreMenu = false; action() })
                        item(if (multi) "Mehrfachauswahl aus" else "Mehrfachauswahl an") { editor.setMulti(!multi) }
                        item("Gruppieren", selected.size >= 2) { editor.groupSelected() }
                        item("Gruppe auflösen", doc.elements.any { it.id in selected && it.groupId != null }) { editor.ungroupSelected() }
                        item("Kamerafoto als Hintergrund") { cameraOpen = true }
                        item("Materialtest …") {
                            confirm = Confirm("Materialtest erstellen?", "Das aktuelle Projekt wird durch ein Testraster ersetzt (Rückgängig holt es zurück).", "Weiter") { materialTest = true }
                        }
                        item("Neues Projekt") { confirm = Confirm("Neues Projekt?", "Alle Platten und Elemente werden entfernt. Ebenen bleiben.", "Neu", danger = true) { editor.newDocument() } }
                        item("Projekt öffnen …") { projectOpener.launch(arrayOf("application/json", "*/*")) }
                        item("Projekt speichern …") { projectSaver.launch(PiClient.jobNameFrom(doc.title).removeSuffix(".gcode") + ".lumacut.json") }
                    }
                }
            }
            PlateMenu(editor)
            BarBtn(LcIcons.right, "Starten", onNext, primary = true, enabled = project.elements.isNotEmpty(), description = "Weiter: Starten")
        }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ToolColumn(tool, editor::setTool)
            Box(Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(16.dp)).background(Color(0xFF0B1015)).border(1.dp, Lc.line, RoundedCornerShape(16.dp))) {
                EditorCanvas(editor, machineStatus?.position, onText = { textAt = it })
                de.millione.lumacut.app.workspace.RunStrip(ws, Modifier.align(Alignment.BottomCenter).padding(bottom = 30.dp))
                if (tool == Tool.MEASURE) MeasureBar(editor, Modifier.align(Alignment.TopStart).padding(8.dp))
                else ToolOptions(editor, tool, Modifier.align(Alignment.TopStart).padding(8.dp).padding(end = 56.dp))
                // Shows / hides the right-hand panel (laser, layers, measurements).
                BarBtn(if (panelOpen) LcIcons.chevronRight else LcIcons.panel,
                    if (panelOpen) null else if (tool == Tool.MEASURE) "Messwerte" else "Laser & Ebenen",
                    { panelOpen = !panelOpen }, Modifier.align(Alignment.TopEnd).padding(8.dp),
                    description = if (panelOpen) "Seitenleiste ausblenden" else "Seitenleiste einblenden")
                Text(
                    when (tool) {
                        Tool.SELECT -> if (multi) "Mehrfachauswahl: Antippen fügt hinzu oder entfernt · Rahmen ziehen wählt mehrere"
                                       else "Antippen wählt · ziehen verschiebt · Rahmen ziehen wählt mehrere · ⟳ dreht · Ecke skaliert · zwei Finger zoomen"
                        Tool.PEN -> "Mit dem Finger zeichnen"
                        Tool.NODES -> "Element antippen · Punkte ziehen verschiebt sie · ziehen auf leerer Fläche verschiebt die Ansicht"
                        Tool.CURVE -> "Punkte antippen – die Kurve läuft weich hindurch · ersten Punkt erneut antippen schließt sie"
                        Tool.STAMP -> "Antippen setzt eine Kopie der Vorlage"
                        Tool.PAINT -> "Element antippen legt es auf die Ebene, die rechts gewählt ist"
                        Tool.ERASER -> "Antippen oder darüber wischen löscht Elemente"
                        Tool.TEXT -> "Antippen, wo der Text beginnen soll"
                        Tool.MEASURE -> measureHint(measureMode, measurePoints.size, measureFirst != null) + " · zwei Finger zoomen"
                        else -> "Ziehen, um ${tool.label.lowercase()} aufzuziehen · zwei Finger zoomen"
                    },
                    style = LcTypography.bodySmall, color = Lc.faint, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.align(Alignment.BottomStart).padding(horizontal = 10.dp, vertical = 6.dp),
                )
            }
            AnimatedVisibility(panelOpen, enter = expandHorizontally(), exit = shrinkHorizontally()) {
                if (tool == Tool.MEASURE) MeasurePanel(editor, Modifier.width(320.dp).fillMaxHeight())
                else Inspector(editor, Modifier.width(320.dp).fillMaxHeight(), onAdjust = { adjustOpen = true })
            }
        }
    }

    textAt?.let { at -> TextDialog(onDismiss = { textAt = null }) { text, size, bold, family, radius ->
        textAt = null
        val flat = TextPaths.build(text, size, bold, family)
        val raw = if (radius != 0.0 && flat.isNotEmpty()) de.millione.lumacut.core.ArcText.bend(flat, radius) else flat
        if (raw.isEmpty()) { editor.notify("Kein darstellbarer Text", true); return@TextDialog }
        val b = de.millione.lumacut.core.boundsOf(raw)!!
        editor.addVector("Text", raw.map { p -> p.map { Pt(it.x - b.minX + at.x, it.y - b.minY + at.y) } }, text, size, bold, family)
        editor.moveSelected(0.0, 0.0, "text")
    } }

    if (materialTest) MaterialTestDialog(onDismiss = { materialTest = false }) { spec ->
        materialTest = false
        val generated = MaterialTest.build(spec) { t, h -> TextPaths.build(t, h, true, "sans-serif") }
        editor.replaceDocument(generated)
        editor.notify("Materialtest mit ${spec.powerSteps * spec.speedSteps} Feldern erstellt")
    }

    if (cameraOpen) CameraBackgroundDialog(editor, machine) { cameraOpen = false }
    val pending by editor.pendingImport.collectAsStateWithLifecycle()
    pending?.let { ImportFitDialog(it) { editor.pendingImport.value = null } }
    if (contourOpen) ContourDialog(editor) { contourOpen = false }
    if (qrOpen) QrDialog(editor) { qrOpen = false }
    if (gridOpen) GridDialog(editor) { gridOpen = false }
    if (tabsOpen) TabsDialog(editor) { tabsOpen = false }
    if (circleOpen) CircularArrayDialog(editor) { circleOpen = false }
    if (boxOpen) BoxDialog(editor) { boxOpen = false }
    when (personal) {
        "tags" -> TagsDialog(editor) { personal = null }
        "emblem" -> EmblemDialog(editor) { personal = null }
        "frame" -> FrameDialog(editor, selected.isNotEmpty()) { personal = null }
        "ruler" -> RulerDialog(editor) { personal = null }
        "puzzle" -> PuzzleDialog(editor, selected.isNotEmpty()) { personal = null }
    }
    if (adjustOpen) {
        val picture = doc.elements.firstOrNull { it.id in selected && it.isImage }
        if (picture != null) ImageAdjustDialog(editor, picture) { adjustOpen = false } else adjustOpen = false
    }
    ConfirmDialog(confirm) { confirm = null }
}

@Composable
private fun ToolColumn(tool: Tool, onTool: (Tool) -> Unit) {
    val icons = mapOf(Tool.SELECT to LcIcons.select, Tool.NODES to LcIcons.nodes, Tool.RECT to LcIcons.rect, Tool.ELLIPSE to LcIcons.ellipse,
                      Tool.POLYGON to LcIcons.polygon, Tool.SHAPE to LcIcons.heart, Tool.LINE to LcIcons.line, Tool.CURVE to LcIcons.curve,
                      Tool.PEN to LcIcons.pen, Tool.TEXT to LcIcons.text, Tool.STAMP to LcIcons.stamp, Tool.PAINT to LcIcons.brush,
                      Tool.ERASER to LcIcons.eraser, Tool.MEASURE to LcIcons.ruler)
    // Scrolls when the screen is too short for all tools (otherwise the last one, Messen, is cut off).
    Column(
        Modifier.width(70.dp).fillMaxHeight().clip(RoundedCornerShape(16.dp)).background(Lc.surface).border(1.dp, Lc.line, RoundedCornerShape(18.dp))
            .verticalScroll(rememberScrollState()).padding(6.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp), horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        for (t in Tool.entries) {
            val on = t == tool
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(if (on) Lc.accentSoft else Color.Transparent)
                    .clickable { onTool(t) }.padding(vertical = 7.dp),
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

private enum class Drag { NONE, MOVE, BAND, ROTATE, SCALE, PAN, NODE }

/** Screen positions of the selection frame and its handles. */
private class Handles(val topLeft: Offset, val size: Size) {
    val rotate get() = Offset(topLeft.x + size.width / 2, topLeft.y - 44f)
    val scale get() = topLeft + Offset(size.width, size.height)
    companion object {
        fun of(m: WorkMapper, b: WBox): Handles {
            val a = m.at(Pt(b.minX, b.minY)); val c = m.at(Pt(b.maxX, b.maxY))
            return Handles(Offset(minOf(a.x, c.x) - 6, minOf(a.y, c.y) - 6), Size(abs(c.x - a.x) + 12, abs(c.y - a.y) + 12))
        }
    }
}

@Composable
private fun EditorCanvas(editor: EditorViewModel, head: List<Double>?, onText: (Pt) -> Unit) {
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
    var band by remember { mutableStateOf<Pair<Pt, Pt>?>(null) }
    var angleHint by remember { mutableStateOf<String?>(null) }
    var probe by remember { mutableStateOf<Offset?>(null) }
    var probeHit by remember { mutableStateOf<SnapHit?>(null) }
    val measureMode by editor.measureMode.collectAsStateWithLifecycle()
    val snapOn by editor.snapOn.collectAsStateWithLifecycle()
    val measurements by editor.measurements.collectAsStateWithLifecycle()
    val measureSel by editor.measureSelected.collectAsStateWithLifecycle()
    val pendingPoints by editor.pendingPoints.collectAsStateWithLifecycle()
    val pendingElement by editor.pendingElement.collectAsStateWithLifecycle()
    val measuring = tool == Tool.MEASURE
    val measureViews = remember(doc, measurements, measuring) { if (measuring) measurements.map { it.id to MeasureEval.eval(it, doc) } else emptyList() }
    val pointMode = measureMode == MeasureMode.DISTANCE || measureMode == MeasureMode.ANGLE
    val pen = remember { mutableStateListOf<Pt>() }
    val images = remember { HashMap<String, ImageBitmap>() }
    val curvePts by editor.curve.collectAsStateWithLifecycle()
    val shapeKind by editor.shapeKind.collectAsStateWithLifecycle()
    val sides by editor.polygonSides.collectAsStateWithLifecycle()
    val activeNode by editor.activeNode.collectAsStateWithLifecycle()

    fun mapper() = WorkMapper.fit(Size(size.width.toFloat(), size.height.toFloat()), zoom = zoom, pan = pan)

    val gestures = Modifier.pointerInput(tool) {
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false)
            val start = down.position
            var mode = 0          // 0 undecided, 1 single-finger action, 2 pinch/pan
            var drag = Drag.NONE
            var last = start
            val key = "g" + System.nanoTime()
            val slop = viewConfiguration.touchSlop
            // Handles are decided at touch-down so they win over moving the shape underneath.
            val startHandles = editor.selectionBounds()?.takeIf { tool == Tool.SELECT }?.let { Handles.of(mapper(), it) }
            val startNode = if (tool == Tool.NODES) editor.nodeAt(mapper().toWork(start), mapper().mm(24.dp.toPx()).toDouble()) else null
            if (startNode != null) editor.setActiveNode(startNode)
            fun refreshProbe(pos: Offset) {
                probe = pos
                val mm = mapper()
                val pm = editor.measureMode.value
                probeHit = if (pm == MeasureMode.DISTANCE || pm == MeasureMode.ANGLE) editor.snapAt(mm.toWork(pos), mm.mm(24.dp.toPx()).toDouble()) else null
            }
            if (tool == Tool.MEASURE) refreshProbe(start)
            val pivot = editor.selectionBounds()?.center
            val anchor = editor.selectionBounds()?.let { Pt(it.minX, it.minY) }
            do {
                val event = awaitPointerEvent()
                val pressed = event.changes.filter { it.pressed }
                if (pressed.size >= 2) {
                    if (mode == 1) { draftStart = null; draftEnd = null; pen.clear(); band = null; angleHint = null }
                    mode = 2
                    probe = null; probeHit = null
                    val m = mapper()
                    val z = event.calculateZoom(); val p = event.calculatePan(); val c = event.calculateCentroid()
                    val newZoom = (zoom * z).coerceIn(0.6f, 12f); val k = newZoom / zoom
                    val ox2 = c.x - (c.x - m.ox) * k + p.x; val oy2 = c.y - (c.y - m.oy) * k + p.y
                    val base = WorkMapper.fit(Size(size.width.toFloat(), size.height.toFloat()), zoom = newZoom)
                    zoom = newZoom
                    pan = Offset(ox2 - base.ox, oy2 - base.oy)
                    event.changes.forEach { it.consume() }
                } else if (pressed.size == 1 && mode != 2) {
                    val pos = pressed.first().position
                    if (tool == Tool.MEASURE && mode != 2) refreshProbe(pos)
                    if (mode == 0 && (pos - start).getDistance() > slop) {
                        mode = 1
                        val m = mapper(); val p0 = m.toWork(start)
                        when (tool) {
                            Tool.SELECT -> {
                                drag = when {
                                    startHandles != null && (start - startHandles.rotate).getDistance() < 40f -> Drag.ROTATE
                                    startHandles != null && (start - startHandles.scale).getDistance() < 40f -> Drag.SCALE
                                    else -> {
                                        val hit = editor.hit(p0, m.mm(24f).toDouble())
                                        if (hit != null) {
                                            if (hit.id !in editor.selected.value) editor.select(hit.id)
                                            Drag.MOVE
                                        } else { band = p0 to p0; Drag.BAND }
                                    }
                                }
                            }
                            Tool.PEN -> { pen.clear(); pen.add(p0) }
                            Tool.TEXT, Tool.CURVE, Tool.STAMP, Tool.PAINT -> drag = Drag.PAN
                            Tool.NODES -> drag = if (startNode != null) Drag.NODE else Drag.PAN
                            Tool.ERASER -> editor.eraseAt(p0, m.mm(16f).toDouble(), key)
                            Tool.MEASURE -> {}
                            else -> { draftStart = p0; draftEnd = p0 }
                        }
                    }
                    if (mode == 1) {
                        val m = mapper()
                        val a = m.toWork(last); val b = m.toWork(pos)
                        when (tool) {
                            Tool.SELECT -> { when (drag) {
                                Drag.MOVE -> editor.moveSelected(b.x - a.x, b.y - a.y, key)
                                Drag.BAND -> band = band?.first?.let { it to b }
                                Drag.ROTATE -> if (pivot != null) {
                                    var d = Math.toDegrees(atan2(b.y - pivot.y, b.x - pivot.x) - atan2(a.y - pivot.y, a.x - pivot.x))
                                    if (d > 180) d -= 360; if (d < -180) d += 360
                                    editor.rotateSelectionBy(d, pivot, key)
                                    angleHint = editor.selectedElement()?.let { "%.1f°".format(it.transform.rotation) }
                                }
                                Drag.SCALE -> if (anchor != null) {
                                    val d0 = hypot(a.x - anchor.x, a.y - anchor.y); val d1 = hypot(b.x - anchor.x, b.y - anchor.y)
                                    if (d0 > 0.5) editor.scaleSelectionBy(d1 / d0, anchor, key)
                                    angleHint = editor.selectionBounds()?.let { "%.1f × %.1f mm".format(it.width, it.height) }
                                }
                                else -> pan += pos - last
                            } }
                            Tool.PEN -> pen.add(b)
                            Tool.TEXT, Tool.CURVE, Tool.STAMP, Tool.PAINT -> pan += pos - last
                            Tool.NODES -> if (drag == Drag.NODE && startNode != null) editor.moveNode(startNode, b, key) else pan += pos - last
                            Tool.ERASER -> editor.eraseAt(b, m.mm(16f).toDouble(), key)
                            Tool.MEASURE -> {}
                            else -> draftEnd = b
                        }
                        pressed.first().consume()
                    }
                    last = pos
                }
            } while (event.changes.any { it.pressed })
            val m = mapper()
            if (tool == Tool.MEASURE) {
                val pr = probe
                if (mode != 2 && pr != null) editor.measureTap(m.toWork(pr), probeHit, m.mm(24.dp.toPx()).toDouble())
                probe = null; probeHit = null
                return@awaitEachGesture
            }
            if (mode == 0) {
                val p = m.toWork(start)
                when (tool) {
                    Tool.SELECT -> editor.select(editor.hit(p, m.mm(24f).toDouble())?.id)
                    Tool.TEXT -> if (Work.contains(p)) onText(p) else editor.notify("Text bitte im Arbeitsbereich beginnen", true)
                    Tool.NODES -> if (startNode == null) { editor.setActiveNode(null); editor.select(editor.hit(p, m.mm(24f).toDouble())?.id, false) }
                    Tool.CURVE -> editor.curveTap(p, m.mm(30f).toDouble())
                    Tool.STAMP -> if (Work.contains(p)) editor.stampAt(p)
                    Tool.PAINT -> editor.paintAt(p, m.mm(24f).toDouble())
                    Tool.ERASER -> editor.eraseAt(p, m.mm(24f).toDouble(), key)
                    else -> {}
                }
            } else if (mode == 1) {
                when (tool) {
                    Tool.PEN -> if (pen.size > 2) editor.addVector("Freihand", listOf(simplify(pen.toList(), 0.15)))
                    Tool.SELECT -> {
                        band?.let { (a, b) -> editor.selectIn(WBox(minOf(a.x, b.x), minOf(a.y, b.y), maxOf(a.x, b.x), maxOf(a.y, b.y))) }
                        if (drag == Drag.ROTATE || drag == Drag.SCALE) editor.keepInside(key)
                    }
                    Tool.TEXT, Tool.NODES, Tool.CURVE, Tool.STAMP, Tool.PAINT, Tool.ERASER -> {}
                    else -> {
                        val a = draftStart; val b = draftEnd
                        if (a != null && b != null) shapeFromDrag(tool, clampWork(a), clampWork(b), editor.shapeKind.value, editor.polygonSides.value)
                            ?.let { editor.addVector(if (tool == Tool.SHAPE) editor.shapeKind.value.label else tool.label, listOf(it)) }
                    }
                }
                draftStart = null; draftEnd = null; pen.clear(); band = null; angleHint = null
            }
        }
    }

    Canvas(Modifier.fillMaxSize().onSizeChanged { size = it }.then(gestures)) {
        if (size == IntSize.Zero) return@Canvas
        val m = mapper()
        fun DrawScope.scene() {
        drawWorkArea(m)
        background?.let { bmp ->
            val a = m.at(Pt(0.0, 0.0)); val b = m.at(Pt(Work.WIDTH, Work.HEIGHT))
            drawImage(bmp, dstOffset = IntOffset(a.x.roundToInt(), a.y.roundToInt()),
                dstSize = IntSize((b.x - a.x).roundToInt(), (b.y - a.y).roundToInt()), alpha = bgAlpha)
        }
        for (e in doc.elements) {
            val layer = doc.layer(e.layerId) ?: continue
            if (!layer.visible) continue
            val alpha = when { !layer.output -> .35f; layer.locked -> .6f; else -> 1f }
            val color = Color(layer.color.toInt()).copy(alpha = alpha)
            if (e.isImage) {
                val r = e.raster ?: continue
                val img = images.getOrPut(e.id + r.hashCode()) { Images.toBitmap(r).asImageBitmap() }
                val bx = e.worldBounds() ?: continue
                val a = m.at(Pt(bx.minX, bx.minY)); val c = m.at(Pt(bx.maxX, bx.maxY))
                drawImage(img, dstOffset = IntOffset(a.x.roundToInt(), a.y.roundToInt()),
                    dstSize = IntSize((c.x - a.x).roundToInt().coerceAtLeast(1), (c.y - a.y).roundToInt().coerceAtLeast(1)), alpha = .9f * alpha)
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
        // selection: frame per element, handles on the whole selection
        val sel = doc.elements.filter { it.id in selected }
        if (sel.size > 1) for (e in sel) e.worldBounds()?.let { b ->
            val h = Handles.of(m, b)
            drawRect(Lc.accent.copy(alpha = .45f), h.topLeft, h.size, style = Stroke(1f))
        }
        sel.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) }?.let { b ->
            val h = Handles.of(m, b)
            val outside = !Work.contains(b)
            val c = if (outside) Lc.bad else Lc.accent
            drawRect(c, h.topLeft, h.size, style = Stroke(2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
            for (corner in listOf(h.topLeft, h.topLeft + Offset(h.size.width, 0f), h.topLeft + Offset(0f, h.size.height))) drawCircle(c, 6f, corner)
            drawRect(c, h.scale - Offset(11f, 11f), Size(22f, 22f))
            if (sel.any { !it.isImage }) {
                drawLine(c, Offset(h.rotate.x, h.topLeft.y), h.rotate, 2f)
                drawCircle(Lc.bg, 14f, h.rotate); drawCircle(c, 14f, h.rotate, style = Stroke(3f))
            }
        }
        band?.let { (a0, b0) ->
            val a = m.at(a0); val b = m.at(b0)
            val tl = Offset(minOf(a.x, b.x), minOf(a.y, b.y)); val sz = Size(abs(b.x - a.x), abs(b.y - a.y))
            drawRect(Lc.accent.copy(alpha = .1f), tl, sz)
            drawRect(Lc.accent, tl, sz, style = Stroke(1.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 6f))))
        }
        val a = draftStart; val b = draftEnd
        if (a != null && b != null) shapeFromDrag(tool, clampWork(a), clampWork(b), shapeKind, sides)?.let { poly ->
            val path = Path().apply { val p0 = m.at(poly.first()); moveTo(p0.x, p0.y); poly.drop(1).forEach { val q = m.at(it); lineTo(q.x, q.y) } }
            drawPath(path, Lc.accent, style = Stroke(2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 6f))))
        }
        if (pen.size > 1) {
            val path = Path().apply { val p0 = m.at(pen.first()); moveTo(p0.x, p0.y); pen.drop(1).forEach { val q = m.at(it); lineTo(q.x, q.y) } }
            drawPath(path, Lc.accent, style = Stroke(2.5f, cap = StrokeCap.Round))
        }
        if (tool == Tool.CURVE && curvePts.isNotEmpty()) {
            val smooth = Curves.catmullRom(curvePts, false)
            val path = Path().apply { val p0 = m.at(smooth.first()); moveTo(p0.x, p0.y); smooth.drop(1).forEach { val q = m.at(it); lineTo(q.x, q.y) } }
            drawPath(path, Lc.accent, style = Stroke(2.5f, cap = StrokeCap.Round))
            curvePts.forEachIndexed { i, q -> val o = m.at(q); drawCircle(Lc.bg, 9f, o); drawCircle(if (i == 0) Lc.warn else Lc.accent, 7f, o) }
        }
        if (tool == Tool.NODES) editor.editableNodes()?.takeIf { it.id in selected }?.let { e ->
            e.worldPaths().forEachIndexed { pi, poly -> poly.forEachIndexed { i, q ->
                val o = m.at(q); val on = activeNode?.let { it.elementId == e.id && it.poly == pi && it.index == i } == true
                drawRect(Lc.bg, o - Offset(7f, 7f), Size(14f, 14f))
                drawRect(if (on) Lc.warn else Lc.accent, o - Offset(5f, 5f), Size(10f, 10f), style = if (on) androidx.compose.ui.graphics.drawscope.Fill else Stroke(2f))
            } }
        }
        drawHead(m, head)
        }
        scene()
        fun DrawScope.measureLayer() {
            drawMeasurements(m, measureViews, measureSel)
            val pts = pendingPoints.map { m.at(it.p) }
            pts.zipWithNext().forEach { (a, b) -> drawLine(Lc.accent, a, b, 2f) }
            pts.forEach { drawCircle(Lc.bg, 8f, it); drawCircle(Lc.accent, 6f, it) }
            pendingElement?.let { id ->
                doc.elements.firstOrNull { it.id == id }?.worldBounds()?.let { b ->
                    val a = m.at(Pt(b.minX, b.minY)); val c = m.at(Pt(b.maxX, b.maxY))
                    drawRect(Lc.accent, a, Size(c.x - a.x, c.y - a.y), style = Stroke(2.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
                }
            }
            val pr = probe
            if (pr != null && pointMode) pts.lastOrNull()?.let { last ->
                drawLine(Lc.accent.copy(alpha = .8f), last, probeHit?.let { m.at(it.p) } ?: pr, 2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 6f)))
            }
        }
        if (measuring) {
            measureLayer()
            val pr = probe
            if (pr != null && pointMode) {
                probeHit?.let { drawSnapMarker(m.at(it.p), it.kind) }
                drawLoupe(pr, probeHit, probeHit?.let { m.at(it.p) }, snapOn, 64.dp.toPx()) { scene(); measureLayer() }
            }
        }
    }
    angleHint?.let { Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) { Banner(it, Lc.accent, Modifier.padding(12.dp)) } }
}

private fun clampWork(p: Pt) = Pt(p.x.coerceIn(0.0, Work.WIDTH), p.y.coerceIn(0.0, Work.HEIGHT))

/** World polygon for a drag from [a] to [b]. */
private fun shapeFromDrag(tool: Tool, a: Pt, b: Pt, kind: ShapeKind, sides: Int): Poly? {
    val x = minOf(a.x, b.x); val y = minOf(a.y, b.y); val w = abs(b.x - a.x); val h = abs(b.y - a.y)
    if (tool == Tool.LINE) return if (a.dist(b) < 0.5) null else listOf(a, b)
    if (w < 0.5 || h < 0.5) return null
    val local = when (tool) {
        Tool.RECT -> Shapes.rect(w, h)
        Tool.ELLIPSE -> Shapes.ellipse(w, h)
        Tool.POLYGON -> Shapes.polygon(sides, w, h)
        Tool.SHAPE -> ShapeLib.make(kind, w, h)
        else -> return null
    }
    return local.map { Pt(it.x + x, it.y + y) }
}

/* ---------- inspector ---------- */

@Composable
private fun Inspector(editor: EditorViewModel, modifier: Modifier, onAdjust: () -> Unit) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val selected by editor.selected.collectAsStateWithLifecycle()
    val active by editor.activeLayer.collectAsStateWithLifecycle()
    val background by editor.background.collectAsStateWithLifecycle()
    val bgAlpha by editor.backgroundAlpha.collectAsStateWithLifecycle()
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        val sel = doc.elements.filter { it.id in selected }
        when {
            sel.size == 1 -> SelectionCard(editor, sel.first(), onAdjust)
            sel.size > 1 -> MultiCard(editor, sel)
        }
        LaserCard(editor, doc, sel, active)
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
private fun NudgePad(editor: EditorViewModel) {
    var step by remember { mutableStateOf(1.0) }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        IconBtn(LcIcons.left, "Links", { editor.nudge(-step, 0.0) })
        IconBtn(LcIcons.up, "Hoch", { editor.nudge(0.0, -step) })
        IconBtn(LcIcons.down, "Runter", { editor.nudge(0.0, step) })
        IconBtn(LcIcons.right, "Rechts", { editor.nudge(step, 0.0) })
        Segmented(listOf(0.1 to "0,1", 1.0 to "1", 10.0 to "10"), step, { step = it }, Modifier.weight(1f))
    }
}

@Composable
private fun SelectionCard(editor: EditorViewModel, e: Element, onAdjust: () -> Unit) {
    val b = e.worldBounds() ?: return
    LcCard(padding = 16.dp, accent = Lc.accent) {
        Text(e.text?.let { "Text: $it" } ?: e.kind, style = LcTypography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (e.groupId != null) SmallText("Teil einer Gruppe", Lc.faint)
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Num("Drehung", e.transform.rotation, Modifier.weight(1f), suffix = "°") { editor.rotateSelected(it) }
                IconBtn(LcIcons.rotate, "90° drehen", { editor.rotateSelected((e.transform.rotation + 90) % 360) })
            }
        } else {
            val r = e.raster
            if (r != null) {
                val dpi = r.width / (e.imageWidthMm * e.transform.scaleX / 25.4)
                Num("Auflösung", dpi, Modifier.fillMaxWidth(), suffix = "dpi") { editor.setImageDpi(e.id, it) }
                SmallText("${r.width} × ${r.height} px · Größe folgt der Auflösung. Gelasert wird im Zeilenabstand der Ebene.", Lc.faint)
            }
            Spacer(Modifier.height(4.dp))
            LcButton("Bild anpassen …", onAdjust, Modifier.fillMaxWidth(), icon = LcIcons.image)
            SmallText("Aktuell: " + when (e.imageMode) {
                ImageMode.GRAYSCALE -> "Graustufen"; ImageMode.DITHER -> "Floyd-Steinberg"; ImageMode.DITHER_JARVIS -> "Jarvis"
                ImageMode.DITHER_STUCKI -> "Stucki"; ImageMode.THRESHOLD -> "Schwarz/Weiß" }, Lc.faint)
        }
        Spacer(Modifier.height(8.dp))
        NudgePad(editor)
        Spacer(Modifier.height(8.dp))
        AlignRows(editor, 1)
        if (!Work.contains(b)) { Spacer(Modifier.height(8.dp)); Banner("Liegt nicht vollständig im Arbeitsbereich (360 × 340 mm) – so wird nicht gelasert.", Lc.bad) }
    }
}

@Composable
private fun MultiCard(editor: EditorViewModel, sel: List<Element>) {
    val b = sel.mapNotNull { it.worldBounds() }.reduceOrNull { x, y -> x.union(y) } ?: return
    val grouped = sel.all { it.groupId != null } && sel.map { it.groupId }.distinct().size == 1
    LcCard(padding = 16.dp, accent = Lc.accent) {
        Text(if (grouped) "Gruppe · ${sel.size} Elemente" else "${sel.size} Elemente", style = LcTypography.titleLarge)
        SmallText("%.1f × %.1f mm".format(b.width, b.height), Lc.faint)
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Num("X", b.minX, Modifier.weight(1f)) { editor.placeSelected(it, null) }
            Num("Y", b.minY, Modifier.weight(1f)) { editor.placeSelected(null, it) }
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (grouped) LcButton("Gruppe auflösen", editor::ungroupSelected, Modifier.weight(1f), LcIcons.ungroup)
            else LcButton("Gruppieren", editor::groupSelected, Modifier.weight(1f), LcIcons.group)
            LcButton("90°", { b.center.let { editor.rotateSelectionBy(90.0, it, "r90"); editor.keepInside("r90") } }, Modifier.weight(1f), LcIcons.rotate)
        }
        Spacer(Modifier.height(8.dp))
        NudgePad(editor)
        Spacer(Modifier.height(8.dp))
        AlignRows(editor, sel.map { it.groupId ?: it.id }.distinct().size)
        if (!Work.contains(b)) { Spacer(Modifier.height(8.dp)); Banner("Liegt nicht vollständig im Arbeitsbereich (360 × 340 mm).", Lc.bad) }
    }
}

/** Numeric field that commits valid numbers as you type. */
@Composable
internal fun Num(label: String, value: Double, modifier: Modifier, suffix: String = "mm", onValue: (Double) -> Unit) {
    fun fmt(v: Double) = "%.1f".format(java.util.Locale.ROOT, v)
    var text by remember { mutableStateOf(fmt(value)) }
    var focused by remember { mutableStateOf(false) }
    // Follow outside changes (dragging, undo) but never overwrite what is being typed.
    LaunchedEffect(value) { if (!focused) text = fmt(value) }
    NumberField(label, text, { t -> text = t; t.replace(',', '.').toDoubleOrNull()?.let(onValue) },
        modifier.onFocusChanged { focused = it.isFocused }, suffix)
}

/* ---------- dialogs ---------- */

@Composable
private fun TextDialog(onDismiss: () -> Unit, onOk: (String, Double, Boolean, String, Double) -> Unit) {
    var text by remember { mutableStateOf("LumaCut") }
    var size by remember { mutableStateOf("15") }
    var bold by remember { mutableStateOf(true) }
    var family by remember { mutableStateOf("sans-serif") }
    var radius by remember { mutableStateOf("0") }
    val radiusMm = radius.replace(',', '.').toDoubleOrNull()
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Text einfügen", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(text, { text = it }, label = { Text("Text (mehrzeilig möglich)") }, modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp), colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Lc.accent))
                NumberField("Schriftgröße", size, { size = it }, Modifier.fillMaxWidth(), "mm")
                Segmented(Fonts.families, family, { family = it })
                NumberField("Auf dem Bogen: Radius (0 = gerade, minus = unten)", radius, { radius = it }, Modifier.fillMaxWidth(), "mm")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(bold, { bold = it }, colors = CheckboxDefaults.colors(checkedColor = Lc.accent, checkmarkColor = Lc.accentInk)); Text("Fett")
                }
            }
        },
        confirmButton = { LcButton("Einfügen", { size.replace(',', '.').toDoubleOrNull()?.takeIf { it in 1.0..300.0 }?.let { s -> radiusMm?.let { r -> onOk(text, s, bold, family, r) } } }, kind = BtnKind.PRIMARY, enabled = text.isNotBlank() && radiusMm != null && (radiusMm == 0.0 || kotlin.math.abs(radiusMm) >= 1.0)) },
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
    fun d(s: String) = s.replace(',', '.').toDouble()
    val spec = runCatching {
        MaterialTest.Spec(
            powerFrom = d(pFrom), powerTo = d(pTo), powerSteps = pSteps.toInt(),
            speedFrom = d(sFrom), speedTo = d(sTo), speedSteps = sSteps.toInt(),
            mode = mode, cellMm = d(cell).coerceIn(3.0, 40.0), intervalMm = d(interval).coerceIn(0.03, 2.0),
        )
    }.getOrNull()
    val valid = spec != null && spec.powerSteps in 1..10 && spec.speedSteps in 1..10 &&
        spec.powerFrom in Limits.POWER && spec.powerTo in Limits.POWER && spec.speedFrom in Limits.SPEED && spec.speedTo in Limits.SPEED
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = Lc.surface, shape = RoundedCornerShape(24.dp),
        title = { Text("Materialtest", style = LcTypography.titleLarge) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SmallText("Raster aus Leistung (Spalten) × Tempo (Zeilen, bis zum Maschinenlimit aus der Bewegungs-Kalibrierung). Jedes Feld bekommt eine eigene Ebene, die Beschriftung wird leicht graviert.")
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
