package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.util.Base64
import java.util.UUID
import kotlin.math.ceil

@Serializable
enum class LayerMode { LINE, FILL }

/** Limits shared with the Windows app (lumacut_canvas/model.py). */
object Limits {
    val POWER = 0.0..100.0
    val SPEED = 1.0..6000.0
    val PASSES = 1..30
    val Z_STEP = 0.0..2.0
    /** Total focus drop over all passes; the Pi keeps Z >= surface + 2 mm, focus sits at surface + 5.5 mm. */
    const val MAX_FOCUS_DROP_MM = 3.0
    val THICKNESS = 0.0..50.0
    val DEPTH_PER_PASS = 0.0..10.0
}

/**
 * Laser settings shared by all elements on the layer. Power in percent of
 * S255. [zStepMm] lowers the focus between passes (cutting thick material).
 */
@Serializable
data class Layer(
    val id: String = UUID.randomUUID().toString(),
    val name: String,
    val color: Long,
    val mode: LayerMode = LayerMode.LINE,
    val powerPct: Double = 50.0,
    val minPowerPct: Double = 0.0,
    val speed: Double = 1500.0,
    val passes: Int = 1,
    val intervalMm: Double = 0.1,
    val overscanMm: Double = 2.5,
    val zStepMm: Double = 0.0,
    val output: Boolean = true,
    val visible: Boolean = true,
    val locked: Boolean = false,
    val materialName: String? = null,
    val thicknessMm: Double = 0.0,
    val depthPerPassMm: Double = 0.0,
) {
    val focusDropMm get() = zStepMm * (passes - 1)
}

/** Grayscale raster: 0 = black (full power), 255 = white (laser off). */
@Serializable
data class Raster(val width: Int, val height: Int, val grayBase64: String) {
    fun gray(): ByteArray = Base64.getDecoder().decode(grayBase64)

    companion object {
        fun of(width: Int, height: Int, gray: ByteArray): Raster {
            require(width > 0 && height > 0 && gray.size == width * height) { "Ungültige Bilddaten" }
            return Raster(width, height, Base64.getEncoder().encodeToString(gray))
        }
    }
}

@Serializable
enum class ImageMode { GRAYSCALE, DITHER, THRESHOLD, DITHER_JARVIS, DITHER_STUCKI }

/**
 * Something on the work area (coordinates in [Work] mm). Vector content
 * lives in [paths] (local mm, before [transform]); text keeps its source;
 * images carry a [raster] stretched over [imageWidthMm] x [imageHeightMm].
 * Elements with the same [groupId] are selected and moved together.
 * [plate] = index of the plate (sheet of material) the element is lasered on.
 */
@Serializable
data class Element(
    val id: String = UUID.randomUUID().toString(),
    val layerId: String,
    val kind: String,
    val transform: Transform = Transform(),
    val paths: List<List<Pt>> = emptyList(),
    val text: String? = null,
    val fontSizeMm: Double = 10.0,
    val bold: Boolean = false,
    val fontFamily: String = "sans-serif",
    val raster: Raster? = null,
    val imageWidthMm: Double = 0.0,
    val imageHeightMm: Double = 0.0,
    val imageMode: ImageMode = ImageMode.GRAYSCALE,
    val adjust: ImageAdjust = ImageAdjust(),
    val groupId: String? = null,
    val plate: Int = 0,
) {
    val isImage get() = raster != null

    /** Paths in work-area coordinates. */
    fun worldPaths(): List<Poly> = paths.map { poly -> poly.map(transform::apply) }

    /** Image corners in work-area coordinates (rotation applies to images too). */
    fun imageCorners(): List<Pt> = listOf(Pt(0.0, 0.0), Pt(imageWidthMm, 0.0), Pt(imageWidthMm, imageHeightMm), Pt(0.0, imageHeightMm))
        .map(transform::apply)

    fun worldBounds(): Box? = if (isImage) boundsOf(listOf(imageCorners())) else boundsOf(worldPaths())
}

/**
 * A project. A motif that does not fit on one sheet continues on further plates
 * ([plateCount], each a full work area); layers (material) are shared by all plates.
 */
