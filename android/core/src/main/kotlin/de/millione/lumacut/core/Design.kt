package de.millione.lumacut.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.util.Base64
import java.util.UUID

@Serializable
enum class LayerMode { LINE, FILL }

/** Laser settings shared by all elements on the layer. Power in percent of S255. */
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
    val output: Boolean = true,
)

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
enum class ImageMode { GRAYSCALE, DITHER, THRESHOLD }

/**
 * Something on the bed. Vector content lives in [paths] (local mm, before
 * [transform]); text keeps its source so it stays editable; images carry a
 * [raster] stretched over [imageWidthMm] x [imageHeightMm].
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
) {
    val isImage get() = raster != null

    /** Paths in machine coordinates. */
    fun worldPaths(): List<Poly> = paths.map { poly -> poly.map(transform::apply) }

    fun worldBounds(): Box? = if (isImage) {
        val corners = listOf(Pt(0.0, 0.0), Pt(imageWidthMm, 0.0), Pt(imageWidthMm, imageHeightMm), Pt(0.0, imageHeightMm))
        boundsOf(listOf(corners.map(transform::apply)))
    } else boundsOf(worldPaths())
}

@Serializable
data class Document(
    val title: String = "Neues Projekt",
    val layers: List<Layer> = defaultLayers(),
    val elements: List<Element> = emptyList(),
) {
    fun layer(id: String) = layers.firstOrNull { it.id == id }
    fun bounds(): Box? = elements.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) }

    fun toJson(): String = JSON.encodeToString(serializer(), this)

    companion object {
        val JSON = Json { ignoreUnknownKeys = true; encodeDefaults = true; prettyPrint = false }
        fun fromJson(text: String): Document = JSON.decodeFromString(serializer(), text)

        fun defaultLayers() = listOf(
            Layer(name = "Gravieren", color = 0xFF4FD8B4, mode = LayerMode.FILL, powerPct = 25.0, speed = 3000.0, intervalMm = 0.1),
            Layer(name = "Linie", color = 0xFF6CB6FF, mode = LayerMode.LINE, powerPct = 40.0, speed = 1500.0),
            Layer(name = "Schneiden", color = 0xFFFF6B70, mode = LayerMode.LINE, powerPct = 85.0, speed = 400.0, passes = 2),
        )
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
) {
    fun applyTo(layer: Layer) = layer.copy(mode = mode, powerPct = powerPct, speed = speed, passes = passes, intervalMm = intervalMm)

    companion object {
        /** Starting points only; every material must be tested on the machine. */
        fun defaults() = listOf(
            Material(name = "Pappelsperrholz", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 90.0, speed = 350.0, passes = 2),
            Material(name = "Pappelsperrholz", thicknessMm = 3.0, process = "Gravieren", mode = LayerMode.FILL, powerPct = 25.0, speed = 3000.0),
            Material(name = "MDF", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 95.0, speed = 300.0, passes = 2),
            Material(name = "Acryl schwarz", thicknessMm = 3.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 100.0, speed = 200.0, passes = 3),
            Material(name = "Leder", thicknessMm = 2.0, process = "Gravieren", mode = LayerMode.FILL, powerPct = 18.0, speed = 3000.0),
            Material(name = "Karton", thicknessMm = 1.0, process = "Schneiden", mode = LayerMode.LINE, powerPct = 45.0, speed = 1200.0),
            Material(name = "Schiefer", thicknessMm = 5.0, process = "Gravieren", mode = LayerMode.FILL, powerPct = 40.0, speed = 2500.0, intervalMm = 0.08),
        )
    }
}
