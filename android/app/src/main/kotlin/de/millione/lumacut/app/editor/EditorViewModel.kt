package de.millione.lumacut.app.editor

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.app.machine.Notice
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.FocusCompensation
import de.millione.lumacut.core.FocusReport
import de.millione.lumacut.core.HeightMapSet
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.MarlinWriter
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Transform
import de.millione.lumacut.core.Work
import de.millione.lumacut.core.boundsOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import java.io.File
import java.util.UUID
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

enum class Tool(val label: String) { SELECT("Auswahl"), RECT("Rechteck"), ELLIPSE("Ellipse"), POLYGON("Vieleck"),
    LINE("Linie"), PEN("Freihand"), TEXT("Text") }

/** A built job: G-code for the Pi plus what the focus compensation did (null = not applied). */
class BuiltJob(val gcode: String, val focus: FocusReport?)

/**
 * Editor state. All geometry is in work-area mm (0..360 × 0..340, origin
 * top-left); the safezone never appears here and nothing can be moved into it.
 */
class EditorViewModel(app: Application) : AndroidViewModel(app) {
    private val dir = app.filesDir
    private val projectFile = File(dir, "project.json")
    private val materialFile = File(dir, "materials.json")
    private val backgroundFile = File(dir, "background.png")
    private val heightFile = File(dir, "heights.json")

    private val _doc = MutableStateFlow(load())
    val doc: StateFlow<Document> = _doc.asStateFlow()

    private val _selected = MutableStateFlow<Set<String>>(emptySet())
    val selected: StateFlow<Set<String>> = _selected.asStateFlow()

    /** Taps add to / remove from the selection instead of replacing it. */
    private val _multi = MutableStateFlow(false)
    val multi: StateFlow<Boolean> = _multi.asStateFlow()

    private val _activeLayer = MutableStateFlow(_doc.value.layers.getOrNull(1)?.id ?: _doc.value.layers.first().id)
    val activeLayer: StateFlow<String> = _activeLayer.asStateFlow()

    private val _tool = MutableStateFlow(Tool.SELECT)
    val tool: StateFlow<Tool> = _tool.asStateFlow()

    private val _materials = MutableStateFlow(loadMaterials())
    val materials: StateFlow<List<Material>> = _materials.asStateFlow()

    private val _background = MutableStateFlow(loadBackground())
    val background: StateFlow<ImageBitmap?> = _background.asStateFlow()
    private val _backgroundAlpha = MutableStateFlow(0.75f)
    val backgroundAlpha: StateFlow<Float> = _backgroundAlpha.asStateFlow()

    /** Measured surface heights of the current workpieces (camera workplace / probe grid). */
    private val _heights = MutableStateFlow(loadHeights())
    val heights: StateFlow<HeightMapSet?> = _heights.asStateFlow()

    private val _canUndo = MutableStateFlow(false); val canUndo: StateFlow<Boolean> = _canUndo
    private val _canRedo = MutableStateFlow(false); val canRedo: StateFlow<Boolean> = _canRedo

    private val _notices = MutableSharedFlow<Notice>(extraBufferCapacity = 8)
    val notices: SharedFlow<Notice> = _notices
    private val _openJobs = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val openJobs: SharedFlow<Unit> = _openJobs

    private val undo = ArrayDeque<Document>()
    private val redo = ArrayDeque<Document>()
    private var lastEditKey: String? = null
    private var lastEditAt = 0L
    private var saveJob: Job? = null

    fun notify(text: String, error: Boolean = false) { _notices.tryEmit(Notice(text, error)) }

    /* ---------- history ---------- */

    /** Applies a change; edits with the same [coalesce] key within 1.5 s share one undo step. */
    fun change(coalesce: String? = null, block: (Document) -> Document) {
        val now = System.currentTimeMillis()
        val merge = coalesce != null && coalesce == lastEditKey && now - lastEditAt < 1500
        if (!merge) { undo.addLast(_doc.value); if (undo.size > 100) undo.removeFirst(); redo.clear() }
        lastEditKey = coalesce; lastEditAt = now
        _doc.value = block(_doc.value)
        afterChange()
    }

    fun undo() {
        val prev = undo.removeLastOrNull() ?: return
        redo.addLast(_doc.value); _doc.value = prev; lastEditKey = null; afterChange()
    }

    fun redo() {
        val next = redo.removeLastOrNull() ?: return
        undo.addLast(_doc.value); _doc.value = next; lastEditKey = null; afterChange()
    }

