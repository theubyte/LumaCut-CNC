package de.millione.lumacut.app.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.millione.lumacut.app.machine.JobView
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.machine.canControl
import de.millione.lumacut.core.Frame
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Toolpath
import de.millione.lumacut.core.Work
import de.millione.lumacut.core.formatDuration
import java.text.DateFormat
import java.util.Date

@Composable
fun JobsScreen(machine: MachineViewModel) {
    val jobs by machine.jobs.collectAsStateWithLifecycle()
    val job by machine.job.collectAsStateWithLifecycle()
    val busy by machine.busy.collectAsStateWithLifecycle()
    val context = LocalContext.current
    LaunchedEffect(Unit) { machine.refreshJobs() }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        val name = displayName(context, uri) ?: "auftrag.gcode"
        val text = context.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) }
        if (text == null) { machine.notify("Datei konnte nicht gelesen werden", true); return@rememberLauncherForActivityResult }
        val base = name.substringBeforeLast('.')
        machine.uploadJob(PiClient.jobNameFrom(base), text)
    }
    SplitPane(Modifier.padding(16.dp), sideWidth = 330.dp, mainShare = .62f, sideFirst = true, main = { mod ->
        LcCard(mod) {
            val view = job
            if (view == null) {
                Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(LcIcons.jobs, null, tint = Lc.faint, modifier = Modifier.size(52.dp))
                    Spacer(Modifier.height(12.dp))
                    Text("Auftrag auswählen oder hochladen", style = LcTypography.titleMedium, color = Lc.text)
                    SmallText("Vorschau, Dauer und Ein-Klick-Start erscheinen hier.")
                }
            } else JobDetail(machine, view, busy)
        }
    }, side = { mod ->
        LcCard(mod) {
            CardTitle("Aufträge") {
                IconBtn(LcIcons.refresh, "Aktualisieren", { machine.refreshJobs() })
                Spacer(Modifier.width(8.dp))
                LcButton("Hochladen", { pick.launch(arrayOf("*/*")) }, icon = LcIcons.upload, kind = BtnKind.PRIMARY, busy = "upload" in busy)
            }
            if (jobs.isEmpty()) SmallText("Noch keine Aufträge auf dem Pi. Im Editor gestaltete Aufträge erscheinen hier nach „An Laser senden“.")
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(jobs, key = { it.name }) { f ->
                    val on = f.name == job?.name
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                            .background(if (on) Lc.accentSoft else Lc.surface2)
                            .border(1.dp, if (on) Lc.accent else Color.Transparent, RoundedCornerShape(16.dp))
                            .clickable { machine.selectJob(f.name) }
                            .padding(horizontal = 16.dp, vertical = 13.dp)
                    ) {
                        Text(f.name, style = LcTypography.titleMedium, color = Lc.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        val size = if (f.bytes > 10240) "${f.bytes / 1024} KB" else "%.1f KB".format(f.bytes / 1024.0)
                        val date = if (f.modified > 0) " · " + DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(f.modified * 1000)) else ""
                        SmallText(size + date, Lc.faint)
                    }
                }
            }
        }
    })
}

