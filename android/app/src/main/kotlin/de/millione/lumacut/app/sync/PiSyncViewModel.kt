package de.millione.lumacut.app.sync

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.app.workspace.WorkspaceViewModel
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.HeightMapSet
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.PiConflictException
import de.millione.lumacut.core.PiWorkspace
import de.millione.lumacut.core.Pt
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.ByteArrayOutputStream
import kotlin.math.round

/**
 * Keeps this device on the Pi's work state: the Pi is the machine's centre,
 * every phone, tablet or PC shows the same. Three parts, each with the Pi
 * revision this device is on:
 *
 * - work state: chosen material, marked areas, height mesh, app settings;
 * - the open project (all plates);
 * - the scan picture.
 *
 * A change on the Pi (its revision in the status differs) is fetched when
 * this device has nothing unsent; a change here is sent shortly after it
 * happened, based on the revision it started from. When both changed the
 * project, the operator decides ([conflict]); for the small work state and
 * the scan the newest change wins.
 */
@OptIn(FlowPreview::class)
class PiSyncViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("lumacut", Context.MODE_PRIVATE)
    private val device = (Build.MODEL ?: "Gerät").take(40)
    private val lock = Mutex()
    private var started = false

    /** Work state as this device holds it, in the Pi's rounding. */
    private data class WorkLocal(val material: String?, val areas: List<List<Double>>, val points: List<List<Double>>,
                                 val heights: HeightMapSet?, val gridPower: Double, val meshSpacing: Double)

    private var machine: MachineViewModel? = null
    private var editor: EditorViewModel? = null
    private var ws: WorkspaceViewModel? = null

    // what this device last sent to / took from the Pi, per part (null = nothing yet)
    private var workSynced: WorkLocal? = null
    private var projectSynced: String? = null
    private var scanSynced: ImageBitmap? = null
    private var scanSyncedOnce = false

    /** Project changed on another device while this one had unsent changes: the operator decides. */
    private val _conflict = MutableStateFlow(false)
    val conflict: StateFlow<Boolean> = _conflict.asStateFlow()

    fun start(machine: MachineViewModel, editor: EditorViewModel, ws: WorkspaceViewModel) {
        if (started) return
        started = true
        this.machine = machine; this.editor = editor; this.ws = ws
        // changes on the Pi (revisions in the status)
        viewModelScope.launch {
            machine.status.filterNotNull().map { if ("workspace" in it.features) it.sync else null }
                .distinctUntilChanged().collect { rev -> if (rev != null) lock.withLock { pull(rev.workspace, rev.project, rev.scan) } }
        }
        // changes here
        viewModelScope.launch {
            combine(combine(editor.materialKey, ws.areas, ws.probePoints) { m, a, p -> Triple(m, a, p) },
                    editor.heights, ws.gridPower, ws.spacing) { (m, a, p), h, g, s -> local(m, a, p, h, g, s) }
                .debounce(1200).distinctUntilChanged().collect { lock.withLock { pushWork(it) } }
        }
        viewModelScope.launch {
            editor.project.debounce(2000).collect { lock.withLock { pushProject() } }
        }
        viewModelScope.launch {
            editor.background.debounce(1500).collect { lock.withLock { pushScan(it) } }
        }
    }

    private fun local(material: String?, areas: List<Box>, points: List<Pt>, heights: HeightMapSet?, gridPower: Double, spacing: Double) =
        WorkLocal(material, areas.map { b -> listOf(b.minX, b.minY, b.maxX, b.maxY).map { round(it * 1000) / 1000 } },
            points.map { p -> listOf(round(p.x * 1000) / 1000, round(p.y * 1000) / 1000) }, heights, gridPower, spacing)

    private fun client(): PiClient? {
        val m = machine ?: return null
        val st = m.status.value ?: return null
        if (m.online.value != true || "workspace" !in st.features) return null
        return m.client
    }

    private fun revKey(part: String) = "sync|${machine?.host?.value}|$part"
    private fun base(part: String) = prefs.getInt(revKey(part), 0)
    private fun setBase(part: String, rev: Int) = prefs.edit().putInt(revKey(part), rev).apply()

    /* ---------- from the Pi ---------- */

    private suspend fun pull(workRev: Int, projectRev: Int, scanRev: Int) {
        val c = client() ?: return
        val e = editor ?: return; val w = ws ?: return
        try {
            if (workRev != base("workspace") && (workSynced == null || currentWork() == workSynced)) {
                val remote = c.workspace()
                apply(remote)
                setBase("workspace", remote.revision)
            }
            if (projectRev != base("project") && projectRev > 0) {
                val unsent = projectSynced != null && e.projectJson() != projectSynced
                if (unsent) _conflict.value = true
                else c.project()?.let { (rev, json) ->
                    if (e.loadSyncedProject(json)) {
                        projectSynced = e.projectJson()
                        setBase("project", rev)
                        machine?.notify("Projekt vom Pi übernommen (an einem anderen Gerät geändert)")
                    }
                }
            }
            if (!scanSyncedOnce && scanRev == base("scan")) { scanSynced = e.background.value; scanSyncedOnce = true }
            else if (scanRev != base("scan") && (!scanSyncedOnce || e.background.value === scanSynced)) {
                val remote = c.scan()
                val bmp = remote?.let { withContext(Dispatchers.Default) { BitmapFactory.decodeByteArray(it.second, 0, it.second.size) } }
                e.setBackground(bmp)
                scanSynced = e.background.value; scanSyncedOnce = true
                setBase("scan", remote?.first ?: scanRev)
            }
            w.syncCalibration(machine!!)
        } catch (ex: Exception) {
            if (ex is kotlinx.coroutines.CancellationException) throw ex
        }
    }

    private fun currentWork(): WorkLocal {
        val e = editor!!; val w = ws!!
        return local(e.materialKey.value, w.areas.value, w.probePoints.value, e.heights.value, w.gridPower.value, w.spacing.value)
    }

    private fun apply(remote: PiWorkspace) {
        val e = editor!!; val w = ws!!
        e.setMaterialKey(remote.material?.key)
        w.setAreas(remote.areas.filter { it.size == 4 }.map { Box(it[0], it[1], it[2], it[3]) })
        w.setProbePoints(remote.probe_points.filter { it.size == 2 }.map { Pt(it[0], it[1]) })
        e.setHeights(remote.heights?.takeIf { it !is JsonNull }?.let { h ->
            runCatching { Document.JSON.decodeFromJsonElement(HeightMapSet.serializer(), h) }.getOrNull() })
        remote.settings["gridPower"]?.jsonPrimitive?.doubleOrNull?.let(w::setGridPower)
        remote.settings["meshSpacing"]?.jsonPrimitive?.doubleOrNull?.let(w::setSpacing)
        workSynced = currentWork()
    }

    /* ---------- to the Pi ---------- */

    private fun fields(v: WorkLocal, since: WorkLocal?): JsonObject = buildJsonObject {
        if (since == null || v.material != since.material) put("material", v.material?.let { key ->
            val name = key.substringBeforeLast("|"); val t = key.substringAfterLast("|").toDoubleOrNull() ?: 0.0
            buildJsonObject { put("name", name); put("thickness_mm", t) }
        } ?: JsonNull)
        if (since == null || v.areas != since.areas) put("areas", buildJsonArray { v.areas.forEach { b -> add(buildJsonArray { b.forEach { add(JsonPrimitive(it)) } }) } })
        if (since == null || v.points != since.points)
            put("probe_points", buildJsonArray { v.points.forEach { p -> add(buildJsonArray { p.forEach { add(JsonPrimitive(it)) } }) } })
        if (since == null || v.heights != since.heights)
            put("heights", v.heights?.let { Document.JSON.encodeToJsonElement(HeightMapSet.serializer(), it) } ?: JsonNull)
        if (since == null || v.gridPower != since.gridPower || v.meshSpacing != since.meshSpacing)
            put("settings", buildJsonObject { put("gridPower", v.gridPower); put("meshSpacing", v.meshSpacing) })
    }

    private suspend fun pushWork(v: WorkLocal) {
        val c = client() ?: return
        if (v == workSynced) return
        // a new device takes the Pi's state first instead of sending its defaults over it
        if (workSynced == null && base("workspace") == 0 && (machine?.status?.value?.sync?.workspace ?: 0) > 0) return
        val changed = fields(v, workSynced)
        if (changed.isEmpty()) { workSynced = v; return }
        try {
            val saved = try { c.saveWorkspace(changed, base("workspace"), device) }
            catch (e: PiConflictException) {
                // another device changed something else in between: take its state, then put this change on top
                val remote = c.workspace()
                setBase("workspace", remote.revision)
                c.saveWorkspace(changed, remote.revision, device)
            }
            setBase("workspace", saved.revision)
            workSynced = v
        } catch (e: Exception) {
            if (e is kotlinx.coroutines.CancellationException) throw e
            if (e.message?.contains("Materialstärke") == true) machine?.notify(e.message!!, true)
        }
    }

    private suspend fun pushProject() {
        val c = client() ?: return
        val e = editor ?: return
        if (_conflict.value) return
        val json = e.projectJson()
        if (json == projectSynced) return
        // a new device with an empty project takes the Pi's project instead of replacing it
        if (projectSynced == null && base("project") == 0 && (machine?.status?.value?.sync?.project ?: 0) > 0) return
        try {
            setBase("project", c.saveProject(json, base("project"), device))
            projectSynced = json
        } catch (ex: PiConflictException) {
            _conflict.value = true
        } catch (ex: Exception) {
            if (ex is kotlinx.coroutines.CancellationException) throw ex
        }
    }

    private suspend fun pushScan(bmp: ImageBitmap?) {
        val c = client() ?: return
        if (scanSyncedOnce && bmp === scanSynced) return
        // Not before the first comparison with the Pi: at start-up the picture cached on this device could be older than
        // the Pi's, and "the newest scan wins" below would then overwrite a newer scan with it.
        if (!scanSyncedOnce) return
        try {
            val png = bmp?.let { b -> withContext(Dispatchers.Default) {
                ByteArrayOutputStream().also { b.asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
            } }
            val rev = try { c.saveScan(png, base("scan"), device) }
            catch (e: PiConflictException) { c.saveScan(png, e.revision ?: c.scan()?.first ?: 0, device) }   // the newest scan wins
            setBase("scan", rev)
            scanSynced = bmp; scanSyncedOnce = true
        } catch (e: Exception) {
            if (e is kotlinx.coroutines.CancellationException) throw e
        }
    }

    /** The operator's answer to [conflict]: take the Pi's project, or put this device's over it. */
    fun resolveConflict(takePi: Boolean) {
        viewModelScope.launch {
            lock.withLock {
                val c = client() ?: return@withLock
                val e = editor ?: return@withLock
                try {
                    val remote = c.project()
                    if (takePi && remote != null) {
                        e.loadSyncedProject(remote.second)
                        projectSynced = e.projectJson()
                        setBase("project", remote.first)
                    } else {
                        val json = e.projectJson()
                        setBase("project", c.saveProject(json, remote?.first ?: 0, device))
                        projectSynced = json
                    }
                    _conflict.value = false
                } catch (ex: Exception) {
                    if (ex is kotlinx.coroutines.CancellationException) throw ex
                    machine?.notify("Abgleich mit dem Pi fehlgeschlagen: ${ex.message}", true)
                }
            }
        }
    }
}