    private fun afterChange() {
        _canUndo.value = undo.isNotEmpty(); _canRedo.value = redo.isNotEmpty()
        val d = _doc.value
        _selected.update { sel -> sel.filter { id -> d.elements.firstOrNull { it.id == id }?.let(::selectable) == true }.toSet() }
        if (d.layers.none { it.id == _activeLayer.value }) _activeLayer.value = d.layers.first().id
        // Autosave: the project survives an app kill or a crash and opens again on the next start.
        saveJob?.cancel()
        saveJob = viewModelScope.launch(Dispatchers.IO) {
            delay(800)
            runCatching { File(dir, "project.json.tmp").apply { writeText(_doc.value.toJson()) }.renameTo(projectFile) }
        }
    }

    private fun load(): Document = runCatching { Document.fromJson(projectFile.readText()) }.getOrElse { Document() }

    /* ---------- selection & tools ---------- */

    fun setTool(t: Tool) { _tool.value = t; if (t != Tool.SELECT) _selected.value = emptySet() }
    fun setMulti(on: Boolean) { _multi.value = on }

    private fun selectable(e: Element): Boolean = _doc.value.layer(e.layerId)?.let { it.visible && !it.locked } ?: false

    /** The element plus its group mates. */
    private fun withGroup(e: Element): Set<String> =
        if (e.groupId == null) setOf(e.id) else _doc.value.elements.filter { it.groupId == e.groupId }.map { it.id }.toSet()

    /** Tap selection: groups are selected as a whole; with [additive] the tap toggles. */
    fun select(id: String?, additive: Boolean = _multi.value) {
        lastEditKey = null
        val e = id?.let { i -> _doc.value.elements.firstOrNull { it.id == i } }?.takeIf(::selectable)
        if (e == null) { if (!additive) _selected.value = emptySet(); return }
        val ids = withGroup(e)
        _selected.value = when {
            !additive -> ids
            _selected.value.containsAll(ids) -> _selected.value - ids
            else -> _selected.value + ids
        }
    }

    /** Rubber band: everything whose bounds lie fully inside [box]. */
    fun selectIn(box: Box, additive: Boolean = _multi.value) {
        val hits = _doc.value.elements.filter { e ->
            selectable(e) && e.worldBounds()?.let { b -> b.minX >= box.minX && b.maxX <= box.maxX && b.minY >= box.minY && b.maxY <= box.maxY } == true
        }.flatMap(::withGroup).toSet()
        _selected.value = if (additive) _selected.value + hits else hits
    }

    fun selectAll() { _selected.value = _doc.value.elements.filter(::selectable).map { it.id }.toSet() }

    fun setActiveLayer(id: String) {
        _activeLayer.value = id
        val ids = _selected.value
        if (ids.isNotEmpty() && _doc.value.layer(id)?.locked == false)
            change("layer") { d -> d.copy(elements = d.elements.map { if (it.id in ids) it.copy(layerId = id) else it }) }
    }

