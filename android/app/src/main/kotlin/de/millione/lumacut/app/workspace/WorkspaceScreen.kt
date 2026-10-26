package de.millione.lumacut.app.workspace

import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.material3.Icon
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
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.editor.MarkerCanvas
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
import de.millione.lumacut.app.ui.Progress
import de.millione.lumacut.app.ui.Segmented
import de.millione.lumacut.app.ui.SmallText
import de.millione.lumacut.app.ui.WorkMapper
import de.millione.lumacut.app.ui.drawHead
import de.millione.lumacut.app.ui.drawWorkArea
import de.millione.lumacut.app.ui.rememberConfirm
import de.millione.lumacut.core.Box as WBox
import de.millione.lumacut.core.Frame
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Work
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

@Composable
fun WorkspaceScreen(machine: MachineViewModel, editor: EditorViewModel, ws: WorkspaceViewModel = viewModel()) {
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val heights by editor.heights.collectAsStateWithLifecycle()
    val background by editor.background.collectAsStateWithLifecycle()
    val doc by editor.doc.collectAsStateWithLifecycle()
    val cal by ws.calibration.collectAsStateWithLifecycle()
    val areas by ws.areas.collectAsStateWithLifecycle()
    val spacing by ws.spacing.collectAsStateWithLifecycle()
    val run by ws.run.collectAsStateWithLifecycle()
    val done by ws.done.collectAsStateWithLifecycle()
    var marking by remember { mutableStateOf(false) }
    var calibrating by remember { mutableStateOf(false) }
    var confirm by rememberConfirm()

    val ready = status.canControl(online) && run == null
    val homed = status?.homed == true
    val camera = status?.camera?.available == true
    val surfaceKnown = status?.workpiece_surface_z != null

    Row(Modifier.fillMaxSize().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Segmented(listOf(false to "Ansehen", true to "Bereiche markieren"), marking, { marking = it }, Modifier.width(360.dp))
                SmallText(if (marking) "Rahmen ziehen fügt einen Bereich hinzu · Antippen entfernt ihn" else "Kamera-Scan, Motiv, Bereiche und Höhenmesh im Arbeitsbereich", Lc.faint)
            }
            Box(Modifier.weight(1f).fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(Color(0xFF0B1015)).border(1.dp, Lc.line, RoundedCornerShape(18.dp))) {
                WorkspaceCanvas(editor, ws, status?.position, marking)
            }
        }
        Column(Modifier.width(390.dp).fillMaxHeight().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            run?.let { r ->
                LcCard(padding = 16.dp, accent = Lc.accent) {
                    Text(r.title, style = LcTypography.titleMedium)
                    SmallText(r.text)
                    Spacer(Modifier.height(8.dp))
                    Progress(r.fraction, Modifier.fillMaxWidth(), thick = true)
                    Spacer(Modifier.height(10.dp))
                    LcButton("Abbrechen", { ws.cancel() }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER)
                }
            }
            LcCard(padding = 16.dp) {
                Text("Geführter Ablauf", style = LcTypography.titleLarge)
                SmallText("Von oben nach unten. Der Laser ist bei allem außer „Auftrag“ aus.", Lc.faint)
                Spacer(Modifier.height(12.dp))
                Step(1, "Referenzieren", homed, if (homed) "Maschine referenziert" else "X/Y, dann Z, dann Rückzug") {
                    LcButton("Referenzieren", { machine.action("home", success = "Referenziert") }, icon = LcIcons.home,
                        busy = "home" in busy, enabled = ready)
                }
                Step(2, "Arbeitsfläche scannen", "scan" in done, when {
                    !camera -> "Keine Kamera am Pi (USB-Kamera am Kopf anschließen, LUMACUT_CAMERA)"
                    cal == null -> "Kopfkamera einmalig kalibrieren"
                    else -> "Kamerabilder werden zu einem maßstäblichen Hintergrund zusammengesetzt"
                }) {
                    LcButton("Scannen", { ws.scan(machine, editor) }, icon = LcIcons.scan, enabled = ready && homed && camera && cal != null)
                    LcButton(if (cal == null) "Kalibrieren" else "Neu kalibrieren", { calibrating = true }, icon = LcIcons.camera,
                        kind = BtnKind.GHOST, enabled = camera)
                }
                Step(3, "Werkstücke markieren", areas.isNotEmpty(), if (areas.isEmpty()) "Bereiche, in denen gemessen wird" else "${areas.size} Bereich(e) markiert") {
                    LcButton("Aus Motiv", { val n = ws.areasFromDesign(doc); machine.notify(if (n == 0) "Kein Motiv im Editor" else "$n Bereich(e) aus dem Motiv") },
                        icon = LcIcons.rect, enabled = doc.elements.isNotEmpty())
                    LcButton("Leeren", { ws.clearAreas() }, kind = BtnKind.GHOST, enabled = areas.isNotEmpty())
                }
                Step(4, "Abtasten", heights != null || surfaceKnown, when {
                    heights != null -> "Höhenmesh: %.2f … %.2f mm".format(heights?.lowest ?: 0.0, heights?.highest ?: 0.0)
                    surfaceKnown -> "Oberfläche Z %.2f mm".format(status?.workpiece_surface_z ?: 0.0)
                    else -> "Höhenmesh über die Bereiche oder ein Punkt in der Motivmitte"
                }) {
                    LcButton("Höhenmesh", { ws.probeMesh(machine, editor) }, icon = LcIcons.mesh, enabled = ready && homed)
                    LcButton("Nur Mitte", { ws.probeCentre(machine, editor) }, icon = LcIcons.probe, kind = BtnKind.GHOST,
                        busy = "probe" in busy, enabled = ready && homed)
                }
                Row(Modifier.padding(start = 40.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    var text by remember(spacing) { mutableStateOf(spacing.roundToInt().toString()) }
                    NumberField("Rasterabstand", text, { t -> text = t; t.toDoubleOrNull()?.let(ws::setSpacing) }, Modifier.width(150.dp), "mm")
                    if (heights != null) LcButton("Mesh löschen", { editor.setHeights(null) }, kind = BtnKind.GHOST)
                }
                Step(5, "Fokus", surfaceKnown, when {
                    heights != null -> "Fokus folgt dem Höhenmesh je 2-mm-Stück (Oberfläche + %.1f mm)".format((status?.config?.focus_gap_mm ?: 7.0) - (status?.config?.z_switch_tip_offset_mm ?: 1.5))
                    surfaceKnown -> "Fokus Z %.2f mm – wird vor dem ersten Laserweg angefahren".format(status?.laser_focus_z ?: 0.0)
                    else -> "Ergibt sich aus dem Abtasten"
                }) {}
                Step(6, "Rahmen", "frame" in done, "Umriss mit ausgeschaltetem Laser abfahren") {
                    LcButton("Rahmen", { ws.frame(machine, editor, Frame.Mode.BOX) }, icon = LcIcons.rect, busy = "frame" in busy,
                        enabled = ready && homed && doc.elements.isNotEmpty())
                    LcButton("Gummiband", { ws.frame(machine, editor, Frame.Mode.HULL) }, icon = LcIcons.polygon, kind = BtnKind.GHOST,
                        enabled = ready && homed && doc.elements.isNotEmpty())
                }
                val job = status?.job
                Step(7, "Auftrag", "job" in done && job?.active != true, when {
                    job?.active == true -> "Läuft · ${((job?.fraction ?: 0.0) * 100).toInt()} %"
                    heights != null -> "Mit Höhenkorrektur aus dem Mesh"
                    else -> "Auftrag aus dem Editor senden und starten"
                }) {
                    LcButton("Starten", {
                        confirm = Confirm("Auftrag starten?", "„${doc.title}“\n\n" +
                            (if (heights != null) "Fokus folgt dem Höhenmesh." else "Fokus auf die abgetastete Oberfläche.") +
                            "\nAbluft an, Arbeitsbereich frei, Schutzbrille?", "Starten") { ws.startJob(machine, editor) }
                    }, icon = LcIcons.laser, kind = BtnKind.PRIMARY, busy = "start" in busy,
                        enabled = ready && homed && surfaceKnown && doc.elements.isNotEmpty())
                    if (job?.active == true) LcButton("Abbrechen", { machine.action("abort") }, kind = BtnKind.DANGER, busy = "abort" in busy)
                }
                Step(8, "Parken", false, "Laser aus, Z hoch, Kopf in die Parkposition", last = true) {
                    LcButton("Parken", { machine.action("park") }, icon = LcIcons.park, busy = "park" in busy, enabled = ready && homed)
                }
            }
            if (background != null) SmallText("Hintergrund liegt auch im Editor unter dem Motiv (Deckkraft dort einstellbar).", Lc.faint)
        }
    }
    if (calibrating) CalibrationDialog(machine, ws) { calibrating = false }
    ConfirmDialog(confirm) { confirm = null }
}

