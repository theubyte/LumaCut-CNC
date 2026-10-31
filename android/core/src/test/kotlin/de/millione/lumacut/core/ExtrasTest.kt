package de.millione.lumacut.core

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ImageToolsTest {
    @Test fun `adjust brightness, contrast, invert and sharpen`() {
        val gray = intArrayOf(0, 100, 128, 200, 255)
        assertTrue(ImageTools.adjust(gray, 5, 1, ImageAdjust()) === gray, "untouched picture is returned as is")
        assertEquals(listOf(255, 155, 127, 55, 0), ImageTools.adjust(gray, 5, 1, ImageAdjust(invert = true)).toList())
        val bright = ImageTools.adjust(gray, 5, 1, ImageAdjust(brightness = 20))
        assertEquals(51, bright[0]); assertEquals(255, bright[4])
        val contrast = ImageTools.adjust(gray, 5, 1, ImageAdjust(contrast = 100))
        assertEquals(72, contrast[1]); assertEquals(128, contrast[2]); assertEquals(255, contrast[3])
        val flat = IntArray(25) { 90 }
        assertEquals(flat.toList(), ImageTools.adjust(flat, 5, 5, ImageAdjust(sharpen = 100)).toList(), "flat areas stay flat")
        val edge = IntArray(25) { if (it % 5 < 2) 60 else 180 }
        val sharp = ImageTools.adjust(edge, 5, 5, ImageAdjust(sharpen = 100))
        assertTrue(sharp[2] > edge[2] && sharp[1] < edge[1], "edge contrast grows")
    }

    @Test fun `every dither gives black and white and keeps the mean brightness`() {
        val w = 40; val h = 40
        val mid = IntArray(w * h) { 128 }
        val ramp = IntArray(w * h) { (it % w) * 255 / (w - 1) }
        for (mode in listOf(ImageMode.DITHER, ImageMode.DITHER_JARVIS, ImageMode.DITHER_STUCKI)) {
            val out = ImageTools.binarize(mid, w, h, mode)
            assertTrue(out.all { it == 0 || it == 255 })
            val white = out.count { it == 255 } / out.size.toDouble()
            assertTrue(abs(white - 0.5) < 0.06, "$mode white share $white")
            val r = ImageTools.binarize(ramp, w, h, mode)
            assertTrue(abs(r.average() - ramp.average()) < 10, "$mode ramp mean")
        }
        assertEquals(listOf(0, 255), ImageTools.binarize(intArrayOf(100, 200), 2, 1, ImageMode.THRESHOLD).toList())
    }

    @Test fun `adjustment reaches the g-code`() {
        val layer = Document.defaultLayers()[0].copy(intervalMm = 1.0, powerPct = 100.0, minPowerPct = 0.0, overscanMm = 0.0)
        val raster = Raster.of(2, 1, byteArrayOf(0, 255.toByte()))
        fun job(adjust: ImageAdjust) = MarlinWriter().write(Document(layers = listOf(layer), elements = listOf(
            Element(layerId = layer.id, kind = "Bild", transform = Transform(50.0, 50.0), raster = raster, imageWidthMm = 2.0, imageHeightMm = 1.0, adjust = adjust))))
        val plain = job(ImageAdjust())
        val inverted = job(ImageAdjust(invert = true))
        assertTrue(plain != inverted)
        // where the laser first switches on: the end of the laser-off run-up before the first burning G1
        fun burnStart(g: String): String { val l = g.lines(); val i = l.indexOfFirst { it.startsWith("G1") && !it.endsWith(" S0") }; return l[i - 1] }
        assertTrue(burnStart(plain).contains("X320.000"), "black pixel is column 0 = large X: " + burnStart(plain))
        assertTrue(burnStart(inverted).contains("X319.000"), "inverted: black pixel is the right one: " + burnStart(inverted))
    }
}

class QrTest {
    private fun maskBit(m: Int, x: Int, y: Int) = when (m) {
        0 -> (x + y) % 2 == 0; 1 -> y % 2 == 0; 2 -> x % 3 == 0; 3 -> (x + y) % 3 == 0
        4 -> (x / 3 + y / 2) % 2 == 0; 5 -> x * y % 2 + x * y % 3 == 0; 6 -> (x * y % 2 + x * y % 3) % 2 == 0
        else -> ((x + y) % 2 + x * y % 3) % 2 == 0
    }

