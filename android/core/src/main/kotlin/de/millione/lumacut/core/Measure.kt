package de.millione.lumacut.core

import java.util.Locale
import java.util.UUID
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/** Nearest points of two polylines (or segments) and the segments they lie on. */
class PolyHit(val distance: Double, val onA: Pt, val onB: Pt, val segA: Pair<Pt, Pt>?, val segB: Pair<Pt, Pt>?) {
    /** Both nearest segments run the same way (within 0.5°) and do not touch: "parallel, distance …". */
    val parallel: Boolean get() {
        val a = segA ?: return false; val b = segB ?: return false
        if (distance < 1e-9) return false
        val ax = a.second.x - a.first.x; val ay = a.second.y - a.first.y
        val bx = b.second.x - b.first.x; val by = b.second.y - b.first.y
        val la = hypot(ax, ay); val lb = hypot(bx, by)
        if (la < 1e-9 || lb < 1e-9) return false
        return abs(ax * by - ay * bx) / (la * lb) < 0.0087   // sin 0.5°
    }
}

/** Plain geometry for the measuring tool. Millimetres, no state. */
object Measure {
    /** Closest point to [p] on the segment [a]-[b]. */
    fun closestOnSegment(p: Pt, a: Pt, b: Pt): Pt {
        val dx = b.x - a.x; val dy = b.y - a.y
        val l2 = dx * dx + dy * dy
        if (l2 < 1e-18) return a
        val t = (((p.x - a.x) * dx + (p.y - a.y) * dy) / l2).coerceIn(0.0, 1.0)
        return Pt(a.x + t * dx, a.y + t * dy)
    }

    fun pointSegment(p: Pt, a: Pt, b: Pt): Double = p.dist(closestOnSegment(p, a, b))

