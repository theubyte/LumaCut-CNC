package de.millione.lumacut.app.workspace

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.app.editor.EditorViewModel
import de.millione.lumacut.app.editor.calibrationJob
import de.millione.lumacut.app.machine.MachineViewModel
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.CameraCalibration
import de.millione.lumacut.core.CameraLight
import de.millione.lumacut.core.CameraSettings
import de.millione.lumacut.core.BacklashTest
import de.millione.lumacut.core.CameraCover
import de.millione.lumacut.core.CutTest
import de.millione.lumacut.core.LightFinder
import de.millione.lumacut.core.LightModel
import de.millione.lumacut.core.LineMeasure
import de.millione.lumacut.core.RingingTest
import de.millione.lumacut.core.SpotMeasure
import de.millione.lumacut.core.ToneTest
import de.millione.lumacut.core.MarlinWriter
import de.millione.lumacut.core.MotionTest
import de.millione.lumacut.core.EngraveTest
import de.millione.lumacut.core.FocusTest
import de.millione.lumacut.core.Limits
import de.millione.lumacut.core.MachineStatus
import de.millione.lumacut.core.PhotoSampler
import de.millione.lumacut.core.PiConfig
import de.millione.lumacut.core.ProbeTarget
import de.millione.lumacut.core.Shading
import de.millione.lumacut.core.CameraFocus
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.DotGrid
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
import kotlin.math.roundToInt
import java.util.Locale

