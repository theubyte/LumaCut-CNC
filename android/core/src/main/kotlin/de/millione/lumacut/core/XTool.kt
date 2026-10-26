package de.millione.lumacut.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import java.io.ByteArrayInputStream
import java.util.zip.ZipInputStream
import kotlin.math.cos
import kotlin.math.sin

/**
 * Shared reader for xTool designs: the display objects of xTool Studio (`.xs`, a ZIP of JSON files) and of
 * xTool Creative Space (`.xcs`, JSON) look the same. Each display is placed with the same transforms the
 * editor uses (PixiJS): local skew, shift of the outline to 0/0, then scale/skew/rotation, then (x, y).
 */
object XTool {
    private val json = Json { ignoreUnknownKeys = true }

    private fun num(o: JsonObject, k: String) = (o[k] as? JsonPrimitive)?.doubleOrNull
    private fun str(o: JsonObject, k: String) = (o[k] as? JsonPrimitive)?.contentOrNull
    private fun pair(o: JsonObject, k: String, dx: Double, dy: Double): Pair<Double, Double> {
        val s = o[k] as? JsonObject
        return (s?.let { num(it, "x") } ?: dx) to (s?.let { num(it, "y") } ?: dy)
    }
    private fun flag(o: JsonObject, k: String, sub: String, default: Boolean) =
        ((o[k] as? JsonObject)?.get(sub) as? JsonPrimitive)?.booleanOrNull ?: default

    /**
     * Local outline → work plane (mm, y down). Local skew first (skew.x = π mirrors Y), the outline is moved to
     * 0/0, then scale, skew and rotation (degrees) of the display, then the position (x, y). With skew.x and
     * localSkew.x both π the two mirror images cancel and (x, y) is the lower edge of the part.
     */
    internal fun toPlane(local: List<Poly>, o: JsonObject): List<Poly> {
        val (lkx, lky) = pair(o, "localSkew", 0.0, 0.0)
        val lm = Matrix(cos(lky), sin(lky), -sin(-lkx), cos(-lkx))
        val flat = local.map { p -> p.map(lm::apply) }
        val b = boundsOf(flat) ?: return emptyList()
        val r = Math.toRadians(num(o, "angle") ?: 0.0)
        val (kx, ky) = pair(o, "skew", 0.0, 0.0)
        val (sx, sy) = pair(o, "scale", 1.0, 1.0)
        val dm = Matrix(cos(r + ky) * sx, sin(r + ky) * sx, -sin(r - kx) * sy, cos(r - kx) * sy)
        val x = num(o, "x") ?: 0.0; val y = num(o, "y") ?: 0.0
        return flat.map { p -> p.map { q -> val m = dm.apply(Pt(q.x - b.minX, q.y - b.minY)); Pt(m.x + x, m.y + y) } }
    }

    fun layerInfos(layerData: JsonObject?): List<ImportLayerInfo> = layerData?.mapNotNull { (key, v) ->
        val o = v as? JsonObject ?: return@mapNotNull null
        ImportLayerInfo(key, str(o, "name") ?: key, (num(o, "order") ?: 0.0).toInt(), (o["visible"] as? JsonPrimitive)?.booleanOrNull ?: true)
    }?.sortedBy { it.order }.orEmpty()

    private val IMAGE_KEYS = listOf("base64", "src", "data", "image", "url", "resource", "resourcePath", "path")

