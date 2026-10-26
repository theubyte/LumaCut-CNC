package de.millione.lumacut.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import org.w3c.dom.Element as XmlElement
import org.w3c.dom.Node
import java.io.ByteArrayInputStream
import java.util.Base64
import javax.xml.XMLConstants
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.math.max
import kotlin.math.min

/** What a file contains, recognised from its content (the extension is only a hint). */
enum class FileKind(val label: String) {
    SVG("SVG"), DXF("DXF"), XCS("xTool Creative Space"), XS("xTool Studio"), LBRN("LightBurn"), HPGL("HPGL"),
    PDF("PDF / Illustrator"), IMAGE("Bild"), PROJECT("LumaCut-Projekt"), UNKNOWN("Unbekannt"),
}

object FileKinds {
    fun detect(bytes: ByteArray): FileKind {
        if (bytes.size < 4) return FileKind.UNKNOWN
        if (bytes[0] == 'P'.code.toByte() && bytes[1] == 'K'.code.toByte()) return if (Xs.isXs(bytes)) FileKind.XS else FileKind.UNKNOWN
        fun b(i: Int) = bytes[i].toInt() and 0xFF
        fun ascii(from: Int, n: Int) = if (bytes.size >= from + n) String(bytes, from, n, Charsets.ISO_8859_1) else ""
        if (ascii(0, 4) == "%PDF") return FileKind.PDF
        if (b(0) == 0x89 && ascii(1, 3) == "PNG") return FileKind.IMAGE
        if (b(0) == 0xFF && b(1) == 0xD8 && b(2) == 0xFF) return FileKind.IMAGE
        if (ascii(0, 4) == "GIF8") return FileKind.IMAGE
        if (ascii(0, 2) == "BM" && bytes.size > 30) return FileKind.IMAGE
        if (ascii(0, 4) == "RIFF" && ascii(8, 4) == "WEBP") return FileKind.IMAGE
        if (ascii(4, 4) == "ftyp" && ascii(8, 4).let { it.startsWith("hei") || it.startsWith("mif") || it.startsWith("avi") }) return FileKind.IMAGE
        val head = String(bytes, 0, min(bytes.size, 65536), Charsets.UTF_8).trimStart('﻿', ' ', '\t', '\r', '\n')
        val lower = head.lowercase()
        return when {
            lower.contains("<lightburnproject") -> FileKind.LBRN
            lower.contains("<svg") -> FileKind.SVG
            head.startsWith("{") && lower.contains("\"layers\"") && lower.contains("\"title\"") -> FileKind.PROJECT
            head.startsWith("{") && (lower.contains("\"displays\"") || lower.contains("\"canvas\"") || lower.contains("\"dpath\"")) -> FileKind.XCS
            Regex("^0\\s*\\r?\\n\\s*SECTION", RegexOption.IGNORE_CASE).containsMatchIn(head) ||
                Regex("\\r?\\n\\s*0\\s*\\r?\\n\\s*SECTION\\s*\\r?\\n").containsMatchIn(head) -> FileKind.DXF
            Regex("(?m)^\\s*(IN|SP\\d?|PU|PD|PA)\\b[;\\d\\s,-]").containsMatchIn(head.uppercase()) -> FileKind.HPGL
            else -> FileKind.UNKNOWN
        }
    }
}

/** An image embedded in a design file, placed on the work plane (mm). */
class EmbeddedImage(val bytes: ByteArray, val box: Box)

/** One drawable of a design file: its paths, the layer (xTool colour) it was on, filled or line, and its groups (outermost first). */
class ImportItem(val polys: List<Poly>, val layerKey: String?, val fill: Boolean, val groups: List<String>, val name: String?)

/** A layer of the source file (xTool colour layer) in drawing order. */
class ImportLayerInfo(val key: String, val name: String, val order: Int, val visible: Boolean)

/**
 * Vector geometry (mm, y down) plus embedded pictures; [skipped] says what could not be taken over.
 * Formats that know layers and groups (xTool) also deliver [items] and [layers].
 */
