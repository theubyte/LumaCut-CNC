package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class LensTest {
    private val w = 960
    private val h = 720
    private val head = Pt(150.0, 190.0)

    /** A wide-angle camera: 7 px/mm, turned 4°, slight tilt, strong barrel distortion. */
    private fun trueLens(): Lens {
        val f = hypot(w.toDouble(), h.toDouble()) / 2
        val k = 7.0 / f; val a = Math.toRadians(4.0)
        val off = DotGrid.center - head            // grid centre a bit off the image centre
        val c = cos(a) * k; val s = sin(a) * k
        val g = listOf(c, -s, -(c * (off.x + 6) - s * (off.y - 4)), s, c, -(s * (off.x + 6) + c * (off.y - 4)), 0.0004, -0.0002, 1.0)
        return Lens(w / 2.0, h / 2.0, f, -0.28, 0.06, g, Box(0.0, 0.0, w.toDouble(), h.toDouble()))
    }

    /** Photo of the lasered grid on wood: dark dots, grain, noise, uneven light. */
    private fun render(lens: Lens): IntArray {
        val rnd = Random(3)
        return IntArray(w * h) { k ->
            val x = k % w; val y = k / w
            var dark = 0
            for (sy in 0..1) for (sx in 0..1) {
                val p = head + lens.toRel(Pt(x + 0.25 + sx * 0.5, y + 0.25 + sy * 0.5))
                val i = ((p.x - DotGrid.center.x) / DotGrid.PITCH).roundToInt(); val j = ((p.y - DotGrid.center.y) / DotGrid.PITCH).roundToInt()
                if (abs(i) <= DotGrid.HALF_COLS && abs(j) <= DotGrid.HALF_ROWS && p.dist(DotGrid.position(i, j)) < DotGrid.radius(i, j)) dark++
            }
            val light = 190 + 25 * sin(y / 9.0 + sin(x / 40.0)) - 40.0 * x / w
            val v = (light * (1 - dark / 4.0 * 0.7) + rnd.nextInt(-6, 7)).roundToInt().coerceIn(0, 255)
            (0xFF shl 24) or (v shl 16) or ((v * 0.85).toInt() shl 8) or (v * 0.6).toInt()
        }
    }

    @Test fun `fit recovers a known lens from exact points`() {
        val t = trueLens()
        val rel = (-5..5).flatMap { i -> (-4..4).map { j -> DotGrid.position(i, j) - head } }
        val px = rel.map(t::toPixel)
        val fit = Lens.fit(px, rel, w, h)
        assertTrue(fit.rmsMm < 1e-4, "rms ${fit.rmsMm}")
        for (q in listOf(Pt(10.0, 10.0), Pt(500.0, 300.0), Pt(900.0, 650.0))) assertTrue(fit.toRel(q).dist(t.toRel(q)) < 1e-3)
        assertEquals(-0.28, fit.k1, 1e-3)
        val (k, d) = fit.openCv()
        assertEquals(w / 2.0, k[0][2]); assertEquals(5, d.size)
    }

    @Test fun `toRel and toPixel are inverse`() {
        val t = trueLens()
        for (q in listOf(Pt(0.0, 0.0), Pt(480.0, 360.0), Pt(959.0, 719.0), Pt(30.0, 700.0))) assertTrue(t.toPixel(t.toRel(q)).dist(q) < 1e-6, "$q")
        assertTrue(t.monotonic())
        assertTrue(!t.copy(k1 = -2.5).monotonic(), "strong barrel folds over at the corners")
    }

    @Test fun `dot grid photo calibrates the camera`() {
        val t = trueLens()
        val photo = render(t)
        val r = DotGrid.calibrate(photo, w, h, head, 30.0)
        assertTrue(r.points.size > 80, "found ${r.points.size}")
        assertTrue(r.lens.rmsMm < 0.08, "rms ${r.lens.rmsMm}")
        val cal = r.calibration
        // a point in the middle and one near the corner land where the true camera shows them
        for (q in listOf(Pt(480.0, 360.0), Pt(r.lens.valid.minX + 30, r.lens.valid.minY + 30))) {
            val err = cal.pixelToWork(q, head).dist(head + t.toRel(q))
            assertTrue(err < 0.15, "$q off by $err mm")
        }
        val u = cal.usable(0.0); val f = cal.footprint()
        assertTrue(u.width > 40 && u.height > 30 && u.minX >= f.minX && u.maxY <= f.maxY, "usable $u in $f")
        assertEquals(30.0, cal.scanZ)
        // stored and loaded again
        val again = Document.JSON.decodeFromString(CameraCalibration.serializer(), Document.JSON.encodeToString(CameraCalibration.serializer(), cal))
        assertTrue(again.pixelToWork(Pt(100.0, 100.0), head).dist(cal.pixelToWork(Pt(100.0, 100.0), head)) < 1e-9)
    }

    @Test fun `mirrored camera is recognised by the direction dots`() {
        val t = trueLens().let { l -> l.copy(g = l.g.mapIndexed { i, v -> if (i < 3) -v else v }) }   // image X flipped
        val r = DotGrid.calibrate(render(t), w, h, head, 30.0)
        assertTrue(r.lens.rmsMm < 0.08, "rms ${r.lens.rmsMm}")
    }

    @Test fun `photo without the grid gives a clear message`() {
        val plain = IntArray(w * h) { 0xFFC8B090.toInt() }
        val e = runCatching { DotGrid.calibrate(plain, w, h, head, 30.0) }.exceptionOrNull()
        assertTrue(e is IllegalArgumentException && e.message!!.contains("Punkte"), e.toString())
    }

    @Test fun `lens mosaic puts the grid dots where they are`() {
        val t = trueLens()
        val cal = CameraCalibration(w, h, scanZ = 30.0, lens = t.copy(valid = Box(20.0, 20.0, w - 20.0, h - 20.0)))
        val tile = Scan.Tile(render(t), w, h, head)
        val m = Scan.Mosaic(cal, 4.0); m.add(tile)
        fun lum(p: Pt): Int { val c = m.pixels[(p.y * 4).toInt() * m.width + (p.x * 4).toInt()]; return (c shr 16) and 255 }
        val centre = DotGrid.position(0, 0)
        assertTrue(lum(centre) < lum(centre + Pt(6.0, 6.0)) - 40, "big dot dark, gap light")
        assertTrue(lum(DotGrid.position(2, 1)) < lum(DotGrid.position(2, 1) + Pt(6.0, 0.0)) - 40)
        assertEquals(0, m.pixels[0], "outside the photo stays transparent")
        val plan = Scan.plan(cal)
        assertTrue(plan.heads.size in 10..120, "${plan.heads.size} tiles")
    }

    @Test fun `grid job lasers every dot`() {
        assertEquals(17 * 13, DotGrid.paths().size)
        val g = DotGrid.job()
        assertTrue(g.contains("G1") && g.length > 10_000)
        assertTrue(Work.contains(DotGrid.bounds()))
    }

    @Test fun `grid power is chosen between 20 and 60 percent`() {
        fun powers(g: String) = Regex("""^G1 .* S(\d+)$""", RegexOption.MULTILINE).findAll(g).map { it.groupValues[1] }.toSet()
        assertEquals(setOf("51"), powers(DotGrid.job()))
        assertEquals(setOf("153"), powers(DotGrid.job(60.0)))
        assertTrue(runCatching { DotGrid.job(65.0) }.isFailure)
        assertTrue(runCatching { DotGrid.job(15.0) }.isFailure)
    }

    @Test fun `calibration goes to the Pi and comes back unchanged`() = runBlocking {
        val cal = CameraCalibration(w, h, scanZ = 31.5, lens = trueLens())
        val stored = Document.JSON.encodeToString(CameraCalibration.serializer(), cal)
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"revision":3,"android":null,"placeholder":false}"""))
            enqueue(MockResponse().setBody("""{"revision":4,"message":"Kamera-Kalibrierung gespeichert"}"""))
            enqueue(MockResponse().setBody("""{"revision":4,"android":$stored}"""))
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        assertEquals("Kamera-Kalibrierung gespeichert", pi.saveCameraCalibration(cal))
        srv.takeRequest()
        val put = srv.takeRequest()
        assertEquals("PUT", put.method)
        val body = Json.parseToJsonElement(put.body.readUtf8()).jsonObject
        assertEquals("3", body["revision"].toString())
        assertEquals("$w", body["image_width"].toString())
        assertTrue(body["dist_coeffs"].toString().startsWith("[-0.28"))
        assertTrue(body.getValue("android").jsonObject.containsKey("lens"))
        val (back, rev) = pi.cameraCalibration()
        assertEquals(4, rev); assertEquals(cal, back)
        srv.shutdown()
    }

    @Test fun `scan height sent to the Pi never exceeds the 80 mm rail limit`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody("""{"revision":1,"android":null,"placeholder":false}"""))
            enqueue(MockResponse().setBody("""{"revision":2,"message":"ok"}"""))
            start()
        }
        PiClient("127.0.0.1", srv.port).saveCameraCalibration(CameraCalibration(w, h, scanZ = 85.0, lens = trueLens()))
        srv.takeRequest()
        val body = Json.parseToJsonElement(srv.takeRequest().body.readUtf8()).jsonObject
        assertEquals("80.0", body["scan_z"].toString())
        assertEquals(80.0, Limits.Z_MAX_MM)
        srv.shutdown()
    }

    @Test fun `locate tells how far the image centre is from the grid centre`() {
        val t = trueLens()
        val off = DotGrid.locate(render(t), w, h)!!
        val truth = head + t.toRel(Pt(w / 2.0, h / 2.0)) - DotGrid.center
        assertTrue(off.dist(truth) < 4.0, "located $off, true $truth")
        assertEquals(null, DotGrid.locate(IntArray(w * h) { 0xFFC8B090.toInt() }, w, h))
    }

    @Test fun `focus measure prefers the sharp picture`() {
        val sharp = render(trueLens())
        val blurred = IntArray(w * h) { k ->
            val x = k % w; val y = k / w
            var r = 0; var g = 0; var b = 0; var n = 0
            for (dy in -3..3) for (dx in -3..3) {
                val xx = (x + dx).coerceIn(0, w - 1); val yy = (y + dy).coerceIn(0, h - 1); val c = sharp[yy * w + xx]
                r += (c shr 16) and 255; g += (c shr 8) and 255; b += c and 255; n++
            }
            (0xFF shl 24) or ((r / n) shl 16) or ((g / n) shl 8) or (b / n)
        }
        assertTrue(CameraFocus.sharpness(sharp, w, h) > 2 * CameraFocus.sharpness(blurred, w, h))
    }

    @Test fun `focus helpers`() {
        assertEquals(listOf(10.0, 10.0, 1.0, 1.0, 1.0, 0.1), CameraFocus.jogSteps(23.1))
        assertEquals(listOf(-1.0, -0.1, -0.1), CameraFocus.jogSteps(-1.2))
        assertEquals(emptyList(), CameraFocus.jogSteps(0.04))
        val samples = listOf(40.0, 41.0, 42.0, 43.0, 44.0).map { it to 100 - (it - 42.3) * (it - 42.3) }
        assertEquals(42.3, CameraFocus.peak(samples), 1e-6)
        assertTrue(!CameraFocus.atEdge(samples))
        assertTrue(CameraFocus.atEdge(samples.take(2)))
    }
}