    /** Reads the code words back from the finished matrix, independent of how they were placed. */
    private fun readCodewords(q: QrCode): ByteArray {
        val b = QrCode.Companion.Builder(q.version); b.drawFunctionPatterns()
        val size = q.size
        val bits = ArrayList<Boolean>()
        var right = size - 1
        while (right >= 1) {
            if (right == 6) right = 5
            for (vert in 0 until size) for (j in 0..1) {
                val x = right - j; val upward = ((right + 1) and 2) == 0
                val y = if (upward) size - 1 - vert else vert
                if (!b.isFunction[y][x]) bits += q[x, y] != maskBit(q.mask, x, y)
            }
            right -= 2
        }
        return ByteArray(bits.size / 8) { i -> var v = 0; for (k in 0 until 8) v = (v shl 1) or (if (bits[i * 8 + k]) 1 else 0); v.toByte() }
    }

    @Test fun `reed solomon matches the known 1-M example`() {
        val data = intArrayOf(32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17)
        val ecc = QrCode.Companion.rsRemainder(data, QrCode.Companion.rsDivisor(10))
        assertEquals(listOf(196, 35, 39, 119, 235, 215, 231, 226, 93, 23), ecc.toList())
    }

    @Test fun `format information is valid and the text can be read back`() {
        for (text in listOf("HELLO", "https://lumacut.example/abc?x=1", "Ä ö ü – Straße 12345678901234567890123456789012345678901234567890")) {
            val q = QrCode.encode(text)
            val size = q.size
            assertEquals(q.version * 4 + 17, size)
            // finder patterns and the dark module
            for ((fx, fy) in listOf(0 to 0, size - 7 to 0, 0 to size - 7)) {
                assertTrue(q[fx, fy] && q[fx + 6, fy + 6] && !q[fx + 1, fy + 1] && q[fx + 3, fy + 3])
            }
            assertTrue(q[8, size - 8])
            // format bits: both copies equal, BCH valid, level M, mask as announced
            fun f1(): Int { var v = 0
                val pos = listOf(8 to 0, 8 to 1, 8 to 2, 8 to 3, 8 to 4, 8 to 5, 8 to 7, 8 to 8, 7 to 8, 5 to 8, 4 to 8, 3 to 8, 2 to 8, 1 to 8, 0 to 8)
                for ((i, p) in pos.withIndex()) if (q[p.first, p.second]) v = v or (1 shl i); return v }
            fun f2(): Int { var v = 0
                for (i in 0..7) if (q[size - 1 - i, 8]) v = v or (1 shl i)
                for (i in 8..14) if (q[8, size - 15 + i]) v = v or (1 shl i); return v }
            assertEquals(f1(), f2())
            var v = f1() xor 0x5412
            for (i in 14 downTo 10) if ((v ushr i) and 1 == 1) v = v xor (0x537 shl (i - 10))
            assertEquals(0, v, "BCH remainder")
            assertEquals(0, ((f1() xor 0x5412) ushr 13) and 3, "level M")
            assertEquals(q.mask, ((f1() xor 0x5412) ushr 10) and 7)
            // code words: de-interleave, check ECC per block, decode the byte-mode text
            val words = readCodewords(q).map { it.toInt() and 0xFF }
            val ver = q.version
            val blocks = intArrayOf(-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)[ver]
            val ecc = intArrayOf(-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)[ver]
            val raw = words.size
            val short = blocks - raw % blocks; val shortLen = raw / blocks
            val dataBlocks = List(blocks) { ArrayList<Int>() }; val eccBlocks = List(blocks) { ArrayList<Int>() }
            var k = 0
            for (i in 0..shortLen) for (j in 0 until blocks) {
                if (i < shortLen - ecc) { dataBlocks[j] += words[k++] }
                else if (i == shortLen - ecc) { if (j >= short) dataBlocks[j] += words[k++] }
                else if (i <= shortLen) { if (i - 1 - (shortLen - ecc) + (if (j >= short) 0 else 1) >= 0) { /* placeholder */ } }
            }
            // simpler second pass for the ECC part: it follows all data code words, interleaved
            for (i in 0 until ecc) for (j in 0 until blocks) eccBlocks[j] += words[k++]
            for (j in 0 until blocks) {
                val expected = QrCode.Companion.rsRemainder(dataBlocks[j].toIntArray(), QrCode.Companion.rsDivisor(ecc))
                assertEquals(expected.toList(), eccBlocks[j], "ECC of block $j")
            }
            val data = dataBlocks.flatten()
            assertEquals(4, data[0] ushr 4, "byte mode")
            val len = ((data[0] and 0xF) shl 4) or (data[1] ushr 4)
            val bytes = ByteArray(len) { i -> (((data[1 + i] and 0xF) shl 4) or (data[2 + i] ushr 4)).toByte() }
            assertEquals(text, String(bytes, Charsets.UTF_8))
        }
    }