    private fun cross(o: Pt, a: Pt, b: Pt) = (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

    private fun intersection(a: Pt, b: Pt, c: Pt, d: Pt): Pt? {
        val d1 = cross(a, b, c); val d2 = cross(a, b, d); val d3 = cross(c, d, a); val d4 = cross(c, d, b)
        if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
            val t = d3 / (d3 - d4)
            return Pt(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y))
        }
        return null
    }

    /** Shortest distance between two segments (0 where they cross) with the nearest points. */
    fun segmentSegment(a: Pt, b: Pt, c: Pt, d: Pt): PolyHit {
        intersection(a, b, c, d)?.let { return PolyHit(0.0, it, it, a to b, c to d) }
        var best: PolyHit? = null
        fun offer(onA: Pt, onB: Pt) {
            val dist = onA.dist(onB)
            if (best == null || dist < best!!.distance) best = PolyHit(dist, onA, onB, a to b, c to d)
        }
        for (p in listOf(a, b)) offer(p, closestOnSegment(p, c, d))
        for (p in listOf(c, d)) offer(closestOnSegment(p, a, b), p)
        return best!!
    }

    private fun boxGap(a: Box, b: Box): Double {
        val dx = max(0.0, max(a.minX - b.maxX, b.minX - a.maxX))
        val dy = max(0.0, max(a.minY - b.maxY, b.minY - a.maxY))
        return hypot(dx, dy)
    }

    private fun segBox(a: Pt, b: Pt) = Box(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))

    /**
     * Minimal distance between two sets of polylines. Bounding boxes of whole paths and of single segments
     * are compared with the best distance so far, so large imports stay quick. Crossing or touching = 0.
     */
    fun polyDistance(a: List<Poly>, b: List<Poly>): PolyHit? {
        var best: PolyHit? = null
        val boxesB = b.map { boundsOf(listOf(it)) }
        for (pa in a) {
            if (pa.isEmpty()) continue
            val ba = boundsOf(listOf(pa)) ?: continue
            for ((j, pb) in b.withIndex()) {
                if (pb.isEmpty()) continue
                val bb = boxesB[j] ?: continue
                if (best != null && boxGap(ba, bb) >= best!!.distance) continue
                val sa = if (pa.size == 1) listOf(pa[0] to pa[0]) else pa.zipWithNext()
                val sb = if (pb.size == 1) listOf(pb[0] to pb[0]) else pb.zipWithNext()
                for ((a1, a2) in sa) {
                    val boxA = segBox(a1, a2)
                    for ((b1, b2) in sb) {
                        if (best != null && boxGap(boxA, segBox(b1, b2)) >= best!!.distance) continue
                        val h = segmentSegment(a1, a2, b1, b2)
                        if (best == null || h.distance < best!!.distance) best = h
                        if (best!!.distance <= 0.0) return best
                    }
                }
            }
        }
        return best
    }

    fun perimeter(polys: List<Poly>): Double = polys.sumOf { it.length() }

    /** Signed shoelace area of a ring (the closing point may or may not be repeated). */
    fun ringArea(ring: Poly): Double {
        if (ring.size < 3) return 0.0
        var s = 0.0
        for (i in ring.indices) { val p = ring[i]; val q = ring[(i + 1) % ring.size]; s += p.x * q.y - q.x * p.y }
        return s / 2
    }

    fun inside(p: Pt, ring: Poly): Boolean {
        var c = false
        var j = ring.size - 1
        for (i in ring.indices) {
            val a = ring[i]; val b = ring[j]
            if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) c = !c
            j = i
        }
        return c
    }

    /**
     * Area of the closed paths by the even-odd rule: a ring counts positive at even nesting depth and negative
     * at odd depth, so holes are subtracted and islands inside holes added back. Open paths are ignored.
     */
    fun area(polys: List<Poly>): Double {
        val rings = polys.filter { it.isClosed() }.map { it.dropLast(1) }.filter { it.size >= 3 }
        var total = 0.0
        for ((i, r) in rings.withIndex()) {
            val depth = rings.indices.count { j -> j != i && inside(r[0], rings[j]) }
            total += abs(ringArea(r)) * (if (depth % 2 == 0) 1 else -1)
        }
        return total
    }

    /** Angle at [v] between the rays to [a] and [c], 0..180°. */
    fun angleDeg(a: Pt, v: Pt, c: Pt): Double {
        val ux = a.x - v.x; val uy = a.y - v.y; val wx = c.x - v.x; val wy = c.y - v.y
        val l = hypot(ux, uy) * hypot(wx, wy)
        if (l < 1e-12) return 0.0
        return Math.toDegrees(acos(((ux * wx + uy * wy) / l).coerceIn(-1.0, 1.0)))
    }

    /** Direction of the line a→b against the X axis, 0..180°, counter-clockwise as seen on screen (Y points down). */
    fun lineAngleDeg(a: Pt, b: Pt): Double {
        var d = Math.toDegrees(atan2(-(b.y - a.y), b.x - a.x))
        while (d < 0) d += 180.0
        while (d >= 180.0) d -= 180.0
        return d
    }

    /**
     * Detects a circle or ellipse among local paths: one closed ring whose points lie on the ellipse of its
     * bounding box (1 % tolerance). Returns the full axes (width, height) in local units, or null.
     */
    fun ellipseAxes(local: List<Poly>): Pair<Double, Double>? {
        val ring = local.singleOrNull()?.takeIf { it.isClosed() && it.size >= 12 } ?: return null
        val b = boundsOf(listOf(ring)) ?: return null
        if (b.width < 1e-6 || b.height < 1e-6) return null
        val c = b.center; val rx = b.width / 2; val ry = b.height / 2
        for (p in ring) {
            val r = sqrt(((p.x - c.x) / rx).let { it * it } + ((p.y - c.y) / ry).let { it * it })
            if (abs(r - 1.0) > 0.01) return null
        }
        return b.width to b.height
    }

    /** Laser path length on its layer: line layers trace the paths, fill layers draw the hatch; times passes. */
    fun laserLength(e: Element, layer: Layer): Double? {
        if (e.isImage) return null
        val world = e.worldPaths()
        val once = if (layer.mode == LayerMode.FILL) hatch(world, layer.intervalMm.coerceAtLeast(0.02)).sumOf { it.length() } else perimeter(world)
        return once * layer.passes
    }
}

/* ---------- snapping ---------- */

/** Order of preference: corner first, then centres/midpoints, then any point on an edge. */
enum class SnapKind(val label: String, val rank: Int) {
    CORNER("Ecke", 0), CENTER("Mitte", 1), MID("Kantenmitte", 1), EDGE("Kante", 2)
}

class SnapHit(val p: Pt, val kind: SnapKind, val elementId: String?)

