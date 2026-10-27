package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class CalibrationsTest {
    private val w = 800
    private val h = 600
    private val pxPerMm = 12.0

    /** Undistorted camera looking straight down, [pxPerMm], picture centre = head + [centre]. */
    private fun camera(centre: Pt = Pt(0.0, 0.0)): CameraCalibration {
        val hw = w / pxPerMm / 2; val hh = h / pxPerMm / 2
        return CameraCalibration(w, h, photo = listOf(Pt(0.0, 0.0), Pt(w.toDouble(), 0.0), Pt(w.toDouble(), h.toDouble()), Pt(0.0, h.toDouble())),
            relMm = listOf(Pt(centre.x - hw, centre.y - hh), Pt(centre.x + hw, centre.y - hh), Pt(centre.x + hw, centre.y + hh), Pt(centre.x - hw, centre.y + hh)), scanZ = 30.0)
    }

    /** Grey photo of [shade] (0..1 darkness at a work point), 3 × 3 supersampled, a little noise. */
    private fun photo(cal: CameraCalibration, head: Pt, light: Double = 200.0, seed: Int = 1, shade: (Pt) -> Double): IntArray {
        val rnd = Random(seed)
        return IntArray(w * h) { k ->
            val x = k % w; val y = k / w
            var d = 0.0
            for (sy in 0..2) for (sx in 0..2) d += shade(cal.pixelToWork(Pt(x + (sx + 0.5) / 3, y + (sy + 0.5) / 3), head))
            val v = (light * (1 - d / 9) + rnd.nextInt(-3, 4)).roundToInt().coerceIn(0, 255)
            (0xFF shl 24) or (v shl 16) or (v shl 8) or v
        }
    }

    @Test fun `flat field from shifted photos of a white sheet evens out the edges`() {
        // vignetting: 45 % darker in the corners, a little bluer at the left; some marks on the sheet
        fun vign(x: Int, y: Int) = 1 - 0.45 * (((x - w / 2.0) / (w / 2.0)).let { it * it } + ((y - h / 2.0) / (h / 2.0)).let { it * it }) / 2
        val photos = (0 until 5).map { n ->
            val rnd = Random(n)
            val spot = Pt(rnd.nextDouble(100.0, 700.0), rnd.nextDouble(100.0, 500.0))
            IntArray(w * h) { k ->
                val x = k % w; val y = k / w
                val mark = if (Pt(x.toDouble(), y.toDouble()).dist(spot) < 25) 0.5 else 1.0
                val v = vign(x, y) * mark * (180 + n * 10)                // the camera's own brightness varies
                val r = (v).roundToInt().coerceIn(0, 255); val b = (v * (1.0 + 0.1 * (1 - x.toDouble() / w))).roundToInt().coerceIn(0, 255)
                (0xFF shl 24) or (r shl 16) or (r shl 8) or b
            }
        }
        val s = Shading.measure(photos, w, h)
        for ((x, y) in listOf(10 to 10, 400 to 300, 790 to 590, 50 to 300)) {
            val c = s.correct(photos[0][y * w + x], (x + 0.5) / w, (y + 0.5) / h)
            assertEquals(180.0, ((c shr 16) and 255).toDouble(), 9.0, "red at $x,$y")
            assertEquals(((photos[0][300 * w + 400]) and 255).toDouble(), (c and 255).toDouble(), 10.0, "blue at $x,$y")
        }
    }

    @Test fun `white balance search finds the neutral setting`() = runBlocking {
        var shots = 0
        val wb = CameraLight.whiteBalance(2500..7000) { k -> shots++; ln(k / 4630.0) * 0.8 }
        assertEquals(4630.0, wb.toDouble(), 60.0)
        assertTrue(shots <= 8, "$shots pictures")
        // no sign change: the end with the smaller cast
        assertEquals(7000, CameraLight.whiteBalance(2500..7000) { k -> -1.0 + k / 10000.0 })
    }

    @Test fun `tint of a warm white sheet is positive`() {
        val px = IntArray(100 * 80) { (0xFF shl 24) or (220 shl 16) or (200 shl 8) or 170 }
        assertTrue(CameraLight.tint(px, 100, 80) > 0.2)
    }

    @Test fun `mosaic matches the brightness of overlapping tiles and leaves no seam`() {
        val cal = camera()
        val wood = { p: Pt -> 0.15 + 0.1 * kotlin.math.sin(p.x / 3.0) * kotlin.math.sin(p.y / 5.0) }
        val a = Pt(100.0, 100.0); val b = Pt(130.0, 100.0)          // 30 mm apart, field 66 mm: half overlaps
        val m = Scan.Mosaic(cal, 4.0)
        m.add(Scan.Tile(photo(cal, a, 200.0, 1, wood), w, h, a))
        m.add(Scan.Tile(photo(cal, b, 150.0, 2, wood), w, h, b))  // the camera made this one darker
        assertEquals(200.0 / 150.0, m.lastGain[0], 0.03)
        fun lum(x: Double, y: Double) = (m.pixels[(y * 4).toInt() * m.width + (x * 4).toInt()] shr 16) and 255
        // across the whole overlap the result equals the first tile's brightness
        for (x in listOf(85.0, 100.0, 115.0, 130.0, 145.0)) {
            val expect = 200 * (1 - wood(Pt(x + 0.125, 100.125)))
            assertEquals(expect, lum(x, 100.0).toDouble(), 5.0, "x $x")
        }
    }

    @Test fun `mosaic applies the flat field`() {
        val half = List(4 * 4 * 3) { k -> if ((k / 3) % 4 < 2) 2.0f else 1.0f }   // left half twice as bright after correction
        val cal = camera().copy(shading = Shading(4, 4, half))
        val tile = Scan.Tile(IntArray(w * h) { (0xFF shl 24) or (100 shl 16) or (100 shl 8) or 100 }, w, h, Pt(100.0, 100.0))
        val m = Scan.Mosaic(cal, 2.0); m.add(tile)
        fun r(x: Double) = (m.pixels[(100 * 2) * m.width + (x * 2).toInt()] shr 16) and 255
        assertEquals(200, r(75.0)); assertEquals(100, r(125.0))
    }

    @Test fun `focus test finds the narrowest line`() {
        val gap = 5.5
        val offsets = FocusTest.offsets(gap)
        assertEquals(-3.0, offsets.first()); assertEquals(3.0, offsets.last())
        assertTrue(FocusTest.offsets(4.0).first() >= -1.8)
        val trueFocus = 0.8
        fun width(off: Double) = 0.18 + 0.22 * abs(off - trueFocus)
        val centre = Work.center
        val cal = camera()
        val shade = { p: Pt ->
            var d = 0.0
            for ((k, off) in offsets.withIndex()) {
                val (a, b) = FocusTest.line(k, offsets.size, centre)
                if (p.y < a.y || p.y > b.y) continue
                val wd = width(off)
                val dist = abs(p.x - a.x)
                if (dist < wd / 2) d = 0.7 * (0.18 / wd).coerceAtMost(1.0) + 0.1
            }
            d
        }
        val px = photo(cal, centre, shade = shade)
        val r = FocusTest.evaluate(PhotoSampler(px, w, h, cal, centre), offsets, centre)
        assertEquals(trueFocus, r.bestOffset, 0.3)
        assertEquals(width(r.bestOffset), r.widthAtBest, 0.1)
        assertTrue(r.lines.all { !it.widthMm.isNaN() })
    }

    @Test fun `focus job moves Z relative between the lines and returns`() {
        val g = FocusTest.job(listOf(-1.0, 0.0, 1.0), 30.0, 1000.0)
        val lines = g.lines()
        assertTrue("G0 Z-1.000 F600" in lines && "G0 Z1.000 F600" in lines)
        assertEquals("G0 Z-1.000 F600", lines[lines.lastIndexOf("G91") + 1])
        assertEquals(3, lines.count { it.startsWith("G1 ") && it.endsWith(" S77") })
        assertTrue(lines.indexOfFirst { it.startsWith("G0 X") } < lines.indexOfFirst { it.startsWith("G1 ") })
    }

    @Test fun `engraving test measures tone and halo and picks the fastest clean setting`() {
        val spec = EngraveTest.Spec()
        fun tone(p: Double, s: Double) = (1 - exp(-p / s * 60)).coerceAtMost(0.95)
        val cal = camera()
        val centre = spec.centre
        val shade = { q: Pt ->
            var d = 0.0
            for (i in spec.powers.indices) for (j in spec.speeds.indices) {
                val b = spec.cell(i, j)
                val t = tone(spec.powers[i], spec.speeds[j])
                val out = maxOf(b.minX - q.x, q.x - b.maxX, b.minY - q.y, q.y - b.maxY)
                if (out <= 0) d = maxOf(d, t)
                else if (t > 0.85 && out < 0.8) d = maxOf(d, 0.25)      // smoke ring around charred squares
            }
            d
        }
        val px = photo(cal, centre, shade = shade)
        val sampler = PhotoSampler(px, w, h, cal, centre)
        val fields = spec.powers.indices.flatMap { i -> spec.speeds.indices.mapNotNull { j -> EngraveTest.measure(spec, i, j, sampler) } }
        assertEquals(25, fields.size)
        for (f in fields) assertEquals(tone(f.power, f.speed), f.tone, 0.05, "${f.power} % ${f.speed}")
        val charred = fields.filter { tone(it.power, it.speed) > 0.85 }
        assertTrue(charred.isNotEmpty() && charred.all { it.charred })
        val pick = assertNotNull(EngraveTest.pick(fields, EngraveTest.Tone.MEDIUM))
        assertTrue(abs(pick.tone - 0.5) <= 0.08 && pick.clean)
        assertTrue(fields.filter { it.clean && abs(it.tone - 0.5) <= 0.08 }.all { it.speed <= pick.speed })
    }

    @Test fun `engraving photos cover every square`() {
        val spec = EngraveTest.Spec(powers = (1..8).map { it * 10.0 }, speeds = (1..8).map { it * 700.0 })
        val cal = camera()
        val heads = EngraveTest.photos(spec, cal)
        val u = cal.usable(0.1)
        for (i in spec.powers.indices) for (j in spec.speeds.indices) {
            val b = spec.cell(i, j)
            assertTrue(heads.any { hd -> b.minX - 1.5 >= hd.x + u.minX && b.maxX + 1.5 <= hd.x + u.maxX && b.minY - 1.5 >= hd.y + u.minY && b.maxY + 1.5 <= hd.y + u.maxY },
                "square $i,$j not fully in a photo")
        }
        val job = EngraveTest.job(spec)
        assertTrue(job.contains("G1 ") && job.contains("; Ebene 10 % · 700 mm/min"))
    }

    @Test fun `camera settings go to the Pi with nulls and come back with ranges`() = runBlocking {
        okhttp3.mockwebserver.MockWebServer().use { srv ->
            srv.enqueue(okhttp3.mockwebserver.MockResponse().setBody("""{"message":"Kamera-Einstellungen gespeichert"}"""))
            srv.enqueue(okhttp3.mockwebserver.MockResponse().setBody("""{"exposure":null,"gain":null,"white_balance":4700,"light":100,"ranges":{"white_balance":[2500,7000]}}"""))
            srv.enqueue(okhttp3.mockwebserver.MockResponse().setBody(okio.Buffer().write(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0, 0))))
            srv.start()
            val pi = PiClient("127.0.0.1", srv.port)
            pi.saveCameraSettings(CameraSettings(white_balance = 4700, light = 100))
            val put = srv.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("""{"exposure":null,"gain":null,"white_balance":4700,"light":100}""", put.body.readUtf8())
            val s = pi.cameraSettings()
            assertEquals("/api/camera/settings", srv.takeRequest().path)
            assertEquals(4700, s.white_balance); assertEquals(2500..7000, s.range("white_balance", 0..1)); assertEquals(0..9, s.range("gain", 0..9))
            pi.cameraSnapshot(1920, 1080, whiteBalance = 0)
            assertEquals("/api/camera/snapshot?w=1920&h=1080&wb=auto", srv.takeRequest().path)
        }
    }

    @Test fun `status carries the fixed camera values`() {
        val s = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }.decodeFromString(MachineStatus.serializer(),
            """{"config":{"focus_gap_mm":7.0,"camera":{"exposure":null,"gain":null,"white_balance":5200,"light":100}}}""")
        assertEquals(5200, s.config.camera?.white_balance)
    }

    @Test fun `fill run-up is long enough for the speed with the machine's acceleration`() {
        val layer = Layer(name = "Gravur", color = 0xFF4FD8B4, mode = LayerMode.FILL, powerPct = 30.0, speed = 6000.0, intervalMm = 1.0)
        val doc = Document("t", listOf(layer), listOf(Element(layerId = layer.id, kind = "r", transform = Transform(100.0, 100.0), paths = listOf(Shapes.rect(10.0, 3.0)))))
        fun firstRunUp(motion: MarlinWriter.Motion): Double {
            val lines = MarlinWriter("t", motion).write(doc).lines()
            val rapid = lines.first { it.startsWith("G0 X") }
            val runUp = lines[lines.indexOf(rapid) + 1]
            fun x(l: String) = Regex("X([-0-9.]+)").find(l)!!.groupValues[1].toDouble()
            assertTrue(runUp.endsWith(" S0"), runUp)
            return abs(x(runUp) - x(rapid))
        }
        assertEquals(100.0 * 100.0 / (2 * 500) * 1.15 + 0.3, firstRunUp(MarlinWriter.Motion.FIRMWARE), 0.01)  // 11.8 mm at 500 mm/s²
        assertEquals(2.5, firstRunUp(MarlinWriter.Motion(5000.0, 250.0)), 0.01)                            // the layer's own 2.5 mm is enough
        val e = runCatching { MarlinWriter("t", MarlinWriter.Motion(3000.0, 80.0)).write(doc) }.exceptionOrNull()
        assertTrue(e is JobBuildException && e.message!!.contains("4800"), e.toString())
    }

    @Test fun `motion test finds the level where a step was lost`() {
        val n = MotionTest.LEVELS.size + 1
        // true shift of each check mark: baseline 0.04 (backlash), lost 0.3 mm in X at level 3 (index 3 → glyph 4)
        val truth = listOf(0.04, 0.04, 0.05, 0.04, 0.34, 0.34, 0.35)
        val centre = Work.center
        val cal = camera()
        val shade = { p: Pt ->
            var d = 0.0
            for (k in 0 until n) {
                val ref = MotionTest.reference(k, n, centre)
                val chk = MotionTest.check(k, n, centre).map { path -> path.map { it + Pt(truth[k], -truth[k] / 2) } }
                for (seg in ref + chk) {
                    val a = seg[0]; val b = seg[1]
                    val near = if (a.x == b.x) abs(p.x - a.x) < 0.1 && p.y in a.y..b.y else abs(p.y - a.y) < 0.1 && p.x in a.x..b.x
                    if (near) d = 0.6
                }
            }
            d
        }
        val px = photo(cal, MotionTest.bounds(n, centre).center, shade = shade)
        val sampler = PhotoSampler(px, w, h, cal, MotionTest.bounds(n, centre).center)
        val shifts = (0 until n).map { MotionTest.measure(sampler, it, n, centre) }
        for (k in 0 until n) {
            assertEquals(truth[k], shifts[k].dx, 0.03, "dx $k"); assertEquals(-truth[k] / 2, shifts[k].dy, 0.03, "dy $k")
        }
        assertEquals(2, MotionTest.lastGood(shifts))      // levels 0, 1, 2 held, level 3 lost steps
        val keep = MotionTest.recommend(MotionTest.LEVELS[2])
        assertEquals(2100.0, keep.accel); assertEquals(200.0, keep.speed)
        assertTrue(MotionTest.job("Referenz", (0 until n).flatMap { MotionTest.reference(it, n, centre) }).contains("G1 "))
    }

    @Test fun `cut test picks the quickest square with reserve`() {
        val spec = CutTest.Spec(thicknessMm = 3.0)
        assertEquals(1.0, spec.zStep)
        // columns = speeds 150 … 600, rows = 1, 2, 3 passes
        val through = setOf(0 to 0, 0 to 1, 1 to 1, 2 to 1, 3 to 1, 0 to 2, 1 to 2, 2 to 2, 3 to 2, 4 to 2)
        val p = assertNotNull(CutTest.pick(spec, through))
        // quickest: 2 passes at 450 (2/450) – reserve: 2 passes at 350 (2/350 ≥ 1.15 × 2/450) is the next one
        assertEquals(350.0, p.speed); assertEquals(2, p.passes); assertTrue(p.reserve); assertTrue(!p.inconsistent)
        assertTrue(CutTest.pick(spec, setOf(2 to 0)).let { it != null && it.inconsistent })
        assertEquals(null, CutTest.pick(spec, emptySet()))
        val job = CutTest.job(spec).lines()
        assertTrue("G0 Z-1.000 F600" in job)
        assertEquals(15, job.count { it.startsWith("; Ebene 100 %") })
    }

    @Test fun `motion limits go to the Pi and come back in the status`() = runBlocking {
        okhttp3.mockwebserver.MockWebServer().use { srv ->
            repeat(3) { srv.enqueue(okhttp3.mockwebserver.MockResponse().setBody("""{"message":"ok"}""")) }
            srv.start()
            val pi = PiClient("127.0.0.1", srv.port)
            pi.motionTest(3000.0, 250.0, 195.0, 200.0, 40.0, 6)
            assertEquals("op=motion_test&accel=3000&speed=250&x=195.000&y=200.000&span=40.0&cycles=6", srv.takeRequest().body.readUtf8())
            pi.motionLimits(MarlinWriter.Motion(2100.0, 200.0))
            assertEquals("op=motion_limits&accel=2100&speed=200", srv.takeRequest().body.readUtf8())
            pi.motionLimits(null)
            assertEquals("op=motion_limits&accel=&speed=", srv.takeRequest().body.readUtf8())
        }
        val s = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }.decodeFromString(MachineStatus.serializer(),
            """{"config":{"motion":{"accel":2100.0,"speed":200.0}}}""")
        assertEquals(MarlinWriter.Motion(2100.0, 200.0), s.config.motion?.toMotion())
        assertEquals(MarlinWriter.Motion.FIRMWARE, PiMotion().toMotion())
    }

    @Test fun `part scan photographs only the area and keeps the earlier scan around it`() {
        val cal = camera()
        val u = cal.usable()
        // a small area: one picture centred on it
        val small = Box(150.0, 120.0, 170.0, 140.0)
        val one = Scan.plan(cal, small)
        assertEquals(1, one.heads.size)
        assertEquals(small.center.x, one.heads[0].x + u.center.x, 0.01); assertEquals(small.center.y, one.heads[0].y + u.center.y, 0.01)
        // a larger area: covered completely, far fewer pictures than the whole work area
        val area = Box(40.0, 60.0, 200.0, 150.0)
        val plan = Scan.plan(cal, area)
        assertTrue(plan.uncovered.isEmpty(), plan.uncovered.toString())
        assertTrue(plan.heads.size < Scan.plan(cal).heads.size)
        for (x in listOf(40.0, 120.0, 200.0)) for (y in listOf(60.0, 100.0, 150.0))
            assertTrue(plan.heads.any { h -> x >= h.x + u.minX - 1e-6 && x <= h.x + u.maxX + 1e-6 && y >= h.y + u.minY - 1e-6 && y <= h.y + u.maxY + 1e-6 }, "$x,$y")
        // two marked workpieces: the pictures of both
        assertEquals(2, Scan.plan(cal, listOf(small, Box(300.0, 280.0, 320.0, 300.0))).heads.size)
        // the earlier scan stays outside the new pictures
        val m0 = Scan.Mosaic(cal, 2.0)
        val old = IntArray(m0.width * m0.height) { 0xFF112233.toInt() }
        val m = Scan.Mosaic(cal, 2.0, old)
        m.add(Scan.Tile(IntArray(w * h) { 0xFFC8C8C8.toInt() }, w, h, one.heads[0]))
        assertEquals(0xFF112233.toInt(), m.pixels[10 * m.width + 10])
        assertEquals(0xFFC8C8C8.toInt(), m.pixels[(130 * 2) * m.width + 160 * 2])
        assertEquals(0xFF112233.toInt(), old[(130 * 2) * m.width + 160 * 2], "base itself unchanged")
    }

    @Test fun `status says why the reference was lost`() {
        val json = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
        val s = json.decodeFromString(MachineStatus.serializer(),
            """{"homed":false,"reference":{"switch_check":true,"lost":"Kopf steht nicht mehr am Nullpunkt (Endschalter X offen)"}}""")
        assertEquals(true, s.reference.switch_check); assertTrue(s.reference.lost.contains("Endschalter X"))
        assertEquals(ReferenceInfo(), json.decodeFromString(MachineStatus.serializer(), "{}").reference)   // older Pi
    }

    @Test fun `probe offset from the head position over the mark`() {
        val off = Pt(-23.0, 15.0)
        val head = ProbeTarget.headFor(off)
        assertEquals(off, ProbeTarget.offset(head))
        assertTrue(ProbeTarget.job().contains("S64"))
    }
}