    fun selectedElements(): List<Element> = _doc.value.elements.filter { it.id in _selected.value }
    fun selectedElement(): Element? = selectedElements().singleOrNull()
    fun selectionBounds(): Box? = selectedElements().mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) }

    /** Topmost selectable element whose bounds (plus a touch margin) contain [p]. */
    fun hit(p: Pt, marginMm: Double): Element? = _doc.value.elements.lastOrNull { e ->
        selectable(e) && e.worldBounds()?.let { b -> p.x in b.minX - marginMm..b.maxX + marginMm && p.y in b.minY - marginMm..b.maxY + marginMm } == true
    }

    /* ---------- elements ---------- */

    /** Adds vector content given in work mm; it is normalised so its local origin is the top-left of its bounds. */
    fun addVector(kind: String, worldPaths: List<Poly>, text: String? = null, fontSizeMm: Double = 10.0,
                  bold: Boolean = false, fontFamily: String = "sans-serif"): Element? {
        val box = boundsOf(worldPaths) ?: return null
        val local = worldPaths.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } }
        val e = Element(layerId = writableLayer(), kind = kind, transform = Transform(box.minX, box.minY), paths = local,
                        text = text, fontSizeMm = fontSizeMm, bold = bold, fontFamily = fontFamily)
        change { it.copy(elements = it.elements + e) }
        _selected.value = setOf(e.id)
        return e
    }

    fun addElement(e: Element) { change { it.copy(elements = it.elements + e.copy(layerId = writableLayer())) }; _selected.value = setOf(e.id) }

    /** Active layer, or the first unlocked visible one when the active layer is locked/hidden. */
    private fun writableLayer(): String {
        val d = _doc.value
        val active = d.layer(_activeLayer.value)
        if (active != null && active.visible && !active.locked) return active.id
        val other = d.layers.firstOrNull { it.visible && !it.locked } ?: return _activeLayer.value
        notify("Aktive Ebene ist gesperrt oder ausgeblendet – Element liegt auf „${other.name}“")
        return other.id
    }

    fun updateElement(id: String, coalesce: String? = null, block: (Element) -> Element) =
        change(coalesce?.let { "$id/$it" }) { d -> d.copy(elements = d.elements.map { if (it.id == id) block(it) else it }) }

    private fun updateSelected(coalesce: String?, block: (Element) -> Element) {
        val ids = _selected.value
        if (ids.isEmpty()) return
        change(coalesce?.let { "sel/$it" }) { d -> d.copy(elements = d.elements.map { if (it.id in ids) block(it) else it }) }
    }

    /** Moves the selection; it stops at the edge of the work area instead of entering the safezone. */
    fun moveSelected(dx: Double, dy: Double, coalesce: String) {
        val b = selectionBounds() ?: return
        val mx = clampDelta(dx, b.minX, b.maxX, Work.WIDTH)
        val my = clampDelta(dy, b.minY, b.maxY, Work.HEIGHT)
        if (mx == 0.0 && my == 0.0) return
        updateSelected(coalesce) { it.copy(transform = it.transform.copy(x = it.transform.x + mx, y = it.transform.y + my)) }
    }

    private fun clampDelta(d: Double, lo: Double, hi: Double, size: Double): Double {
        val min = -lo; val max = size - hi
        // Already (partly) outside: only allow moves that bring it back in.
        return if (min > max) d else d.coerceIn(minOf(min, 0.0), maxOf(max, 0.0))
    }

    fun nudge(dx: Double, dy: Double) = moveSelected(dx, dy, "nudge")

    /** After rotating or scaling: shifts the selection back into the work area if it fits there. */
    fun keepInside(coalesce: String) {
        val b = selectionBounds() ?: return
        fun shift(lo: Double, hi: Double, size: Double) = when {
            hi - lo > size -> 0.0
            lo < 0 -> -lo
            hi > size -> size - hi
            else -> 0.0
        }
        val dx = shift(b.minX, b.maxX, Work.WIDTH); val dy = shift(b.minY, b.maxY, Work.HEIGHT)
        if (dx != 0.0 || dy != 0.0) updateSelected(coalesce) { it.copy(transform = it.transform.copy(x = it.transform.x + dx, y = it.transform.y + dy)) }
        if (b.width > Work.WIDTH || b.height > Work.HEIGHT) notify("Größer als der Arbeitsbereich 360 × 340 mm – bitte verkleinern", true)
    }

    /** Sets the world size of a single selection by scaling its local content. */
    fun resizeSelected(widthMm: Double?, heightMm: Double?, keepAspect: Boolean) {
        val e = selectedElement() ?: return
        val local = localSize(e) ?: return
        var sx = widthMm?.let { it / local.first } ?: e.transform.scaleX
        var sy = heightMm?.let { it / local.second } ?: e.transform.scaleY
        if (keepAspect) { if (widthMm != null) sy = sx * (e.transform.scaleY / e.transform.scaleX) else if (heightMm != null) sx = sy * (e.transform.scaleX / e.transform.scaleY) }
        if (sx <= 0 || sy <= 0 || sx.isNaN() || sy.isNaN()) return
        updateElement(e.id, "size") { it.copy(transform = it.transform.copy(scaleX = sx, scaleY = sy)) }
    }

    /** Absolute rotation of a single element around its centre. Images stay upright (the raster runs line by line). */
    fun rotateSelected(deg: Double) {
        val e = selectedElement() ?: return
        if (e.isImage) return
        val pivot = e.worldBounds()?.center ?: return
        rotateSelectionBy(deg - e.transform.rotation, pivot, "rotate")
    }

    /** Rotates every selected vector element by [deg] around [pivot] (rotate handle). */
    fun rotateSelectionBy(deg: Double, pivot: Pt, coalesce: String) {
        if (deg == 0.0) return
        if (selectedElements().any { it.isImage }) { notify("Bilder werden nicht gedreht", true) }
        updateSelected(coalesce) { e ->
            if (e.isImage) e else {
                val t = rotateAround(Pt(e.transform.x, e.transform.y), pivot, deg)
                e.copy(transform = e.transform.copy(x = t.x, y = t.y, rotation = ((e.transform.rotation + deg) % 360 + 360) % 360))
            }
        }
    }

    /** Uniform scale of the selection by [k] around [anchor] (corner handle). */
    fun scaleSelectionBy(k: Double, anchor: Pt, coalesce: String) {
        if (k <= 0 || k.isNaN() || k == 1.0) return
        val b = selectionBounds() ?: return
        if (min(b.width, b.height) * k < 0.5 && k < 1) return
        updateSelected(coalesce) { e ->
            val t = e.transform
            e.copy(transform = t.copy(x = anchor.x + (t.x - anchor.x) * k, y = anchor.y + (t.y - anchor.y) * k,
                scaleX = t.scaleX * k, scaleY = t.scaleY * k))
        }
    }

    fun placeSelected(xMm: Double?, yMm: Double?) {
        val b = selectionBounds() ?: return
        moveSelected((xMm ?: b.minX) - b.minX, (yMm ?: b.minY) - b.minY, "place")
    }

    fun localSize(e: Element): Pair<Double, Double>? =
        if (e.isImage) e.imageWidthMm to e.imageHeightMm
        else boundsOf(e.paths)?.let { maxOf(it.width, 1e-6) to maxOf(it.height, 1e-6) }

    /** Sets an image's size from a resolution in dots per inch of its raster. */
    fun setImageDpi(id: String, dpi: Double) {
        if (dpi !in 10.0..2400.0) return
        updateElement(id, "dpi") { e ->
            val r = e.raster ?: return@updateElement e
            e.copy(imageWidthMm = r.width / dpi * 25.4, imageHeightMm = r.height / dpi * 25.4,
                transform = e.transform.copy(scaleX = 1.0, scaleY = 1.0))
        }
    }

    fun deleteSelected() {
        val ids = _selected.value
        if (ids.isEmpty()) return
        change { d -> d.copy(elements = d.elements.filterNot { it.id in ids }) }
    }

    fun duplicateSelected() {
        val items = selectedElements()
        if (items.isEmpty()) return
        val groups = items.mapNotNull { it.groupId }.distinct().associateWith { UUID.randomUUID().toString() }
        val copies = items.map { e ->
            e.copy(id = UUID.randomUUID().toString(), groupId = e.groupId?.let(groups::get),
                transform = e.transform.copy(x = e.transform.x + 5, y = e.transform.y + 5))
        }
        change { d -> d.copy(elements = d.elements + copies) }
        _selected.value = copies.map { it.id }.toSet()
        moveSelected(0.0, 0.0, "dup")
    }

    fun groupSelected() {
        if (_selected.value.size < 2) return
        val gid = UUID.randomUUID().toString()
        updateSelected(null) { it.copy(groupId = gid) }
        notify("${_selected.value.size} Elemente gruppiert")
    }

    fun ungroupSelected() {
        if (selectedElements().none { it.groupId != null }) return
        updateSelected(null) { it.copy(groupId = null) }
        notify("Gruppe aufgelöst")
    }

    /** Centres the selection, or everything, in the work area. */
    fun centerInWorkArea() {
        val target = Work.center
        val ids = _selected.value
        val box = (if (ids.isNotEmpty()) selectionBounds() else _doc.value.bounds()) ?: return
        val dx = target.x - box.center.x; val dy = target.y - box.center.y
        change { d -> d.copy(elements = d.elements.map { if (ids.isEmpty() || it.id in ids) it.copy(transform = it.transform.copy(x = it.transform.x + dx, y = it.transform.y + dy)) else it }) }
    }

    /* ---------- layers ---------- */

    fun updateLayer(id: String, coalesce: String? = null, block: (Layer) -> Layer) =
        change(coalesce?.let { "layer/$id/$it" }) { d -> d.copy(layers = d.layers.map { if (it.id == id) block(it) else it }) }

    fun addLayer() {
        val palette = listOf(0xFFFFB45CL, 0xFFB98CFFL, 0xFFFF8AD8L, 0xFF9BE15DL, 0xFF5CE1E6L)
        val n = _doc.value.layers.size
        val layer = Layer(name = "Ebene ${n + 1}", color = palette[n % palette.size], mode = LayerMode.LINE, powerPct = 50.0, speed = 1200.0)
        change { it.copy(layers = it.layers + layer) }
        _activeLayer.value = layer.id
    }

    fun deleteLayer(id: String) {
        val d = _doc.value
        if (d.layers.size <= 1) { notify("Die letzte Ebene bleibt bestehen", true); return }
        if (d.elements.any { it.layerId == id }) { notify("Ebene enthält noch Elemente", true); return }
        change { it.copy(layers = it.layers.filterNot { l -> l.id == id }) }
    }

    fun moveLayer(id: String, up: Boolean) = change { d ->
        val i = d.layers.indexOfFirst { it.id == id }
        val j = if (up) i - 1 else i + 1
        if (i < 0 || j !in d.layers.indices) d else d.copy(layers = d.layers.toMutableList().apply { add(j, removeAt(i)) })
    }

    fun applyMaterial(layerId: String, m: Material) {
        updateLayer(layerId) { m.applyTo(it) }
        val passes = m.effectivePasses
        notify("„${m.name} ${m.thicknessMm} mm · ${m.process}“ übernommen" + if (passes > 1) " · $passes Durchgänge" else "")
    }

    /* ---------- materials ---------- */

    private fun loadMaterials(): List<Material> = runCatching {
        Document.JSON.decodeFromString(ListSerializer(Material.serializer()), materialFile.readText())
    }.getOrElse { Material.defaults() }

    fun saveMaterial(m: Material) {
        _materials.update { list -> if (list.any { it.id == m.id }) list.map { if (it.id == m.id) m else it } else list + m }
        persistMaterials()
    }

    fun deleteMaterial(id: String) { _materials.update { it.filterNot { m -> m.id == id } }; persistMaterials() }

    private fun persistMaterials() = viewModelScope.launch(Dispatchers.IO) {
        runCatching { materialFile.writeText(Document.JSON.encodeToString(ListSerializer(Material.serializer()), _materials.value)) }
    }

    /* ---------- background photo & heights ---------- */

    private fun loadBackground(): ImageBitmap? =
        if (backgroundFile.exists()) runCatching { BitmapFactory.decodeFile(backgroundFile.path)?.asImageBitmap() }.getOrNull() else null

    /** Work-area image (0..360 × 0..340 mm, any resolution) under the design. */
    fun setBackground(bitmap: Bitmap?) {
        _background.value = bitmap?.asImageBitmap()
        viewModelScope.launch(Dispatchers.IO) {
            if (bitmap == null) backgroundFile.delete()
            else backgroundFile.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }

    fun setBackgroundAlpha(a: Float) { _backgroundAlpha.value = a.coerceIn(0f, 1f) }

    private fun loadHeights(): HeightMapSet? =
        runCatching { Document.JSON.decodeFromString(HeightMapSet.serializer(), heightFile.readText()) }.getOrNull()?.takeIf { it.maps.isNotEmpty() }

    fun setHeights(set: HeightMapSet?) {
        _heights.value = set?.takeIf { it.maps.isNotEmpty() }
        viewModelScope.launch(Dispatchers.IO) {
            val s = _heights.value
            if (s == null) heightFile.delete() else runCatching { heightFile.writeText(Document.JSON.encodeToString(HeightMapSet.serializer(), s)) }
        }
    }

    /* ---------- documents & output ---------- */

    /** Replaces the project (e.g. by a generated material test); undo brings the old one back. */
    fun replaceDocument(d: Document) {
        change { d }
        _selected.value = emptySet()
        _activeLayer.value = d.layers.first().id
    }

    fun newDocument() { change { Document(layers = it.layers) }; _selected.value = emptySet() }

    fun openJson(text: String) = runCatching { Document.fromJson(text) }
        .onSuccess { d -> change { d }; _selected.value = emptySet(); notify("Projekt „${d.title}“ geöffnet") }
        .onFailure { notify("Keine gültige LumaCut-Projektdatei", true) }

    fun rename(title: String) = change("title") { it.copy(title = title) }

    /**
     * Builds the job. With [focusGapMm]/[tipOffsetMm] and a height mesh, every
     * burning segment gets its own focus height over the measured surface.
     */
    suspend fun buildJob(compensate: Boolean, focusGapMm: Double, tipOffsetMm: Double): BuiltJob = withContext(Dispatchers.Default) {
        val gcode = MarlinWriter(appVersion()).write(_doc.value)
        val maps = _heights.value
        if (compensate && maps != null) {
            val (out, report) = FocusCompensation.apply(gcode, maps, focusGapMm, tipOffsetMm)
            BuiltJob(out, report)
        } else BuiltJob(gcode, null)
    }

    fun jobSent() { _openJobs.tryEmit(Unit) }

    private fun appVersion(): String = runCatching {
        val ctx = getApplication<Application>()
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
    }.getOrDefault("?")
}

/** Rotates [p] around [c] by [deg] degrees. */
fun rotateAround(p: Pt, c: Pt, deg: Double): Pt {
    val r = Math.toRadians(deg); val dx = p.x - c.x; val dy = p.y - c.y
    return Pt(c.x + dx * cos(r) - dy * sin(r), c.y + dx * sin(r) + dy * cos(r))
}