object Snap {
    private const val CORNER_ANGLE_DEG = 20.0
    private const val MIN_MID_EDGE_MM = 1.0

    /** Outline of an element in work mm; images count as their rectangle. */
    fun outline(e: Element): List<Poly> =
        if (e.isImage) e.imageCorners().let { listOf(it + it.first()) } else e.worldPaths()

    private fun turnDeg(a: Pt, v: Pt, c: Pt): Double {
        val ux = v.x - a.x; val uy = v.y - a.y; val wx = c.x - v.x; val wy = c.y - v.y
        val l = hypot(ux, uy) * hypot(wx, wy)
        if (l < 1e-12) return 0.0
        return Math.toDegrees(acos(((ux * wx + uy * wy) / l).coerceIn(-1.0, 1.0)))
    }

    private class Best(val radius: Double, val from: Pt) {
        var hit: SnapHit? = null
        private var dist = Double.MAX_VALUE
        fun offer(p: Pt, kind: SnapKind, id: String?) {
            val d = from.dist(p)
            if (d > radius) return
            val h = hit
            if (h == null || kind.rank < h.kind.rank || (kind.rank == h.kind.rank && d < dist)) { hit = SnapHit(p, kind, id); dist = d }
        }
    }

    private fun scan(best: Best, polys: List<Poly>, id: String?) {
        val p = best.from
        for (poly in polys) {
            if (poly.isEmpty()) continue
            val closed = poly.isClosed()
            val ring = if (closed) poly.dropLast(1) else poly
            val n = ring.size
            for (i in 0 until n) {
                val v = ring[i]
                if (best.from.dist(v) <= best.radius) {
                    val corner = when {
                        n == 1 -> true
                        !closed && (i == 0 || i == n - 1) -> true
                        else -> turnDeg(ring[(i - 1 + n) % n], v, ring[(i + 1) % n]) >= CORNER_ANGLE_DEG
                    }
                    if (corner) best.offer(v, SnapKind.CORNER, id)
                }
            }
            for ((a, b) in poly.zipWithNext()) {
                val c = Measure.closestOnSegment(p, a, b)
                if (p.dist(c) <= best.radius) {
                    best.offer(c, SnapKind.EDGE, id)
                    if (a.dist(b) >= MIN_MID_EDGE_MM) best.offer(Pt((a.x + b.x) / 2, (a.y + b.y) / 2), SnapKind.MID, id)
                }
            }
        }
    }

    /**
     * The element to measure at [p]: the one whose outline is nearest within [radius] mm (topmost on a tie),
     * otherwise the topmost one whose filled shape (even-odd) or image contains [p].
     */
    fun pick(p: Pt, radius: Double, elements: List<Element>): Element? {
        var best: Element? = null
        var bestD = Double.MAX_VALUE
        for (e in elements) {
            val b = e.worldBounds() ?: continue
            if (p.x < b.minX - radius || p.x > b.maxX + radius || p.y < b.minY - radius || p.y > b.maxY + radius) continue
            var d = Double.MAX_VALUE
            for (poly in outline(e)) {
                if (poly.size == 1) d = minOf(d, p.dist(poly[0]))
                for ((a, c) in poly.zipWithNext()) d = minOf(d, Measure.pointSegment(p, a, c))
            }
            if (d <= radius && d <= bestD) { best = e; bestD = d }
        }
        if (best != null) return best
        return elements.lastOrNull { e ->
            if (e.isImage) e.worldBounds()?.contains(p) == true
            else e.worldPaths().filter { it.isClosed() }.count { Measure.inside(p, it.dropLast(1)) } % 2 == 1
        }
    }

    /**
     * The point to catch near [p] within [radius] mm, or null (= free point). Candidates: corners and end points,
     * edge midpoints, the centre of an element with a closed shape (circle centre, image centre), the nearest
     * point on an edge, and corners/centre/edges of the work area.
     */
    fun find(p: Pt, radius: Double, elements: List<Element>, workArea: Boolean = true): SnapHit? {
        val best = Best(radius, p)
        for (e in elements) {
            val b = e.worldBounds() ?: continue
            if (p.x < b.minX - radius || p.x > b.maxX + radius || p.y < b.minY - radius || p.y > b.maxY + radius) continue
            val polys = outline(e)
            scan(best, polys, e.id)
            if (e.isImage || polys.any { it.isClosed() }) best.offer(b.center, SnapKind.CENTER, e.id)
        }
        if (workArea) {
            val w = Work.WIDTH; val h = Work.HEIGHT
            val rect = listOf(Pt(0.0, 0.0), Pt(w, 0.0), Pt(w, h), Pt(0.0, h), Pt(0.0, 0.0))
            scan(best, listOf(rect), null)
            best.offer(Work.center, SnapKind.CENTER, null)
        }
        return best.hit
    }
}