@Serializable
data class Document(
    val title: String = "Neues Projekt",
    val layers: List<Layer> = defaultLayers(),
    val elements: List<Element> = emptyList(),
    val plateCount: Int = 1,
    val activePlate: Int = 0,
) {
    fun layer(id: String) = layers.firstOrNull { it.id == id }
    fun bounds(): Box? = elements.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) }

    /** Only the elements of plate [i] (what is lasered when that plate is started). */
    fun plateView(i: Int = activePlate): Document = copy(elements = elements.filter { it.plate == i })

    fun plateSize(i: Int): Int = elements.count { it.plate == i }

    /** Writes an edited [plateView] of the active plate back: title and layers from [view], its elements onto the active plate. */
    fun withPlate(view: Document): Document = copy(title = view.title, layers = view.layers,
        elements = elements.filter { it.plate != activePlate } + view.elements.map { if (it.plate == activePlate) it else it.copy(plate = activePlate) })

    /** A new empty plate after the last one, made active. */
    fun addPlate(): Document = copy(plateCount = plateCount + 1, activePlate = plateCount)

    /** Removes plate [i] with its elements; later plates move up one. The last plate stays. */
    fun removePlate(i: Int): Document {
        if (plateCount <= 1 || i !in 0 until plateCount) return this
        val els = elements.filter { it.plate != i }.map { if (it.plate > i) it.copy(plate = it.plate - 1) else it }
        val active = if (activePlate >= i) maxOf(0, activePlate - 1) else activePlate
        return copy(elements = els, plateCount = plateCount - 1, activePlate = active)
    }

    /** Moves the elements [ids] (same position) onto plate [target]. */
    fun moveToPlate(ids: Set<String>, target: Int): Document =
        if (target !in 0 until plateCount) this else copy(elements = elements.map { if (it.id in ids) it.copy(plate = target) else it })

    /** Old or hand-edited files: plate indices and the active plate inside 0 until plateCount. */
    fun normalized(): Document {
        val n = maxOf(plateCount, (elements.maxOfOrNull { it.plate } ?: 0) + 1, 1)
        return copy(plateCount = n, activePlate = activePlate.coerceIn(0, n - 1),
            elements = if (elements.any { it.plate < 0 }) elements.map { if (it.plate < 0) it.copy(plate = 0) else it } else elements)
    }

    fun toJson(): String = JSON.encodeToString(serializer(), this)

    companion object {
        val JSON = Json { ignoreUnknownKeys = true; encodeDefaults = true; prettyPrint = false }
        fun fromJson(text: String): Document = JSON.decodeFromString(serializer(), text).normalized()

        fun defaultLayers() = listOf(
            Layer(name = "Gravieren", color = 0xFF4FD8B4, mode = LayerMode.FILL, powerPct = 25.0, speed = 3000.0, intervalMm = 0.1),
            Layer(name = "Linie", color = 0xFF6CB6FF, mode = LayerMode.LINE, powerPct = 40.0, speed = 1500.0),
            Layer(name = "Schneiden", color = 0xFFFF6B70, mode = LayerMode.LINE, powerPct = 85.0, speed = 400.0, passes = 2),
        )

        /** Passes needed to reach [depthMm] with [depthPerPassMm] per pass (Windows: material.py). */
        fun passesFor(depthMm: Double, depthPerPassMm: Double): Int =
            if (depthPerPassMm <= 0.0 || depthMm <= 0.0) 1
            else ceil(depthMm / depthPerPassMm - 1e-9).toInt().coerceIn(Limits.PASSES)
    }
}

/** Saved laser settings for a material and process. */
@Serializable
data class Material(
    val id: String = UUID.randomUUID().toString(),
    val name: String,
    val thicknessMm: Double,
    val process: String,
    val mode: LayerMode,
    val powerPct: Double,
    val speed: Double,
    val passes: Int = 1,
    val intervalMm: Double = 0.1,
    val depthPerPassMm: Double = 0.0,
    val zStepMm: Double = 0.0,
    val builtin: Boolean = false,
) {
    /** Passes derived from thickness / depth per pass when set, otherwise the stored passes. */
    val effectivePasses get() = if (depthPerPassMm > 0) Document.passesFor(thicknessMm, depthPerPassMm) else passes

    fun applyTo(layer: Layer): Layer {
        val p = effectivePasses
        val z = if (p > 1) zStepMm.coerceAtMost(Limits.MAX_FOCUS_DROP_MM / (p - 1)) else 0.0
        return layer.copy(mode = mode, powerPct = powerPct, speed = speed, passes = p, intervalMm = intervalMm,
            zStepMm = z, materialName = name, thicknessMm = thicknessMm, depthPerPassMm = depthPerPassMm)
    }

    companion object {
        /** Starting points only; every material must be tested on the machine. */
        fun defaults() = listOf(
            Material(name = "Pappelsperrholz", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 90.0, speed = 350.0,
                     depthPerPassMm = 1.5, zStepMm = 0.5),
            Material(name = "Pappelsperrholz", thicknessMm = 3.0, process = "Gravieren", mode = LayerMode.FILL, powerPct = 25.0, speed = 3000.0),
            Material(name = "MDF", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 95.0, speed = 300.0,
                     depthPerPassMm = 1.5, zStepMm = 0.5),
            Material(name = "Acryl schwarz", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 100.0, speed = 200.0,
                     depthPerPassMm = 1.0, zStepMm = 0.5),
            Material(name = "Leder", thicknessMm = 2.0, process = "Gravieren", mode = LayerMode.FILL, powerPct = 18.0, speed = 3000.0),
            Material(name = "Karton", thicknessMm = 1.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 45.0, speed = 1200.0),
            Material(name = "Schiefer", thicknessMm = 5.0, process = "Gravieren", mode = LayerMode.FILL, powerPct = 40.0, speed = 2500.0, intervalMm = 0.08),
        )
    }
}
