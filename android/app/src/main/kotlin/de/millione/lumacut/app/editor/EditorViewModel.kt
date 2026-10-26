package de.millione.lumacut.app.editor

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.app.machine.Notice
import de.millione.lumacut.core.Bed
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.MarlinWriter
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Transform
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
import kotlin.math.sin

enum class Tool(val label: String) { SELECT("Auswahl"), RECT("Rechteck"), ELLIPSE("Ellipse"), POLYGON("Vieleck"),
    LINE("Linie"), PEN("Freihand"), TEXT("Text") }

class EditorViewModel(app: Application) : AndroidViewModel(app) {
    private val dir = app.filesDir
    private val projectFile = File(dir, "project.json")
    private val materialFile = File(dir, "materials.json")
    private val backgroundFile = File(dir, "background.png")

    private val _doc = MutableStateFlow(load())
    val doc: StateFlow<Document> = _doc.asStateFlow()

    private val _selected = MutableStateFlow<String?>(null)
    val selected: StateFlow<String?> = _selected.asStateFlow()

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
        if (_doc.value.elements.none { it.id == _selected.value }) _selected.value = null
        if (_doc.value.layers.none { it.id == _activeLayer.value }) _activeLayer.value = _doc.value.layers.first().id
        saveJob?.cancel()
        saveJob = viewModelScope.launch(Dispatchers.IO) { delay(800); runCatching { projectFile.writeText(_doc.value.toJson()) } }
    }

    private fun load(): Document = runCatching { Document.fromJson(projectFile.readText()) }.getOrElse { Document() }

    /* ---------- selection & tools ---------- */

    fun setTool(t: Tool) { _tool.value = t; if (t != Tool.SELECT) _selected.value = null }
    fun select(id: String?) { _selected.value = id; lastEditKey = null }
    fun setActiveLayer(id: String) {
        _activeLayer.value = id
        selectedElement()?.let { e -> if (e.layerId != id) updateElement(e.id, "layer") { it.copy(layerId = id) } }
    }
    fun selectedElement(): Element? = _doc.value.elements.firstOrNull { it.id == _selected.value }

    /** Topmost element whose bounds (plus a touch margin) contain [p]. */
    fun hit(p: Pt, marginMm: Double): Element? = _doc.value.elements.lastOrNull { e ->
        e.worldBounds()?.let { b -> p.x in b.minX - marginMm..b.maxX + marginMm && p.y in b.minY - marginMm..b.maxY + marginMm } == true
    }

    /* ---------- elements ---------- */

    /** Adds vector content given in machine mm; it is normalised so its local origin is the top-left of its bounds. */
    fun addVector(kind: String, worldPaths: List<Poly>, text: String? = null, fontSizeMm: Double = 10.0,
                  bold: Boolean = false, fontFamily: String = "sans-serif"): Element? {
        val box = boundsOf(worldPaths) ?: return null
        val local = worldPaths.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } }
        val e = Element(layerId = _activeLayer.value, kind = kind, transform = Transform(box.minX, box.minY), paths = local,
                        text = text, fontSizeMm = fontSizeMm, bold = bold, fontFamily = fontFamily)
        change { it.copy(elements = it.elements + e) }
        _selected.value = e.id
        return e
    }

    fun addElement(e: Element) { change { it.copy(elements = it.elements + e) }; _selected.value = e.id }

    fun updateElement(id: String, coalesce: String? = null, block: (Element) -> Element) =
        change(coalesce?.let { "$id/$it" }) { d -> d.copy(elements = d.elements.map { if (it.id == id) block(it) else it }) }

    fun moveSelected(dx: Double, dy: Double, coalesce: String) {
        val e = selectedElement() ?: return
        updateElement(e.id, coalesce) { it.copy(transform = it.transform.copy(x = it.transform.x + dx, y = it.transform.y + dy)) }
    }

    /** Sets the world size of the selection by scaling its local content. */
    fun resizeSelected(widthMm: Double?, heightMm: Double?, keepAspect: Boolean) {
        val e = selectedElement() ?: return
        val local = localSize(e) ?: return
        var sx = widthMm?.let { it / local.first } ?: e.transform.scaleX
        var sy = heightMm?.let { it / local.second } ?: e.transform.scaleY
        if (keepAspect) { if (widthMm != null) sy = sx * (e.transform.scaleY / e.transform.scaleX) else if (heightMm != null) sx = sy * (e.transform.scaleX / e.transform.scaleY) }
        if (sx <= 0 || sy <= 0 || sx.isNaN() || sy.isNaN()) return
        updateElement(e.id, "size") { it.copy(transform = it.transform.copy(scaleX = sx, scaleY = sy)) }
    }

    /** Rotation around the element centre (images do not rotate). */
    fun rotateSelected(deg: Double) {
        val e = selectedElement() ?: return
        if (e.isImage) return
        val before = e.worldBounds()?.center ?: return
        val rotated = e.copy(transform = e.transform.copy(rotation = deg))
        val after = rotated.worldBounds()?.center ?: return
        updateElement(e.id, "rotate") { rotated.copy(transform = rotated.transform.copy(x = rotated.transform.x + before.x - after.x, y = rotated.transform.y + before.y - after.y)) }
    }

    fun placeSelected(xMm: Double?, yMm: Double?) {
        val e = selectedElement() ?: return
        val b = e.worldBounds() ?: return
        moveSelected((xMm ?: b.minX) - b.minX, (yMm ?: b.minY) - b.minY, "place")
    }

    fun localSize(e: Element): Pair<Double, Double>? =
        if (e.isImage) e.imageWidthMm to e.imageHeightMm
        else boundsOf(e.paths)?.let { maxOf(it.width, 1e-6) to maxOf(it.height, 1e-6) }

    fun deleteSelected() { val id = _selected.value ?: return; change { d -> d.copy(elements = d.elements.filterNot { it.id == id }) } }

    fun duplicateSelected() {
        val e = selectedElement() ?: return
        val copy = e.copy(id = UUID.randomUUID().toString(), transform = e.transform.copy(x = e.transform.x + 5, y = e.transform.y + 5))
        addElement(copy)
    }

    /** Centres the selection, or everything, in the work area. */
    fun centerInWorkArea() {
        val target = Pt((Bed.SAFE + Bed.WIDTH) / 2, (Bed.SAFE + Bed.HEIGHT) / 2)
        val sel = selectedElement()
        val box = (if (sel != null) sel.worldBounds() else _doc.value.bounds()) ?: return
        val dx = target.x - box.center.x; val dy = target.y - box.center.y
        change { d -> d.copy(elements = d.elements.map { if (sel == null || it.id == sel.id) it.copy(transform = it.transform.copy(x = it.transform.x + dx, y = it.transform.y + dy)) else it }) }
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
        notify("„${m.name} ${m.thicknessMm} mm · ${m.process}“ übernommen")
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

    /* ---------- background photo ---------- */

    private fun loadBackground(): ImageBitmap? =
        if (backgroundFile.exists()) runCatching { BitmapFactory.decodeFile(backgroundFile.path)?.asImageBitmap() }.getOrNull() else null

    fun setBackground(bitmap: Bitmap?) {
        _background.value = bitmap?.asImageBitmap()
        viewModelScope.launch(Dispatchers.IO) {
            if (bitmap == null) backgroundFile.delete()
            else backgroundFile.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }

    fun setBackgroundAlpha(a: Float) { _backgroundAlpha.value = a.coerceIn(0f, 1f) }

    /* ---------- documents & output ---------- */

    /** Replaces the project (e.g. by a generated material test); undo brings the old one back. */
    fun replaceDocument(d: Document) {
        change { d }
        _selected.value = null
        _activeLayer.value = d.layers.first().id
    }

    fun newDocument() { change { Document(layers = it.layers) }; _selected.value = null }

    fun openJson(text: String) = runCatching { Document.fromJson(text) }
        .onSuccess { d -> change { d }; _selected.value = null; notify("Projekt „${d.title}“ geöffnet") }
        .onFailure { notify("Keine gültige LumaCut-Projektdatei", true) }

    fun rename(title: String) = change("title") { it.copy(title = title) }

    suspend fun buildGcode(imageTopAtMaxY: Boolean): String = withContext(Dispatchers.Default) {
        MarlinWriter(appVersion(), imageTopAtMaxY).write(_doc.value)
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