/* ---------- measurements ---------- */

/** A measured point; when it was caught on an element it follows that element ([local] = its place in element coordinates). */
data class MeasPt(val p: Pt, val elementId: String? = null, val local: Pt? = null) {
    companion object {
        fun of(hit: SnapHit?, free: Pt, elements: List<Element>): MeasPt {
            val id = hit?.elementId
            val e = id?.let { i -> elements.firstOrNull { it.id == i } }
            val at = hit?.p ?: free
            return if (e != null) MeasPt(at, e.id, e.transform.invert(at)) else MeasPt(at)
        }
    }
}

/** What was measured. Pure display data, never part of the document or the job. */
sealed class Measurement {
    abstract val id: String
    class Distance(val a: MeasPt, val b: MeasPt, override val id: String = UUID.randomUUID().toString()) : Measurement()
    class Gap(val a: String, val b: String, override val id: String = UUID.randomUUID().toString()) : Measurement()
    class Info(val ids: List<String>, override val id: String = UUID.randomUUID().toString()) : Measurement()
    class Angle(val a: MeasPt, val v: MeasPt, val c: MeasPt, override val id: String = UUID.randomUUID().toString()) : Measurement()
    class Edges(val ids: List<String>, override val id: String = UUID.randomUUID().toString()) : Measurement()
}

class MLabel(val at: Pt, val text: String)
class MArc(val vertex: Pt, val from: Pt, val to: Pt)

/** Drawing instructions in work mm. */
class Overlay(val segs: List<Pair<Pt, Pt>> = emptyList(), val dots: List<Pt> = emptyList(), val labels: List<MLabel> = emptyList(),
              val arc: MArc? = null, val boxes: List<Box> = emptyList(), val dashed: List<Pair<Pt, Pt>> = emptyList())

/** Result for the list and the canvas. [copy] is the main value for the clipboard; [stale] = an element is gone. */
class MeasureView(val title: String, val lines: List<String>, val copy: String, val stale: Boolean, val overlay: Overlay)

object MeasureEval {
    fun mm(v: Double) = String.format(Locale.ROOT, "%.2f", v) + " mm"
    fun deg(v: Double) = String.format(Locale.ROOT, "%.1f", v) + "°"
    private fun num(v: Double) = String.format(Locale.ROOT, "%.2f", v)

    private fun resolve(m: MeasPt, doc: Document): Pair<Pt, Boolean> {
        val id = m.elementId ?: return m.p to false
        val e = doc.elements.firstOrNull { it.id == id } ?: return m.p to true
        val l = m.local ?: return m.p to false
        return e.transform.apply(l) to false
    }

    private fun elementsOf(ids: List<String>, doc: Document): List<Element> = ids.mapNotNull { id -> doc.elements.firstOrNull { it.id == id } }

    fun eval(m: Measurement, doc: Document): MeasureView = when (m) {
        is Measurement.Distance -> distance(m, doc)
        is Measurement.Gap -> gap(m, doc)
        is Measurement.Info -> info(m, doc)
        is Measurement.Angle -> angle(m, doc)
        is Measurement.Edges -> edges(m, doc)
    }

    private fun distance(m: Measurement.Distance, doc: Document): MeasureView {
        val (a, sa) = resolve(m.a, doc); val (b, sb) = resolve(m.b, doc)
        val len = a.dist(b); val dx = b.x - a.x; val dy = b.y - a.y
        val lines = listOf("Länge ${mm(len)}", "ΔX ${mm(abs(dx))} · ΔY ${mm(abs(dy))}", "Winkel zur X-Achse ${deg(Measure.lineAngleDeg(a, b))}",
            "von X ${num(a.x)} · Y ${num(a.y)}", "nach X ${num(b.x)} · Y ${num(b.y)}")
        val ov = Overlay(segs = listOf(a to b), dots = listOf(a, b), labels = listOf(MLabel(Pt((a.x + b.x) / 2, (a.y + b.y) / 2), mm(len))),
            dashed = listOf(a to Pt(b.x, a.y), Pt(b.x, a.y) to b))
        return MeasureView("Abstand", lines, num(len), sa || sb, ov)
    }

