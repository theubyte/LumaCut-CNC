package de.millione.lumacut.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class MatcalTest {
    private fun status(calibration: String) = """{"connected":true,"homed":true,"features":["material_calibration"],
        "material_calibration":$calibration}"""

    @Test fun `engraving summary from the status gives the tones found`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody(status("""{"kind":"engrave","material":"Sperrholz","state":"complete","steps":7,
                "last":{"target":"hell","power":7.3,"speed":4500.0,"tone":0.259,"clean":true,"uneven":0.05},
                "result":{"dunkel":{"power":12.8,"speed":4500.0,"tone":0.92,"approximate":false},
                          "mittel":{"power":8.8,"speed":4500.0,"tone":0.504,"approximate":false},
                          "hell":{"power":7.3,"speed":4500.0,"tone":0.259,"approximate":true}},
                "saved":[{"id":"a","name":"Sperrholz","process":"Gravieren"}],"error":""}""")))
            start()
        }
        val s = PiClient("127.0.0.1", srv.port).status().material_calibration!!
        assertEquals("engrave", s.kind)
        assertEquals("Feld 7: 7,3 % · 4500 mm/min → Ton 0,26 · sauber (Ziel hell)", Matcal.lastStep(s))
        assertEquals(listOf("Dunkel: 12,8 % · 4500 mm/min (Ton 0,92)", "Mittel: 8,8 % · 4500 mm/min (Ton 0,50)",
            "Hell: 7,3 % · 4500 mm/min (Ton 0,26) – nur ungefähr"), Matcal.results(s))
        assertEquals("Sperrholz", s.saved.single().name)
        srv.shutdown()
    }

    @Test fun `cutting summary names the setting with the least energy`() = runBlocking {
        val srv = MockWebServer().apply {
            enqueue(MockResponse().setBody(status("""{"kind":"cut","material":"Sperrholz","state":"running","steps":3,
                "last":{"square":1,"speed":500.0,"power":100.0,"pass":1,"ratio":0.001,"fell":true},
                "result":{"squares":[{"speed":350.0,"passes":2,"fell":true},{"speed":1200.0,"passes":7,"fell":false}],
                          "best":{"speed":350.0,"passes":2,"fell":true}}}""")))
            start()
        }
        val s = PiClient("127.0.0.1", srv.port).status().material_calibration!!
        assertEquals("500 mm/min, Durchgang 2: durchgefallen", Matcal.lastStep(s))
        assertEquals(listOf("350 mm/min: 2 Durchgänge", "1200 mm/min: nach 7 nicht durch", "Gespeichert: 350 mm/min × 2 (wenigste Energie)"),
            Matcal.results(s))
        srv.shutdown()
    }

    @Test fun `older Pi without the feature has no summary`() = runBlocking {
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody("""{"connected":true}""")); start() }
        assertEquals(null, PiClient("127.0.0.1", srv.port).status().material_calibration)
        srv.shutdown()
    }

    @Test fun `start sends the area corner in machine mm`() = runBlocking {
        val srv = MockWebServer().apply { enqueue(MockResponse().setBody("""{"message":"ok"}""")); start() }
        PiClient("127.0.0.1", srv.port).materialCalibration("cut", 150.0, 120.5, " Sperrholz ", 4.0, raised = true)
        val body = srv.takeRequest().body.readUtf8()
        assertEquals("op=matcal&kind=cut&x=150.00&y=120.50&name=Sperrholz&thickness=4.00&raised=1", body)
        assertEquals(Box(147.0, 120.0, 198.0, 141.0), Matcal.area("engrave", 150.0, 120.0))
        assertTrue(Matcal.area("cut", 150.0, 120.0).width == Matcal.CUT_W)
        srv.shutdown()
    }
}