@Composable
private fun JobDetail(machine: MachineViewModel, view: JobView, busy: Set<String>) {
    val status by machine.status.collectAsStateWithLifecycle()
    val online by machine.online.collectAsStateWithLifecycle()
    var confirm by rememberConfirm()
    val tp = view.toolpath
    val running = status?.job?.let { it.active && it.file == view.name } == true
    CardTitle(view.name) {
        IconBtn(LcIcons.trash, "Löschen", {
            confirm = Confirm("Auftrag löschen?", view.name, "Löschen", danger = true) { machine.deleteJob(view.name) }
        }, tint = Lc.bad, enabled = !running)
    }
    SplitPane(sideWidth = 310.dp, breakpoint = 640.dp, mainShare = .45f, main = { mod -> CanvasSurface(mod) {
            when {
                view.error != null -> Banner("Vorschau nicht möglich: ${view.error}", Lc.bad, Modifier.align(Alignment.Center).padding(20.dp))
                tp == null -> CircularProgressIndicator(color = Lc.accent, modifier = Modifier.align(Alignment.Center))
                else -> ToolpathCanvas(
                    tp, view.probe, status?.position, if (running) status?.job?.line ?: 0 else 0,
                    Modifier.fillMaxSize(), onTap = { if (!running) machine.setProbe(it) },
                )
            }
            Row(Modifier.align(Alignment.BottomStart).padding(12.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Legend(Lc.cut, "Laser"); Legend(Lc.travel, "Leerfahrt"); Legend(Lc.info, "Abtastpunkt", dot = true)
                SmallText("Antippen setzt den Abtastpunkt", Lc.faint)
            }
        } }, side = { mod ->
        Column(mod.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            val st = tp?.stats
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Tile("Dauer (ca.)", st?.let { formatDuration(it.seconds) } ?: "—", Modifier.weight(1f))
                Tile("Max. Leistung", st?.let { "${(it.maxPower * 100 / 255)} %" } ?: "—", Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Tile("Laserweg", st?.let { "%.2f m".format(it.cutMm / 1000) } ?: "—", Modifier.weight(1f))
                Tile("Leerweg", st?.let { "%.2f m".format(it.travelMm / 1000) } ?: "—", Modifier.weight(1f))
            }
            Tile("Größe · Position", tp?.bounds?.let { val o = Work.fromMachine(it.maxX, it.minY); "%.1f × %.1f mm · ab X %.0f Y %.0f".format(it.width, it.height, o.x, o.y) } ?: "—", Modifier.fillMaxWidth())
            Tile("Abtastpunkt", view.probe?.let { "X %.1f · Y %.1f · %s".format(it.x, it.y, if (view.probeChosen) "gewählt" else "Motivmitte") } ?: "—", Modifier.fillMaxWidth())
            st?.warnings?.forEach { Banner(it) }
            view.probe?.let { p ->
                if (machine.probeReachable(p) == false)
                    Banner("Den Punkt X %.1f / Y %.1f erreicht der Taster nicht (er sitzt versetzt zum Laser). Anderen Punkt antippen.".format(p.x, p.y))
            }
            Spacer(Modifier.height(6.dp))
            val jobState = status?.job
            if (running && jobState != null) {
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Lc.accentSoft)
                        .border(1.dp, Lc.accent.copy(alpha = .3f), RoundedCornerShape(16.dp)).padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(when (jobState.state) { "homing" -> "Referenzfahrt"; "probing" -> "Abtasten"; else -> "Auftrag läuft" }, style = LcTypography.titleMedium, color = Lc.text)
                    val pct = (jobState.fraction * 100).toInt()
                    SmallText(if (jobState.state == "running") "$pct % · noch ca. ${formatDuration(tp?.remainingSeconds(jobState.line) ?: 0.0)}" else "Vorbereitung …")
                    Progress(jobState.fraction.toFloat(), Modifier.fillMaxWidth(), thick = true)
                    LcButton("Abbrechen", {
                        confirm = Confirm("Auftrag abbrechen?", "Der Laser wird ausgeschaltet und der Kopf parkt auf X0/Y0.", "Abbrechen", danger = true) { machine.action("abort") }
                    }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER, busy = "abort" in busy)
                }
            } else {
                val ready = status.canControl(online) && tp?.bounds != null
                if (status?.frame?.active == true) {
                    Banner("Rahmenfahrt läuft (Laser aus) · ${status?.frame?.line}/${status?.frame?.total}", Lc.info)
                    LcButton("Rahmen abbrechen", { machine.action("abort") }, Modifier.fillMaxWidth(), kind = BtnKind.DANGER, busy = "abort" in busy)
                }
                // Laser-off outline first: shows where the job will burn before anything is lasered.
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    val canFrame = ready && status?.homed == true
                    LcButton("Rahmen", { tp?.let { machine.frame(Frame.cutPoints(it), Frame.Mode.BOX) } },
                        Modifier.weight(1f), LcIcons.rect, busy = "frame" in busy, enabled = canFrame)
                    LcButton("Gummiband", { tp?.let { machine.frame(Frame.cutPoints(it), Frame.Mode.HULL) } },
                        Modifier.weight(1f), LcIcons.polygon, busy = "frame" in busy, enabled = canFrame)
                }
                LcButton("Ein-Klick-Start", {
                    val p = view.probe
                    confirm = Confirm("Ein-Klick-Start",
                        "${view.name}\n\nReferenzieren → Abtasten bei X %.1f / Y %.1f → Fokus → Auftrag → Parken.\nDauer ca. %s.\n\nMaterial liegt unter dem Abtastpunkt, Arbeitsbereich ist frei?"
                            .format(p?.x ?: 0.0, p?.y ?: 0.0, formatDuration(tp?.stats?.seconds ?: 0.0)), "Starten") { machine.startJob(oneClick = true) }
                }, Modifier.fillMaxWidth(), LcIcons.play, BtnKind.PRIMARY, busy = "start" in busy, enabled = ready, big = true)
                LcButton("Start ohne Abtasten", {
                    confirm = Confirm("Auftrag starten", "Maschine ist referenziert und das Werkstück abgetastet? Der Fokus wird vor dem ersten Laserweg angefahren.", "Starten") { machine.startJob(oneClick = false) }
                }, Modifier.fillMaxWidth(), enabled = ready && status?.homed == true && status?.workpiece_surface_z != null)
                SmallText("Ein-Klick: Referenzieren (X/Y, dann Z) → Abtasten → Fokus → Auftrag → Parken mit Melodie.")
            }
        }
    })
    ConfirmDialog(confirm) { confirm = null }
}

