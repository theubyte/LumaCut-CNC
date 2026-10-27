package de.millione.lumacut.app.editor

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.millione.lumacut.app.machine.Notice
import de.millione.lumacut.core.Arrange
import de.millione.lumacut.core.TagStyle
import de.millione.lumacut.core.ShapeKind
import de.millione.lumacut.core.Personalize
import de.millione.lumacut.core.Parts
import de.millione.lumacut.core.Curves
import de.millione.lumacut.core.Tabs
import de.millione.lumacut.core.Nest
import de.millione.lumacut.core.ImportUnit
import de.millione.lumacut.core.ImportItem
import de.millione.lumacut.core.BoxSpec
import de.millione.lumacut.core.BoxMaker
import de.millione.lumacut.core.Booleans
import de.millione.lumacut.core.Align
import de.millione.lumacut.core.EmbeddedImage
import de.millione.lumacut.core.ImportLayerInfo
import de.millione.lumacut.core.ImportLayout
import de.millione.lumacut.core.Layout
import de.millione.lumacut.core.Raster
import de.millione.lumacut.core.Box
import de.millione.lumacut.core.Document
import de.millione.lumacut.core.Element
import de.millione.lumacut.core.MeasPt
import de.millione.lumacut.core.Measurement
import de.millione.lumacut.core.Snap
import de.millione.lumacut.core.SnapHit
import de.millione.lumacut.core.FocusCompensation
import de.millione.lumacut.core.FocusReport
import de.millione.lumacut.core.HeightMapSet
import de.millione.lumacut.core.Layer
import de.millione.lumacut.core.LayerMode
import de.millione.lumacut.core.MarlinWriter
import de.millione.lumacut.core.Material
import de.millione.lumacut.core.MaterialGroup
import de.millione.lumacut.core.PartSplitter
import de.millione.lumacut.core.Poly
import de.millione.lumacut.core.Pt
import de.millione.lumacut.core.Transform
import de.millione.lumacut.core.Work
import de.millione.lumacut.core.boundsOf
import de.millione.lumacut.core.isClosed
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

/** An import that does not fit as drawn: the operator picks one of the ways out (dialog in the editor). */
class PendingImport(val kindLabel: String, val total: Int, val fitting: Int, val shrinkPercent: Int,
                    val onFitting: () -> Unit, val onShrink: () -> Unit,
                    val plates: Int = 0, val onPlates: (() -> Unit)? = null)

enum class Tool(val label: String) { SELECT("Auswahl"), NODES("Knoten"), RECT("Rechteck"), ELLIPSE("Ellipse"), POLYGON("Vieleck"),
    SHAPE("Formen"), LINE("Linie"), CURVE("Kurve"), PEN("Freihand"), TEXT("Text"), STAMP("Stempel"), PAINT("Zuweisen"),
    ERASER("Radierer"), MEASURE("Messen") }

/** A vertex of a vector element: path [poly], point [index]. */
data class NodeRef(val elementId: String, val poly: Int, val index: Int)

/** What the next taps of the measuring tool create. */
enum class MeasureMode(val label: String) {
    DISTANCE("Abstand"), GAP("Linie–Linie"), INFO("Element"), ANGLE("Winkel"), EDGES("Rand")
}

/** A built job: G-code for the Pi plus what the focus compensation did (null = not applied). */
class BuiltJob(val gcode: String, val focus: FocusReport?)

/**
 * Editor state. All geometry is in work-area mm (0..360 × 0..340, origin
 * top-left); the safezone never appears here and nothing can be moved into it.
 * The project can have several plates; [doc] is the plate being edited, so every
 * editing function works on that plate only, and [project] holds all of them.
 */
class EditorViewModel(app: Application) : AndroidViewModel(app) {
    private val dir = app.filesDir
    private val projectFile = File(dir, "project.json")
    private val prefs = app.getSharedPreferences("lumacut", Context.MODE_PRIVATE)
    private val backgroundFile = File(dir, "background.png")
    private val heightFile = File(dir, "heights.json")

    private val _project = MutableStateFlow(load())
    val project: StateFlow<Document> = _project.asStateFlow()
    private val _doc = MutableStateFlow(_project.value.plateView())
    val doc: StateFlow<Document> = _doc.asStateFlow()

    private val _selected = MutableStateFlow<Set<String>>(emptySet())
    val selected: StateFlow<Set<String>> = _selected.asStateFlow()

    /** Taps add to / remove from the selection instead of replacing it. */
    private val _multi = MutableStateFlow(false)
    val multi: StateFlow<Boolean> = _multi.asStateFlow()

    private val _activeLayer = MutableStateFlow(_doc.value.layers.firstOrNull { it.name == "Gravieren" }?.id ?: _doc.value.layers.first().id)
    val activeLayer: StateFlow<String> = _activeLayer.asStateFlow()

    private val _tool = MutableStateFlow(Tool.SELECT)
    val tool: StateFlow<Tool> = _tool.asStateFlow()

    private val _materials = MutableStateFlow<List<Material>>(emptyList())
    val materials: StateFlow<List<Material>> = _materials.asStateFlow()

    private val _background = MutableStateFlow(loadBackground())
    val background: StateFlow<ImageBitmap?> = _background.asStateFlow()
    private val _backgroundAlpha = MutableStateFlow(0.75f)
    val backgroundAlpha: StateFlow<Float> = _backgroundAlpha.asStateFlow()

    /** Measured surface heights of the current workpieces (camera workplace / probe grid). */
    private val _heights = MutableStateFlow(loadHeights())
    val heights: StateFlow<HeightMapSet?> = _heights.asStateFlow()

    val pendingImport = MutableStateFlow<PendingImport?>(null)

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

    /** Applies a change to the plate being edited; edits with the same [coalesce] key within 1.5 s share one undo step. */
    fun change(coalesce: String? = null, block: (Document) -> Document) =
        changeProject(coalesce) { p -> p.withPlate(block(p.plateView())) }

    /** Applies a change to the whole project (all plates). */
    private fun changeProject(coalesce: String? = null, block: (Document) -> Document) {
        val now = System.currentTimeMillis()
        val merge = coalesce != null && coalesce == lastEditKey && now - lastEditAt < 1500
        if (!merge) { undo.addLast(_project.value); if (undo.size > 100) undo.removeFirst(); redo.clear() }
        lastEditKey = coalesce; lastEditAt = now
        _project.value = block(_project.value)
        afterChange()
    }