class VectorImport(val polys: List<Poly>, val images: List<EmbeddedImage>, val skipped: List<String>,
                   val items: List<ImportItem> = emptyList(), val layers: List<ImportLayerInfo> = emptyList()) {
    /** One sentence for the operator, or null when nothing was left out. */
    fun skippedSentence(): String? =
        if (skipped.isEmpty()) null else "Übersprungen: " + skipped.joinToString(", ") + " (in Pfade bzw. Bild umwandeln)"
}

class ImportException(message: String) : IllegalArgumentException(message)

object ImportFormats {
    /** Parses any vector format ([kind] from [FileKinds.detect]). Images and PDF are handled by the app. */
    fun parseVector(kind: FileKind, bytes: ByteArray): VectorImport = when (kind) {
        FileKind.SVG -> VectorImport(SvgImport.parse(bytes), emptyList(), emptyList())
        FileKind.DXF -> VectorImport(DxfImport.parse(bytes), emptyList(), emptyList())
        FileKind.XCS -> Xcs.parse(bytes)
        FileKind.XS -> Xs.parse(bytes)
        FileKind.LBRN -> Lbrn.parse(bytes)
        FileKind.HPGL -> VectorImport(Hpgl.parse(bytes), emptyList(), emptyList())
        else -> throw ImportException("Dieses Format wird nicht als Vektor gelesen")
    }

    internal fun secureXml(bytes: ByteArray): org.w3c.dom.Document {
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = false
            isExpandEntityReferences = false
            runCatching { setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
            runCatching { setFeature("http://xml.org/sax/features/external-general-entities", false) }
            runCatching { setFeature("http://xml.org/sax/features/external-parameter-entities", false) }
            runCatching { setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "") }
        }
        return try { factory.newDocumentBuilder().parse(ByteArrayInputStream(bytes)) }
        catch (e: Exception) { throw ImportException("Die Datei konnte nicht gelesen werden") }
    }

    internal fun decodeBase64(text: String): ByteArray? = runCatching {
        Base64.getMimeDecoder().decode(text.substringAfter("base64,").trim())
    }.getOrNull()?.takeIf { it.size > 8 }

    internal fun translate(polys: List<Poly>, dx: Double, dy: Double) = polys.map { p -> p.map { Pt(it.x + dx, it.y + dy) } }
}

/** LightBurn projects (.lbrn / .lbrn2, XML): Rect, Ellipse, Path (lines and Béziers), Bitmap, Groups, XForm. */
object Lbrn {
    private const val CURVE_MM = 0.15
    private val NUM = "-?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?"

    fun parse(bytes: ByteArray): VectorImport {
        val doc = ImportFormats.secureXml(bytes)
        val root = doc.documentElement
        if (!root.tagName.equals("LightBurnProject", true)) throw ImportException("Keine LightBurn-Datei")
        val polys = ArrayList<Poly>(); val images = ArrayList<EmbeddedImage>(); val skipped = LinkedHashMap<String, Int>()
        fun shapes(parent: XmlElement, m: Matrix) {
            var n: Node? = parent.firstChild
            while (n != null) {
                val el = n as? XmlElement
                if (el != null && el.tagName == "Shape") shape(el, m, polys, images, skipped)
                else if (el != null && el.tagName != "XForm" && el.tagName != "CutSetting" && el.tagName != "Notes") shapes(el, m)
                n = n.nextSibling
            }
        }
        shapes(root, Matrix())
        if (polys.isEmpty() && images.isEmpty()) {
            val what = if (skipped.isEmpty()) "Keine Formen gefunden" else "Nur " + skipped.keys.joinToString(", ") + " gefunden (nicht lesbar)"
            throw ImportException("$what – in LightBurn Text in Pfade umwandeln (Rechtsklick) und erneut speichern")
        }
        return VectorImport(polys, images, skipped.map { (k, c) -> "$c× $k" })
    }

