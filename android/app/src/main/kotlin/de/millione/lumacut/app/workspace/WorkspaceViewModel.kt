package de.millione.lumacut.app.workspace

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.editor.calibrationJob
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.CameraCalibration
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.Frame
import de.millione.lumacut.core.HeightMap
import de.millione.lumacut.core.HeightMapSet
import de.millione.lumacut.core.PiClient
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Scan
import de.millione.lumacut.core.Toolpath
import de.millione.lumacut.core.Work
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

/** A long run (scan, probe grid) with progress for the UI. */
data class Run(val title: String, val done: Int, val total: Int, val text: String = "") {
    val fraction get() = if (total > 0) done.toFloat() / total else 0f
}

/**
 * Camera workplace: head-camera calibration, scanning the work area into a
 * background mosaic, marking the workpieces, probing a height mesh and the
 * guided run (Home → Scan → Markieren → Abtasten → Fokus → Rahmen → Auftrag
 * → Parken). Everything here is work-area mm; Pi calls get machine mm via
 * [Work.toMachine]. Every move is laser-off and checked by the Pi again.
 */
class WorkspaceViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("lumacut", Context.MODE_PRIVATE)

    private val _calibration = MutableStateFlow(loadCalibration())
    val calibration: StateFlow<CameraCalibration?> = _calibration.asStateFlow()

    private val _areas = MutableStateFlow<List<Box>>(emptyList())
    val areas: StateFlow<List<Box>> = _areas.asStateFlow()

    private val _spacing = MutableStateFlow(prefs.getFloat("meshSpacing", 20f).toDouble())
    val spacing: StateFlow<Double> = _spacing.asStateFlow()

    private val _run = MutableStateFlow<Run?>(null)
    val run: StateFlow<Run?> = _run.asStateFlow()

    /** Steps of the guided run the operator finished in this session (frame, job). */
    private val _done = MutableStateFlow<Set<String>>(emptySet())
    val done: StateFlow<Set<String>> = _done.asStateFlow()

    private var worker: Job? = null

    private fun loadCalibration(): CameraCalibration? = runCatching {
        Document.JSON.decodeFromString(CameraCalibration.serializer(), prefs.getString("headCamera2", null)!!)
    }.getOrNull()

    fun markDone(step: String) = _done.update { it + step }

    /* ---------- areas ---------- */

    fun addArea(b: Box) {
        val c = Box(b.minX.coerceIn(0.0, Work.WIDTH), b.minY.coerceIn(0.0, Work.HEIGHT), b.maxX.coerceIn(0.0, Work.WIDTH), b.maxY.coerceIn(0.0, Work.HEIGHT))
        if (c.width < 3 || c.height < 3) return
        _areas.update { it + c }
    }

    fun removeAreaAt(p: Pt) = _areas.update { list ->
        val i = list.indexOfLast { p.x in it.minX..it.maxX && p.y in it.minY..it.maxY }
        if (i < 0) list else list.toMutableList().apply { removeAt(i) }
    }

    fun clearAreas() { _areas.value = emptyList() }

    /** One area per cluster of overlapping design parts, 3 mm larger: the material under the motif. */
    fun areasFromDesign(doc: Document): Int {
        val boxes = doc.elements.filter { e -> doc.layer(e.layerId)?.let { it.visible && it.output } == true }
            .mapNotNull { it.worldBounds() }.map { Box(it.minX - 3, it.minY - 3, it.maxX + 3, it.maxY + 3) }.toMutableList()
        var merged = true
        while (merged) {
            merged = false
            loop@ for (i in boxes.indices) for (j in i + 1 until boxes.size) {
                val a = boxes[i]; val b = boxes[j]
                if (a.minX <= b.maxX && b.minX <= a.maxX && a.minY <= b.maxY && b.minY <= a.maxY) {
                    boxes[i] = a.union(b); boxes.removeAt(j); merged = true; break@loop
                }
            }
        }
        _areas.value = emptyList()
        boxes.forEach(::addArea)
        return _areas.value.size
    }

    fun setSpacing(mm: Double) {
        _spacing.value = mm.coerceIn(5.0, 100.0)
        prefs.edit().putFloat("meshSpacing", _spacing.value.toFloat()).apply()
    }

    /* ---------- camera ---------- */

    /** Snapshot from the head camera, scaled to [width] px wide (scan tiles and calibration share this size). */
    suspend fun snapshot(c: PiClient, width: Int = TILE_WIDTH): Bitmap {
        val bytes = c.cameraSnapshot(1280, 720)
        return withContext(Dispatchers.Default) {
            val raw = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw IllegalStateException("Kamerabild nicht lesbar")
            val h = (raw.height.toLong() * width / raw.width).toInt()
            Bitmap.createScaledBitmap(raw, width, h, true)
        }
    }

    /** Lasered marks for the head camera: a 60 × 40 mm rectangle in the middle of the work area. */
    fun calibrationRect(): List<Pt> {
        val c = Work.center
        return listOf(Pt(c.x - 30, c.y - 20), Pt(c.x + 30, c.y - 20), Pt(c.x + 30, c.y + 20), Pt(c.x - 30, c.y + 20))
    }

    fun sendCalibrationJob(machine: MachineViewModel) =
        machine.uploadJob("kopfkamera-kalibrierung.gcode", calibrationJob(calibrationRect()))

    /** Moves the head (laser off) so the calibration rectangle is under the camera centre, as far as known. */
    fun headOverRect(machine: MachineViewModel) {
        val target = Work.center - (_calibration.value?.usable(0.0)?.center ?: Pt(0.0, 0.0))
        val m = Work.toMachine(target)
        machine.request("moveto", quietSuccess = true) { it.moveTo(m.x.coerceIn(0.0, 390.0), m.y.coerceIn(0.0, 370.0)) }
    }

    fun saveCalibration(machine: MachineViewModel, photo: Bitmap, marksPx: List<Pt>): Boolean {
        val pos = machine.status.value?.position
        if (pos == null || pos.size < 3) { machine.notify("Kopfposition unbekannt – Pi verbunden?", true); return false }
        val head = Work.fromMachine(pos[0], pos[1])
        val cal = runCatching { CameraCalibration.fromRectangle(photo.width, photo.height, marksPx, calibrationRect(), head, pos[2]) }
            .getOrElse { machine.notify("Kalibrierung ungültig: ${it.message}", true); return false }
        val f = cal.footprint()
        if (f.width < 10 || f.height < 10 || f.width > 400 || f.height > 400) {
            machine.notify("Kalibrierung unplausibel (Bildfeld %.0f × %.0f mm) – Marker prüfen".format(f.width, f.height), true); return false
        }
        _calibration.value = cal
        prefs.edit().putString("headCamera2", Document.JSON.encodeToString(CameraCalibration.serializer(), cal)).apply()
        machine.notify("Kopfkamera kalibriert: Bildfeld %.0f × %.0f mm".format(Locale.GERMANY, f.width, f.height))
        return true
    }

    /* ---------- scan ---------- */

    fun cancel() { worker?.cancel(); worker = null; _run.value = null }

    fun scan(machine: MachineViewModel, editor: EditorViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus()
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val plan = Scan.plan(cal)
                plan.uncovered.forEach { machine.notify(it) }
                val tiles = ArrayList<Scan.Tile>()
                for ((i, head) in plan.heads.withIndex()) {
                    if (!isActive) return@launch
                    _run.value = Run("Scan", i, plan.heads.size, "Bild ${i + 1} von ${plan.heads.size}")
                    val m = Work.toMachine(head)
                    c.moveTo(m.x, m.y)
                    delay(350)                       // let the gantry settle before the picture
                    val bmp = snapshot(c, cal.photoWidth)
                    val sized = if (bmp.height == cal.photoHeight) bmp else Bitmap.createScaledBitmap(bmp, cal.photoWidth, cal.photoHeight, true)
                    val px = IntArray(sized.width * sized.height).also { sized.getPixels(it, 0, sized.width, 0, 0, sized.width, sized.height) }
                    tiles += Scan.Tile(px, sized.width, sized.height, head)
                    machine.refreshStatus()?.position?.getOrNull(2)?.let { z ->
                        if (i == 0 && kotlin.math.abs(z - cal.scanZ) > 1.0)
                            machine.notify("Kamerahöhe Z %.1f statt %.1f wie bei der Kalibrierung – Maßstab weicht ab".format(z, cal.scanZ), true)
                    }
                }
                _run.value = Run("Scan", plan.heads.size, plan.heads.size, "Mosaik wird berechnet …")
                val bmp = withContext(Dispatchers.Default) {
                    val (out, w, h) = Scan.mosaic(tiles, cal)
                    Bitmap.createBitmap(out, w, h, Bitmap.Config.ARGB_8888)
                }
                editor.setBackground(bmp)
                markDone("scan")
                machine.notify("Arbeitsfläche gescannt (${tiles.size} Bilder)")
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Scan abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /* ---------- probing ---------- */

    /**
     * Probes a grid over every marked area (or the motif when none is
     * marked), fills points the switch cannot reach from their neighbours,
     * and probes the lowest point last: the Pi's own surface (Z floor =
     * surface + 2 mm) is then the lowest one, so every compensated height
     * passes its check.
     */
    fun probeMesh(machine: MachineViewModel, editor: EditorViewModel) {
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        if (_areas.value.isEmpty() && areasFromDesign(editor.doc.value) == 0) { machine.notify("Erst Bereiche markieren oder ein Motiv anlegen", true); return }
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus()
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val offset = st?.probeOffset ?: throw IllegalStateException("Tasterversatz fehlt (Einstellungen → Fokus & Taster)")
                val grids = _areas.value.mapIndexed { i, a -> HeightMap.grid("Bereich ${i + 1}", a, _spacing.value) }
                val total = grids.sumOf { it.cols * it.rows }
                var n = 0; var skipped = 0
                var lowest: Pair<Pt, Double>? = null
                val measured = grids.map { g ->
                    val z = g.z.toMutableList()
                    for ((idx, p) in g.points()) {
                        if (!isActive) return@launch
                        _run.value = Run("Abtasten", n, total, "Punkt ${n + 1} von $total · X %.0f Y %.0f".format(p.x, p.y))
                        n++
                        if (!Scan.reachable(p, offset)) { skipped++; continue }
                        val v = probe(c, machine, p)
                        z[idx] = v
                        if (lowest == null || v < lowest!!.second) lowest = p to v
                    }
                    g.copy(z = z)
                }
                val low = lowest ?: throw IllegalStateException("Kein Punkt erreichbar – Bereiche weiter innen markieren")
                val maps = measured.map { it.filled() }.filter { it.measured.isNotEmpty() }
                // Last probe on the lowest point: the Pi keeps that surface for its Z floor.
                _run.value = Run("Abtasten", total, total, "Tiefsten Punkt erneut antasten")
                probe(c, machine, low.first)
                editor.setHeights(HeightMapSet(maps))
                markDone("probe")
                val set = HeightMapSet(maps)
                machine.notify("Höhenmesh: %d Punkte, Oberfläche %.2f … %.2f mm%s".format(total - skipped, set.lowest ?: 0.0, set.highest ?: 0.0,
                    if (skipped > 0) " · $skipped nicht erreichbar (aus Nachbarn ergänzt)" else ""))
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Abtasten abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    private suspend fun probe(c: PiClient, machine: MachineViewModel, p: Pt): Double {
        val m = Work.toMachine(p)
        c.action("probe", mapOf("x" to "%.3f".format(Locale.ROOT, m.x), "y" to "%.3f".format(Locale.ROOT, m.y)))
        return machine.refreshStatus()?.workpiece_surface_z ?: throw IllegalStateException("Pi meldet keine Oberfläche")
    }

    /** Single probe at the motif centre (no mesh): the Pi focuses on that surface. */
    fun probeCentre(machine: MachineViewModel, editor: EditorViewModel) {
        val centre = editor.doc.value.bounds()?.center ?: Work.center
        if (machine.probeReachable(centre) == false) { machine.notify("Motivmitte für den Taster nicht erreichbar – Höhenmesh mit Bereichen nutzen", true); return }
        val m = Work.toMachine(centre)
        editor.setHeights(null)
        machine.action("probe", mapOf("x" to "%.3f".format(Locale.ROOT, m.x), "y" to "%.3f".format(Locale.ROOT, m.y)), key = "probe")
    }

    /* ---------- frame & job ---------- */

    fun frame(machine: MachineViewModel, editor: EditorViewModel, mode: Frame.Mode) {
        viewModelScope.launch {
            try {
                val tp = withContext(Dispatchers.Default) { Toolpath.parse(editor.buildJob(false, 7.0, 1.5).gcode) }
                machine.frame(Frame.cutPoints(tp), mode)
                markDone("frame")
            } catch (e: Exception) { machine.notify(e.message ?: "Rahmen nicht möglich", true) }
        }
    }

    /** Builds (with focus compensation when a mesh exists), uploads and starts without probing again. */
    fun startJob(machine: MachineViewModel, editor: EditorViewModel) {
        val cfg = machine.status.value?.config
        machine.request("start") { c ->
            val job = editor.buildJob(true, cfg?.focus_gap_mm ?: 7.0, cfg?.z_switch_tip_offset_mm ?: 1.5)
            val name = PiClient.jobNameFrom(editor.doc.value.title)
            c.uploadJob(name, job.gcode)
            val msg = c.action("start", mapOf("name" to name))
            markDone("job")
            msg
        }
    }

    companion object { const val TILE_WIDTH = 640 }
}