    // Undo shows the plate the step happened on (the snapshot carries its active plate).
    fun undo() {
        val prev = undo.removeLastOrNull() ?: return
        redo.addLast(_project.value); _project.value = prev; lastEditKey = null; afterChange()
    }

    fun redo() {
        val next = redo.removeLastOrNull() ?: return
        undo.addLast(_project.value); _project.value = next; lastEditKey = null; afterChange()
    }

    private fun afterChange() {
        _canUndo.value = undo.isNotEmpty(); _canRedo.value = redo.isNotEmpty()
        if (_doc.value.activePlate != _project.value.activePlate) clearMeasurements()
        _doc.value = _project.value.plateView()
        val d = _doc.value
        _selected.update { sel -> sel.filter { id -> d.elements.firstOrNull { it.id == id }?.let(::selectable) == true }.toSet() }
        if (d.layers.none { it.id == _activeLayer.value }) _activeLayer.value = d.layers.first().id
        // Autosave: the project survives an app kill or a crash and opens again on the next start.
        saveJob?.cancel()
        saveJob = viewModelScope.launch(Dispatchers.IO) {
            delay(800)
            runCatching { File(dir, "project.json.tmp").apply { writeText(_project.value.toJson()) }.renameTo(projectFile) }
        }
    }

    private fun load(): Document = runCatching { Document.fromJson(projectFile.readText()) }.getOrElse { Document() }

    /** The whole project (all plates) as JSON, for "Projekt speichern". */
    fun projectJson(): String = _project.value.toJson()

    /* ---------- plates ---------- */

    /** Shows plate [i] in the editor (not an undo step). */
    fun setPlate(i: Int) {
        val p = _project.value
        if (i !in 0 until p.plateCount || i == p.activePlate) return
        _project.value = p.copy(activePlate = i)
        _selected.value = emptySet(); lastEditKey = null
        afterChange()
    }

    /** A new empty plate after the last one; the editor switches to it. */
    fun addPlate() {
        changeProject { it.addPlate() }
        _selected.value = emptySet()
        notify("Platte ${_project.value.plateCount} angelegt – hier geht es weiter")
    }

    fun deletePlate(i: Int) {
        if (_project.value.plateCount <= 1) { notify("Die letzte Platte bleibt bestehen", true); return }
        changeProject { it.removePlate(i) }
        notify("Platte ${i + 1} entfernt")
    }

    /** Moves the selection (same position) to plate [target]; [target] = plate count makes a new plate. */
    fun moveSelectedToPlate(target: Int) {
        val ids = _selected.value
        if (ids.isEmpty() || target == _project.value.activePlate) return
        changeProject { p ->
            val q = if (target >= p.plateCount) p.copy(plateCount = p.plateCount + 1) else p
            val t = minOf(target, q.plateCount - 1)
            q.moveToPlate(ids, t).copy(activePlate = t)
        }
        _selected.value = ids
        notify("${ids.size} Element(e) auf Platte ${_project.value.activePlate + 1} verschoben")
    }

    /* ---------- selection & tools ---------- */

    fun setTool(t: Tool) {
        if (t == Tool.STAMP) {
            val sel = selectedElements()
            if (sel.isNotEmpty()) _stamp.value = sel
            if (_stamp.value.isEmpty()) notify("Erst etwas auswählen, dann Stempel – jedes Antippen setzt eine Kopie", true)
        }
        _tool.value = t
        if (t != Tool.SELECT && t != Tool.NODES) _selected.value = emptySet()
        if (t == Tool.NODES && selectedElements().size > 1) _selected.value = emptySet()
        if (t != Tool.MEASURE) clearPendingMeasure()
        if (t != Tool.CURVE) _curve.value = emptyList()
    }

    /* ---------- creating and editing tools of the left bar ---------- */

    private val _shapeKind = MutableStateFlow(ShapeKind.STAR)
    val shapeKind: StateFlow<ShapeKind> = _shapeKind.asStateFlow()
    fun setShapeKind(k: ShapeKind) { _shapeKind.value = k }

    private val _polygonSides = MutableStateFlow(6)
    val polygonSides: StateFlow<Int> = _polygonSides.asStateFlow()
    fun setPolygonSides(n: Int) { _polygonSides.value = n.coerceIn(3, 24) }

    /** Points tapped so far with the curve tool. */
    private val _curve = MutableStateFlow<List<Pt>>(emptyList())
    val curve: StateFlow<List<Pt>> = _curve.asStateFlow()

    /** Adds a curve point; tapping the first point again closes the curve. */
    fun curveTap(p: Pt, closeRadiusMm: Double) {
        val pts = _curve.value
        if (pts.size >= 3 && p.dist(pts.first()) <= closeRadiusMm) { finishCurve(true); return }
        _curve.value = pts + Pt(p.x.coerceIn(0.0, Work.WIDTH), p.y.coerceIn(0.0, Work.HEIGHT))
    }

    fun finishCurve(closed: Boolean) {
        val pts = _curve.value
        _curve.value = emptyList()
        if (pts.size < 2) return
        addVector("Kurve", listOf(Curves.catmullRom(pts, closed && pts.size >= 3)))
        moveSelected(0.0, 0.0, "curve")
    }

    fun undoCurvePoint() { _curve.value = _curve.value.dropLast(1) }
    fun cancelCurve() { _curve.value = emptyList() }

    /** What the stamp tool places: the selection when the tool was picked. */
    private val _stamp = MutableStateFlow<List<Element>>(emptyList())
    val stamp: StateFlow<List<Element>> = _stamp.asStateFlow()