    @Test fun `polygons are filled runs and sizes are checked`() {
        val q = QrCode.encode("A")
        val polys = q.toPolys(1.0)
        assertTrue(polys.all { it.isClosed() })
        val b = boundsOf(polys)!!
        assertEquals(q.size.toDouble(), b.width, 1e-9)
        assertEquals(q.size.toDouble(), b.height, 1e-9)
        val areaSum = polys.sumOf { (it[1].x - it[0].x) * (it[2].y - it[1].y) }
        assertEquals(q.size * q.size - 0.0, areaSum + (0 until q.size).sumOf { y -> (0 until q.size).count { x -> !q[x, y] } }, 1e-9)
        assertEquals(1, QrCode.encode("a".repeat(14)).version); assertEquals(2, QrCode.encode("a".repeat(15)).version)
        assertEquals(10, QrCode.encode("a".repeat(213)).version)
        assertFailsWith<IllegalArgumentException> { QrCode.encode("a".repeat(214)) }
        assertFailsWith<IllegalArgumentException> { QrCode.encode("") }
    }
}

class ShapeToolsTest {
    @Test fun `arc text keeps the baseline on the circle`() {
        val line = listOf(listOf(Pt(-20.0, 10.0), Pt(0.0, 10.0), Pt(20.0, 10.0)), listOf(Pt(-20.0, 0.0), Pt(20.0, 0.0)))   // baseline y=10, top y=0
        val top = ArcText.bend(line, 50.0)
        // circle centre is at (0, 50): baseline points have distance 50, top points distance 60
        for (p in top[0]) assertEquals(50.0, hypot(p.x, p.y - 50.0), 1e-9)
        for (p in top[1]) assertEquals(60.0, hypot(p.x, p.y - 50.0), 1e-9)
        assertEquals(0.0, top[0][1].x, 1e-9); assertEquals(0.0, top[0][1].y, 1e-9)
        assertTrue(top[0][0].x < 0 && top[0][2].x > 0, "still reads left to right")
        assertTrue(top[0][0].y > top[0][1].y, "ends bend down")
        val bottom = ArcText.bend(line, -50.0)
        for (p in bottom[0]) assertEquals(50.0, hypot(p.x, p.y + 50.0), 1e-9)
        for (p in bottom[1]) assertEquals(40.0, hypot(p.x, p.y + 50.0), 1e-9)
        assertTrue(bottom[0][0].x < 0 && bottom[0][2].x > 0)
        assertFailsWith<IllegalArgumentException> { ArcText.bend(line, 0.5) }
    }

    @Test fun `grid offsets and work area check`() {
        val piece = Box(10.0, 10.0, 30.0, 20.0)
        val offsets = Arrange.gridOffsets(piece, 3, 2, 5.0, 4.0)
        assertEquals(5, offsets.size)
        assertEquals(Pt(25.0, 0.0), offsets[0]); assertEquals(Pt(0.0, 14.0), offsets[2]); assertEquals(Pt(50.0, 14.0), offsets.last())
        assertEquals(5, Arrange.inside(piece, offsets).size)
        val big = Arrange.gridOffsets(Box(0.0, 0.0, 100.0, 100.0), 4, 1, 0.0, 0.0)
        assertEquals(2, Arrange.inside(Box(0.0, 0.0, 100.0, 100.0), big).size, "third and fourth copy leave the 360 mm area")
        assertFailsWith<IllegalArgumentException> { Arrange.gridOffsets(piece, 0, 1, 0.0, 0.0) }
    }

    @Test fun `shape library`() {
        val heart = ShapeLib.heart(40.0, 36.0)
        val hb = boundsOf(listOf(heart))!!
        assertEquals(40.0, hb.width, 1e-6); assertEquals(36.0, hb.height, 1e-6); assertTrue(heart.isClosed())
        val star = ShapeLib.star(5, 50.0, 48.0)
        assertEquals(11, star.size); assertTrue(star.isClosed()); assertEquals(50.0, boundsOf(listOf(star))!!.width, 1e-6)
        val pendant = ShapeLib.pendant(40.0, 25.0, 4.0)
        assertEquals(2, pendant.size)
        assertTrue(pendant.all { it.isClosed() })
        val outer = boundsOf(listOf(pendant[0]))!!; val hole = boundsOf(listOf(pendant[1]))!!
        assertTrue(outer.contains(Pt(hole.minX, hole.minY)) && outer.contains(Pt(hole.maxX, hole.maxY)))
        assertEquals(20.0, hole.center.x, 0.05)
    }
}