@Composable
private fun Legend(color: Color, label: String, dot: Boolean = false) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(if (dot) 10.dp else 14.dp, if (dot) 10.dp else 3.dp).clip(if (dot) CircleShape else RoundedCornerShape(2.dp)).background(color))
        Spacer(Modifier.width(6.dp)); SmallText(label)
    }
}

/** Toolpath on the bed. Cut lines get more opaque with higher power; done part turns accent. */
@Composable
fun ToolpathCanvas(tp: Toolpath, probe: Pt?, head: List<Double>?, doneLine: Int,
                   modifier: Modifier = Modifier, onTap: (Pt) -> Unit = {}) {
    val buckets = remember(tp) { List(4) { b -> tp.segments.filter { it.cut && it.power * 4 / 256 == b } } }
    val travel = remember(tp) { tp.segments.filter { !it.cut } }
    Canvas(modifier.pointerInput(Unit) {
        detectTapGestures { o -> onTap(WorkMapper.fit(androidx.compose.ui.geometry.Size(size.width.toFloat(), size.height.toFloat())).toWork(o)) }
    }) {
        val m = WorkMapper.fit(size)
        drawWorkArea(m)
        // G-code is in machine mm; everything on screen is the work area.
        fun path(list: List<de.millione.lumacut.core.Segment>) = Path().apply {
            for (s in list) { val a = m.machine(s.x0, s.y0); moveTo(a.x, a.y); val e = m.machine(s.x1, s.y1); lineTo(e.x, e.y) }
        }
        drawPath(path(travel), Lc.travel, style = Stroke(1f))
        val width = (m.scale * 0.3f).coerceIn(1f, 2.4f)
        buckets.forEachIndexed { b, list ->
            if (list.isNotEmpty()) drawPath(path(list), Lc.cut.copy(alpha = .35f + .65f * (b + 1) / 4f), style = Stroke(width, cap = StrokeCap.Round))
        }
        if (doneLine > 0) drawPath(path(tp.segments.filter { it.cut && it.line <= doneLine }), Lc.accent, style = Stroke(width + .6f, cap = StrokeCap.Round))
        tp.bounds?.let { b ->
            val a = m.machine(b.minX, b.minY); val c = m.machine(b.maxX, b.maxY)
            drawRect(Lc.muted.copy(alpha = .5f), Offset(minOf(a.x, c.x), minOf(a.y, c.y)),
                androidx.compose.ui.geometry.Size(kotlin.math.abs(c.x - a.x), kotlin.math.abs(c.y - a.y)),
                style = Stroke(1.2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 8f))))
        }
        probe?.let {
            val c = m.at(it)
            drawCircle(Lc.info.copy(alpha = .25f), 14f, c); drawCircle(Lc.info, 14f, c, style = Stroke(3f))
            drawLine(Lc.info, Offset(c.x - 24f, c.y), Offset(c.x + 24f, c.y), 3f)
            drawLine(Lc.info, Offset(c.x, c.y - 24f), Offset(c.x, c.y + 24f), 3f)
        }
        drawHead(m, head)
    }
}

private fun displayName(context: android.content.Context, uri: Uri): String? =
    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) c.getString(0) else null
    }
