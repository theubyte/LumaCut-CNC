package de.millione.lumacut.core

import kotlin.math.abs

/** Result of [PartSplitter.split]: [parts] each a list of polylines; [tooMany] = not split, one part with everything. */
class Split(val parts: List<List<Poly>>, val tooMany: Boolean)

/**
 * Splits imported geometry into editable parts: every outer closed contour together with the holes inside it
 * (even-odd nesting) is one part, every open path is one part. A letter O, a ring or a drilled plate stays whole.
 */
object PartSplitter {
    const val MAX_PARTS = 500
    private const val MAX_CLOSED = 2000

    fun split(polys: List<Poly>): Split {
        val usable = polys.filter { it.size >= 2 }
        val closedIdx = usable.indices.filter { usable[it].size >= 4 && usable[it].isClosed() }
        if (closedIdx.size > MAX_CLOSED) return Split(listOf(usable), true)
        val closed = closedIdx.map { usable[it] }
        val boxes = closed.map { boundsOf(listOf(it))!! }
        val area = closed.map { abs(signedArea(it)) }
        // containers[i] = indices of closed polygons that contain polygon i
        val containers = closed.indices.map { i ->
            closed.indices.filter { j -> j != i && area[j] > area[i] && boxes[j].let { b -> b.contains(Pt(boxes[i].minX, boxes[i].minY)) && b.contains(Pt(boxes[i].maxX, boxes[i].maxY)) } && inside(closed[i], closed[j]) }
        }
        val depth = containers.map { it.size }
        // each odd-depth polygon is a hole of its nearest container (the one with the greatest depth)
        val holesOf = HashMap<Int, MutableList<Int>>()
        for (i in closed.indices) if (depth[i] % 2 == 1) {
            val parent = containers[i].maxByOrNull { depth[it] } ?: continue
            holesOf.getOrPut(parent) { ArrayList() } += i
        }
        val parts = ArrayList<List<Poly>>()
        val closedPos = closedIdx.toSet()
        var ci = 0
        for ((k, poly) in usable.withIndex()) {
            if (k in closedPos) {
                val i = ci++
                if (depth[i] % 2 == 0) parts += listOf(poly) + holesOf[i].orEmpty().map { closed[it] }
            } else parts += listOf(poly)
        }
        if (parts.size > MAX_PARTS) return Split(listOf(usable), true)
        return Split(parts, false)
    }

    private fun signedArea(p: Poly): Double = p.zipWithNext().sumOf { (a, b) -> a.x * b.y - b.x * a.y } / 2

    /** True when [inner] lies inside [outer]: all sampled vertices are inside (ray casting). */
    private fun inside(inner: Poly, outer: Poly): Boolean {
        val step = maxOf(1, inner.size / 8)
        var n = 0; var hit = 0
        var i = 0
        while (i < inner.size) { n++; if (contains(outer, inner[i])) hit++; i += step }
        return hit * 2 > n
    }

    private fun contains(poly: Poly, p: Pt): Boolean {
        var c = false
        for ((a, b) in poly.zipWithNext()) {
            if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) c = !c
        }
        return c
    }
}