    private fun gap(m: Measurement.Gap, doc: Document): MeasureView {
        val ea = doc.elements.firstOrNull { it.id == m.a }; val eb = doc.elements.firstOrNull { it.id == m.b }
        if (ea == null || eb == null) return MeasureView("Linie zu Linie", listOf("Ein Element wurde gelöscht."), "", true, Overlay())
        val hit = Measure.polyDistance(Snap.outline(ea), Snap.outline(eb))
            ?: return MeasureView("Linie zu Linie", listOf("Keine Linien zum Messen."), "", false, Overlay())
        val lines = mutableListOf<String>()
        lines += if (hit.distance < 1e-6) "Abstand 0.00 mm (berühren oder kreuzen sich)" else "Kürzester Abstand ${mm(hit.distance)}"
        if (hit.parallel) lines += "parallel, Abstand ${mm(hit.distance)}"
        lines += "Punkt A X ${num(hit.onA.x)} · Y ${num(hit.onA.y)}"
        lines += "Punkt B X ${num(hit.onB.x)} · Y ${num(hit.onB.y)}"
        val ov = Overlay(segs = if (hit.distance < 1e-6) emptyList() else listOf(hit.onA to hit.onB), dots = listOf(hit.onA, hit.onB),
            labels = listOf(MLabel(Pt((hit.onA.x + hit.onB.x) / 2, (hit.onA.y + hit.onB.y) / 2), mm(hit.distance) + if (hit.parallel) " ∥" else "")))
        return MeasureView("Linie zu Linie", lines, num(hit.distance), false, ov)
    }

    private fun info(m: Measurement.Info, doc: Document): MeasureView {
        val els = elementsOf(m.ids, doc)
        if (els.isEmpty()) return MeasureView("Element", listOf("Das Element wurde gelöscht."), "", true, Overlay())
        val stale = els.size < m.ids.size
        val box = els.mapNotNull { it.worldBounds() }.reduceOrNull { a, b -> a.union(b) }
            ?: return MeasureView("Element", listOf("Leer."), "", stale, Overlay())
        val outlines = els.flatMap { Snap.outline(it) }
        val closed = outlines.filter { it.isClosed() }; val open = outlines.filter { !it.isClosed() }
        val lines = mutableListOf<String>()
        val title = if (els.size > 1) "Gruppe (${els.size} Teile)" else els.first().kind
        lines += "Breite ${mm(box.width)} · Höhe ${mm(box.height)}"
        val axes = els.singleOrNull()?.takeIf { !it.isImage }?.let { e ->
            Measure.ellipseAxes(e.paths)?.let { (w, h) -> abs(w * e.transform.scaleX) to abs(h * e.transform.scaleY) }
        }
        if (axes != null) {
            lines += if (abs(axes.first - axes.second) < 0.02 * max(axes.first, axes.second))
                "Kreis Ø ${mm((axes.first + axes.second) / 2)} · Radius ${mm((axes.first + axes.second) / 4)}"
            else "Ellipse Achsen ${mm(axes.first)} × ${mm(axes.second)} · Radien ${mm(axes.first / 2)} / ${mm(axes.second / 2)}"
        }
        if (closed.isNotEmpty() && open.isNotEmpty()) {
            lines += "Umfang (geschlossen) ${mm(Measure.perimeter(closed))}"; lines += "Länge (offen) ${mm(Measure.perimeter(open))}"
        } else if (closed.isNotEmpty()) lines += "Umfang ${mm(Measure.perimeter(closed))}"
        else if (open.isNotEmpty()) lines += "Länge ${mm(Measure.perimeter(open))}"
        val area = if (closed.isNotEmpty()) Measure.area(closed) else 0.0
        if (closed.isNotEmpty()) lines += "Fläche ${num(area)} mm²"
        lines += "Mittelpunkt X ${num(box.center.x)} · Y ${num(box.center.y)}"
        val byLayer = els.groupBy { it.layerId }
        for ((lid, group) in byLayer) {
            val layer = doc.layer(lid) ?: continue
            val total = group.mapNotNull { Measure.laserLength(it, layer) }.takeIf { it.isNotEmpty() }?.sum() ?: continue
            lines += "Laserweg auf „${layer.name}“ ${mm(total)}" + if (layer.passes > 1) " (${layer.passes} Durchgänge)" else ""
        }
        val main = if (closed.isNotEmpty() || open.isNotEmpty()) num(Measure.perimeter(outlines)) else num(box.width)
        val ov = Overlay(boxes = listOf(box), dots = listOf(box.center),
            labels = listOf(MLabel(Pt(box.center.x, box.minY), mm(box.width)), MLabel(Pt(box.maxX, box.center.y), mm(box.height))))
        return MeasureView(title, lines, main, stale, ov)
    }

