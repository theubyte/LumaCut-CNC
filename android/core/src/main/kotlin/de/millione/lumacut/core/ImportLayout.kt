package de.millione.lumacut.core

import kotlin.math.max
import kotlin.math.min

/** A group of items (and pictures) that moves as one when an import is arranged on the work area. */
class ImportUnit(val items: List<ImportItem>, val images: List<EmbeddedImage>) {
    val box: Box = (items.flatMap { it.polys }.let(::boundsOf)?.let { b -> images.fold(b) { acc, i -> i.box.union(acc) } }
        ?: images.map { it.box }.reduce { a, b -> a.union(b) })
}

enum class FitKind { AS_IS, PACKED, PARTIAL }

/** [offsets] = translation per unit (null = does not fit and is left out). */
class Layout(val kind: FitKind, val units: List<ImportUnit>, val offsets: List<Pt?>) {
    val leftOut get() = offsets.count { it == null }
}

/**
 * Vector imports keep their original size. Fits as drawn: centred. Too big: the top-level groups are packed in
 * rows (5 mm apart, no rotating); if even that fails, the parts that do not fit are reported so the operator
 * can pick: only the parts that fit, or shrink everything.
 */
object ImportLayout {
    const val GAP = 5.0
    private const val MARGIN = 1.0

    /** Items of [r]: the structured ones (xTool) or the parts of [PartSplitter]; parts of one import share one group. */
    fun items(r: VectorImport): List<ImportItem> {
        if (r.items.isNotEmpty()) return r.items
        val split = PartSplitter.split(r.polys)
        val group = if (split.parts.size > 1) listOf("*") else emptyList()
        return split.parts.map { ImportItem(it, null, false, group, null) }
    }

    fun units(r: VectorImport): List<ImportUnit> {
        val byTop = LinkedHashMap<String, MutableList<ImportItem>>()
        var single = 0
        for (item in items(r)) byTop.getOrPut(item.groups.firstOrNull() ?: "#${single++}") { ArrayList() } += item
        val units = byTop.values.map { ImportUnit(it, emptyList()) }.toMutableList()
        for (img in r.images) units += ImportUnit(emptyList(), listOf(img))
        return units
    }

    fun union(units: List<ImportUnit>): Box = units.map { it.box }.reduce { a, b -> a.union(b) }

    fun arrange(units0: List<ImportUnit>, w: Double = Work.WIDTH, h: Double = Work.HEIGHT): Layout {
        val all = union(units0)
        if (all.width <= w && all.height <= h) {
            val d = Pt(w / 2 - all.center.x, h / 2 - all.center.y)
            return Layout(FitKind.AS_IS, units0, units0.map { d })
        }
        // one big group: its parts become the units
        val units = if (units0.size == 1) units0[0].let { u -> u.items.map { ImportUnit(listOf(it), emptyList()) } + u.images.map { ImportUnit(emptyList(), listOf(it)) } } else units0
        val packed = shelf(units.map { it.box }, w, h)
        return Layout(if (packed.all { it != null }) FitKind.PACKED else FitKind.PARTIAL, units, packed)
    }

    /** Factor (< 1) that shrinks everything into the work area with a 5 mm border. */
    fun shrinkFactor(units: List<ImportUnit>, w: Double = Work.WIDTH, h: Double = Work.HEIGHT, border: Double = 5.0): Double {
        val all = union(units)
        return min(1.0, min((w - 2 * border) / max(all.width, 1e-9), (h - 2 * border) / max(all.height, 1e-9)))
    }

    /** Shelf packing, tallest first, rows from the top left; returns the translation per box or null. */
    fun shelf(boxes: List<Box>, w: Double, h: Double, gap: Double = GAP): List<Pt?> {
        val out = arrayOfNulls<Pt>(boxes.size)
        var x = MARGIN; var y = MARGIN; var rowH = 0.0
        for (i in boxes.indices.sortedByDescending { boxes[it].height }) {
            val b = boxes[i]
            if (b.width > w - 2 * MARGIN || b.height > h - 2 * MARGIN) continue
            var px = x; var py = y; var newRow = false
            if (px + b.width > w - MARGIN) { px = MARGIN; py = y + rowH + gap; newRow = true }
            if (py + b.height > h - MARGIN) continue
            out[i] = Pt(px - b.minX, py - b.minY)
            x = px + b.width + gap
            if (newRow) { y = py; rowH = b.height } else rowH = max(rowH, b.height)
        }
        return out.toList()
    }
}

/**
 * Cutting order for line layers: inner paths before the closed contours that enclose them, so a part
 * never drops out before its inner cuts are done. Within each level nearest neighbour.
 */
fun orderForCutting(paths: List<Poly>, start: Pt): List<Poly> {
    val p = paths.filter { it.size >= 2 }
    if (p.size < 2 || p.size > 1500) return orderPaths(p, start)
    val closed = p.map { it.size >= 4 && it.isClosed() }
    val boxes = p.map { boundsOf(listOf(it))!! }
    val area = boxes.map { it.width * it.height }
    fun inside(poly: Poly, pt: Pt): Boolean {
        var c = false
        for ((a, b) in poly.zipWithNext()) if ((a.y > pt.y) != (b.y > pt.y) && pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x) c = !c
        return c
    }
    val height = IntArray(p.size)
    for (i in p.indices.sortedBy { area[it] }) {
        if (!closed[i]) continue
        var h = 0
        for (j in p.indices) {
            if (j == i || area[j] >= area[i]) continue
            if (!boxes[i].contains(Pt(boxes[j].minX, boxes[j].minY)) || !boxes[i].contains(Pt(boxes[j].maxX, boxes[j].maxY))) continue
            if (inside(p[i], p[j].first())) h = max(h, height[j] + 1)
        }
        height[i] = h
    }
    val out = ArrayList<Poly>(p.size)
    var at = start
    for (level in height.toSet().sorted()) {
        val tier = orderPaths(p.indices.filter { height[it] == level }.map { p[it] }, at)
        if (tier.isNotEmpty()) at = tier.last().last()
        out += tier
    }
    return out
}