    private fun xform(el: XmlElement): Matrix {
        val x = el.getElementsByTagName("XForm")
        for (i in 0 until x.length) if (x.item(i).parentNode === el) {
            val v = x.item(i).textContent.trim().split(Regex("\\s+")).mapNotNull { it.toDoubleOrNull() }
            if (v.size == 6) return Matrix(v[0], v[1], v[2], v[3], v[4], v[5])
        }
        return Matrix()
    }

    private fun attr(el: XmlElement, name: String) = el.getAttribute(name).toDoubleOrNull() ?: 0.0

    private fun child(el: XmlElement, tag: String): XmlElement? {
        var n: Node? = el.firstChild
        while (n != null) { if (n is XmlElement && n.tagName == tag) return n; n = n.nextSibling }
        return null
    }

    private fun shape(el: XmlElement, parent: Matrix, polys: MutableList<Poly>, images: MutableList<EmbeddedImage>, skipped: MutableMap<String, Int>) {
        val m = parent * xform(el)
        fun add(local: List<Poly>) { polys += local.map { p -> p.map(m::apply) } }
        when (val type = el.getAttribute("Type")) {
            "Rect" -> {
                val w = attr(el, "W"); val h = attr(el, "H")
                add(listOf(Shapes.rect(w, h, attr(el, "Cr"))).map { p -> p.map { Pt(it.x - w / 2, it.y - h / 2) } })
            }
            "Ellipse" -> {
                val rx = attr(el, "Rx"); val ry = attr(el, "Ry")
                add(listOf(Shapes.ellipse(2 * rx, 2 * ry)).map { p -> p.map { Pt(it.x - rx, it.y - ry) } })
            }
            "Path" -> {
                val verts = child(el, "VertList")?.textContent ?: ""
                val prims = child(el, "PrimList")?.textContent ?: ""
                add(path(verts, prims))
            }
            "Bitmap" -> {
                val data = ImportFormats.decodeBase64(el.getAttribute("Data"))
                val w = attr(el, "W"); val h = attr(el, "H")
                if (data == null || w <= 0 || h <= 0) { skipped.merge("Bitmap", 1, Int::plus); return }
                val box = boundsOf(listOf(listOf(Pt(-w / 2, -h / 2), Pt(w / 2, -h / 2), Pt(w / 2, h / 2), Pt(-w / 2, h / 2)).map(m::apply)))!!
                images += EmbeddedImage(data, box)
            }
            "Group" -> {
                val kids = child(el, "Children")
                if (kids != null) { var n: Node? = kids.firstChild; while (n != null) { (n as? XmlElement)?.takeIf { it.tagName == "Shape" }?.let { shape(it, m, polys, images, skipped) }; n = n.nextSibling } }
            }
            else -> skipped.merge(type.ifBlank { "Element" }, 1, Int::plus)
        }
    }

    private class Vert(val x: Double, val y: Double) {
        var c0: Pt? = null; var c1: Pt? = null
        val p get() = Pt(x, y)
    }

