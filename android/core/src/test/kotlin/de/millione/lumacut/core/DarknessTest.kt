package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DarknessTest {
    /** Poplar plywood 4 mm, 10 W (docs/MATERIAL_KALIBRIERUNG.md). */
    private val plywood = DarknessCurve(listOf(
        DarknessPoint(4.5, 3000.0, 0.34), DarknessPoint(6.0, 3000.0, 0.53), DarknessPoint(7.7, 3000.0, 0.79),
        DarknessPoint(8.5, 3000.0, 0.87), DarknessPoint(10.6, 3000.0, 0.98), DarknessPoint(12.8, 4500.0, 0.92),
        DarknessPoint(14.0, 6000.0, 0.79, clean = false)))
    private val dark = Layer(name = "Gravieren", color = 0, mode = LayerMode.FILL, powerPct = 12.8, speed = 4500.0, darkness = plywood)

    @Test fun `curve never falls and inverts`() {
        assertTrue(plywood.usable)
        assertEquals(0.87, plywood.tone(8.5 / 3000), 1e-9)
        assertEquals(8.5 / 3000, plywood.energyFor(0.87), 1e-9)
        // the streaky 14 % @ 6000 (0.79) has less energy than 7.7 % @ 3000 (0.79): the curve stays flat, never falls
        assertEquals(0.79, plywood.tone(7.5 / 3000), 1e-9)
        assertTrue(plywood.tone(12.8 / 4500) in 0.87..0.98)
        assertEquals(0.98, plywood.tone(1.0))
        assertEquals(0.34, plywood.tone(1e-6))
    }

    @Test fun `slower keeps the tone and stops at the firing limit`() {
        val slower = Darkness.atSpeed(dark, 3000.0, 6000.0)
        assertNull(slower.limit)
        assertEquals(12.8 * 3000 / 4500, slower.layer.powerPct, 1e-9)
        assertEquals(Darkness.tone(dark)!!, Darkness.tone(slower.layer)!!, 1e-9)
        val tooSlow = Darkness.atSpeed(dark, 1000.0, 6000.0)
        assertEquals(8.0, tooSlow.layer.powerPct, 1e-9)
        assertEquals(4500 * 8 / 12.8, tooSlow.layer.speed, 1e-9)
        assertTrue(tooSlow.limit!!.contains("zündet unter 8 %"))
        val range = Darkness.speedRange(dark, 6000.0)
        assertEquals(0.0, Darkness.speedPosition(tooSlow.layer, 6000.0), 1e-9)
        assertEquals(range.endInclusive, Darkness.speedAt(dark, 1.0, 6000.0), 1e-6)
    }

    @Test fun `lines slide too, without a curve`() {
        val line = Layer(name = "Linie", color = 0, mode = LayerMode.LINE, powerPct = 40.0, speed = 1500.0)
        assertNull(Darkness.tone(line))
        val r = Darkness.atSpeed(line, 600.0, 6000.0)
        assertEquals(16.0, r.layer.powerPct, 1e-9)
        assertEquals(3750.0, Darkness.speedRange(line, 6000.0).endInclusive, 1e-9)    // 100 %
        assertEquals("Für diese Ebene gibt es keine Schwärze-Kurve.", Darkness.atTone(line, 0.5, 6000.0).limit)
    }

    @Test fun `lighter goes faster instead of below the firing power`() {
        val mid = Darkness.atTone(dark.copy(speed = 3000.0, powerPct = 8.5), 0.53, 6000.0)
        assertEquals(8.0, mid.layer.powerPct, 1e-9)
        assertEquals(4000.0, mid.layer.speed, 1e-6)
        assertNull(mid.limit)
        val darker = Darkness.atTone(dark.copy(speed = 3000.0), 0.87, 6000.0)
        assertEquals(8.5, darker.layer.powerPct, 1e-9)
        assertEquals(3000.0, darker.layer.speed, 1e-9)
        // closer lines overlap: half the interval, half the energy per mm
        val fine = Darkness.atTone(dark.copy(speed = 3000.0, intervalMm = 0.05), 0.87, 9000.0)
        assertEquals(8.5 / 2 / 3000, fine.layer.powerPct / fine.layer.speed, 1e-9)
        val tooLight = Darkness.atTone(dark, 0.34, 4000.0)
        assertTrue(tooLight.limit!!.startsWith("Heller geht nicht"))
    }

    @Test fun `curve comes from the Pi and goes back only when set`() = runBlocking {
        val body = """{"revision":3,"materials":[{"id":"s","name":"Sperrholz","thickness_mm":4.0,"process":"Gravieren","mode":"fill",
            "power_pct":12.8,"speed_mm_min":4500.0,"tone_curve":{"points":[{"power":6.0,"speed":3000,"tone":0.53},
            {"power":8.5,"speed":3000,"tone":0.87,"clean":true}],"min_power_pct":8.0,"interval_mm":0.1,"speed_min":1500.0,"speed_max":6000.0}},
            {"id":"c","name":"Sperrholz","thickness_mm":4.0,"process":"Schneiden","mode":"line","power_pct":100.0,"speed_mm_min":500.0}]}"""
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody(body))
            repeat(2) { enqueue(MockResponse().setBody("""{"revision":4,"material":{"id":"x","name":"x","thickness_mm":4,"power_pct":1,"speed_mm_min":1}}""")) }
            start()
        }
        val pi = PiClient("127.0.0.1", srv.port)
        val (engrave, cut) = pi.materials().materials.map { it.toMaterial() }
        val curve = assertNotNull(engrave.darkness)
        assertEquals(2, curve.points.size); assertEquals(8.0, curve.minPowerPct)
        assertNull(cut.darkness)
        val layer = engrave.applyTo(Layer(name = "Gravieren", color = 0))
        assertEquals(curve, layer.darkness)
        srv.takeRequest()
        pi.updateMaterial(engrave, 3)
        assertTrue(srv.takeRequest().body.readUtf8().contains("\"tone_curve\":{\"points\""))
        pi.updateMaterial(cut, 3)
        assertFalse(srv.takeRequest().body.readUtf8().contains("tone_curve"))
        srv.shutdown()
    }
}
