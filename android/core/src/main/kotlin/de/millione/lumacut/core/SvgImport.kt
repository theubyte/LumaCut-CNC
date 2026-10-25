package de.millione.lumacut.core

import org.w3c.dom.Element as XmlElement
import org.w3c.dom.Node
import java.io.ByteArrayInputStream
import javax.xml.XMLConstants
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

class SvgException(message: String) : IllegalArgumentException(message)

/** 2D affine matrix (a b c d e f) as in SVG. */
data class Matrix(val a: Double = 1.0, val b: Double = 0.0, val c: Double = 0.0,
                  val d: Double = 1.0, val e: Double = 0.0, val f: Double = 0.0) {
    operator fun times(o: Matrix) = Matrix(
        a * o.a + c * o.b, b * o.a + d * o.b,
        a * o.c + c * o.d, b * o.c + d * o.d,
        a * o.e + c * o.f + e, b * o.e + d * o.f + f)
    fun apply(p: Pt) = Pt(a * p.x + c * p.y + e, b * p.x + d * p.y + f)
}

/**
 * Reads the visible geometry of an SVG as polylines in millimetres,
 * origin at the SVG's top-left. Supports path (all commands), rect,
 * circle, ellipse, line, polyline, polygon and nested transforms.
 */
object SvgImport {
    private const val CURVE_MM = 0.2
    private const val MAX_POINTS = 400_000