    private fun path(vertText: String, primText: String): List<Poly> {
        val verts = ArrayList<Vert>()
        var c0x: Double? = null; var c0y: Double? = null
        val token = Regex("V($NUM)\\s+($NUM)|c0x($NUM)|c0y($NUM)|c1x($NUM)|c1y($NUM)")
        var c1x: Double? = null; var c1y: Double? = null
        fun flush() {
            val v = verts.lastOrNull() ?: return
            if (c0x != null && c0y != null) v.c0 = Pt(c0x!!, c0y!!)
            if (c1x != null && c1y != null) v.c1 = Pt(c1x!!, c1y!!)
            c0x = null; c0y = null; c1x = null; c1y = null
        }
        for (t in token.findAll(vertText)) {
            val g = t.groupValues
            when {
                g[1].isNotEmpty() -> { flush(); verts += Vert(g[1].toDouble(), g[2].toDouble()) }
                g[3].isNotEmpty() -> c0x = g[3].toDouble()
                g[4].isNotEmpty() -> c0y = g[4].toDouble()
                g[5].isNotEmpty() -> c1x = g[5].toDouble()
                g[6].isNotEmpty() -> c1y = g[6].toDouble()
            }
        }
        flush()
        val out = ArrayList<Poly>()
        var cur = ArrayList<Pt>(); var last = -1
        for (m in Regex("([LB])\\s*(\\d+)\\s+(\\d+)").findAll(primText)) {
            val kind = m.groupValues[1]; val i = m.groupValues[2].toInt(); val j = m.groupValues[3].toInt()
            if (i !in verts.indices || j !in verts.indices) continue
            if (i != last) { if (cur.size >= 2) out += cur; cur = ArrayList(); cur += verts[i].p }
            if (kind == "L") cur += verts[j].p
            else cur += bezier(verts[i].p, verts[i].c1 ?: verts[i].p, verts[j].c0 ?: verts[j].p, verts[j].p)
            last = j
        }
        if (cur.size >= 2) out += cur
        return out
    }

    private fun bezier(p0: Pt, c1: Pt, c2: Pt, p1: Pt): List<Pt> {
        val len = p0.dist(c1) + c1.dist(c2) + c2.dist(p1)
        val n = max(2, kotlin.math.ceil(len / CURVE_MM / 4).toInt()).coerceAtMost(400)
        return (1..n).map { k ->
            val t = k.toDouble() / n; val u = 1 - t
            Pt(u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
               u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y)
        }
    }
}

/** HPGL plot files: IN, SP, PU, PD, PA, PR with 40 plotter units per millimetre, y flipped to point down. */
object Hpgl {
    private const val UNITS_PER_MM = 40.0

    fun parse(bytes: ByteArray): List<Poly> {
        val text = String(bytes, Charsets.ISO_8859_1)
        val out = ArrayList<Poly>()
        var cur = ArrayList<Pt>(); var down = false; var x = 0.0; var y = 0.0; var absolute = true
        fun flush() { if (cur.size >= 2) out += cur; cur = ArrayList() }
        for (raw in text.split(';', '\n', '\r')) {
            val cmd = raw.trim().filter { it != '\u001b' }
            if (cmd.length < 2) continue
            val op = cmd.substring(0, 2).uppercase()
            val args = cmd.substring(2).split(',', ' ').mapNotNull { it.trim().toDoubleOrNull() }
            when (op) {
                "IN" -> { flush(); down = false; absolute = true }
                "PA" -> absolute = true
                "PR" -> absolute = false
                "PU", "PD" -> {
                    if (op == "PU") { flush() }
                    down = op == "PD"
                    if (op == "PA") absolute = true
                    var i = 0
                    while (i + 1 < args.size) {
                        val nx = if (absolute) args[i] else x + args[i]; val ny = if (absolute) args[i + 1] else y + args[i + 1]
                        if (down) { if (cur.isEmpty()) cur += Pt(x / UNITS_PER_MM, -y / UNITS_PER_MM); cur += Pt(nx / UNITS_PER_MM, -ny / UNITS_PER_MM) }
                        x = nx; y = ny; i += 2
                    }
                }
                "PA2" -> {}
                else -> {}
            }
            if (op == "PA" || op == "PR") {
                var i = 0
                while (i + 1 < args.size) {
                    val nx = if (absolute) args[i] else x + args[i]; val ny = if (absolute) args[i + 1] else y + args[i + 1]
                    if (down) { if (cur.isEmpty()) cur += Pt(x / UNITS_PER_MM, -y / UNITS_PER_MM); cur += Pt(nx / UNITS_PER_MM, -ny / UNITS_PER_MM) }
                    else { flush() }
                    x = nx; y = ny; i += 2
                }
            }
        }
        flush()
        if (out.isEmpty()) throw ImportException("Keine Linien in der HPGL-Datei gefunden")
        val b = boundsOf(out)!!
        return ImportFormats.translate(out, -b.minX, -b.minY)
    }
}
