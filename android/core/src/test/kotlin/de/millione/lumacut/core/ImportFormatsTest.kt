package de.millione.lumacut.core

import java.util.Base64
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ImportFormatsTest {
    private fun kind(text: String) = FileKinds.detect(text.toByteArray())

    @Test fun `type is recognised from the content`() {
        assertEquals(FileKind.SVG, kind("<?xml version=\"1.0\"?>\n<svg xmlns=\"http://www.w3.org/2000/svg\"/>"))
        assertEquals(FileKind.LBRN, kind("<?xml version=\"1.0\" encoding=\"UTF-8\"?><LightBurnProject AppVersion=\"1.4\"></LightBurnProject>"))
        assertEquals(FileKind.XCS, kind("""{"canvas":[{"id":"1","displays":[]}],"device":{}}"""))
        assertEquals(FileKind.PROJECT, kind("""{"title":"Neues Projekt","layers":[],"elements":[]}"""))
        assertEquals(FileKind.DXF, kind("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"))
        assertEquals(FileKind.DXF, kind("  0\r\nSECTION\r\n  2\r\nHEADER\r\n"))
        assertEquals(FileKind.HPGL, kind("IN;SP1;PU0,0;PD400,0;"))
        assertEquals(FileKind.PDF, kind("%PDF-1.5\n1 0 obj"))
        assertEquals(FileKind.IMAGE, FileKinds.detect(byteArrayOf(0x89.toByte(), 'P'.code.toByte(), 'N'.code.toByte(), 'G'.code.toByte(), 13, 10)))
        assertEquals(FileKind.IMAGE, FileKinds.detect(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte(), 0, 0)))
        assertEquals(FileKind.IMAGE, FileKinds.detect("RIFF\u0000\u0000\u0000\u0000WEBPVP8 ".toByteArray(Charsets.ISO_8859_1)))
        assertEquals(FileKind.IMAGE, FileKinds.detect("\u0000\u0000\u0000\u0018ftypheic\u0000\u0000\u0000\u0000".toByteArray(Charsets.ISO_8859_1)))
        assertEquals(FileKind.UNKNOWN, kind("das ist nur Text ohne Format"))
    }

    @Test fun `hpgl uses 40 units per mm and points down`() {
        val polys = ImportFormats.parseVector(FileKind.HPGL, "IN;SP1;PU0,0;PD400,0,400,800,0,800,0,0;PU;".toByteArray()).polys
        assertEquals(1, polys.size)
        val b = boundsOf(polys)!!
        assertEquals(10.0, b.width, 1e-9); assertEquals(20.0, b.height, 1e-9)
        assertEquals(0.0, b.minX, 1e-9); assertEquals(0.0, b.minY, 1e-9)
        assertTrue(polys[0].isClosed())
        // a second stroke after a pen-up move is a separate line
        assertEquals(2, Hpgl.parse("IN;PU0,0;PD40,0;PU80,0;PD120,0;".toByteArray()).size)
        assertFailsWith<ImportException> { Hpgl.parse("IN;SP1;".toByteArray()) }
    }

    @Test fun `lightburn rect, ellipse and path with bezier and xform`() {
        val xml = """<?xml version="1.0" encoding="UTF-8"?>
            <LightBurnProject AppVersion="1.4.00" FormatVersion="1">
              <CutSetting type="Cut"><index Value="0"/></CutSetting>
              <Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="0"><XForm>1 0 0 1 100 50</XForm></Shape>
              <Shape Type="Ellipse" CutIndex="0" Rx="10" Ry="10"><XForm>1 0 0 1 200 50</XForm></Shape>
              <Shape Type="Path" CutIndex="0"><XForm>1 0 0 1 0 0</XForm>
                <VertList>V0 0c0x0c0y0c1x0c1y10V10 10c0x0c0y10c1x10c1y10</VertList>
                <PrimList>B0 1L1 0</PrimList></Shape>
              <Shape Type="Group"><XForm>1 0 0 1 10 0</XForm><Children>
                <Shape Type="Rect" W="10" H="10"><XForm>1 0 0 1 5 5</XForm></Shape></Children></Shape>
              <Shape Type="Text" CutIndex="0"><XForm>1 0 0 1 0 0</XForm></Shape>
            </LightBurnProject>"""
        val r = ImportFormats.parseVector(FileKind.LBRN, xml.toByteArray())
        assertEquals(4, r.polys.size)
        val rect = boundsOf(listOf(r.polys[0]))!!
        assertEquals(Box(80.0, 40.0, 120.0, 60.0), rect)               // centred on the XForm origin
        val circle = boundsOf(listOf(r.polys[1]))!!
        assertEquals(20.0, circle.width, 0.01); assertEquals(200.0, circle.center.x, 0.01)
        val path = boundsOf(listOf(r.polys[2]))!!
        assertEquals(0.0, path.minX, 1e-6); assertEquals(10.0, path.maxX, 1e-6)
        assertTrue(r.polys[2].size > 5, "bezier flattened")
        assertEquals(Box(10.0, 0.0, 20.0, 10.0), boundsOf(listOf(r.polys[3])))   // group transform applied
        assertEquals("Übersprungen: 1× Text (in Pfade bzw. Bild umwandeln)", r.skippedSentence())
    }

    @Test fun `lightburn bitmap becomes an embedded image`() {
        val png = Base64.getEncoder().encodeToString(ByteArray(40) { it.toByte() })
        val xml = """<LightBurnProject><Shape Type="Bitmap" W="30" H="20" Data="$png"><XForm>1 0 0 1 50 40</XForm></Shape>
            <Shape Type="Rect" W="1" H="1"><XForm>1 0 0 1 0 0</XForm></Shape></LightBurnProject>"""
        val r = Lbrn.parse(xml.toByteArray())
        assertEquals(1, r.images.size)
        assertEquals(Box(35.0, 30.0, 65.0, 50.0), r.images[0].box)
        assertEquals(40, r.images[0].bytes.size)
    }

    @Test fun `xcs paths, rect, circle, bitmap, text skipped`() {
        val png = Base64.getEncoder().encodeToString(ByteArray(64) { 7 })
        val json = """{"canvas":[{"id":"c1","displays":[
            {"id":"a","type":"PATH","x":10,"y":10,"graphicX":10,"graphicY":10,"width":20,"height":10,"dPath":"M0 0L20 0L20 10L0 10Z"},
            {"id":"b","type":"RECT","x":50,"y":10,"width":10,"height":5},
            {"id":"c","type":"CIRCLE","x":70,"y":10,"width":8,"height":8},
            {"id":"d","type":"BITMAP","x":0,"y":30,"width":15,"height":15,"base64":"data:image/png;base64,$png"},
            {"id":"e","type":"TEXT","x":0,"y":0,"width":30,"height":10,"text":"Hallo"}]}],"device":{}}"""
        val r = ImportFormats.parseVector(FileKind.XCS, json.toByteArray())
        assertEquals(3, r.polys.size)
        assertEquals(Box(10.0, 10.0, 30.0, 20.0), boundsOf(listOf(r.polys[0])))
        assertEquals(Box(50.0, 10.0, 60.0, 15.0), boundsOf(listOf(r.polys[1])))
        assertEquals(8.0, boundsOf(listOf(r.polys[2]))!!.width, 1e-6)
        assertEquals(1, r.images.size); assertEquals(Box(0.0, 30.0, 15.0, 45.0), r.images[0].box)
        assertEquals(listOf("1× Text"), r.skipped)
        assertFailsWith<ImportException> { Xcs.parse("""{"canvas":[{"displays":[{"type":"TEXT","width":3,"height":3}]}]}""".toByteArray()) }
        assertFailsWith<ImportException> { Xcs.parse("kein json".toByteArray()) }
    }

    @Test fun `unknown vector kind is refused with a sentence`() {
        assertEquals("Dieses Format wird nicht als Vektor gelesen",
            assertFailsWith<ImportException> { ImportFormats.parseVector(FileKind.UNKNOWN, ByteArray(10)) }.message)
    }
}