@Composable
private fun Step(n: Int, title: String, ok: Boolean, text: String, last: Boolean = false, actions: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(bottom = if (last) 0.dp else 12.dp)) {
        Box(Modifier.size(28.dp).clip(CircleShape).background(if (ok) Lc.ok.copy(alpha = .2f) else Lc.surface3), contentAlignment = Alignment.Center) {
            if (ok) Icon(LcIcons.check, null, tint = Lc.ok, modifier = Modifier.size(16.dp))
            else Text("$n", style = LcTypography.labelMedium, color = Lc.muted)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = LcTypography.titleMedium, fontWeight = FontWeight.SemiBold)
            SmallText(text, if (ok) Lc.muted else Lc.faint)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { actions() }
        }
    }
}

/** Work area with scan mosaic, motif outline, marked areas and height mesh. */
@Composable
private fun WorkspaceCanvas(editor: EditorViewModel, ws: WorkspaceViewModel, head: List<Double>?, marking: Boolean) {
    val doc by editor.doc.collectAsStateWithLifecycle()
    val background by editor.background.collectAsStateWithLifecycle()
    val heights by editor.heights.collectAsStateWithLifecycle()
    val areas by ws.areas.collectAsStateWithLifecycle()
    var size by remember { mutableStateOf(IntSize.Zero) }
    var drag by remember { mutableStateOf<Pair<Pt, Pt>?>(null) }
    fun mapper() = WorkMapper.fit(Size(size.width.toFloat(), size.height.toFloat()))
    val input = if (!marking) Modifier else Modifier
        .pointerInput(Unit) { detectTapGestures { ws.removeAreaAt(mapper().toWork(it)) } }
        .pointerInput(Unit) {
            detectDragGestures(
                onDragStart = { o -> val p = mapper().toWork(o); drag = p to p },
                onDragEnd = { drag?.let { (a, b) -> ws.addArea(WBox(minOf(a.x, b.x), minOf(a.y, b.y), maxOf(a.x, b.x), maxOf(a.y, b.y))) }; drag = null },
                onDragCancel = { drag = null },
            ) { change, _ -> change.consume(); drag = drag?.first?.let { it to mapper().toWork(change.position) } }
        }
    Canvas(Modifier.fillMaxSize().onSizeChanged { size = it }.then(input)) {
        if (size == IntSize.Zero) return@Canvas
        val m = mapper()
        drawWorkArea(m)
        background?.let { bmp ->
            val a = m.at(Pt(0.0, 0.0)); val b = m.at(Pt(Work.WIDTH, Work.HEIGHT))
            drawImage(bmp, dstOffset = IntOffset(a.x.roundToInt(), a.y.roundToInt()), dstSize = IntSize((b.x - a.x).roundToInt(), (b.y - a.y).roundToInt()))
        }
        for (e in doc.elements) {
            val layer = doc.layer(e.layerId) ?: continue
            if (!layer.visible) continue
            val color = Color(layer.color.toInt()).copy(alpha = if (layer.output) .9f else .3f)
            if (e.isImage) {
                e.worldBounds()?.let { b -> val a = m.at(Pt(b.minX, b.minY)); val c = m.at(Pt(b.maxX, b.maxY)); drawRect(color, a, Size(c.x - a.x, c.y - a.y), style = Stroke(1.5f)) }
                continue
            }
            val path = Path().apply {
                for (poly in e.worldPaths()) if (poly.isNotEmpty()) {
                    val p0 = m.at(poly.first()); moveTo(p0.x, p0.y)
                    for (p in poly.drop(1)) { val q = m.at(p); lineTo(q.x, q.y) }
                }
            }
            drawPath(path, color, style = Stroke(1.5f))
        }
        val dash = PathEffect.dashPathEffect(floatArrayOf(10f, 7f))
        for (b in areas + listOfNotNull(drag?.let { (a, c) -> WBox(minOf(a.x, c.x), minOf(a.y, c.y), maxOf(a.x, c.x), maxOf(a.y, c.y)) })) {
            val a = m.at(Pt(b.minX, b.minY)); val c = m.at(Pt(b.maxX, b.maxY))
            drawRect(Lc.info.copy(alpha = .10f), a, Size(c.x - a.x, c.y - a.y))
            drawRect(Lc.info, a, Size(c.x - a.x, c.y - a.y), style = Stroke(2f, pathEffect = dash))
        }
        heights?.let { set ->
            val lo = set.lowest ?: return@let; val hi = set.highest ?: return@let
            for (map in set.maps) for ((idx, p) in map.points()) {
                val z = map.z[idx]
                val t = if (hi - lo < 1e-6) 0.5f else ((z - lo) / (hi - lo)).toFloat()
                val c = lerp(Color(0xFF4FA3FF), Color(0xFFFFA24F), t)
                drawCircle(c.copy(alpha = .85f), 9f, m.at(p))
                drawCircle(Color.Black.copy(alpha = .4f), 9f, m.at(p), style = Stroke(1f))
            }
        }
        drawHead(m, head)
    }
}