    /** A copy of the stamp centred at [p], moved back into the work area when it sticks out. */
    fun stampAt(p: Pt) {
        val items = _stamp.value
        val b = items.mapNotNull { it.worldBounds() }.reduceOrNull { a, c -> a.union(c) } ?: run { notify("Erst etwas auswählen, dann Stempel", true); return }
        if (b.width > Work.WIDTH || b.height > Work.HEIGHT) { notify("Die Vorlage ist größer als der Arbeitsbereich", true); return }
        val dx = (p.x - b.width / 2).coerceIn(0.0, Work.WIDTH - b.width) - b.minX
        val dy = (p.y - b.height / 2).coerceIn(0.0, Work.HEIGHT - b.height) - b.minY
        val groups = items.mapNotNull { it.groupId }.distinct().associateWith { UUID.randomUUID().toString() }
        val writable = _doc.value.layers.filter { !it.locked && it.visible }.map { it.id }.toSet()
        val copies = items.map { e -> e.copy(id = UUID.randomUUID().toString(), groupId = e.groupId?.let(groups::get),
            layerId = if (e.layerId in writable) e.layerId else writableLayer(),
            transform = e.transform.copy(x = e.transform.x + dx, y = e.transform.y + dy)) }
        change { d -> d.copy(elements = d.elements + copies) }
    }

    /** Puts the element at [p] on the active layer (Gravieren / Markieren / Schneiden from the right panel). */
    fun paintAt(p: Pt, marginMm: Double) {
        val e = hit(p, marginMm) ?: return
        val target = _activeLayer.value
        if (e.layerId == target) return
        val ids = withGroup(e)
        change { d -> d.copy(elements = d.elements.map { if (it.id in ids) it.copy(layerId = target) else it }) }
        notify("Auf „${_doc.value.layer(target)?.name}“ gelegt")
    }

    /** Deletes the element under [p] (only that element, not its group); one drag is one undo step. */
    fun eraseAt(p: Pt, marginMm: Double, coalesce: String) {
        val e = hit(p, marginMm) ?: return
        change(coalesce) { d -> d.copy(elements = d.elements.filterNot { it.id == e.id }) }
    }

    /** The vertex of the single selected vector element nearest to [p] within [radiusMm]. */
    fun nodeAt(p: Pt, radiusMm: Double): NodeRef? {
        val e = editableNodes() ?: return null
        var best: NodeRef? = null; var bestD = radiusMm
        e.worldPaths().forEachIndexed { pi, poly -> poly.forEachIndexed { i, q -> val d = q.dist(p); if (d <= bestD) { bestD = d; best = NodeRef(e.id, pi, i) } } }
        return best
    }

    /** The vertex last touched with the node tool ("Punkt löschen" acts on it). */
    private val _activeNode = MutableStateFlow<NodeRef?>(null)
    val activeNode: StateFlow<NodeRef?> = _activeNode.asStateFlow()
    fun setActiveNode(ref: NodeRef?) { _activeNode.value = ref }

    /** The single selected vector element whose points can be dragged (not too many to show), or null. */
    fun editableNodes(): Element? = selectedElement()?.takeIf { !it.isImage && it.paths.sumOf { p -> p.size } in 2..NODE_LIMIT }

    /** Moves a vertex to [world] (work mm); start and end of a closed path move together. */
    fun moveNode(ref: NodeRef, world: Pt, coalesce: String) {
        val w = Pt(world.x.coerceIn(0.0, Work.WIDTH), world.y.coerceIn(0.0, Work.HEIGHT))
        updateElement(ref.elementId, coalesce) { e ->
            val local = e.transform.invert(w)
            e.copy(paths = e.paths.mapIndexed { pi, poly ->
                if (pi != ref.poly) poly else {
                    val closed = poly.isClosed()
                    poly.mapIndexed { i, q -> if (i == ref.index || (closed && (ref.index == 0 || ref.index == poly.lastIndex) && (i == 0 || i == poly.lastIndex))) local else q }
                }
            })
        }
    }

    /** Removes a vertex (paths keep at least two points; closed ones at least a triangle). */
    fun deleteActiveNode() { _activeNode.value?.let(::deleteNode); _activeNode.value = null }

    fun deleteNode(ref: NodeRef) {
        updateElement(ref.elementId) { e ->
            e.copy(paths = e.paths.mapIndexed { pi, poly ->
                if (pi != ref.poly) poly else {
                    val closed = poly.isClosed()
                    if (poly.size <= (if (closed) 4 else 2)) poly
                    else if (closed && (ref.index == 0 || ref.index == poly.lastIndex)) poly.drop(1).dropLast(1).let { it + it.first() }
                    else poly.filterIndexed { i, _ -> i != ref.index }
                }
            })
        }
    }

    /* ---------- personalised pieces ---------- */

