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

    /** Largest picture size the camera delivered so far (Full HD first, 1280 × 720 if it refuses). */
    private var cameraSize = CAMERA_SIZES.first()

    /**
     * Snapshot from the head camera at full resolution, or scaled to
     * [width] px wide. Scan tiles are brought to the calibration's size.
     */
    suspend fun snapshot(c: PiClient, width: Int? = null): Bitmap {
        val bytes = try { c.cameraSnapshot(cameraSize.first, cameraSize.second) } catch (e: Exception) {
            val next = CAMERA_SIZES.getOrNull(CAMERA_SIZES.indexOf(cameraSize) + 1) ?: throw e
            cameraSize = next
            c.cameraSnapshot(next.first, next.second)
        }
        return withContext(Dispatchers.Default) {
            val raw = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw IllegalStateException("Kamerabild nicht lesbar")
            if (width == null || width == raw.width) raw
            else Bitmap.createScaledBitmap(raw, width, (raw.height.toLong() * width / raw.width).toInt(), true)
        }
    }

    fun sendGridJob(machine: MachineViewModel) =
        machine.uploadJob(GRID_JOB, DotGrid.job())

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
    private fun store(machine: MachineViewModel, cal: CameraCalibration) {
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

    private suspend fun pixels(c: PiClient): Triple<IntArray, Int, Int> {
        val bmp = snapshot(c)
        return withContext(Dispatchers.Default) {
            Triple(IntArray(bmp.width * bmp.height).also { bmp.getPixels(it, 0, bmp.width, 0, 0, bmp.width, bmp.height) }, bmp.width, bmp.height)
        }
    }

    /** Waits for the Pi's run of [name] to end; throws unless it completed. */
    private suspend fun waitForJob(machine: MachineViewModel, name: String, onProgress: (String) -> Unit) {
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
                    else -> "Punktraster wird gelasert: %d %%".format((job.fraction * 100).toInt())
                })
            }
            if (ours && !job.active && (seen || System.currentTimeMillis() - start > 20_000)) {
                if (job.state == "complete") return
                throw IllegalStateException("Punktraster nicht gelasert: " + job.error.ifBlank { job.state })
            }
            if (System.currentTimeMillis() - start > 40 * 60_000) throw IllegalStateException("Punktraster dauert ungewöhnlich lange – am Pi prüfen")
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
        val low = surface + 8; val high = Z_TOP
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
                c.uploadJob(GRID_JOB, DotGrid.job())
                lasering = true
                c.autorun(GRID_JOB)
                waitForJob(machine, GRID_JOB) { step(0, it) }
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
                // same distance to the material as at the calibration: same scale, sharp picture
                val scanZ = cal.aboveSurface?.let { above ->
                    val surface = st?.workpiece_surface_z ?: run {
                        _run.value = Run("Scan", 0, plan.heads.size, "Oberfläche abtasten …")
                        probe(c, machine, editor.doc.value.bounds()?.center ?: Work.center)
                    }
                    (surface + above).also { if (it > Z_TOP + 5) throw IllegalStateException("Material zu hoch für die Kamera") }
                }
                val mosaic = Scan.Mosaic(cal, mosaicResolution(cal))
                for ((i, head) in plan.heads.withIndex()) {
                    if (!isActive) return@launch
                    _run.value = Run("Scan", i, plan.heads.size, "Bild ${i + 1} von ${plan.heads.size}")
                    headTo(c, machine, head, scanZ)
                    val bmp = snapshot(c, cal.photoWidth)
                    withContext(Dispatchers.Default) {
                        val sized = if (bmp.height == cal.photoHeight) bmp else Bitmap.createScaledBitmap(bmp, cal.photoWidth, cal.photoHeight, true)
                        val px = IntArray(sized.width * sized.height).also { sized.getPixels(it, 0, sized.width, 0, 0, sized.width, sized.height) }
                        mosaic.add(Scan.Tile(px, sized.width, sized.height, head))
                    }
                    if (scanZ == null) machine.refreshStatus()?.position?.getOrNull(2)?.let { z ->
                        if (i == 0 && kotlin.math.abs(z - cal.scanZ) > 1.0)
                            machine.notify("Kamerahöhe Z %.1f statt %.1f wie bei der Kalibrierung – Maßstab weicht ab".format(z, cal.scanZ), true)
                    }
                }
                _run.value = Run("Scan", plan.heads.size, plan.heads.size, "Mosaik wird berechnet …")
                val bmp = withContext(Dispatchers.Default) { Bitmap.createBitmap(mosaic.pixels, mosaic.width, mosaic.height, Bitmap.Config.ARGB_8888) }
                editor.setBackground(bmp)
                markDone("scan")
                machine.notify("Arbeitsfläche gescannt (${plan.heads.size} Bilder)")
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
        /** Highest Z the camera is sent to (Pi travel 90 mm). */
        const val Z_TOP = 85.0
        /** Tried in this order; the OV2710 (HBVCAM F1716) does Full HD, many webcams only 1280 × 720 raw. */
        val CAMERA_SIZES = listOf(1920 to 1080, 1280 to 720)
    }
}