    fun parse(bytes: ByteArray): List<Poly> {
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = false
            isExpandEntityReferences = false
            runCatching { setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
            runCatching { setFeature("http://xml.org/sax/features/external-general-entities", false) }
            runCatching { setFeature("http://xml.org/sax/features/external-parameter-entities", false) }
            runCatching { setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "") }
        }
        val doc = try { factory.newDocumentBuilder().parse(ByteArrayInputStream(bytes)) }
                  catch (e: Exception) { throw SvgException("SVG konnte nicht gelesen werden") }
        val root = doc.documentElement
        if (root.tagName.substringAfter(':') != "svg") throw SvgException("Keine SVG-Datei")
        val out = ArrayList<Poly>()
        walk(root, rootMatrix(root), out)
        if (out.isEmpty()) throw SvgException("Keine Vektoren gefunden (Text vorher in Pfade umwandeln)")
        if (out.sumOf { it.size } > MAX_POINTS) throw SvgException("SVG zu komplex")
        return out
    }

    /** Scales user units to mm from width/height and viewBox (96 px per inch default). */
    private fun rootMatrix(svg: XmlElement): Matrix {
        val vb = svg.getAttribute("viewBox").split(Regex("[\\s,]+")).mapNotNull { it.toDoubleOrNull() }
        val w = length(svg.getAttribute("width"))
        val h = length(svg.getAttribute("height"))
        if (vb.size == 4 && vb[2] > 0 && vb[3] > 0) {
            val sx = (w ?: (vb[2] * PX_MM)) / vb[2]
            val sy = (h ?: (vb[3] * PX_MM)) / vb[3]
            val k = if (w != null && h != null) minOf(sx, sy) else if (w != null) sx else if (h != null) sy else PX_MM
            return Matrix(a = k, d = k, e = -vb[0] * k, f = -vb[1] * k)
        }
        return Matrix(a = PX_MM, d = PX_MM)
    }

    private const val PX_MM = 25.4 / 96.0

    private fun length(v: String): Double? {
        val m = Regex("^\\s*([-+]?[0-9.]+(?:e[-+]?\\d+)?)\\s*(mm|cm|in|pt|pc|px)?\\s*$", RegexOption.IGNORE_CASE).find(v) ?: return null
        val n = m.groupValues[1].toDoubleOrNull() ?: return null
        return when (m.groupValues[2].lowercase()) {
            "mm" -> n; "cm" -> n * 10; "in" -> n * 25.4; "pt" -> n * 25.4 / 72; "pc" -> n * 25.4 / 6
            else -> n * PX_MM
        }
    }

    private val SKIP = setOf("defs", "clipPath", "mask", "symbol", "marker", "pattern", "title", "desc",
                             "metadata", "style", "script", "text", "image", "linearGradient", "radialGradient", "filter")

    private fun walk(node: XmlElement, parent: Matrix, out: MutableList<Poly>) {
        val tag = node.tagName.substringAfter(':')
        if (tag in SKIP) return
        val style = node.getAttribute("style")
        if (node.getAttribute("display") == "none" || style.contains(Regex("display\\s*:\\s*none"))) return
        val m = parent * transform(node.getAttribute("transform"))
        val local: List<Poly> = when (tag) {
            "path" -> pathData(node.getAttribute("d"))
            "rect" -> {
                val x = num(node, "x"); val y = num(node, "y"); val w = num(node, "width"); val h = num(node, "height")
                val rx = max(num(node, "rx"), num(node, "ry"))
                if (w > 0 && h > 0) listOf(Shapes.rect(w, h, rx).map { Pt(it.x + x, it.y + y) }) else emptyList()
            }
            "circle" -> { val r = num(node, "r"); if (r > 0) listOf(Shapes.ellipse(2 * r, 2 * r, CURVE_MM).map { Pt(it.x + num(node, "cx") - r, it.y + num(node, "cy") - r) }) else emptyList() }
            "ellipse" -> { val rx = num(node, "rx"); val ry = num(node, "ry"); if (rx > 0 && ry > 0) listOf(Shapes.ellipse(2 * rx, 2 * ry, CURVE_MM).map { Pt(it.x + num(node, "cx") - rx, it.y + num(node, "cy") - ry) }) else emptyList() }
            "line" -> listOf(listOf(Pt(num(node, "x1"), num(node, "y1")), Pt(num(node, "x2"), num(node, "y2"))))
            "polyline", "polygon" -> {
                val n = numbers(node.getAttribute("points"))
                val pts = n.chunked(2).filter { it.size == 2 }.map { Pt(it[0], it[1]) }
                if (pts.size < 2) emptyList() else listOf(if (tag == "polygon") pts + pts.first() else pts)
            }
            else -> emptyList()
        }
        local.filter { it.size >= 2 }.forEach { poly -> out += poly.map(m::apply) }
        var child = node.firstChild
        while (child != null) {
            if (child.nodeType == Node.ELEMENT_NODE) walk(child as XmlElement, m, out)
            child = child.nextSibling
        }
    }

    private fun num(e: XmlElement, name: String) = e.getAttribute(name).trim().removeSuffix("px").toDoubleOrNull() ?: 0.0

    private val NUMBER = Regex("[-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?")
    private fun numbers(s: String) = NUMBER.findAll(s).map { it.value.toDouble() }.toList()

    fun transform(s: String): Matrix {
        var m = Matrix()
        for (t in Regex("(matrix|translate|scale|rotate|skewX|skewY)\\s*\\(([^)]*)\\)").findAll(s)) {
            val v = numbers(t.groupValues[2])
            m *= when (t.groupValues[1]) {
                "matrix" -> if (v.size == 6) Matrix(v[0], v[1], v[2], v[3], v[4], v[5]) else Matrix()
                "translate" -> Matrix(e = v.getOrElse(0) { 0.0 }, f = v.getOrElse(1) { 0.0 })
                "scale" -> Matrix(a = v.getOrElse(0) { 1.0 }, d = v.getOrElse(1) { v.getOrElse(0) { 1.0 } })
                "rotate" -> {
                    val r = Math.toRadians(v.getOrElse(0) { 0.0 }); val cx = v.getOrElse(1) { 0.0 }; val cy = v.getOrElse(2) { 0.0 }
                    Matrix(e = cx, f = cy) * Matrix(cos(r), sin(r), -sin(r), cos(r)) * Matrix(e = -cx, f = -cy)
                }
                "skewX" -> Matrix(c = tan(Math.toRadians(v.getOrElse(0) { 0.0 })))
                else -> Matrix(b = tan(Math.toRadians(v.getOrElse(0) { 0.0 })))
            }
        }
        return m
    }

    /** SVG path data → polylines (curves flattened in user units). */
    fun pathData(d: String): List<Poly> {
        val tokens = Regex("[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?").findAll(d).map { it.value }.toList()
        val out = ArrayList<Poly>()
        var cur = ArrayList<Pt>()
        var pos = Pt(0.0, 0.0); var start = pos
        var lastCtrl: Pt? = null; var lastCmd = ' '
        var i = 0; var cmd = ' '
        fun has() = i < tokens.size && tokens[i][0].let { !it.isLetter() }
        fun n(): Double = tokens.getOrNull(i++)?.toDoubleOrNull() ?: throw SvgException("Ungültige Pfaddaten")
        fun flush() { if (cur.size >= 2) out += cur; cur = ArrayList() }
        fun to(p: Pt) { if (cur.isEmpty()) cur.add(pos); cur.add(p); pos = p }
        while (i < tokens.size) {
            if (tokens[i][0].isLetter()) cmd = tokens[i++][0]
            else if (cmd == ' ') throw SvgException("Ungültige Pfaddaten")
            val rel = cmd.isLowerCase()
            fun pt(): Pt { val x = n(); val y = n(); return if (rel) Pt(pos.x + x, pos.y + y) else Pt(x, y) }
            when (cmd.uppercaseChar()) {
                'M' -> { flush(); pos = pt(); start = pos; cur.add(pos); cmd = if (rel) 'l' else 'L'; lastCtrl = null }
                'L' -> { to(pt()); lastCtrl = null }
                'H' -> { val x = n(); to(Pt(if (rel) pos.x + x else x, pos.y)); lastCtrl = null }
                'V' -> { val y = n(); to(Pt(pos.x, if (rel) pos.y + y else y)); lastCtrl = null }
                'C', 'S' -> {
                    val c1 = if (cmd.uppercaseChar() == 'C') pt() else
                        lastCtrl?.takeIf { lastCmd.uppercaseChar() in "CS" }?.let { Pt(2 * pos.x - it.x, 2 * pos.y - it.y) } ?: pos
                    val c2 = pt(); val p = pt()
                    cubic(pos, c1, c2, p).forEach(::to); lastCtrl = c2
                }
                'Q', 'T' -> {
                    val c = if (cmd.uppercaseChar() == 'Q') pt() else
                        lastCtrl?.takeIf { lastCmd.uppercaseChar() in "QT" }?.let { Pt(2 * pos.x - it.x, 2 * pos.y - it.y) } ?: pos
                    val p = pt()
                    cubic(pos, pos + (c - pos) * (2.0 / 3), p + (c - p) * (2.0 / 3), p).forEach(::to); lastCtrl = c
                }
                'A' -> {
                    val rx = n(); val ry = n(); val rot = n(); val large = n() != 0.0; val sweep = n() != 0.0; val p = pt()
                    arc(pos, rx, ry, rot, large, sweep, p).forEach(::to); lastCtrl = null
                }
                'Z' -> { if (cur.isNotEmpty()) { to(start); flush() }; pos = start; lastCtrl = null }
                else -> throw SvgException("Unbekannter Pfadbefehl $cmd")
            }
            lastCmd = cmd
            if (cmd.uppercaseChar() == 'Z' && has()) throw SvgException("Ungültige Pfaddaten")
        }
        flush()
        return out
    }

    private fun cubic(p0: Pt, c1: Pt, c2: Pt, p1: Pt): List<Pt> {
        val approx = p0.dist(c1) + c1.dist(c2) + c2.dist(p1)
        val n = ceil(approx / CURVE_MM).toInt().coerceIn(2, 400)
        return (1..n).map { k ->
            val t = k.toDouble() / n; val u = 1 - t
            Pt(u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
               u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y)
        }
    }

    /** Endpoint to centre parameterisation (SVG spec F.6.5). */
    private fun arc(p0: Pt, rxIn: Double, ryIn: Double, rotDeg: Double, large: Boolean, sweep: Boolean, p1: Pt): List<Pt> {
        if (p0.dist(p1) < 1e-9) return emptyList()
        var rx = abs(rxIn); var ry = abs(ryIn)
        if (rx < 1e-9 || ry < 1e-9) return listOf(p1)
        val phi = Math.toRadians(rotDeg); val cp = cos(phi); val sp = sin(phi)
        val dx = (p0.x - p1.x) / 2; val dy = (p0.y - p1.y) / 2
        val x1 = cp * dx + sp * dy; val y1 = -sp * dx + cp * dy
        val lambda = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
        if (lambda > 1) { rx *= sqrt(lambda); ry *= sqrt(lambda) }
        val num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
        val den = rx * rx * y1 * y1 + ry * ry * x1 * x1
        val coef = (if (large == sweep) -1 else 1) * sqrt(max(0.0, num / den))
        val cx1 = coef * rx * y1 / ry; val cy1 = -coef * ry * x1 / rx
        val cx = cp * cx1 - sp * cy1 + (p0.x + p1.x) / 2; val cy = sp * cx1 + cp * cy1 + (p0.y + p1.y) / 2
        fun angle(ux: Double, uy: Double, vx: Double, vy: Double): Double {
            val dot = ux * vx + uy * vy; val len = sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
            val a = acos((dot / len).coerceIn(-1.0, 1.0)); return if (ux * vy - uy * vx < 0) -a else a
        }
        val t1 = angle(1.0, 0.0, (x1 - cx1) / rx, (y1 - cy1) / ry)
        var dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
        if (!sweep && dt > 0) dt -= 2 * PI else if (sweep && dt < 0) dt += 2 * PI
        val n = ceil(abs(dt) * max(rx, ry) / CURVE_MM).toInt().coerceIn(2, 720)
        return (1..n).map { k ->
            if (k == n) p1 else {
                val t = t1 + dt * k / n
                Pt(cx + rx * cos(t) * cp - ry * sin(t) * sp, cy + rx * cos(t) * sp + ry * sin(t) * cp)
            }
        }
    }
}