/** What a scan photographs: the marked areas, the motif (with 10 mm margin) or the whole work area. */
enum class ScanRegion(val label: String) {
    AREAS("Markierte Bereiche"), MOTIF("Nur das Motiv"), ALL("Ganzer Arbeitsplatz"),
}

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

    private val _gridPower = MutableStateFlow(
        prefs.getFloat("gridPower", DotGrid.POWER_MIN.toFloat()).toDouble().coerceIn(DotGrid.POWER_MIN, DotGrid.POWER_MAX))
    val gridPower: StateFlow<Double> = _gridPower.asStateFlow()

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

    /** Areas as another device marked them (from the Pi). */
    fun setAreas(list: List<Box>) { _areas.value = list }

    /* ---------- tapped probe points ---------- */

    private val _probePoints = MutableStateFlow<List<Pt>>(emptyList())
    /** Where the operator tapped material in the scan: probing (also the Pi's automatic run) happens only there. */
    val probePoints: StateFlow<List<Pt>> = _probePoints.asStateFlow()

    /**
     * Tap at [p]: removes the point within 6 mm, else adds one. Refused
     * (message returned) where the probe cannot reach or past 50 points.
     */
    fun tapProbePoint(p: Pt, probeOffset: Pt?): String? {
        val q = Pt(p.x.coerceIn(0.0, Work.WIDTH), p.y.coerceIn(0.0, Work.HEIGHT))
        val near = _probePoints.value.indexOfFirst { it.dist(q) < 6.0 }
        if (near >= 0) { _probePoints.update { it.toMutableList().apply { removeAt(near) } }; return null }
        if (_probePoints.value.size >= 50) return "Höchstens 50 Abtastpunkte"
        if (probeOffset != null && !Scan.reachable(q, probeOffset)) return "Dort kommt der Taster nicht hin (er sitzt versetzt zum Laser) – etwas weiter innen antippen"
        _probePoints.update { it + q }
        return null
    }

    fun setProbePoints(list: List<Pt>) { _probePoints.value = list }
    fun clearProbePoints() { _probePoints.value = emptyList() }

    /**
     * Probes the tapped points one by one (lowest again at the end, so the
     * Pi's Z floor fits every point) and shows their heights; between the
     * points the highest measured surface counts, never too low.
     */
    fun probeAtPoints(machine: MachineViewModel, editor: EditorViewModel) {
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        val pts = _probePoints.value
        if (pts.isEmpty()) { machine.notify("Erst Abtastpunkte im Scan antippen", true); return }
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus()
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val measured = ArrayList<Pair<Pt, Double>>()
                for ((i, p) in pts.withIndex()) {
                    if (!isActive) return@launch
                    _run.value = Run("Abtasten", i, pts.size, "Punkt ${i + 1} von ${pts.size}")
                    measured += p to probe(c, machine, p)
                }
                val low = measured.minBy { it.second }
                _run.value = Run("Abtasten", pts.size, pts.size, "Tiefsten Punkt erneut antasten")
                probe(c, machine, low.first)
                editor.setHeights(HeightMapSet(measured.mapIndexed { i, (p, z) -> HeightMap("Punkt ${i + 1}", p.x, p.y, 0.0, 0.0, 1, 1, listOf(z)) }))
                markDone("probe")
                machine.notify("%d Punkte abgetastet: %.2f … %.2f mm".format(Locale.GERMANY, measured.size, low.second, measured.maxOf { it.second }))
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Abtasten abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

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

    /** Dot grid laser power in whole 5 % steps, 20–60 %. */
    fun setGridPower(pct: Double) {
        _gridPower.value = ((pct / 5).roundToInt() * 5.0).coerceIn(DotGrid.POWER_MIN, DotGrid.POWER_MAX)
        prefs.edit().putFloat("gridPower", _gridPower.value.toFloat()).apply()
    }

    /* ---------- camera ---------- */

    /** Largest picture size the camera delivered so far (Full HD first, smaller ones if it refuses). */
    private var cameraSize = CAMERA_SIZES.first()

    /**
     * Snapshot from the head camera: the largest size it delivers, or
     * exactly [size] (the calibration's, for scan tiles; an older Pi sends
     * its own size, then the picture is scaled). [whiteBalance] in Kelvin
     * (0 = automatic) overrides the stored value for this picture.
     */
    suspend fun snapshot(c: PiClient, size: Pair<Int, Int>? = null, whiteBalance: Int? = null): Bitmap {
        val bytes = if (size != null) c.cameraSnapshot(size.first, size.second, whiteBalance) else {
            var result: ByteArray? = null
            var error: Exception? = null
            for (s in CAMERA_SIZES.drop(CAMERA_SIZES.indexOf(cameraSize))) {
                try { result = c.cameraSnapshot(s.first, s.second, whiteBalance); cameraSize = s; break } catch (e: Exception) { error = e }
            }
            result ?: throw error!!
        }
        return withContext(Dispatchers.Default) {
            val raw = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw IllegalStateException("Kamerabild nicht lesbar")
            if (size == null || (raw.width == size.first && raw.height == size.second)) raw
            else Bitmap.createScaledBitmap(raw, size.first, size.second, true)
        }
    }

    fun sendGridJob(machine: MachineViewModel) =
        machine.uploadJob(GRID_JOB, DotGrid.job(_gridPower.value))

    /** Moves the head (laser off) so the dot grid's centre is under the camera, as far as known. */
    fun headOverGrid(machine: MachineViewModel) {
        val target = DotGrid.center - (_calibration.value?.usable(0.0)?.center ?: Pt(0.0, 0.0))
        val m = Work.toMachine(target)
        machine.request("moveto", quietSuccess = true) { it.moveTo(m.x.coerceIn(0.0, 390.0), m.y.coerceIn(0.0, 370.0)) }
    }

    /** Finds the dot grid in [photo] and fits the lens; the head position and Z come from the Pi. */
    suspend fun evaluateGrid(machine: MachineViewModel, photo: Bitmap): DotGrid.Result {
        val pos = machine.refreshStatus()?.position
        if (pos == null || pos.size < 3) throw IllegalStateException("Kopfposition unbekannt – Pi verbunden?")
        val head = Work.fromMachine(pos[0], pos[1])
        return withContext(Dispatchers.Default) {
            val px = IntArray(photo.width * photo.height).also { photo.getPixels(it, 0, photo.width, 0, 0, photo.width, photo.height) }
            DotGrid.calibrate(px, photo.width, photo.height, head, pos[2])
        }
    }

    fun saveGridCalibration(machine: MachineViewModel, result: DotGrid.Result) {
        val cal = result.calibration
        store(machine, cal)
        val u = cal.usable(0.0)
        machine.notify("Kopfkamera kalibriert: Bildfeld %.0f × %.0f mm, Genauigkeit %.2f mm".format(Locale.GERMANY, u.width, u.height, result.lens.rmsMm))
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

    /** Keeps [cal] on the tablet and on the Pi (the calibration belongs to the machine). */
    private fun store(machine: MachineViewModel, measured: CameraCalibration) {
        // a new lens measurement keeps the light calibration (same camera and light)
        val old = _calibration.value
        var cal = if (measured.shading == null) measured.copy(shading = old?.shading) else measured
        // the 3D light models are in picture pixels: they stay only while the picture size is the same
        if (old != null && old.photoWidth == cal.photoWidth && old.photoHeight == cal.photoHeight)
            cal = cal.copy(spot = cal.spot ?: old.spot, line = cal.line ?: old.line)
        _calibration.value = cal
        prefs.edit().putString("headCamera2", Document.JSON.encodeToString(CameraCalibration.serializer(), cal)).apply()
        val c = machine.clientOrNotify() ?: return
        viewModelScope.launch {
            try { c.saveCameraCalibration(cal); machine.notify("Kamera-Kalibrierung auf dem Pi gespeichert") }
            catch (e: Exception) { machine.notify("Nur auf dem Tablet gespeichert – Pi: ${e.message}", true) }
        }
    }

    /**
     * Takes the calibration from the Pi when it has one from a tablet;
     * otherwise uploads the one this tablet still keeps locally (older app).
     */
    fun syncCalibration(machine: MachineViewModel) {
        val c = machine.client ?: return
        viewModelScope.launch {
            runCatching { c.cameraCalibration() }.onSuccess { (onPi, _) ->
                val local = _calibration.value
                when {
                    onPi != null && onPi != local -> {
                        _calibration.value = onPi
                        prefs.edit().putString("headCamera2", Document.JSON.encodeToString(CameraCalibration.serializer(), onPi)).apply()
                    }
                    onPi == null && local != null -> runCatching { c.saveCameraCalibration(local) }
                }
            }
        }
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
        store(machine, cal)
        machine.notify("Kopfkamera kalibriert: Bildfeld %.0f × %.0f mm".format(Locale.GERMANY, f.width, f.height))
        return true
    }

    /* ---------- automatic calibration ---------- */

    /** Moves Z (laser off) in jog steps to the absolute height [target]; the Pi refuses anything below surface + 2 mm. */
    private suspend fun zTo(c: PiClient, machine: MachineViewModel, target: Double): Double {
        val z = machine.refreshStatus()?.position?.getOrNull(2) ?: throw IllegalStateException("Z-Position unbekannt")
        if (target > Z_TOP + 0.01) throw IllegalStateException("Z %.1f über der Höchstgrenze Z %.0f – Material zu hoch für die Kamera".format(target, Z_TOP))
        for (step in CameraFocus.jogSteps(target - z)) c.action("jog", mapOf("axis" to "Z", "distance" to step.toString()))
        return machine.refreshStatus()?.position?.getOrNull(2) ?: target
    }

    /** Head to work point [head] (laser off, machine travel limits); Z back to [z] when the Pi lifted it. */
    private suspend fun headTo(c: PiClient, machine: MachineViewModel, head: Pt, z: Double?): Pt {
        val m = Work.toMachine(head)
        val mx = m.x.coerceIn(0.0, 390.0); val my = m.y.coerceIn(0.0, 370.0)
        c.moveTo(mx, my)
        if (z != null) {
            val now = machine.refreshStatus()?.position?.getOrNull(2)
            if (now == null || kotlin.math.abs(now - z) > 0.05) zTo(c, machine, z)
        }
        delay(300)                                   // let the gantry settle before the picture
        return Work.fromMachine(mx, my)
    }

    private suspend fun pixels(c: PiClient, size: Pair<Int, Int>? = null, whiteBalance: Int? = null): Triple<IntArray, Int, Int> {
        val bmp = snapshot(c, size, whiteBalance)
        return withContext(Dispatchers.Default) {
            Triple(IntArray(bmp.width * bmp.height).also { bmp.getPixels(it, 0, bmp.width, 0, 0, bmp.width, bmp.height) }, bmp.width, bmp.height)
        }
    }

    /** Waits for the Pi's run of [name] ([what], e.g. "Punktraster") to end; throws unless it completed. */
    private suspend fun waitForJob(machine: MachineViewModel, name: String, what: String, onProgress: (String) -> Unit) {
        var seen = false
        val start = System.currentTimeMillis()
        while (true) {
            delay(2000)
            val job = machine.refreshStatus()?.job ?: continue
            val ours = job.file == name
            if (ours && job.active) {
                seen = true
                onProgress(when (job.step) {
                    "homing" -> "Referenzieren …"; "probing", "focusing" -> "Abtasten …"; "parking" -> "Parken …"
                    else -> "$what wird gelasert: %d %%".format((job.fraction * 100).toInt())
                })
            }
            if (ours && !job.active && (seen || System.currentTimeMillis() - start > 20_000)) {
                if (job.state == "complete") return
                throw IllegalStateException("$what nicht gelasert: " + job.error.ifBlank { job.state })
            }
            if (System.currentTimeMillis() - start > 40 * 60_000) throw IllegalStateException("$what dauert ungewöhnlich lange – am Pi prüfen")
        }
    }

    /**
     * Brings the grid centre into the middle of the picture: looks around
     * the start position (the camera sits beside the laser, so first time
     * its offset is unknown) and then centres on the big dot.
     */
    private suspend fun findGrid(c: PiClient, machine: MachineViewModel, start: Pt, z: Double?): Pt? {
        val rings = listOf(Pt(0.0, 0.0)) + listOf(45.0, 90.0).flatMap { r ->
            (0 until 8).map { k -> val a = Math.PI / 4 * k; Pt(r * kotlin.math.cos(a), r * kotlin.math.sin(a)) }
        }
        for (d in rings) {
            var head = headTo(c, machine, start + d, z)
            var off = withContext(Dispatchers.Default) { pixels(c).let { (px, w, h) -> DotGrid.locate(px, w, h) } } ?: continue
            repeat(3) {
                if (kotlin.math.hypot(off.x, off.y) < 2.0) return head
                head = headTo(c, machine, head - off, z)
                off = withContext(Dispatchers.Default) { pixels(c).let { (px, w, h) -> DotGrid.locate(px, w, h) } } ?: return head
            }
            return head
        }
        return null
    }

    /** Z sweep for the sharpest picture: 5 mm steps upwards, then 1 mm around the best; ends at the sharp height. */
    private suspend fun focusSweep(c: PiClient, machine: MachineViewModel, surface: Double, onProgress: (String) -> Unit): Double {
        // never closer than 5 mm between probe tip and material (owner's decision 2026-10-27)
        val low = surface + 5; val high = Z_TOP
        if (high - low < 5) throw IllegalStateException("Zu wenig Platz über dem Material für die Kamera")
        suspend fun measure(z: Double): Pair<Double, Double> {
            val at = zTo(c, machine, z)
            delay(300)
            val (px, w, h) = pixels(c)
            return at to withContext(Dispatchers.Default) { CameraFocus.sharpness(px, w, h) }
        }
        val coarse = ArrayList<Pair<Double, Double>>()
        var z = low
        while (z <= high + 0.01) {
            onProgress("Schärfe suchen: Z %.0f mm".format(z))
            coarse += measure(z)
            val best = coarse.maxOf { it.second }
            if (coarse.size >= 3 && coarse.takeLast(2).all { it.second < best * 0.5 }) break   // past the peak
            z += 5.0
        }
        if (CameraFocus.atEdge(coarse)) {
            val top = coarse.maxBy { it.second }.first > (low + high) / 2
            throw IllegalStateException(if (top) "Kamera wird erst oberhalb von Z %.0f scharf – Objektiv auf kürzeren Abstand drehen".format(high)
                                        else "Kamera ist schon direkt über dem Material am schärfsten – Objektiv auf größeren Abstand drehen")
        }
        val centre = CameraFocus.peak(coarse)
        val fine = ArrayList<Pair<Double, Double>>()
        for (k in -4..4) {
            val zz = centre + k
            if (zz < low || zz > high) continue
            onProgress("Schärfe fein einstellen: Z %.1f mm".format(zz))
            fine += measure(zz)
        }
        val best = CameraFocus.peak(fine).coerceIn(low, high)
        return zTo(c, machine, best)
    }

    /**
     * Fully automatic head-camera calibration: laser the dot grid (the Pi
     * homes, probes, focuses and parks), find it with the camera, search
     * the sharp height, centre on the grid, measure lens and position, and
     * store the result on the tablet and the Pi. Needs only a scrap plate
     * in the middle of the bed.
     */
    fun autoCalibrate(machine: MachineViewModel) {
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            var lasering = false
            fun step(n: Int, text: String) { _run.value = Run("Kamera kalibrieren", n, 5, text) }
            try {
                val st = machine.refreshStatus() ?: throw IllegalStateException("Pi nicht erreichbar")
                if (!st.camera.available) throw IllegalStateException("Keine Kamera am Pi angeschlossen")
                if (st.job.active) throw IllegalStateException("Es läuft gerade ein Auftrag")
                step(0, "Punktraster wird hochgeladen …")
                c.uploadJob(GRID_JOB, DotGrid.job(_gridPower.value))
                lasering = true
                c.autorun(GRID_JOB)
                waitForJob(machine, GRID_JOB, "Punktraster") { step(0, it) }
                lasering = false

                val surface = machine.refreshStatus()?.workpiece_surface_z ?: run {
                    step(1, "Oberfläche abtasten …"); probe(c, machine, DotGrid.center)
                }
                step(1, "Kamera sucht das Raster …")
                var z = zTo(c, machine, (surface + 40).coerceAtMost(Z_TOP))
                val guess = DotGrid.center - (_calibration.value?.usable(0.0)?.center ?: Pt(0.0, 0.0))
                var head = findGrid(c, machine, guess, z)
                if (head == null) {
                    // too blurred to recognise: get sharp where the camera is, then look again
                    headTo(c, machine, guess, z)
                    z = focusSweep(c, machine, surface) { step(2, it) }
                    head = findGrid(c, machine, guess, z) ?: throw IllegalStateException(
                        "Raster im Kamerabild nicht gefunden – liegt die Platte mittig, ist das Raster dunkel genug?")
                }
                step(2, "Schärfe suchen …")
                z = focusSweep(c, machine, surface) { step(2, it) }
                step(3, "Kamera über die Rastermitte …")
                head = findGrid(c, machine, head, z) ?: throw IllegalStateException("Raster nach dem Scharfstellen verloren")

                step(4, "Linse und Lage einmessen …")
                val result = evaluateGrid(machine, snapshot(c))
                val cal = result.calibration.copy(aboveSurface = result.calibration.scanZ - surface)
                store(machine, cal)
                val u = cal.usable(0.0)
                machine.notify("Kamera kalibriert: scharf %.1f mm über dem Material, Bildfeld %.0f × %.0f mm, Genauigkeit %.2f mm"
                    .format(Locale.GERMANY, cal.aboveSurface ?: 0.0, u.width, u.height, result.lens.rmsMm))
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                if (lasering) withContext(kotlinx.coroutines.NonCancellable) { runCatching { c.action("abort") } }
                throw e
            } catch (e: Exception) {
                machine.notify("Kalibrierung abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /* ---------- camera light, probe offset, focus and engraving tests ---------- */

    private val _focusResult = MutableStateFlow<FocusTest.Result?>(null)
    /** Last focus test (for the line-width chart). */
    val focusResult: StateFlow<FocusTest.Result?> = _focusResult.asStateFlow()

    /** Last engraving test: the measured squares. */
    class EngraveOutcome(val spec: EngraveTest.Spec, val fields: List<EngraveTest.Field>)
    private val _engrave = MutableStateFlow<EngraveOutcome?>(null)
    val engrave: StateFlow<EngraveOutcome?> = _engrave.asStateFlow()

    /** Runs [block] with the LEDs at [level] % (null: as they are) and puts the light back afterwards. */
    private suspend fun <T> withScanLight(c: PiClient, machine: MachineViewModel, level: Int?, block: suspend () -> T): T {
        if (level == null) return block()
        val st = machine.status.value
        val wasOn = st?.lights == true; val wasLevel = st?.light_brightness?.let { kotlin.math.round(it).toInt() }
        runCatching { c.light(on = true, brightness = level) }
        delay(300)
        try { return block() } finally {
            withContext(kotlinx.coroutines.NonCancellable) { runCatching { c.light(on = wasOn, brightness = wasLevel) } }
        }
    }

    /**
     * Puts the camera over work point [p] at the distance to the material
     * of the calibration (probes [p] first when no surface is known).
     * Returns the head position (work mm) and the Z used.
     */
    private suspend fun cameraOver(c: PiClient, machine: MachineViewModel, cal: CameraCalibration, p: Pt): Pair<Pt, Double> {
        val surface = machine.refreshStatus()?.workpiece_surface_z ?: probe(c, machine, p)
        val z = cal.aboveSurface?.let { surface + it } ?: cal.scanZ
        if (z > Z_TOP) throw IllegalStateException("Material zu hoch für die Kamera")
        if (z < surface + 3) throw IllegalStateException("Kamerahöhe der Kalibrierung liegt zu nah am Material – Kamera neu kalibrieren")
        val head = headTo(c, machine, p - cal.usable(0.0).center, z)
        return head to z
    }

    private fun needCamera(st: MachineStatus?, needsSettings: Boolean = false) {
        if (st == null) throw IllegalStateException("Pi nicht erreichbar")
        if (!st.camera.available) throw IllegalStateException("Keine Kamera am Pi angeschlossen")
        if (st.job.active) throw IllegalStateException("Es läuft gerade ein Auftrag")
        if (needsSettings && "camera_settings" !in st.features) throw IllegalStateException("Pi zu alt für die Lichtkalibrierung – Pi aktualisieren")
    }

    /**
     * Light calibration on a plain white sheet under the camera: LEDs to
     * [LIGHT_LEVEL], white balance until the sheet is neutral grey, five
     * photos at slightly shifted positions for the brightness fall-off to
     * the edges (flat field). The white balance and light level go to the
     * Pi (every picture uses them), the flat field into the calibration.
     */
    fun calibrateLight(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Kamera-Licht kalibrieren", n, 4, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st, needsSettings = true)
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val ranges = c.cameraSettings()
                val size = cal.photoWidth to cal.photoHeight
                withScanLight(c, machine, LIGHT_LEVEL) {
                    step(0, "Kamera über das Blatt fahren …")
                    val (head, z) = cameraOver(c, machine, cal, Work.center)
                    val (first, w, h) = pixels(c, size, 0)
                    val bright = withContext(Dispatchers.Default) { CameraLight.brightness(first, w, h) }
                    if (bright < 50) throw IllegalStateException("Bild zu dunkel – liegt ein weißes Blatt unter der Kamera, ist das Licht an?")
                    val wb = CameraLight.whiteBalance(ranges.range("white_balance", 2500..7000)) { k ->
                        step(1, "Weißabgleich: $k K")
                        val (px, pw, ph) = pixels(c, size, k)
                        withContext(Dispatchers.Default) { CameraLight.tint(px, pw, ph) }
                    }
                    val shifts = listOf(Pt(0.0, 0.0), Pt(12.0, 0.0), Pt(-12.0, 0.0), Pt(0.0, 9.0), Pt(0.0, -9.0))
                    val photos = shifts.mapIndexed { i, d ->
                        step(2, "Randabfall messen: Bild ${i + 1} von ${shifts.size}")
                        headTo(c, machine, head + d, z)
                        pixels(c, size, wb).first
                    }
                    step(3, "Speichern …")
                    val shading = withContext(Dispatchers.Default) { Shading.measure(photos, size.first, size.second) }
                    c.saveCameraSettings(CameraSettings(white_balance = wb, light = LIGHT_LEVEL))
                    store(machine, cal.copy(shading = shading))
                    machine.notify("Kamera-Licht kalibriert: Weißabgleich %d K, Licht %d %%, Randabfall bis %.0f %% ausgeglichen"
                        .format(wb, LIGHT_LEVEL, (1 - 1 / shading.gain.max()) * 100))
                }
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Lichtkalibrierung abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /** Uploads and runs [gcode] as [name] automatically (home, probe, focus, laser, park); aborts the laser when cancelled. */
    private suspend fun laserTest(c: PiClient, machine: MachineViewModel, name: String, gcode: String, what: String, onProgress: (String) -> Unit) {
        c.uploadJob(name, gcode)
        try {
            c.autorun(name)
            waitForJob(machine, name, what, onProgress)
        } catch (e: kotlinx.coroutines.CancellationException) {
            withContext(kotlinx.coroutines.NonCancellable) { runCatching { c.action("abort") } }
            throw e
        }
    }

    /** Lasers the probe target in the middle of the work area, then puts the probe tip over it (as far as the offset is known). */
    fun laserProbeTarget(machine: MachineViewModel) {
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus() ?: throw IllegalStateException("Pi nicht erreichbar")
                if (st.job.active) throw IllegalStateException("Es läuft gerade ein Auftrag")
                laserTest(c, machine, PROBE_JOB, ProbeTarget.job(), "Tasterziel") { _run.value = Run("Taster-Versatz", 0, 2, it) }
                _run.value = Run("Taster-Versatz", 1, 2, "Taster über das Ziel fahren …")
                tipOver(c, machine)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Tasterziel: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    private suspend fun tipOver(c: PiClient, machine: MachineViewModel) {
        val off = machine.refreshStatus()?.probeOffset ?: Pt(0.0, 0.0)
        val m = ProbeTarget.headFor(off)
        c.moveTo(m.x.coerceIn(0.0, 390.0), m.y.coerceIn(0.0, 370.0))
        machine.refreshStatus()
    }

    fun tipOverTarget(machine: MachineViewModel) = machine.request("moveto", quietSuccess = true) { c -> tipOver(c, machine); "Taster über dem Ziel" }

    /** Offset from the current head position, the tip sitting exactly over the target centre (machine mm). */
    fun probeOffsetHere(machine: MachineViewModel): Pt? = machine.status.value?.position?.takeIf { it.size >= 2 }?.let { ProbeTarget.offset(Pt(it[0], it[1])) }

    fun saveProbeOffset(machine: MachineViewModel) {
        val off = probeOffsetHere(machine) ?: run { machine.notify("Kopfposition unbekannt", true); return }
        val cfg = machine.status.value?.config ?: return
        if (kotlin.math.abs(off.x) > 80 || kotlin.math.abs(off.y) > 80) { machine.notify("Versatz über 80 mm – Taster wirklich über dem Ziel?", true); return }
        machine.saveSettings(settingsFrom(cfg, probe = off))
    }

    /** GPIO (BCM) of the measuring line laser on the Pi, null = none fitted. */
    fun setLineLaserGpio(machine: MachineViewModel, pin: Int?) {
        val cfg = machine.status.value?.config ?: return
        machine.saveSettings(settingsFrom(cfg) + ("line_laser_gpio" to (pin?.toString() ?: "")))
    }

    private fun settingsFrom(cfg: PiConfig, focusGap: Double = cfg.focus_gap_mm, probe: Pt? = cfg.probe_offset_x_mm?.let { x -> cfg.probe_offset_y_mm?.let { Pt(x, it) } }) =
        mapOf("focus_gap_mm" to "%.2f".format(Locale.ROOT, focusGap), "z_clearance_mm" to cfg.z_clearance_mm.toString(),
              "z_switch_tip_offset_mm" to cfg.z_switch_tip_offset_mm.toString(),
              "probe_offset_x_mm" to (probe?.let { "%.2f".format(Locale.ROOT, it.x) } ?: ""),
              "probe_offset_y_mm" to (probe?.let { "%.2f".format(Locale.ROOT, it.y) } ?: ""))

    /**
     * Focus ramp: 13 lines from 3 mm below to 3 mm above the current focus,
     * photographed and measured; the narrowest line's height becomes the new
     * focus distance on the Pi.
     */
    fun focusTest(machine: MachineViewModel, powerPct: Double, speed: Double) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Fokus-Test", n, 3, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                val cfg = st!!.config
                val offsets = FocusTest.offsets(cfg.focus_gap_mm - cfg.z_switch_tip_offset_mm)
                val area = FocusTest.bounds(offsets.size)
                val u = cal.usable(0.05)
                if (area.width > u.width || area.height > u.height) throw IllegalStateException("Kamerabild zu klein für die Testlinien – Kamera höher kalibrieren")
                laserTest(c, machine, FOCUS_JOB, FocusTest.job(offsets, powerPct, speed), "Fokus-Test") { step(0, it) }
                step(1, "Linien fotografieren …")
                val result = withScanLight(c, machine, cfg.camera?.light) {
                    val (head, _) = cameraOver(c, machine, cal, area.center)
                    val (px, w, h) = pixels(c, cal.photoWidth to cal.photoHeight)
                    step(2, "Linienbreiten messen …")
                    withContext(Dispatchers.Default) { FocusTest.evaluate(PhotoSampler(px, w, h, cal, head), offsets) }
                }
                _focusResult.value = result
                val gap = kotlin.math.round((cfg.focus_gap_mm + result.bestOffset) * 10) / 10
                c.settings(settingsFrom(cfg, focusGap = gap))
                machine.refreshStatus()
                machine.notify("Fokus-Test: schärfste Linie bei %+.1f mm · Fokusabstand %.1f → %.1f mm · Strahlbreite %.2f mm"
                    .format(Locale.GERMANY, result.bestOffset, cfg.focus_gap_mm, gap, result.widthAtBest))
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Fokus-Test abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /** Engraving test with [spec]: lasered, photographed square by square and measured; the result waits for the operator's choice. */
    fun engraveTest(machine: MachineViewModel, spec: EngraveTest.Spec) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            val heads = EngraveTest.photos(spec, cal)
            fun step(n: Int, text: String) { _run.value = Run("Gravur-Test", n, heads.size + 2, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                laserTest(c, machine, ENGRAVE_JOB, EngraveTest.job(spec, st!!.config.motion?.toMotion() ?: MarlinWriter.Motion.FIRMWARE), "Gravur-Test") { step(0, it) }
                val u = cal.usable(0.1)
                val fields = HashMap<Pair<Int, Int>, EngraveTest.Field>()
                withScanLight(c, machine, st!!.config.camera?.light) {
                    var z: Double? = null
                    for ((n, head) in heads.withIndex()) {
                        step(n + 1, "Felder fotografieren: Bild ${n + 1} von ${heads.size}")
                        val at = z?.let { headTo(c, machine, head, it) } ?: cameraOver(c, machine, cal, head + u.center).also { z = it.second }.first
                        val (px, w, h) = pixels(c, cal.photoWidth to cal.photoHeight)
                        withContext(Dispatchers.Default) {
                            val sampler = PhotoSampler(px, w, h, cal, at)
                            for (i in spec.powers.indices) for (j in spec.speeds.indices) {
                                if ((i to j) in fields) continue
                                val b = spec.cell(i, j); val m = spec.gapMm / 2
                                val inside = b.minX - m >= at.x + u.minX && b.maxX + m <= at.x + u.maxX && b.minY - m >= at.y + u.minY && b.maxY + m <= at.y + u.maxY
                                if (inside) EngraveTest.measure(spec, i, j, sampler)?.let { fields[i to j] = it }
                            }
                        }
                    }
                }
                val total = spec.powers.size * spec.speeds.size
                if (fields.size < total) machine.notify("Gravur-Test: ${total - fields.size} von $total Feldern nicht messbar", true)
                _engrave.value = EngraveOutcome(spec, fields.values.sortedWith(compareBy<EngraveTest.Field>({ it.speed }, { it.power })))
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Gravur-Test abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /* ---------- scan ---------- */

    fun cancel() { worker?.cancel(); worker = null; _run.value = null }

    /* ---------- more camera tests: ringing, backlash, grey scale, 3D height ---------- */

    private fun Box.holds(b: Box) = b.minX >= minX && b.maxX <= maxX && b.minY >= minY && b.maxY <= maxY

    /**
     * Photographs [area] (several pictures when it is larger than one) at the
     * calibrated distance and hands every picture with the work box it
     * shows well to [each].
     */
    private suspend fun photographArea(c: PiClient, machine: MachineViewModel, cal: CameraCalibration, area: Box, light: Int?,
                                       onStep: (Int, Int) -> Unit = { _, _ -> }, each: suspend (PhotoSampler, Box) -> Unit) {
        val heads = CameraCover.heads(area, cal)
        val u = cal.usable(0.1)
        withScanLight(c, machine, light) {
            var z: Double? = null
            for ((n, head) in heads.withIndex()) {
                onStep(n, heads.size)
                val at = z?.let { headTo(c, machine, head, it) } ?: cameraOver(c, machine, cal, head + u.center).also { z = it.second }.first
                val (px, w, h) = pixels(c, cal.photoWidth to cal.photoHeight)
                each(PhotoSampler(px, w, h, cal, at), Box(at.x + u.minX, at.y + u.minY, at.x + u.maxX, at.y + u.maxY))
            }
        }
    }

    /** Uploads [gcode] and starts it as it is (no probing, no focus of the Pi: the job sets its own Z); waits for the end. */
    private suspend fun runPlain(c: PiClient, machine: MachineViewModel, name: String, gcode: String, what: String, onProgress: (String) -> Unit) {
        c.uploadJob(name, gcode)
        try {
            c.action("start", mapOf("name" to name))
            waitForJob(machine, name, what, onProgress)
        } catch (e: kotlinx.coroutines.CancellationException) {
            withContext(kotlinx.coroutines.NonCancellable) { runCatching { c.action("abort") } }
            throw e
        }
    }

    private suspend fun decode(bytes: ByteArray?): Triple<IntArray, Int, Int>? = bytes?.let { b ->
        withContext(Dispatchers.Default) {
            BitmapFactory.decodeByteArray(b, 0, b.size)?.let { bmp -> Triple(IntArray(bmp.width * bmp.height).also { bmp.getPixels(it, 0, bmp.width, 0, 0, bmp.width, bmp.height) }, bmp.width, bmp.height) }
        }
    }

    private val _ringing = MutableStateFlow<List<RingingTest.Result>?>(null)
    /** Last ringing test: per line the swing after the corner. */
    val ringing: StateFlow<List<RingingTest.Result>?> = _ringing.asStateFlow()

    /** Ringing test: corner-and-line patterns along X and Y at rising speeds, photographed and measured. */
    fun ringingTest(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Schwing-Test", n, 3, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                val maxFeed = st!!.config.motion?.toMotion()?.maxFeed ?: MarlinWriter.Motion.FIRMWARE.maxFeed
                val spec = RingingTest.Spec(speeds = listOf(1500.0, 3000.0, 4500.0, 6000.0).filter { it <= maxFeed }.ifEmpty { listOf(maxFeed) })
                laserTest(c, machine, RINGING_JOB, RingingTest.job(spec), "Schwing-Test") { step(0, it) }
                val results = HashMap<RingingTest.Leg, RingingTest.Result>()
                photographArea(c, machine, cal, RingingTest.bounds(spec), st.config.camera?.light, { n, of -> step(1, "Linien fotografieren: Bild ${n + 1} von $of") }) { sampler, view ->
                    withContext(Dispatchers.Default) {
                        for (leg in RingingTest.legs(spec)) {
                            if (results[leg]?.found == true) continue
                            val a = leg.corner - leg.across * spec.lead; val b = leg.corner + leg.dir * spec.length
                            val box = Box(minOf(a.x, b.x) - 1.5, minOf(a.y, b.y) - 1.5, maxOf(a.x, b.x) + 1.5, maxOf(a.y, b.y) + 1.5)
                            if (view.holds(box)) results[leg] = RingingTest.measure(sampler, spec, leg)
                        }
                    }
                }
                val list = RingingTest.legs(spec).mapNotNull { results[it] }
                _ringing.value = list
                val worst = list.filter { it.found }.maxByOrNull { it.amplitude }
                machine.notify(when {
                    worst == null -> "Schwing-Test: Linien nicht erkannt – Licht oder Kamera prüfen"
                    list.none { it.rings } -> "Schwing-Test: kein Nachschwingen messbar (höchstens %.2f mm)".format(Locale.GERMANY, worst.amplitude)
                    else -> "Schwing-Test: %c-Achse schwingt %.2f mm nach%s".format(Locale.GERMANY, worst.swingingAxis, worst.amplitude,
                        if (worst.frequency.isNaN()) "" else " (%.0f Hz)".format(worst.frequency))
                }, worst == null)
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Schwing-Test abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    private val _backlash = MutableStateFlow<Map<Char, Double>?>(null)
    val backlash: StateFlow<Map<Char, Double>?> = _backlash.asStateFlow()

    /** Backlash test: line pairs approached from both sides, photographed and measured. */
    fun backlashTest(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Umkehrspiel", n, 2, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                laserTest(c, machine, BACKLASH_JOB, BacklashTest.job(), "Umkehrspiel-Test") { step(0, it) }
                val values = HashMap<Int, Pair<Char, Double>>()
                val pairs = BacklashTest.pairs()
                photographArea(c, machine, cal, BacklashTest.bounds(), st!!.config.camera?.light, { n, of -> step(1, "Linien fotografieren: Bild ${n + 1} von $of") }) { sampler, view ->
                    withContext(Dispatchers.Default) {
                        for ((i, pair) in pairs.withIndex()) {
                            if (values[i]?.second?.isNaN() == false) continue
                            val (axis, o) = pair
                            val far = o + if (axis == 'X') Pt(BacklashTest.GAP, BacklashTest.LEN) else Pt(BacklashTest.LEN, BacklashTest.GAP)
                            if (view.holds(Box(o.x - 1.5, o.y - 1.5, far.x + 1.5, far.y + 1.5))) values[i] = axis to BacklashTest.measure(sampler, axis, o)
                        }
                    }
                }
                val res = BacklashTest.result(values.values.toList())
                _backlash.value = res
                machine.notify("Umkehrspiel: X %.2f mm · Y %.2f mm%s".format(Locale.GERMANY, res['X'], res['Y'],
                    if (res.values.any { !it.isNaN() && it > 0.1 }) " – über 0,1 mm: Riemen nachspannen, Madenschrauben prüfen" else ""))
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Umkehrspiel-Test abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /** Grey-scale test result: the spec, measured tones and the curve. */
    class ToneOutcome(val spec: ToneTest.Spec, val tones: List<Double>, val curve: List<Double>)
    private val _tone = MutableStateFlow<ToneOutcome?>(null)
    val tone: StateFlow<ToneOutcome?> = _tone.asStateFlow()

    fun toneTest(machine: MachineViewModel, maxPower: Double, speed: Double) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Graustufen-Test", n, 2, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                val spec = ToneTest.Spec(maxPower, speed)
                laserTest(c, machine, TONE_JOB, ToneTest.job(spec, st!!.config.motion?.toMotion() ?: MarlinWriter.Motion.FIRMWARE), "Graustufen-Test") { step(0, it) }
                val tones = HashMap<Int, Double>()
                val f = spec.fields
                photographArea(c, machine, cal, f.bounds(), st.config.camera?.light, { n, of -> step(1, "Felder fotografieren: Bild ${n + 1} von $of") }) { sampler, view ->
                    withContext(Dispatchers.Default) {
                        for (i in f.powers.indices) {
                            if (i in tones) continue
                            val b = f.cell(i, 0); val m = f.gapMm / 2
                            if (view.holds(Box(b.minX - m, b.minY - m, b.maxX + m, b.maxY + m))) EngraveTest.measure(f, i, 0, sampler)?.let { tones[i] = it.tone }
                        }
                    }
                }
                if (tones.size < f.powers.size) throw IllegalStateException("${f.powers.size - tones.size} Felder nicht messbar")
                val list = f.powers.indices.map { tones.getValue(it) }
                _tone.value = ToneOutcome(spec, list, ToneTest.curve(list))
                machine.notify("Graustufen gemessen – Kurve auf die Gravur-Ebene übernehmen")
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Graustufen-Test abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /* ---------- 3D height: work laser glimmer spot, later the red line laser ---------- */

    private val _spotPower = MutableStateFlow(prefs.getInt("spotPower", 0).takeIf { it > 0 })
    /** Glimmer power (S of 255) from the power test: seen by the camera, leaves no mark. */
    val spotPower: StateFlow<Int?> = _spotPower.asStateFlow()

    fun setSpotPower(s: Int?) {
        _spotPower.value = s
        prefs.edit().putInt("spotPower", s ?: 0).apply()
    }

    private val _spotTest = MutableStateFlow<List<SpotMeasure.PowerStep>?>(null)
    val spotTest: StateFlow<List<SpotMeasure.PowerStep>?> = _spotTest.asStateFlow()

    /**
     * Power test for the glimmer spot: short slow lines at S 1 … 13, a
     * picture during each; afterwards a photo of the lines. Keeps the lowest
     * power the camera sees while nothing up to it left a mark.
     */
    fun spotPowerTest(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Laserpunkt-Leistungstest", n, 3, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val origin = Work.center - Pt(SpotMeasure.LENGTH / 2, 18.0)
                step(0, "Oberfläche abtasten …")
                val surface = probe(c, machine, origin + Pt(SpotMeasure.LENGTH / 2, 18.0))
                runCatching { c.clearCaptures() }
                runPlain(c, machine, SPOT_JOB, SpotMeasure.powerTestJob(origin, surface, cal.photoWidth, cal.photoHeight), "Leistungstest") { step(1, it) }
                val steps = SpotMeasure.TEST_POWERS.mapIndexed { k, s ->
                    val spot = decode(c.cameraCapture("spotpow-$k"))?.let { (px, w, h) -> withContext(Dispatchers.Default) { LightFinder.spot(px, w, h) } }
                    Triple(k, s, spot)
                }
                val marks = HashMap<Int, Double>()
                val box = Box(origin.x - 2, origin.y - 2, origin.x + SpotMeasure.LENGTH + 2, SpotMeasure.powerLine(origin, SpotMeasure.TEST_POWERS.size - 1).y + 2)
                photographArea(c, machine, cal, box, st.config.camera?.light, { _, _ -> step(2, "Spuren suchen …") }) { sampler, view ->
                    for ((k, _, _) in steps) {
                        if (k in marks) continue
                        val a = SpotMeasure.powerLine(origin, k)
                        if (view.holds(Box(a.x, a.y - 1.5, a.x + SpotMeasure.LENGTH, a.y + 1.5))) marks[k] = SpotMeasure.markOf(sampler, a)
                    }
                }
                val result = steps.map { (k, s, spot) -> SpotMeasure.PowerStep(s, spot != null && spot.strength >= 60, spot?.strength ?: 0.0, marks[k] ?: Double.NaN) }
                _spotTest.value = result
                val pick = SpotMeasure.pickPower(result.filter { !it.mark.isNaN() })
                setSpotPower(pick)
                machine.notify(pick?.let { "Laserpunkt: S$it (%.1f %%) – sichtbar, ohne Spur".format(Locale.GERMANY, it / 2.55) }
                    ?: "Laserpunkt: keine Leistung, die sichtbar ist und keine Spur hinterlässt – auf diesem Material nicht nutzbar", pick == null)
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Leistungstest abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /** Calibrates the glimmer spot over the flat plate: one line at each distance, the spot's picture position each time. */
    fun spotCalibrate(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val power = _spotPower.value ?: run { machine.notify("Erst den Leistungstest für den Laserpunkt", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Laserpunkt kalibrieren", n, 2, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val origin = Work.center - Pt(SpotMeasure.LENGTH / 2, 6.0)
                step(0, "Oberfläche abtasten …")
                val surface = probe(c, machine, origin + Pt(SpotMeasure.LENGTH / 2, 5.0))
                runCatching { c.clearCaptures() }
                runPlain(c, machine, SPOT_JOB, SpotMeasure.calibrationJob(origin, surface, power, cal.photoWidth, cal.photoHeight), "Kalibrierlinien") { step(1, it) }
                val samples = SpotMeasure.CAL_DISTANCES.mapIndexedNotNull { k, d ->
                    decode(c.cameraCapture("spotcal-$k"))?.let { (px, w, h) -> withContext(Dispatchers.Default) { LightFinder.spot(px, w, h) } }?.let { d to listOf<Pt?>(it.px) }
                }
                if (samples.size < 4) throw IllegalStateException("Laserpunkt nur in ${samples.size} von ${SpotMeasure.CAL_DISTANCES.size} Bildern gefunden – Leistungstest wiederholen")
                val model = LightModel.fit("spot", listOf(0), samples, power)
                store(machine, cal.copy(spot = model))
                machine.notify("Laserpunkt kalibriert (%d Höhen)".format(samples.size))
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Kalibrierung abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /**
     * Heights without touching at the tapped probe points (or the motif
     * centre): the head stays at the travel height, a glimmer line through
     * every point, the spot's picture position gives the distance.
     */
    fun spotMeasure(machine: MachineViewModel, editor: EditorViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val model = cal.spot ?: run { machine.notify("Erst den Laserpunkt kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        val pts = _probePoints.value.ifEmpty { listOfNotNull(editor.doc.value.bounds()?.center) }
        if (pts.isEmpty()) { machine.notify("Erst Abtastpunkte im Scan antippen", true); return }
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Höhe messen (Laserpunkt)", n, 2, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                // the Pi allows own Z only over a measured surface: one touch at the first point if none is known
                if (st!!.workpiece_surface_z == null) { step(0, "Bezugsfläche abtasten …"); probe(c, machine, pts.first()) }
                val headZ = machine.refreshStatus()?.travel_z_mm ?: (st.workpiece_surface_z ?: 0.0) + SpotMeasure.MEASURE_DISTANCE
                runCatching { c.clearCaptures() }
                runPlain(c, machine, SPOT_JOB, SpotMeasure.measureJob(pts, headZ, model.power, cal.photoWidth, cal.photoHeight), "Messlinien") { step(1, it) }
                val heights = pts.mapIndexedNotNull { k, p ->
                    val spot = decode(c.cameraCapture("spotmes-$k"))?.let { (px, w, h) -> withContext(Dispatchers.Default) { LightFinder.spot(px, w, h) } }
                    spot?.let { model.distance(0, it.px) }?.let { (d, _) -> p to headZ - d }
                }
                if (heights.isEmpty()) throw IllegalStateException("Laserpunkt in keinem Bild gefunden")
                editor.setHeights(HeightMapSet(heights.mapIndexed { i, (p, z) -> HeightMap("Punkt ${i + 1}", p.x, p.y, 0.0, 0.0, 1, 1, listOf(z)) }))
                reportHeights(machine, heights.map { it.second }, pts.size - heights.size)
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Höhenmessung abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    private fun reportHeights(machine: MachineViewModel, zs: List<Double>, missing: Int) {
        val st = machine.status.value
        val thick = st?.travel_z_mm?.let { it - 20.0 }
        val top = zs.max()
        machine.notify("Höhen %.1f … %.1f mm%s%s".format(Locale.GERMANY, zs.min(), top,
            if (missing > 0) " · $missing Punkt(e) ohne Messwert" else "",
            if (thick != null && top > thick + 2) " – höher als das gewählte Material (%.1f mm): Materialhöhe anpassen!".format(Locale.GERMANY, thick) else ""),
            thick != null && top > thick + 2)
    }

    /** Line laser calibration over the flat plate: on/off pictures at each distance (no laser burn, the head stands). */
    fun lineCalibrate(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            fun step(n: Int, text: String) { _run.value = Run("Linienlaser kalibrieren", n, SpotMeasure.CAL_DISTANCES.size + 1, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                if (st?.line_laser?.gpio == null) throw IllegalStateException("Linienlaser nicht eingerichtet (GPIO-Pin eintragen)")
                if (!st!!.homed) throw IllegalStateException("Erst referenzieren")
                step(0, "Oberfläche abtasten …")
                val surface = probe(c, machine, Work.center)
                headTo(c, machine, Work.center - cal.usable(0.0).center, null)
                val cols = LineMeasure.columns(cal.photoWidth)
                val samples = ArrayList<Pair<Double, List<Pt?>>>()
                try {
                    for ((k, d) in SpotMeasure.CAL_DISTANCES.withIndex()) {
                        step(k + 1, "Höhe %.0f mm über der Platte".format(d))
                        zTo(c, machine, surface + d)
                        c.lineLaser(true); val (on, w, h) = pixels(c, cal.photoWidth to cal.photoHeight)
                        c.lineLaser(false); val (off, _, _) = pixels(c, cal.photoWidth to cal.photoHeight)
                        samples += d to withContext(Dispatchers.Default) { LightFinder.line(on, off, w, h, cols) }
                    }
                } finally { withContext(kotlinx.coroutines.NonCancellable) { runCatching { c.lineLaser(false) } } }
                val model = LightModel.fit("line", cols, samples)
                if (model.keys.size < cols.size / 4) throw IllegalStateException("Linie nur in ${model.keys.size} von ${cols.size} Spalten gesehen – Laser ausrichten")
                store(machine, cal.copy(line = model))
                machine.notify("Linienlaser kalibriert (%d Spalten, %d Höhen)".format(model.keys.size, model.d.size))
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Linienlaser-Kalibrierung abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /**
     * 3D scan with the line laser over the marked areas (or the motif): the
     * head steps 2 mm at a time at the travel height, an on and an off
     * picture each time; heights become the height mesh.
     */
    fun lineScan(machine: MachineViewModel, editor: EditorViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val model = cal.line ?: run { machine.notify("Erst den Linienlaser kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        val boxes = _areas.value.ifEmpty { listOfNotNull(editor.doc.value.bounds()?.let { Box(it.minX - 5, it.minY - 5, it.maxX + 5, it.maxY + 5) }) }
        if (boxes.isEmpty()) { machine.notify("Erst Bereiche markieren oder ein Motiv anlegen", true); return }
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                if (st!!.workpiece_surface_z == null) probe(c, machine, boxes.first().center)
                val headZ = machine.refreshStatus()?.travel_z_mm ?: 20.0
                // where the line falls relative to the head at the measuring distance
                val dist = (headZ - (machine.status.value?.workpiece_surface_z ?: 0.0)).coerceIn(model.d.first(), model.d.last())
                val linePts = model.keys.indices.map { cal.pixelToWork(model.predict(it, dist), Pt(0.0, 0.0)) }
                val offY = linePts.map { it.y }.average(); val minX = linePts.minOf { it.x }; val maxX = linePts.maxOf { it.x }
                val span = (maxX - minX) * 0.9
                val heads = boxes.flatMap { b ->
                    val xs = if (b.width <= span) listOf(b.center.x - (minX + maxX) / 2) else
                        (0..(b.width / span).toInt()).map { b.minX + span / 2 + it * span - (minX + maxX) / 2 }
                    generateSequence(b.minY) { it + 2.0 }.takeWhile { it <= b.maxY }.flatMap { y -> xs.map { x -> Pt(x, y - offY) } }.toList()
                }
                val pts = ArrayList<Triple<Double, Double, Double>>()
                try {
                    for ((n, head) in heads.withIndex()) {
                        if (!isActive) return@launch
                        _run.value = Run("3D-Scan", n, heads.size, "Linie ${n + 1} von ${heads.size}")
                        val at = headTo(c, machine, head, headZ)
                        c.lineLaser(true); val (on, w, h) = pixels(c, cal.photoWidth to cal.photoHeight)
                        c.lineLaser(false); val (off, _, _) = pixels(c, cal.photoWidth to cal.photoHeight)
                        pts += withContext(Dispatchers.Default) { LineMeasure.points(model, on, off, w, h, cal, at, headZ) }
                    }
                } finally { withContext(kotlinx.coroutines.NonCancellable) { runCatching { c.lineLaser(false) } } }
                val grid = LineMeasure.grid("3D-Scan", pts) ?: throw IllegalStateException("Linie in keinem Bild gefunden")
                editor.setHeights(HeightMapSet(listOf(grid)))
                markDone("probe")
                reportHeights(machine, grid.measured, 0)
                runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("3D-Scan abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    /* ---------- motion and cut tests ---------- */

    /** Last motion calibration: per level the shift of its check mark and the last level that held. */
    class MotionOutcome(val levels: List<MotionTest.Level>, val shifts: List<MotionTest.Shift>, val lastGood: Int, val kept: MarlinWriter.Motion?)
    private val _motion = MutableStateFlow<MotionOutcome?>(null)
    val motion: StateFlow<MotionOutcome?> = _motion.asStateFlow()

    /**
     * Motion calibration: reference marks, a check mark without stress (the
     * baseline), then per level laser-off stress moves at rising
     * acceleration and speed followed by a check mark, photographed and
     * measured right away. Stops at the first level that lost a step and
     * stores 70 % / 80 % of the last good level on the Pi.
     */
    fun motionCalibration(machine: MachineViewModel) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            val levels = MotionTest.LEVELS
            val n = levels.size + 1
            val total = 2 + 2 * levels.size
            fun step(k: Int, text: String) { _run.value = Run("Bewegungs-Kalibrierung", k, total, text) }
            try {
                val st = machine.refreshStatus()
                needCamera(st)
                val motion = st!!.config.motion?.toMotion() ?: MarlinWriter.Motion.FIRMWARE
                laserTest(c, machine, MOTION_REF_JOB, MotionTest.job("Referenzmarken", (0 until n).flatMap { MotionTest.reference(it, n) }, motion), "Referenzmarken") { step(0, it) }
                val shifts = ArrayList<MotionTest.Shift>()
                val area = MotionTest.bounds(n)
                suspend fun checkAndMeasure(k: Int, label: String) {
                    c.uploadJob(MOTION_CHECK_JOB, MotionTest.job("Prüfmarke ${k + 1}", MotionTest.check(k, n), motion))
                    c.action("start", mapOf("name" to MOTION_CHECK_JOB))
                    waitForJob(machine, MOTION_CHECK_JOB, "Prüfmarke") { step(2 * k + 1, "$label: Prüfmarke lasern") }
                    step(2 * k + 1, "$label: Prüfmarke messen")
                    val o = MotionTest.origin(k, n)
                    val shift = withScanLight(c, machine, st.config.camera?.light) {
                        val (head, _) = cameraOver(c, machine, cal, Pt(o.x + MotionTest.ARM / 2, o.y + MotionTest.ARM / 2))
                        val (px, w, h) = pixels(c, cal.photoWidth to cal.photoHeight)
                        withContext(Dispatchers.Default) { MotionTest.measure(PhotoSampler(px, w, h, cal, head), k, n) }
                    }
                    shifts += shift
                }
                checkAndMeasure(0, "Ohne Belastung")
                if (!shifts[0].found) throw IllegalStateException("Prüfmarke nicht erkannt – Kamera neu kalibrieren oder Licht prüfen")
                val m = Work.toMachine(area.center)
                for ((i, level) in levels.withIndex()) {
                    val label = "Stufe ${i + 1}: %.0f mm/s² · %.0f mm/min".format(level.accel, level.speed * 60)
                    step(2 * i + 2, "$label: Testfahrten")
                    c.motionTest(level.accel, level.speed, m.x, m.y, 40.0, 6)
                    checkAndMeasure(i + 1, label)
                    if (MotionTest.lastGood(shifts) < i) break      // this level lost steps: no harder ones
                }
                val last = MotionTest.lastGood(shifts)
                val keep = if (last >= 0) MotionTest.recommend(levels[last]) else null
                if (keep != null && (keep.accel > MarlinWriter.Motion.FIRMWARE.accel || keep.speed > MarlinWriter.Motion.FIRMWARE.speed)) {
                    c.motionLimits(MarlinWriter.Motion(maxOf(keep.accel, MarlinWriter.Motion.FIRMWARE.accel), maxOf(keep.speed, MarlinWriter.Motion.FIRMWARE.speed)))
                }
                machine.refreshStatus()
                _motion.value = MotionOutcome(levels, shifts, last, keep)
                machine.notify(when {
                    keep == null -> "Schon bei der ersten Stufe Schrittverlust – Riemenspannung und Motorstrom prüfen; Firmware-Werte bleiben"
                    last == levels.lastIndex -> "Bewegung: alle Stufen sauber – gespeichert %.0f mm/s², bis %.0f mm/min (Reserve eingerechnet)".format(keep.accel, keep.speed * 60)
                    else -> "Bewegung: Stufe ${last + 2} verlor Schritte – gespeichert %.0f mm/s², bis %.0f mm/min".format(keep.accel, keep.speed * 60)
                }, keep == null)
                // after lost steps the machine no longer knows where it is: parking could drive past the switches
                if (last < levels.lastIndex) runCatching { c.action("home") } else runCatching { c.action("park") }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Bewegungs-Kalibrierung abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    fun resetMotion(machine: MachineViewModel) = machine.request("motion", "Bewegung: Firmware-Werte") { c -> c.motionLimits(null).also { _motion.value = null; machine.refreshStatus() } }

    /** Cut test lasered with [spec], waiting for the operator to mark which squares fell out. */
    private val _cut = MutableStateFlow<CutTest.Spec?>(null)
    val cut: StateFlow<CutTest.Spec?> = _cut.asStateFlow()

    fun cutTest(machine: MachineViewModel, spec: CutTest.Spec) {
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus() ?: throw IllegalStateException("Pi nicht erreichbar")
                if (st.job.active) throw IllegalStateException("Es läuft gerade ein Auftrag")
                _cut.value = null
                laserTest(c, machine, CUT_JOB, CutTest.job(spec, st.config.motion?.toMotion() ?: MarlinWriter.Motion.FIRMWARE), "Schnitt-Test") {
                    _run.value = Run("Schnitt-Test", 0, 1, it)
                }
                _cut.value = spec
                machine.notify("Schnitt-Test fertig: Felder herausdrücken und in der App antippen, welche durchgefallen sind")
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                machine.notify("Schnitt-Test abgebrochen: ${e.message}", true)
            } finally { _run.value = null }
        }
    }

    fun clearCut() { _cut.value = null }

    /**
     * Photographs [region] and puts the pictures together. A part scan
     * keeps the earlier scan around it: only the photographed area changes.
     */
    fun scan(machine: MachineViewModel, editor: EditorViewModel, region: ScanRegion = ScanRegion.ALL) {
        val cal = _calibration.value ?: run { machine.notify("Erst die Kopfkamera kalibrieren", true); return }
        val c = machine.clientOrNotify() ?: return
        if (worker?.isActive == true) return
        val boxes = when (region) {
            ScanRegion.ALL -> listOf(Box(0.0, 0.0, Work.WIDTH, Work.HEIGHT))
            ScanRegion.MOTIF -> editor.doc.value.bounds()?.let { listOf(Box(it.minX - 10, it.minY - 10, it.maxX + 10, it.maxY + 10)) }
                ?: run { machine.notify("Kein Motiv im Editor – „Ganzer Arbeitsplatz“ wählen", true); return }
            ScanRegion.AREAS -> _areas.value.takeIf { it.isNotEmpty() }
                ?: run { machine.notify("Keine Bereiche markiert – unter Maschine → Arbeitsplatz scannen → „Bereiche markieren“ Rahmen ziehen", true); return }
        }
        worker = viewModelScope.launch {
            try {
                val st = machine.refreshStatus()
                if (st?.homed != true) throw IllegalStateException("Erst referenzieren")
                val plan = Scan.plan(cal, boxes)
                if (region == ScanRegion.ALL) plan.uncovered.forEach { machine.notify(it) }
                // same distance to the material as at the calibration: same scale, sharp picture
                val scanZ = cal.aboveSurface?.let { above ->
                    val surface = st?.workpiece_surface_z ?: run {
                        _run.value = Run("Scan", 0, plan.heads.size, "Oberfläche abtasten …")
                        probe(c, machine, boxes.first().center)
                    }
                    (surface + above).also { if (it > Z_TOP) throw IllegalStateException("Material zu hoch für die Kamera") }
                }
                // a part scan goes into the earlier one (same resolution), everything else stays
                val base = if (region == ScanRegion.ALL) null else runCatching {
                    editor.background.value?.asAndroidBitmap()?.let { b -> IntArray(b.width * b.height).also { b.getPixels(it, 0, b.width, 0, 0, b.width, b.height) } }
                }.getOrNull()
                val mosaic = Scan.Mosaic(cal, mosaicResolution(cal), base)
                withScanLight(c, machine, st?.config?.camera?.light) { for ((i, head) in plan.heads.withIndex()) {
                    if (!isActive) return@withScanLight
                    _run.value = Run("Scan", i, plan.heads.size, "Bild ${i + 1} von ${plan.heads.size}")
                    headTo(c, machine, head, scanZ)
                    val bmp = snapshot(c, cal.photoWidth to cal.photoHeight)
                    withContext(Dispatchers.Default) {
                        val sized = if (bmp.height == cal.photoHeight) bmp else Bitmap.createScaledBitmap(bmp, cal.photoWidth, cal.photoHeight, true)
                        val px = IntArray(sized.width * sized.height).also { sized.getPixels(it, 0, sized.width, 0, 0, sized.width, sized.height) }
                        mosaic.add(Scan.Tile(px, sized.width, sized.height, head))
                    }
                    if (scanZ == null) machine.refreshStatus()?.position?.getOrNull(2)?.let { z ->
                        if (i == 0 && kotlin.math.abs(z - cal.scanZ) > 1.0)
                            machine.notify("Kamerahöhe Z %.1f statt %.1f wie bei der Kalibrierung – Maßstab weicht ab".format(z, cal.scanZ), true)
                    }
                } }
                if (!isActive) return@launch
                _run.value = Run("Scan", plan.heads.size, plan.heads.size, "Mosaik wird berechnet …")
                val bmp = withContext(Dispatchers.Default) { Bitmap.createBitmap(Scan.level(mosaic.pixels, mosaic.width, mosaic.height, mosaicResolution(cal)), mosaic.width, mosaic.height, Bitmap.Config.ARGB_8888) }
                editor.setBackground(bmp)
                markDone("scan")
                machine.notify(when (region) {
                    ScanRegion.ALL -> "Arbeitsfläche gescannt (${plan.heads.size} Bilder)"
                    ScanRegion.MOTIF -> "Bereich unter dem Motiv gescannt (${plan.heads.size} Bilder)"
                    ScanRegion.AREAS -> "${boxes.size} markierte(r) Bereich(e) gescannt (${plan.heads.size} Bilder)"
                })
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

    /** Mosaic pixels per mm: close to what the camera resolves, 2 … 5 px/mm (5 px/mm ≈ 1800 × 1700 px). */
    private fun mosaicResolution(cal: CameraCalibration): Double {
        val native = cal.photoWidth / cal.footprint().width.coerceAtLeast(1.0)
        return (native * 0.8).coerceIn(2.0, 5.0)
    }

    companion object {
        const val GRID_JOB = "kamera-punktraster.gcode"
        const val PROBE_JOB = "kalibrierung-tasterziel.gcode"
        const val FOCUS_JOB = "kalibrierung-fokus.gcode"
        const val ENGRAVE_JOB = "kalibrierung-gravur.gcode"
        const val MOTION_REF_JOB = "kalibrierung-bewegung-referenz.gcode"
        const val MOTION_CHECK_JOB = "kalibrierung-bewegung-pruefung.gcode"
        const val CUT_JOB = "kalibrierung-schnitt.gcode"
        const val RINGING_JOB = "kalibrierung-schwingen.gcode"
        const val BACKLASH_JOB = "kalibrierung-umkehrspiel.gcode"
        const val TONE_JOB = "kalibrierung-graustufen.gcode"
        const val SPOT_JOB = "messung-laserpunkt.gcode"
        /** LED level for every camera picture: full on, so the dimming PWM cannot flicker in the picture. */
        const val LIGHT_LEVEL = 100
        /** Highest Z the camera is sent to: the rail limit, never more. */
        const val Z_TOP = Limits.Z_MAX_MM
        /** Tried in this order; the OV2710 (HBVCAM F1716) does Full HD, many webcams only 1280 × 720 raw. */
        val CAMERA_SIZES = listOf(1920 to 1080, 1280 to 720, 640 to 480)
    }
}
