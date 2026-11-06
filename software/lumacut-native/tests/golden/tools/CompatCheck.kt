// Gegenprobe: Datei von der C++-Fassung, gelesen vom echten Kotlin-Code, gleicher G-Code. Siehe tests/golden/README.md.
package de.millione.lumacut.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

class CompatCheck {
    @Test fun readsFile() {
        Bed.configure(370.0, 360.0, 78.0, 35.0)
        val doc = Document.fromJson(File("../compat/from-cpp.json").readText())
        assertEquals(5, doc.elements.size)
        assertEquals("Kompatibel Ä", doc.title)
        assertEquals("Ä\"\n", doc.elements[2].text)
        assertEquals(File("../compat/from-cpp.gcode").readText(), MarlinWriter("x").write(doc.plateView(0)))
        assertEquals(doc.elements[3].raster!!.gray().toList(), doc.elements[4].raster!!.gray().toList())
    }
}