    private fun angle(m: Measurement.Angle, doc: Document): MeasureView {
        val (a, s1) = resolve(m.a, doc); val (v, s2) = resolve(m.v, doc); val (c, s3) = resolve(m.c, doc)
        val ang = Measure.angleDeg(a, v, c)
        val ra = min(a.dist(v), c.dist(v)) * 0.35
        val ua = Pt(a.x - v.x, a.y - v.y); val uc = Pt(c.x - v.x, c.y - v.y)
        val la = hypot(ua.x, ua.y).coerceAtLeast(1e-9); val lc = hypot(uc.x, uc.y).coerceAtLeast(1e-9)
        val from = Pt(v.x + ua.x / la * ra, v.y + ua.y / la * ra); val to = Pt(v.x + uc.x / lc * ra, v.y + uc.y / lc * ra)
        val bis = Pt(ua.x / la + uc.x / lc, ua.y / la + uc.y / lc)
        val bl = hypot(bis.x, bis.y)
        val lab = if (bl < 1e-9) Pt(v.x + ua.y / la * ra * 1.5, v.y - ua.x / la * ra * 1.5) else Pt(v.x + bis.x / bl * ra * 1.6, v.y + bis.y / bl * ra * 1.6)
        val ov = Overlay(segs = listOf(v to a, v to c), dots = listOf(a, v, c), labels = listOf(MLabel(lab, deg(ang))), arc = MArc(v, from, to))
        return MeasureView("Winkel", listOf("Winkel ${deg(ang)}", "Scheitel X ${num(v.x)} · Y ${num(v.y)}"), String.format(Locale.ROOT, "%.1f", ang), s1 || s2 || s3, ov)
    }

    private fun edges(m: Measurement.Edges, doc: Document): MeasureView {
        val els = elementsOf(m.ids, doc)
        if (els.isEmpty()) return MeasureView("Rand", listOf("Das Element wurde gelöscht."), "", true, Overlay())
        val b = els.mapNotNull { it.worldBounds() }.reduceOrNull { a, c -> a.union(c) }
            ?: return MeasureView("Rand", listOf("Leer."), "", false, Overlay())
        val left = b.minX; val right = Work.WIDTH - b.maxX; val top = b.minY; val bottom = Work.HEIGHT - b.maxY
        val c = b.center
        val segs = listOf(Pt(b.minX, c.y) to Pt(0.0, c.y), Pt(b.maxX, c.y) to Pt(Work.WIDTH, c.y), Pt(c.x, b.minY) to Pt(c.x, 0.0), Pt(c.x, b.maxY) to Pt(c.x, Work.HEIGHT))
        val labels = listOf(MLabel(Pt(b.minX / 2, c.y), mm(left)), MLabel(Pt((b.maxX + Work.WIDTH) / 2, c.y), mm(right)),
            MLabel(Pt(c.x, b.minY / 2), mm(top)), MLabel(Pt(c.x, (b.maxY + Work.HEIGHT) / 2), mm(bottom)))
        val lines = listOf("Links ${mm(left)}", "Rechts ${mm(right)}", "Oben ${mm(top)}", "Unten ${mm(bottom)}")
        return MeasureView("Rand", lines, lines.joinToString(" · "), els.size < m.ids.size, Overlay(segs = segs, labels = labels, boxes = listOf(b)))
    }
}