    private fun partsElements(parts: Parts, kind: String, at: Pt, group: Boolean): List<Element> {
        val gid = if (group) UUID.randomUUID().toString() else null
        fun el(polys: List<Poly>, layer: String, k: String): Element? {
            val box = boundsOf(polys) ?: return null
            return Element(layerId = layer, kind = k, transform = Transform(at.x + box.minX, at.y + box.minY),
                paths = polys.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } }, groupId = gid)
        }
        val labels = parts.labels.flatMap { (q, t) ->
            val glyphs = TextPaths.build(t, 3.0, false, "sans-serif")
            val gb = boundsOf(glyphs) ?: return@flatMap emptyList()
            glyphs.map { poly -> poly.map { Pt(it.x - gb.center.x + q.x, it.y - gb.minY + q.y) } }
        }
        return listOfNotNull(
            el(parts.engrave + labels, layerIdByName("Gravieren"), kind),
            el(parts.marks, layerIdByName("Linie"), "$kind (Linien)"),
            el(parts.cut, layerIdByName("Schneiden"), "$kind (Schnitt)"),
        )
    }

    /**
     * Places finished pieces space-saving: on the plate being edited when it is empty, otherwise on new plates
     * (more plates when needed). Returns the number of plates used.
     */
    private fun placePieces(pieces: List<List<Element>>): Int {
        val boxes = pieces.map { u -> u.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) } ?: Box(0.0, 0.0, 1.0, 1.0) }
        val placed = Nest.place(boxes)
        val reuse = _doc.value.elements.isEmpty()
        val base = _project.value.plateCount
        val first = if (reuse) _project.value.activePlate else base
        val used = (placed.filterNotNull().maxOfOrNull { it.first } ?: -1) + 1
        if (used == 0) { notify("Zu groß für eine Platte (360 × 340 mm)", true); return 0 }
        val newPlates = used - if (reuse) 1 else 0
        val all = pieces.flatMapIndexed { i, u -> placed[i]?.let { (k, o) ->
            u.map { e -> e.copy(plate = if (k == 0) first else (if (reuse) base + k - 1 else base + k),
                transform = e.transform.copy(x = e.transform.x + o.x, y = e.transform.y + o.y)) } } ?: emptyList() }
        changeProject { p -> p.copy(plateCount = base + newPlates, activePlate = first, elements = p.elements + all) }
        _selected.value = all.filter { it.plate == first }.map { it.id }.toSet()
        return used
    }

    /** One name tag per name; returns how many were made. */
    fun addTags(names: List<String>, style: TagStyle, heightMm: Double, bold: Boolean, holeMm: Double?): Int {
        val pieces = names.map { it.trim() }.filter { it.isNotEmpty() }.mapNotNull { n ->
            val text = TextPaths.build(n, heightMm, bold, "sans-serif").takeIf { it.isNotEmpty() } ?: return@mapNotNull null
            partsElements(Personalize.tag(text, style, holeMm), n, Pt(0.0, 0.0), true)
        }
        if (pieces.isEmpty()) { notify("Keine Namen eingegeben", true); return 0 }
        val plates = placePieces(pieces)
        if (plates > 0) notify("${pieces.size} × ${style.label}" + if (plates > 1) " auf $plates Platten" else "")
        return pieces.size
    }

    fun addEmblem(initials: String, top: String, bottom: String, diameterMm: Double) {
        fun t(s: String, bold: Boolean) = s.trim().takeIf { it.isNotEmpty() }?.let { TextPaths.build(it, 10.0, bold, "serif") }?.takeIf { it.isNotEmpty() }
        val mid = t(initials, true) ?: run { notify("Bitte Initialen eingeben", true); return }
        val parts = Personalize.emblem(mid, t(top, true), t(bottom, false), diameterMm)
        val at = Pt(Work.center.x - diameterMm / 2, Work.center.y - diameterMm / 2)
        val els = partsElements(parts, "Emblem", at, true)
        change { d -> d.copy(elements = d.elements + els) }
        _selected.value = els.map { it.id }.toSet()
    }

    /** Frame around the selection, or around everything on the plate. */
    fun addFrame(style: Personalize.FrameStyle, marginMm: Double, cut: Boolean) {
        val box = (if (_selected.value.isNotEmpty()) selectionBounds() else _doc.value.bounds())
            ?: run { notify("Erst ein Motiv anlegen – der Rahmen kommt darum herum", true); return }
        val polys = Personalize.frame(box, style, marginMm)
        val fb = boundsOf(polys) ?: return
        if (!Work.contains(fb)) { notify("Der Rahmen passt nicht in den Arbeitsbereich – kleineren Abstand wählen oder Motiv verschieben", true); return }
        val e = Element(layerId = layerIdByName(if (cut) "Schneiden" else "Linie"), kind = "Rahmen", transform = Transform(fb.minX, fb.minY),
            paths = polys.map { poly -> poly.map { Pt(it.x - fb.minX, it.y - fb.minY) } })
        change { d -> d.copy(elements = d.elements + e) }
        _selected.value = setOf(e.id)
    }

    fun addRuler(lengthMm: Int, widthMm: Double, holeMm: Double?) {
        val parts = Personalize.ruler(lengthMm, widthMm, holeMm)
        val b = parts.bounds() ?: return
        if (b.width > Work.WIDTH) { notify("Höchstens ${(Work.WIDTH - 20).toInt()} mm lang", true); return }
        val els = partsElements(parts, "Lineal", Pt(Work.center.x - b.width / 2, Work.center.y - b.height / 2), true)
        change { d -> d.copy(elements = d.elements + els) }
        _selected.value = els.map { it.id }.toSet()
    }

    /** Puzzle cut lines over the selection (e.g. a photo) or as a new [wMm] x [hMm] piece in the middle. */
    fun addPuzzle(cols: Int, rows: Int, wMm: Double, hMm: Double) {
        val box = selectionBounds() ?: Box(Work.center.x - wMm / 2, Work.center.y - hMm / 2, Work.center.x + wMm / 2, Work.center.y + hMm / 2)
        if (!Work.contains(box)) { notify("Das Puzzle passt nicht in den Arbeitsbereich", true); return }
        val polys = Personalize.puzzle(box.width, box.height, cols, rows, (System.currentTimeMillis() % 100000).toInt())
        val e = Element(layerId = layerIdByName("Schneiden"), kind = "Puzzle", transform = Transform(box.minX, box.minY), paths = polys)
        change { d -> d.copy(elements = d.elements + e) }
        _selected.value = setOf(e.id)
        notify("Puzzle mit ${cols * rows} Teilen")
    }

    /* ---------- measuring: display only, never part of the document or the job ---------- */

    private val _measureMode = MutableStateFlow(MeasureMode.DISTANCE)
    val measureMode: StateFlow<MeasureMode> = _measureMode.asStateFlow()
    private val _snapOn = MutableStateFlow(true)
    val snapOn: StateFlow<Boolean> = _snapOn.asStateFlow()
    private val _measurements = MutableStateFlow<List<Measurement>>(emptyList())
    val measurements: StateFlow<List<Measurement>> = _measurements.asStateFlow()
    private val _measureSelected = MutableStateFlow<String?>(null)
    val measureSelected: StateFlow<String?> = _measureSelected.asStateFlow()
    /** Points already placed for the measurement in progress (distance: 1, angle: 1-2). */
    private val _pendingPoints = MutableStateFlow<List<MeasPt>>(emptyList())
    val pendingPoints: StateFlow<List<MeasPt>> = _pendingPoints.asStateFlow()
    /** First element of a line-to-line measurement in progress. */
    private val _pendingElement = MutableStateFlow<String?>(null)
    val pendingElement: StateFlow<String?> = _pendingElement.asStateFlow()

    private fun clearPendingMeasure() { _pendingPoints.value = emptyList(); _pendingElement.value = null }

    fun setMeasureMode(m: MeasureMode) { _measureMode.value = m; clearPendingMeasure() }
    fun setSnap(on: Boolean) { _snapOn.value = on }
    fun selectMeasurement(id: String?) { _measureSelected.value = id }
    fun removeMeasurement(id: String) { _measurements.update { l -> l.filter { it.id != id } }; if (_measureSelected.value == id) _measureSelected.value = null }
    fun clearMeasurements() { _measurements.value = emptyList(); _measureSelected.value = null; clearPendingMeasure() }

    private fun measurable() = _doc.value.elements.filter { e -> _doc.value.layer(e.layerId)?.visible == true }

    /** What the finger would catch at [p] (null = free point or snapping off). */
    fun snapAt(p: Pt, radiusMm: Double): SnapHit? = if (_snapOn.value) Snap.find(p, radiusMm, measurable()) else null

    private fun addMeasurement(m: Measurement) { _measurements.update { it + m }; _measureSelected.value = m.id; clearPendingMeasure() }

    /** A finished touch of the measuring tool at [p]; [hit] is the snap result shown under the finger. */
    fun measureTap(p: Pt, hit: SnapHit?, pickRadiusMm: Double) {
        when (_measureMode.value) {
            MeasureMode.DISTANCE, MeasureMode.ANGLE -> {
                val pt = MeasPt.of(hit, p, _doc.value.elements)
                val pts = _pendingPoints.value + pt
                val need = if (_measureMode.value == MeasureMode.DISTANCE) 2 else 3
                if (pts.size < need) { _pendingPoints.value = pts; return }
                addMeasurement(if (need == 2) Measurement.Distance(pts[0], pts[1]) else Measurement.Angle(pts[0], pts[1], pts[2]))
            }
            MeasureMode.INFO, MeasureMode.EDGES, MeasureMode.GAP -> {
                val e = Snap.pick(p, pickRadiusMm, measurable()) ?: run { notify("Hier ist kein Element – direkt auf eine Form tippen", true); return }
                val ids = if (_measureMode.value == MeasureMode.GAP) listOf(e.id)
                          else (if (e.groupId == null) listOf(e.id) else _doc.value.elements.filter { it.groupId == e.groupId }.map { it.id })
                when (_measureMode.value) {
                    MeasureMode.INFO -> addMeasurement(Measurement.Info(ids))
                    MeasureMode.EDGES -> addMeasurement(Measurement.Edges(ids))
                    else -> {
                        val first = _pendingElement.value
                        when {
                            first == null -> _pendingElement.value = e.id
                            first == e.id -> notify("Das ist dasselbe Element – ein anderes antippen", true)
                            else -> addMeasurement(Measurement.Gap(first, e.id))
                        }
                    }
                }
            }
        }
    }
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

    private fun parseColor(key: String, fallback: Long): Long =
        key.removePrefix("#").takeIf { it.length == 6 }?.toLongOrNull(16)?.let { 0xFF000000L or it } ?: fallback

    /**
     * Places an arranged import as single elements. Original size ([scale] 1) or shrunk about the middle of the work area.
     * Groups of the file become our groups (outermost group, single parts stay single); xTool colour layers become layers
     * named after the colour with the values of the chosen material (lines like Schneiden, fills like Gravieren).
     * Returns the number of elements.
     */
    fun addImported(kind: String, layout: Layout, scale: Double, infos: List<ImportLayerInfo>, rasters: Map<EmbeddedImage, Raster>,
                    fallback: String? = null): Int {
        val doc = _doc.value
        val all = ImportLayout.union(layout.units).center
        fun map(p: Pt, i: Int): Pt {
            val o = layout.offsets[i] ?: Pt(0.0, 0.0)
            return if (scale == 1.0) Pt(p.x + o.x, p.y + o.y) else Pt(Work.center.x + (p.x - all.x) * scale, Work.center.y + (p.y - all.y) * scale)
        }
        val placed = layout.units.indices.filter { layout.offsets[it] != null }
        val cutBase = doc.layers.firstOrNull { it.name == "Schneiden" } ?: doc.layers.last()
        val engraveBase = doc.layers.firstOrNull { it.name == "Gravieren" } ?: doc.layers.first()
        val order = infos.associate { it.key to it.order }
        val used = placed.flatMap { layout.units[it].items }.filter { it.layerKey != null }
            .map { it.layerKey!! to it.fill }.distinct().sortedBy { order[it.first] ?: 1000 }
        val info = infos.associateBy { it.key }
        val layerIds = HashMap<Pair<String, Boolean>, String>()
        val fresh = ArrayList<Pair<Layer, Boolean>>()
        for ((key, fill) in used) {
            val name = (info[key]?.name ?: key) + if (fill) " (Füllen)" else ""
            val existing = doc.layers.firstOrNull { it.name == name }
            if (existing != null) { layerIds[key to fill] = existing.id; continue }
            val base = if (fill) engraveBase else cutBase
            val layer = base.copy(id = UUID.randomUUID().toString(), name = name, color = parseColor(key, base.color),
                mode = if (fill) LayerMode.FILL else LayerMode.LINE, visible = info[key]?.visible ?: true)
            layerIds[key to fill] = layer.id
            fresh += layer to fill
        }
        val groupSize = HashMap<String, Int>()
        for (u in placed) for (item in layout.units[u].items) item.groups.firstOrNull()?.let { groupSize.merge(it, 1, Int::plus) }
        val groupIds = HashMap<String, String>()
        fun groupOf(tag: String?): String? = if (tag == null || (groupSize[tag] ?: 0) < 2) null else groupIds.getOrPut(tag) { UUID.randomUUID().toString() }
        val fallbackLayer = fallback ?: writableLayer()
        val elements = ArrayList<Element>()
        for (u in placed) {
            val unit = layout.units[u]
            for (item in unit.items) {
                val polys = item.polys.map { poly -> poly.map { map(it, u) } }
                val box = boundsOf(polys) ?: continue
                elements += Element(layerId = item.layerKey?.let { layerIds[it to item.fill] } ?: fallbackLayer, kind = item.name?.takeIf { it.isNotBlank() } ?: kind,
                    transform = Transform(box.minX, box.minY), paths = polys.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } },
                    groupId = groupOf(item.groups.firstOrNull()))
            }
            for (img in unit.images) {
                val raster = rasters[img] ?: continue
                val a = map(Pt(img.box.minX, img.box.minY), u); val b = map(Pt(img.box.maxX, img.box.maxY), u)
                elements += Element(layerId = layerIdByName("Gravieren"), kind = "Bild", transform = Transform(a.x, a.y), raster = raster,
                    imageWidthMm = b.x - a.x, imageHeightMm = b.y - a.y)
            }
        }
        if (elements.isEmpty()) return 0
        change { d ->
            val layers = d.layers.toMutableList()
            val afterEngrave = layers.indexOfFirst { it.id == engraveBase.id } + 1
            var insertAt = afterEngrave
            for ((layer, fill) in fresh) if (fill) layers.add(insertAt++, layer)
            for ((layer, fill) in fresh) if (!fill) layers += layer       // cutting layers last
            d.copy(layers = layers, elements = d.elements + elements)
        }
        _selected.value = elements.map { it.id }.toSet()
        return elements.size
    }

    /**
     * An import spread over several plates: the first part on the plate being edited, the rest on new plates
     * after the last one. Returns the number of elements; the editor then shows the last new plate.
     */
    fun addImportedOnPlates(kind: String, plates: List<Layout>, infos: List<ImportLayerInfo>, rasters: Map<EmbeddedImage, Raster>,
                            fallback: String? = null): Int {
        var n = 0
        for ((i, layout) in plates.withIndex()) {
            if (i > 0) changeProject { it.addPlate() }
            n += addImported(kind, layout, 1.0, infos, rasters, fallback)
        }
        return n
    }

    /* ---------- tools: align, mirror, booleans, tabs, circular array, nesting, box maker ---------- */

    /** The selection as units that move together: each group once, single elements alone. */
    private fun selectionUnits(): List<List<Element>> = selectedElements().groupBy { it.groupId ?: it.id }.values.toList()

    private fun unitBox(u: List<Element>): Box? = u.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) }

    private fun moveUnits(units: List<List<Element>>, offsets: List<Pt>, coalesce: String?) {
        val by = HashMap<String, Pt>()
        units.forEachIndexed { i, u -> u.forEach { by[it.id] = offsets[i] } }
        if (by.values.all { it.x == 0.0 && it.y == 0.0 }) return
        change(coalesce) { d -> d.copy(elements = d.elements.map { e ->
            by[e.id]?.let { o -> e.copy(transform = e.transform.copy(x = e.transform.x + o.x, y = e.transform.y + o.y)) } ?: e
        }) }
    }

    /** Several units align to each other; a single element or group aligns to the work area. */
    fun alignSelected(mode: Align.Mode) {
        val units = selectionUnits()
        val boxes = units.map { unitBox(it) ?: return }
        if (boxes.isEmpty()) return
        val ref = if (boxes.size >= 2) boxes.reduce { a, b -> a.union(b) } else Box(0.0, 0.0, Work.WIDTH, Work.HEIGHT)
        moveUnits(units, Align.offsets(boxes, mode, ref), null)
    }

    fun distributeSelected(horizontal: Boolean) {
        val units = selectionUnits()
        if (units.size < 3) { notify("Zum Verteilen mindestens drei Elemente oder Gruppen wählen", true); return }
        moveUnits(units, Align.distribute(units.map { unitBox(it) ?: return }, horizontal), null)
    }

    /** Element with new work-area geometry (rotation and scale are baked into the paths). */
    private fun baked(e: Element, world: List<Poly>): Element {
        val box = boundsOf(world) ?: return e
        return e.copy(transform = Transform(box.minX, box.minY), paths = world.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } })
    }

    /** Mirrors the selection inside its bounds; [horizontal] = left/right, otherwise top/bottom. */
    fun mirrorSelected(horizontal: Boolean) {
        val ids = _selected.value
        val b = selectionBounds() ?: return
        fun m(q: Pt) = if (horizontal) Pt(b.minX + b.maxX - q.x, q.y) else Pt(q.x, b.minY + b.maxY - q.y)
        change { d -> d.copy(elements = d.elements.map { e ->
            when {
                e.id !in ids -> e
                e.isImage -> mirroredImage(e, horizontal, b)
                else -> baked(e, e.worldPaths().map { poly -> poly.map(::m) })
            }
        }) }
    }

    private fun mirroredImage(e: Element, horizontal: Boolean, b: Box): Element {
        val r = e.raster ?: return e
        val eb = e.worldBounds() ?: return e
        val src = r.gray(); val w = r.width; val h = r.height
        val out = ByteArray(src.size) { i -> val x = i % w; val y = i / w; if (horizontal) src[y * w + (w - 1 - x)] else src[(h - 1 - y) * w + x] }
        val t = if (horizontal) e.transform.copy(x = e.transform.x + (b.minX + b.maxX - eb.maxX) - eb.minX)
                else e.transform.copy(y = e.transform.y + (b.minY + b.maxY - eb.maxY) - eb.minY)
        return e.copy(raster = Raster.of(w, h, out), transform = t)
    }

    /** Weld / subtract / intersect the selected shapes into one new element (bottom-most = the one subtracted from). */
    fun booleanSelected(op: Booleans.Op) {
        val ids = _selected.value
        val shapes = _doc.value.elements.filter { it.id in ids && !it.isImage }
        if (shapes.size < 2) { notify("Mindestens zwei Formen wählen (Bilder gehen nicht)", true); return }
        viewModelScope.launch {
            val res = withContext(Dispatchers.Default) { Booleans.apply(shapes.map { it.worldPaths() }, op) }
            val box = boundsOf(res)
            if (res.isEmpty() || box == null) { notify("Kein Ergebnis – die Formen überschneiden sich nicht", true); return@launch }
            val e = Element(layerId = shapes.first().layerId, kind = op.label, transform = Transform(box.minX, box.minY),
                paths = res.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } })
            val gone = shapes.map { it.id }.toSet()
            change { d -> d.copy(elements = d.elements.filterNot { it.id in gone } + e) }
            _selected.value = setOf(e.id)
            notify("${op.label}: ${shapes.size} Formen → 1 Element")
        }
    }

    /** Holding tabs on the closed paths of the selection. Returns how many elements got tabs. */
    fun tabsSelected(count: Int, widthMm: Double): Int {
        val ids = _selected.value
        var n = 0
        val changed = _doc.value.elements.filter { it.id in ids && !it.isImage }.mapNotNull { e ->
            val world = e.worldPaths()
            val out = Tabs.apply(world, count, widthMm)
            if (out.size == world.size) null else baked(e, out).also { n++ }
        }.associateBy { it.id }
        if (changed.isNotEmpty()) change { d -> d.copy(elements = d.elements.map { changed[it.id] ?: it }) }
        return n
    }

    /**
     * Copies of the selection on a circle: [count] in total (the original included), circle centre [radiusMm] below the
     * selection centre. With [rotate] the copies turn with the circle (pictures only move). Returns copies left out.
     */
    fun circularArray(count: Int, radiusMm: Double, rotate: Boolean): Int {
        val items = selectedElements()
        val box = selectionBounds() ?: return 0
        val c = Pt(box.center.x, box.center.y + radiusMm)
        var left = 0
        val copies = ArrayList<Element>()
        for (k in 1 until count) {
            val a = 360.0 * k / count
            val groups = items.mapNotNull { it.groupId }.distinct().associateWith { UUID.randomUUID().toString() }
            val moved = rotateAround(box.center, c, a)
            val batch = items.map { e ->
                val t = e.transform
                val nt = if (rotate && !e.isImage) rotateAround(Pt(t.x, t.y), c, a).let { q -> t.copy(x = q.x, y = q.y, rotation = ((t.rotation + a) % 360 + 360) % 360) }
                         else t.copy(x = t.x + moved.x - box.center.x, y = t.y + moved.y - box.center.y)
                e.copy(id = UUID.randomUUID().toString(), groupId = e.groupId?.let(groups::get), transform = nt)
            }
            val bb = batch.mapNotNull { it.worldBounds() }.reduceOrNull { x, y -> x.union(y) }
            if (bb == null || !Work.contains(bb)) left++ else copies += batch
        }
        if (copies.isNotEmpty()) change { d -> d.copy(elements = d.elements + copies) }
        return left
    }

    /**
     * Arranges the selection (or the whole plate) space-saving from the top left; what does not fit continues on new
     * plates. Returns the number of plates used, 0 when there is nothing.
     */
    fun nestSelected(): Int {
        val units = (if (_selected.value.isEmpty()) _doc.value.elements else selectedElements()).groupBy { it.groupId ?: it.id }.values.toList()
        if (units.isEmpty()) return 0
        val placed = Nest.place(units.map { unitBox(it) ?: return 0 })
        val extra = placed.filterNotNull().maxOfOrNull { it.first } ?: 0
        val active = _project.value.activePlate
        val base = _project.value.plateCount
        val by = HashMap<String, Pair<Int, Pt>>()
        units.forEachIndexed { i, u -> placed[i]?.let { pl -> u.forEach { by[it.id] = pl } } }
        changeProject { p -> p.copy(plateCount = base + extra, elements = p.elements.map { e ->
            by[e.id]?.let { (k, o) -> e.copy(plate = if (k == 0) active else base + k - 1,
                transform = e.transform.copy(x = e.transform.x + o.x, y = e.transform.y + o.y)) } ?: e
        }) }
        val out = placed.count { it == null }
        notify("Platzsparend angeordnet" + (if (extra > 0) " · ${extra} neue Platte(n)" else "") +
            (if (out > 0) " · $out Teil(e) größer als eine Platte, nicht verschoben" else ""), out > 0)
        return extra + 1
    }

    /** A finger-jointed box on the cutting layer, panels side by side (more plates when needed). Returns the panel count. */
    fun addBox(spec: BoxSpec): Int {
        val panels = try { BoxMaker.panels(spec) } catch (e: IllegalArgumentException) { notify(e.message ?: "Box nicht möglich", true); return 0 }
        val units = panels.map { (name, poly) -> ImportUnit(listOf(ImportItem(listOf(poly), null, false, listOf("box"), name)), emptyList()) }
        val spread = ImportLayout.spread(units)
        if (spread.plates.isEmpty()) { notify("Die Box ist größer als eine Platte (360 × 340 mm)", true); return 0 }
        val cut = layerIdByName("Schneiden")
        val n = if (spread.plates.size == 1) addImported("Box", spread.plates[0], 1.0, emptyList(), emptyMap(), cut)
                else addImportedOnPlates("Box", spread.plates, emptyList(), emptyMap(), cut)
        notify("Box ${spec.w.fmt()} × ${spec.d.fmt()} × ${spec.h.fmt()} mm: $n Teile" +
            (if (spread.plates.size > 1) " auf ${spread.plates.size} Platten" else "") +
            (if (spread.leftOut > 0) " · ${spread.leftOut} Teil(e) zu groß" else ""), spread.leftOut > 0)
        return n
    }

    /** Thickness of the material on the cutting layer, for the box maker (3 mm when none is set). */
    fun cutThickness(): Double = _doc.value.layers.firstOrNull { it.name == "Schneiden" }?.thicknessMm?.takeIf { it > 0 } ?: 3.0

    private fun Double.fmt() = if (this % 1.0 == 0.0) toInt().toString() else "%.1f".format(this)

    /**
     * Imported geometry as single parts in one group (outer contour with its holes = one part, open path = one part),
     * so the pieces move together first and can be picked one by one after "Gruppe auflösen". Returns the number of parts.
     */
    fun addParts(kind: String, worldPaths: List<Poly>): Int {
        val split = PartSplitter.split(worldPaths)
        val layer = writableLayer()
        val gid = if (split.parts.size > 1) UUID.randomUUID().toString() else null
        val elements = split.parts.mapNotNull { part ->
            val box = boundsOf(part) ?: return@mapNotNull null
            Element(layerId = layer, kind = kind, transform = Transform(box.minX, box.minY),
                paths = part.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } }, groupId = gid)
        }
        if (elements.isEmpty()) return 0
        change { it.copy(elements = it.elements + elements) }
        _selected.value = elements.map { it.id }.toSet()
        if (split.tooMany) notify("Sehr viele Einzelteile – als ein Element übernommen", false)
        return elements.size
    }

    /** Vector content on the layer named [layerName] (Gravieren, Linie, Schneiden), moved to the middle of the work area. */
    fun addShape(kind: String, paths: List<Poly>, layerName: String): Element? {
        val box = boundsOf(paths) ?: return null
        val dx = Work.center.x - box.center.x; val dy = Work.center.y - box.center.y
        val local = paths.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } }
        val e = Element(layerId = layerIdByName(layerName), kind = kind, transform = Transform(box.minX + dx, box.minY + dy), paths = local)
        change { it.copy(elements = it.elements + e) }
        _selected.value = setOf(e.id)
        if (box.width > Work.WIDTH || box.height > Work.HEIGHT) notify("Größer als der Arbeitsbereich 360 × 340 mm – bitte verkleinern", true)
        return e
    }

    /**
     * Cut outline ([polys], work mm) on the Schneiden layer. Around a picture it is grouped with it and the
     * picture moves to Gravieren; with [removeSource] only the outline remains.
     */
    fun addContour(source: Element?, polys: List<Poly>, removeSource: Boolean) {
        val box = boundsOf(polys) ?: run { notify("Keine Kontur gefunden", true); return }
        val gid: String? = when {
            removeSource || source == null -> null
            else -> source.groupId ?: UUID.randomUUID().toString()
        }
        val local = polys.map { poly -> poly.map { Pt(it.x - box.minX, it.y - box.minY) } }
        val contour = Element(layerId = layerIdByName("Schneiden"), kind = "Kontur", transform = Transform(box.minX, box.minY), paths = local, groupId = gid)
        val engrave = layerIdByName("Gravieren")
        change { d ->
            val rest = if (removeSource && source != null) d.elements.filterNot { it.id == source.id }
                       else d.elements.map { if (source != null && it.id == source.id) it.copy(groupId = gid, layerId = if (it.isImage) engrave else it.layerId) else it }
            d.copy(elements = rest + contour)
        }
        _selected.value = if (gid != null) _doc.value.elements.filter { it.groupId == gid }.map { it.id }.toSet() else setOf(contour.id)
        keepInside("contour")
    }

    /** Copies the selection in a grid; copies that would leave the work area are left out. Returns how many were left out. */
    fun duplicateGrid(nx: Int, ny: Int, gapX: Double, gapY: Double): Int {
        val items = selectedElements()
        val box = selectionBounds() ?: return 0
        val all = Arrange.gridOffsets(box, nx, ny, gapX, gapY)
        val ok = Arrange.inside(box, all)
        val copies = ArrayList<Element>()
        for (o in ok) {
            val groups = items.mapNotNull { it.groupId }.distinct().associateWith { UUID.randomUUID().toString() }
            for (e in items) copies += e.copy(id = UUID.randomUUID().toString(), groupId = e.groupId?.let(groups::get),
                transform = e.transform.copy(x = e.transform.x + o.x, y = e.transform.y + o.y))
        }
        if (copies.isNotEmpty()) change { d -> d.copy(elements = d.elements + copies) }
        return all.size - ok.size
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

    /** The Pi's material list (fed by the shell); only used for the per-layer menu under "Erweitert". */
    fun setMaterials(list: List<Material>) { _materials.value = list }

    /** The machine's X/Y acceleration and speed (Pi config.motion): run-up length and speed limit of every job. */
    @Volatile var motion: MarlinWriter.Motion = MarlinWriter.Motion.FIRMWARE
        private set

    fun setMotion(m: MarlinWriter.Motion) { motion = m }

    /** "name|thickness" of the chosen material; null until the operator picked one. */
    private val _materialKey = MutableStateFlow(prefs.getString("materialKey", null))
    val materialKey: StateFlow<String?> = _materialKey.asStateFlow()

    /**
     * Applies a material to the whole motif: every process of it goes to its layer
     * (Gravieren, Markieren → "Linie", Schneiden). Layers without an entry keep their values.
     */
    fun selectMaterial(g: MaterialGroup) {
        _materialKey.value = g.key
        prefs.edit().putString("materialKey", g.key).apply()
        change { d ->
            d.copy(layers = d.layers.map { layer ->
                val process = when (layer.name) { "Gravieren" -> "Gravieren"; "Linie" -> "Markieren"; "Schneiden" -> "Schneiden"; else -> null }
                val m = process?.let { g.entry(it) }
                if (m != null) m.applyTo(layer) else layer
            })
        }
        notify("„${g.name} ${formatThickness(g.thicknessMm)} mm“ gewählt: " + g.processes.joinToString(" · "))
    }

    private fun formatThickness(v: Double) = if (v % 1.0 == 0.0) v.toInt().toString() else v.toString()

    /** The chosen material as another device set it on the Pi: only the key, the layers come with the project. */
    fun setMaterialKey(key: String?) {
        if (_materialKey.value == key) return
        _materialKey.value = key
        prefs.edit().putString("materialKey", key).apply()
    }

    /** The project as another device stored it on the Pi (undo brings this device's version back). */
    fun loadSyncedProject(json: String): Boolean = runCatching { Document.fromJson(json) }.onSuccess { d ->
        changeProject { d }
        _selected.value = _selected.value.filter { id -> d.elements.any { it.id == id } }.toSet()
    }.isSuccess

    /** Layer with [name] (Gravieren, Linie, Schneiden) or the active one. */
    fun layerIdByName(name: String): String = _doc.value.layers.firstOrNull { it.name == name }?.id ?: _activeLayer.value

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
        changeProject { d.normalized() }
        _selected.value = emptySet()
        _activeLayer.value = d.layers.first().id
    }

    fun newDocument() { changeProject { Document(layers = it.layers) }; _selected.value = emptySet() }

    fun openJson(text: String) = runCatching { Document.fromJson(text) }
        .onSuccess { d -> changeProject { d }; _selected.value = emptySet()
            notify("Projekt „${d.title}“ geöffnet" + if (d.plateCount > 1) " (${d.plateCount} Platten)" else "") }
        .onFailure { notify("Keine gültige LumaCut-Projektdatei", true) }

    fun rename(title: String) = change("title") { it.copy(title = title) }

    /**
     * Builds the job for [plate] (default: the plate being edited). With [focusGapMm]/[tipOffsetMm] and a height
     * mesh, every burning segment gets its own focus height over the measured surface.
     */
    suspend fun buildJob(compensate: Boolean, focusGapMm: Double, tipOffsetMm: Double,
                         plate: Int = _project.value.activePlate): BuiltJob = withContext(Dispatchers.Default) {
        val gcode = MarlinWriter(appVersion(), motion).write(_project.value.plateView(plate))
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

/** Above this many points the node tool does not show handles (imports, traced pictures). */
const val NODE_LIMIT = 600

/** Rotates [p] around [c] by [deg] degrees. */
fun rotateAround(p: Pt, c: Pt, deg: Double): Pt {
    val r = Math.toRadians(deg); val dx = p.x - c.x; val dy = p.y - c.y
    return Pt(c.x + dx * cos(r) - dy * sin(r), c.y + dx * sin(r) + dy * cos(r))
}