    /** Turns display objects into items (one per path), pictures and a list of what was left out. */
    internal fun read(displays: List<JsonObject>, layers: List<ImportLayerInfo>, resources: Map<String, ByteArray>): VectorImport {
        val items = ArrayList<ImportItem>(); val images = ArrayList<EmbeddedImage>(); val skipped = LinkedHashMap<String, Int>()
        fun skip(type: String) { skipped.merge(type.lowercase().replaceFirstChar { it.uppercase() }, 1, Int::plus) }
        for (o in displays) {
            val type = (str(o, "type") ?: "?").uppercase()
            if ((o["visible"] as? JsonPrimitive)?.booleanOrNull == false || (o["visibleState"] as? JsonPrimitive)?.booleanOrNull == false) continue
            val w = num(o, "width") ?: 0.0; val h = num(o, "height") ?: 0.0
            val (sx, sy) = pair(o, "scale", 1.0, 1.0)
            val lw = if (sx != 0.0) w / kotlin.math.abs(sx) else w; val lh = if (sy != 0.0) h / kotlin.math.abs(sy) else h
            if (type == "BITMAP" || type == "IMAGE") {
                val bytes = IMAGE_KEYS.firstNotNullOfOrNull { k ->
                    str(o, k)?.let { v -> resources[v] ?: resources["resources/$v"] ?: v.takeIf { it.length > 64 }?.let(ImportFormats::decodeBase64) }
                }
                if (bytes == null || lw <= 0 || lh <= 0) { skip(type); continue }
                val box = boundsOf(toPlane(listOf(listOf(Pt(0.0, 0.0), Pt(lw, 0.0), Pt(lw, lh), Pt(0.0, lh), Pt(0.0, 0.0))), o)) ?: continue
                images += EmbeddedImage(bytes, box)
                continue
            }
            val d = str(o, "dPath")?.takeIf { it.isNotBlank() }
            val local: List<Poly>? = when {
                d != null -> runCatching { SvgImport.pathData(d) }.getOrNull()
                type == "RECT" && lw > 0 && lh > 0 -> listOf(Shapes.rect(lw, lh, num(o, "radius") ?: num(o, "rx") ?: 0.0))
                (type == "CIRCLE" || type == "ELLIPSE") && lw > 0 && lh > 0 -> listOf(Shapes.ellipse(lw, lh))
                else -> null
            }
            if (local.isNullOrEmpty()) { skip(type); continue }
            val polys = toPlane(local, o)
            if (polys.isEmpty()) { skip(type); continue }
            val key = str(o, "layerTag") ?: str(o, "layerColor") ?: str(o, "originColor") ?: "#000000"
            val tags = (o["groupTags"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
            items += ImportItem(polys, key, flag(o, "fill", "visible", false), tags.reversed(), str(o, "name"))
        }
        val known = layers.associateBy { it.key }
        val used = items.map { it.layerKey!! }.distinct()
        val allLayers = used.mapIndexed { i, k -> known[k] ?: ImportLayerInfo(k, k, 1000 + i, true) }.sortedBy { it.order }
        return VectorImport(items.flatMap { it.polys }, images, skipped.map { (k, n) -> "$n× $k" }, items, allLayers)
    }

    internal fun fail(r: VectorImport): Nothing {
        val what = if (r.skipped.isEmpty()) "Keine Formen gefunden" else "Nur " + r.skipped.joinToString(", ") + " gefunden (nicht lesbar)"
        throw ImportException("$what – in xTool Text in Pfade umwandeln und erneut speichern")
    }
}

/** xTool Creative Space (.xcs, JSON). */
object Xcs {
    private val json = Json { ignoreUnknownKeys = true }

    fun parse(bytes: ByteArray): VectorImport {
        val root = try { json.parseToJsonElement(String(bytes, Charsets.UTF_8)) } catch (e: Exception) { throw ImportException("Keine gültige xTool-Datei") }
        val displays = ArrayList<JsonObject>(); var layerData: JsonObject? = null
        fun walk(e: JsonElement) {
            when (e) {
                is JsonObject -> {
                    if (layerData == null) (e["layerData"] as? JsonObject)?.let { layerData = it }
                    val isDisplay = (e["type"] as? JsonPrimitive)?.contentOrNull != null && (e.containsKey("width") || e.containsKey("dPath"))
                    if (isDisplay) displays += e else e.values.forEach(::walk)
                }
                is JsonArray -> e.forEach(::walk)
                else -> {}
            }
        }
        walk(root)
        val r = XTool.read(displays, XTool.layerInfos(layerData), emptyMap())
        if (r.polys.isEmpty() && r.images.isEmpty()) XTool.fail(r)
        return r
    }
}

/** xTool Studio (.xs): a ZIP with project.json, canvases/<id>.json and canvases/<id>/displays-N.json. */
object Xs {
    private const val MAX_ENTRY = 40 * 1024 * 1024

    private fun readLimited(input: java.io.InputStream, limit: Int): ByteArray {
        val out = java.io.ByteArrayOutputStream(); val buf = ByteArray(65536)
        while (out.size() < limit) {
            val n = input.read(buf, 0, minOf(buf.size, limit - out.size())); if (n < 0) break
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }

    internal fun isXs(bytes: ByteArray): Boolean {
        if (bytes.size < 4 || bytes[0] != 'P'.code.toByte() || bytes[1] != 'K'.code.toByte()) return false
        return try {
            ZipInputStream(ByteArrayInputStream(bytes)).use { z ->
                var hasProject = false; var hasCanvas = false; var n = 0
                var e = z.nextEntry
                while (e != null && n++ < 200) {
                    if (e.name == "project.json") hasProject = true
                    if (e.name.startsWith("canvases/")) hasCanvas = true
                    e = z.nextEntry
                }
                hasProject && hasCanvas
            }
        } catch (ex: Exception) { false }
    }

    fun parse(bytes: ByteArray): VectorImport {
        val files = LinkedHashMap<String, ByteArray>()
        try {
            ZipInputStream(ByteArrayInputStream(bytes)).use { z ->
                var e = z.nextEntry; var total = 0L
                while (e != null) {
                    if (!e.isDirectory) {
                        val data = readLimited(z, MAX_ENTRY + 1)
                        if (data.size > MAX_ENTRY) throw ImportException("Die xTool-Datei ist zu groß")
                        total += data.size
                        if (total > 4L * MAX_ENTRY) throw ImportException("Die xTool-Datei ist zu groß")
                        files[e.name] = data
                    }
                    e = z.nextEntry
                }
            }
        } catch (e: ImportException) { throw e } catch (e: Exception) { throw ImportException("Keine gültige xTool-Studio-Datei") }
        val json = Json { ignoreUnknownKeys = true }
        fun obj(name: String): JsonObject? = files[name]?.let { runCatching { json.parseToJsonElement(String(it, Charsets.UTF_8)) as? JsonObject }.getOrNull() }
        val project = obj("project.json") ?: throw ImportException("Keine gültige xTool-Studio-Datei (project.json fehlt)")
        val canvases = ((project["modules"] as? JsonObject)?.get("canvases") as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
        val active = (project["activeCanvasId"] as? JsonPrimitive)?.contentOrNull ?: canvases.firstOrNull()
            ?: throw ImportException("Die xTool-Datei enthält keine Zeichenfläche")
        val canvas = obj("canvases/$active.json")
        val chunks = files.keys.filter { Regex("canvases/" + Regex.escape(active) + "/displays-(\\d+)\\.json").matches(it) }
            .sortedBy { Regex("displays-(\\d+)").find(it)!!.groupValues[1].toInt() }
        val displays = chunks.flatMap { name ->
            ((obj(name)?.get("displays") as? JsonArray) ?: JsonArray(emptyList())).mapNotNull { it as? JsonObject }
        }
        val r = XTool.read(displays, XTool.layerInfos(canvas?.get("layerData") as? JsonObject), files)
        if (r.polys.isEmpty() && r.images.isEmpty()) XTool.fail(r)
        return r
    }
}