@Composable
private fun CalibrationDialog(machine: MachineViewModel, ws: WorkspaceViewModel, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    val busy by machine.busy.collectAsStateWithLifecycle()
    var photo by remember { mutableStateOf<Bitmap?>(null) }
    var loading by remember { mutableStateOf(false) }
    val markers = remember { mutableStateListOf<Offset>() }
    fun grab() {
        val c = machine.clientOrNotify() ?: return
        loading = true
        scope.launch {
            try {
                val bmp = ws.snapshot(c)
                if (photo == null || markers.size != 4) {
                    markers.clear()
                    val w = bmp.width.toFloat(); val h = bmp.height.toFloat()
                    markers.addAll(listOf(Offset(w * .3f, h * .3f), Offset(w * .7f, h * .3f), Offset(w * .7f, h * .7f), Offset(w * .3f, h * .7f)))
                }
                photo = bmp
            } catch (e: Exception) { machine.notify(e.message ?: "Kein Kamerabild", true) } finally { loading = false }
        }
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Row(Modifier.fillMaxSize().background(Lc.bg).padding(20.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            LcCard(Modifier.width(380.dp).fillMaxHeight()) {
                Text("Kopfkamera kalibrieren", style = LcTypography.headlineSmall)
                Spacer(Modifier.height(8.dp))
                SmallText("1. Kalibrier-Rechteck (60 × 40 mm, Mitte des Arbeitsbereichs) auf Restmaterial lasern.\n2. Kopf darüber fahren, bis das ganze Rechteck im Bild ist.\n3. Die vier Marker auf die nummerierten Ecken ziehen.\n4. Speichern. Danach nicht mehr in Z verstellen – der Scan nutzt dieselbe Höhe.")
                Spacer(Modifier.height(14.dp))
                LcButton("1 · Rechteck an Laser senden", { ws.sendCalibrationJob(machine) }, Modifier.fillMaxWidth(), LcIcons.send, busy = "upload" in busy)
                Spacer(Modifier.height(8.dp))
                LcButton("2 · Kopf über das Rechteck", { ws.headOverRect(machine) }, Modifier.fillMaxWidth(), LcIcons.machine, busy = "moveto" in busy)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                    SmallText("10 mm:")
                    IconBtn(LcIcons.left, "X−", { machine.jog('X', -10.0) })
                    IconBtn(LcIcons.right, "X+", { machine.jog('X', 10.0) })
                    IconBtn(LcIcons.up, "Y−", { machine.jog('Y', -10.0) })
                    IconBtn(LcIcons.down, "Y+", { machine.jog('Y', 10.0) })
                }
                Spacer(Modifier.height(8.dp))
                LcButton("Kamerabild holen", { grab() }, Modifier.fillMaxWidth(), LcIcons.camera, BtnKind.PRIMARY, busy = loading)
                Spacer(Modifier.weight(1f))
                LcButton("Speichern", {
                    val p = photo ?: return@LcButton
                    if (ws.saveCalibration(machine, p, markers.map { Pt(it.x.toDouble(), it.y.toDouble()) })) onClose()
                }, Modifier.fillMaxWidth(), LcIcons.check, BtnKind.PRIMARY, enabled = photo != null && markers.size == 4, big = true)
                Spacer(Modifier.height(8.dp))
                LcButton("Schließen", onClose, Modifier.fillMaxWidth(), kind = BtnKind.GHOST)
            }
            Box(Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(18.dp)).background(Color(0xFF0B1015)), contentAlignment = Alignment.Center) {
                val p = photo
                if (p == null) SmallText("Noch kein Kamerabild") else MarkerCanvas(p, markers)
            }
        }
    }
}

