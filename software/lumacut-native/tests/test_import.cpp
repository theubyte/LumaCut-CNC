/**
 * Import und Export: alle Fälle aus den Android-Tests (ImportFormatsTest, SvgStructureTest, XsLayoutTest) und aus
 * src/core/import/import.test.ts, dazu Bilder mit EXIF, Park-Ecke, Platten und der Rückimport des Exports.
 */
#include "core/export.h"
#include "core/geometry.h"
#include "core/image.h"
#include "core/import/import.h"
#include "core/import/vector.h"
#include "core/import/xml.h"
#include "core/import/zip.h"

#include <QBuffer>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QImage>
#include <QImageReader>
#include <QImageWriter>
#include <QtTest>
#include <cmath>

using namespace lumacut;
using namespace lumacut::import;

// moc versteht Rohstrings nicht; was es nicht zu sehen braucht, sieht es nicht.
#ifndef Q_MOC_RUN
namespace {

/** QStringLiteral verschluckt in moc die Rohstrings. */
QString S(const char* s) { return QString::fromUtf8(s); }

QByteArray enc(const char* s) { return QByteArray(s); }
QByteArray enc(const QString& s) { return s.toUtf8(); }

bool near(double a, double b, double eps = 1e-6) { return std::fabs(a - b) <= eps; }
bool boxIs(const std::optional<Box>& b, double x0, double y0, double x1, double y1, double eps = 1e-6) {
    return b && near(b->minX, x0, eps) && near(b->minY, y0, eps) && near(b->maxX, x1, eps) && near(b->maxY, y1, eps);
}
PolySet onePoly(PolyView p) { PolySet s; s.add(p); return s; }
bool hasPoint(PolyView p, double x, double y) {
    for (const Pt& q : p) if (near(q.x, x, 1e-3) && near(q.y, y, 1e-3)) return true;
    return false;
}
QByteArray b64(int n, std::optional<int> v = {}) {
    QByteArray raw(n, 0);
    for (int i = 0; i < n; ++i) raw[i] = char(v.value_or(i));
    return raw.toBase64();
}

template <class Fn>
QString errorOf(Fn&& fn) {
    try { fn(); }
    catch (const ImportError& e) { return e.sentence(); }
    return {};
}

uint32_t crc32Of(const QByteArray& b) {
    uint32_t c = 0xFFFFFFFF;
    for (const char ch : b) {
        c ^= uint8_t(ch);
        for (int k = 0; k < 8; ++k) c = c & 1 ? 0xEDB88320 ^ (c >> 1) : c >> 1;
    }
    return c ^ 0xFFFFFFFF;
}

/** ZIP-Schreiber für die Testdateien, wahlweise mit Deflate. */
QByteArray makeZip(const std::vector<std::pair<QByteArray, QByteArray>>& files, bool deflate = false) {
    QByteArray body, central;
    const auto le16 = [](QByteArray& o, uint32_t v) { o += char(v & 255); o += char(v >> 8 & 255); };
    const auto le32 = [&](QByteArray& o, uint32_t v) { le16(o, v & 0xFFFF); le16(o, v >> 16); };
    for (const auto& [name, content] : files) {
        QByteArray data = content;
        uint32_t method = 0;
        if (deflate) {
            // qCompress: 4 Bytes Größe, 2 Bytes zlib-Kopf, rohes Deflate, 4 Bytes Adler.
            const QByteArray z = qCompress(content, 9);
            data = z.mid(6, z.size() - 10);
            method = 8;
        }
        const uint32_t offset = uint32_t(body.size());
        le32(body, 0x04034B50); le16(body, 20); le16(body, 0); le16(body, method); le32(body, 0); le32(body, 0);
        le32(body, uint32_t(data.size())); le32(body, uint32_t(content.size())); le16(body, uint32_t(name.size())); le16(body, 0);
        body += name;
        body += data;
        le32(central, 0x02014B50); le16(central, 20); le16(central, 20); le16(central, 0); le16(central, method); le32(central, 0); le32(central, 0);
        le32(central, uint32_t(data.size())); le32(central, uint32_t(content.size())); le16(central, uint32_t(name.size())); le16(central, 0); le16(central, 0);
        le16(central, 0); le16(central, 0); le32(central, 0); le32(central, offset);
        central += name;
    }
    QByteArray end;
    le32(end, 0x06054B50); le16(end, 0); le16(end, 0); le16(end, uint32_t(files.size())); le16(end, uint32_t(files.size()));
    le32(end, uint32_t(central.size())); le32(end, uint32_t(body.size())); le16(end, 0);
    return body + central + end;
}

const char* const PROJECT = R"({"activeCanvasId":"c1","modules":{"canvases":["c1"]}})";
const char* const CANVAS = R"({"id":"c1","layerData":{"#fe0002":{"name":"#FE0002","order":1,"visible":true},"#000000":{"name":"#000000","order":2,"visible":true}}})";

struct Display {
    double x, y;
    const char* d;
    double skewX = 0, localSkewX = 0;
    const char* layer = "#000000";
    bool fill = false;
    const char* groups = "[]";
    const char* scale = R"({"x":1,"y":1})";
};
QByteArray display(const Display& o) {
    return S(R"({"id":"a","type":"PATH","x":%1,"y":%2,"angle":0,"scale":%3,"skew":{"x":%4,"y":0},"localSkew":{"x":%5,"y":0},"layerTag":"%6","groupTags":%7,"fill":{"visible":%8},"stroke":{"visible":true},"dPath":"%9"})")
        .arg(o.x).arg(o.y).arg(QString::fromLatin1(o.scale)).arg(o.skewX, 0, 'f', 6).arg(o.localSkewX, 0, 'f', 6)
        .arg(QString::fromLatin1(o.layer), QString::fromLatin1(o.groups), o.fill ? QStringLiteral("true") : QStringLiteral("false"), QString::fromLatin1(o.d)).toUtf8();
}
QByteArray xs(const std::vector<QByteArray>& displays, bool deflate = false) {
    QByteArray list;
    for (const QByteArray& d : displays) { if (!list.isEmpty()) list += ','; list += d; }
    return makeZip({{".format", "v2"}, {"project.json", PROJECT}, {"canvases/c1.json", CANVAS}, {"canvases/c1/displays-0.json", "{\"displays\":[" + list + "]}"}}, deflate);
}

QByteArray svgDoc(const QString& body) {
    return (S(R"(<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">)") + body + QStringLiteral("</svg>")).toUtf8();
}
const QString SQUARE = S(R"(<rect x="10" y="10" width="10" height="10" )");
const QString OTHER = S(R"(<rect x="40" y="10" width="10" height="10" )");

QByteArray dxfDoc(const char* entities, const char* header = "") {
    return QByteArray("0\nSECTION\n2\nHEADER\n") + header + "0\nENDSEC\n0\nSECTION\n2\nENTITIES\n" + entities + "0\nENDSEC\n0\nEOF\n";
}

ImportItem rectItem(double x, double y, double w, double h, const QString& group = {}) {
    ImportItem it;
    Poly p = Shapes::rect(w, h);
    for (Pt& q : p) q = {q.x + x, q.y + y};
    it.polys.add(PolyView(p));
    it.box = *boundsOf(it.polys);
    if (!group.isEmpty()) it.groups = {group};
    return it;
}
VectorImport result(std::vector<ImportItem> items) {
    VectorImport r;
    r.items = std::move(items);
    return r;
}

ImportContext ctx() { return importContextFor(Document{}); }

QByteArray encodeImage(const QImage& img, const char* format, int quality = -1) {
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    QImageWriter w(&buf, format);
    if (quality >= 0) w.setQuality(quality);
    if (!w.write(img)) qWarning("Schreiben %s: %s", format, qPrintable(w.errorString()));
    return out;
}
/** Linke Hälfte schwarz, rechte weiß. */
QImage halfBlack(int w, int h) {
    QImage img(w, h, QImage::Format_RGB32);
    img.fill(Qt::white);
    for (int y = 0; y < h; ++y) for (int x = 0; x < w / 2; ++x) img.setPixel(x, y, qRgb(0, 0, 0));
    return img;
}
QByteArray tiffOrientationBlock(int o) {
    QByteArray t("II*\0", 4);
    t += QByteArray("\x08\0\0\0", 4);
    t += QByteArray("\x01\0", 2);
    t += QByteArray("\x12\x01\x03\0\x01\0\0\0", 8);
    t += char(o);
    t += QByteArray(3, 0);
    t += QByteArray(4, 0);
    return t;
}
QByteArray jpegWithExif(const QByteArray& jpeg, int o) {
    const QByteArray body = QByteArray("Exif\0\0", 6) + tiffOrientationBlock(o);
    QByteArray seg("\xFF\xE1", 2);
    const int len = int(body.size()) + 2;
    seg += char(len >> 8);
    seg += char(len & 255);
    seg += body;
    return jpeg.left(2) + seg + jpeg.mid(2);
}
QByteArray pngChunk(const char* type, const QByteArray& data) {
    QByteArray out;
    const auto be32 = [&](uint32_t v) { out += char(v >> 24); out += char(v >> 16 & 255); out += char(v >> 8 & 255); out += char(v & 255); };
    be32(uint32_t(data.size()));
    const QByteArray td = QByteArray(type, 4) + data;
    out += td;
    be32(crc32Of(td));
    return out;
}
QByteArray pngWithExif(const QByteArray& png, int o) { return png.left(33) + pngChunk("eXIf", tiffOrientationBlock(o)) + png.mid(33); }
/** Graustufe eines Pixels im Ergebnis. */
int grayAt(const Raster& r, int x, int y) { return r.gray()[size_t(y) * size_t(r.width()) + size_t(x)]; }

/** Handgebautes PDF wie im TS-Test. */
QByteArray pdfDoc(const QByteArray& content, int pages = 1) {
    QByteArray kids;
    for (int i = 0; i < pages; ++i) kids += QByteArray::number(3 + i) + " 0 R ";
    const int streamId = 3 + pages;
    QList<QByteArray> objs{"<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[" + kids + "]/Count " + QByteArray::number(pages) + ">>"};
    for (int i = 0; i < pages; ++i) objs.push_back("<</Type/Page/Parent 2 0 R/MediaBox[0 0 283.46 283.46]/Contents " + QByteArray::number(streamId) + " 0 R/Resources<<>>>>");
    objs.push_back("<</Length " + QByteArray::number(content.size()) + ">>\nstream\n" + content + "\nendstream");
    QByteArray s = "%PDF-1.5\n";
    QList<qsizetype> offs;
    for (int i = 0; i < objs.size(); ++i) {
        offs.push_back(s.size());
        s += QByteArray::number(i + 1) + " 0 obj\n" + objs[i] + "\nendobj\n";
    }
    const qsizetype xref = s.size();
    s += "xref\n0 " + QByteArray::number(objs.size() + 1) + "\n0000000000 65535 f \n";
    for (const qsizetype o : offs) s += QByteArray::number(o).rightJustified(10, '0') + " 00000 n \n";
    s += "trailer\n<</Size " + QByteArray::number(objs.size() + 1) + "/Root 1 0 R>>\nstartxref\n" + QByteArray::number(xref) + "\n%%EOF\n";
    return s;
}

/** Projekt mit Rechteck, Kreis und offener Linie auf zwei Ebenen, Platte 0. */
Document sampleDoc() {
    Document d;
    Element a = newElement(d.layers[2].id, QStringLiteral("Rechteck"));
    a.transform = Transform{20, 30};
    a.paths.add(PolyView(Shapes::rect(100, 50)));
    Element b = newElement(d.layers[0].id, QStringLiteral("Kreis"));
    b.transform = Transform{150, 30};
    b.paths.add(PolyView(Shapes::ellipse(40, 40)));
    Element c = newElement(d.layers[1].id, QStringLiteral("Linie"));
    c.transform = Transform{20, 100};
    c.paths.add({{0, 0}, {60, 20}});
    d.elements = {a, b, c};
    return d;
}

}  // namespace

#endif  // Q_MOC_RUN

class TestImport : public QObject {
    Q_OBJECT
private slots:
    void beispielOrdner();
    void xmlLiestAttributeEntitaetenCdata();
    void xmlLehntKaputtesAbUndExpandiertNichts();
    void dateitypAmInhalt();
    void utf16UndLatin1Svg();
    void unbekannterVektorIstEinSatz();
    void hpgl();
    void hpglOhneSemikolonUndRelativ();
    void lightburnFormen();
    void lightburnBitmap();
    void lightburn2KurzformUndUmriss();
    void lightburnKopienTeilenListen();
    void lightburnEhrlicheFehler();
    void xsTypUndPlatzierung();
    void xsMitDeflate();
    void xsSkewPiHebtSichAuf();
    void xsSpiegelBloeckeVersteckt();
    void xsRechteckKreisBildKaputt();
    void xcs();
    void xcsGleichePlatzierung();
    void zipBombeWirdAbgelehnt();
    void svgZweiFarbenWerdenEbenen();
    void svgEineFarbeBleibtAufDerGewaehlten();
    void svgLinieUndFuellungGleicheFarbe();
    void svgFarbenAusStyleKlasseGruppe();
    void svgRahmenBleibtEigenesTeil();
    void svgBuchstabeBehaeltLoch();
    void svgGruppeUmAllesEntfaellt();
    void svgOhneGruppeEineGruppe();
    void svgWeissStartetAusgeblendet();
    void svgAusgelassenesGemeldet();
    void svgEingebettetesBild();
    void svgFarbwerte();
    void svgEinheitenViewBoxTransform();
    void svgHochskalierteKurveBleibtRund();
    void svgAllePfadbefehle();
    void svgDoctypeUndFehler();
    void dxfLinieKreisYUnten();
    void dxfLwpolylineUndEinheiten();
    void dxfBloeckeUndFormen();
    void dxfCrlfUndLeerzeilenAmEnde();
    void dxfFehlerSindSaetze();
    void dxfBlockInSichSelbstBleibtEndlich();
    void anordnenKleinMittig();
    void anordnenNebenDieParkEcke();
    void anordnenInReihen();
    void anordnenUnplatzierbar();
    void anordnenEineGruppeFaelltAufTeileZurueck();
    void anordnenOhneStrukturEineGruppe();
    void anordnenVerteilen();
    void regalSpartParkEckeAus();
    void gesperrterStreifen();
    void importSvgMittigNeueEbenenWarnsatz();
    void importDxfNimmtSchneidenWerte();
    void importBestehendeEbeneGleichenNamens();
    void importGesperrteEbeneWeichtAus();
    void importZuGrossVerkleinert();
    void importSatzFuerUnbekanntes();
    void importAufPlattenVerteilt();
    void importEbenenReihenfolgeWieAndroid();
    void importWeissAusgeblendetMitSatz();
    void importUngueltigeKoordinatenFliegenRaus();
    void importZuVieleFormenWerdenZusammengefasst();
    void importAsyncLaeuftImPool();
    void dateifilter();
    void bildTransparenzIstWeissLangesMassBegrenzt();
    void bildFlaechenmittel();
    void dpiAusPngUndJpeg();
    void bildformateMitQImage();
    void bildExifDrehung();
    void bildExifInPngUndWebp();
    void bildAufloesungGibtMm();
    void bildZuGrossWirdVerkleinertUndGesagt();
    void bildKaputtIstEinSatz();
    void svgMitKaputtemEingebettetenBildWarnt();
    void pdfWirdBildMitWarnung();
    void pdfKaputtIstEinSatz();
    void exportSvgGrundgeruest();
    void exportSvgRueckimport();
    void exportSvgBildRueckimport();
    void exportDxfRueckimport();
    void exportDxfEbenenNamen();
    void exportWarnsaetze();
    void exportNurDiePlatte();
    void exportPngMm();
    void exportPngBild();
    void graustufenPng();
};

#ifndef Q_MOC_RUN
// ---- XML ----
// Echte Dateien, die nicht ins Repo dürfen (eigene .xs des Besitzers): LUMACUT_IMPORT_SAMPLES=Ordner
void TestImport::beispielOrdner() {
    const QString dir = qEnvironmentVariable("LUMACUT_IMPORT_SAMPLES");
    if (dir.isEmpty()) QSKIP("LUMACUT_IMPORT_SAMPLES nicht gesetzt");
    QDirIterator it(dir, QDir::Files, QDirIterator::Subdirectories);
    while (it.hasNext()) {
        const QString path = it.next();
        QElapsedTimer t;
        t.start();
        const ImportResult r = importPath(path, ctx());
        size_t paths = 0;
        for (const Element& e : r.elements) paths += e.paths.size();
        qInfo().noquote() << QFileInfo(path).fileName() << r.kind << t.elapsed() << "ms" << r.elements.size() << "Elemente" << paths << "Pfade" << r.layers.size() << "Ebenen"
                          << (r.ok() ? r.warnings.join(QStringLiteral(" | ")) : QStringLiteral("FEHLER: ") + r.error);
        QVERIFY(r.ok() || !r.error.isEmpty());
    }
}

void TestImport::xmlLiestAttributeEntitaetenCdata() {
    const QByteArray src = enc(R"(<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd" [<!ENTITY a "b">]><a x="1&amp;2" y='3'><!-- k --><b>t&#228;<![CDATA[<z>]]></b><c/></a>)");
    const XmlDoc doc(src);
    const int a = doc.root();
    QCOMPARE(doc.node(a).tag, QByteArrayView("a"));
    QCOMPARE(doc.attr(a, "x"), QByteArray("1&2"));
    QCOMPARE(doc.attr(a, "y"), QByteArray("3"));
    const int b = doc.node(a).firstChild;
    QCOMPARE(doc.node(b).tag, QByteArrayView("b"));
    QCOMPARE(doc.node(doc.node(b).nextSibling).tag, QByteArrayView("c"));
    QCOMPARE(QString::fromUtf8(doc.text(b)), QStringLiteral("tä<z>"));
}

void TestImport::xmlLehntKaputtesAbUndExpandiertNichts() {
    QVERIFY_THROWS_EXCEPTION(XmlError, XmlDoc(QByteArray("<a><b></a>")));
    QVERIFY_THROWS_EXCEPTION(XmlError, XmlDoc(QByteArray("kein xml")));
    const QByteArray bomb("<!DOCTYPE a [<!ENTITY x \"boom\">]><a v=\"&x;\"/>");
    const XmlDoc doc(bomb);
    QCOMPARE(doc.attr(doc.root(), "v"), QByteArray("&x;"));
}

// ---- Dateityp ----
void TestImport::dateitypAmInhalt() {
    QCOMPARE(detectKind(enc("<?xml version=\"1.0\"?>\n<svg xmlns=\"http://www.w3.org/2000/svg\"/>")), FileKind::Svg);
    QCOMPARE(detectKind(enc("<?xml version=\"1.0\" encoding=\"UTF-8\"?><LightBurnProject AppVersion=\"1.4\"></LightBurnProject>")), FileKind::Lbrn);
    const char* const raw1 = R"({"canvas":[{"id":"1","displays":[]}],"device":{}})";
    QCOMPARE(detectKind(enc(raw1)), FileKind::Xcs);
    const char* const raw2 = R"({"title":"Neues Projekt","layers":[],"elements":[]})";
    QCOMPARE(detectKind(enc(raw2)), FileKind::Project);
    QCOMPARE(detectKind(enc("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")), FileKind::Dxf);
    QCOMPARE(detectKind(enc("  0\r\nSECTION\r\n  2\r\nHEADER\r\n")), FileKind::Dxf);
    QCOMPARE(detectKind(enc("IN;SP1;PU0,0;PD400,0;")), FileKind::Hpgl);
    QCOMPARE(detectKind(enc("%PDF-1.5\n1 0 obj")), FileKind::Pdf);
    QCOMPARE(detectKind(QByteArray("\x89PNG\r\n", 6)), FileKind::Image);
    QCOMPARE(detectKind(QByteArray("\xFF\xD8\xFF\xE0\0\0", 6)), FileKind::Image);
    QCOMPARE(detectKind(QByteArray("RIFF\0\0\0\0WEBPVP8 ", 16)), FileKind::Image);
    QCOMPARE(detectKind(QByteArray("\0\0\0\x18" "ftypheic\0\0\0\0", 16)), FileKind::Image);
    QCOMPARE(detectKind(enc("das ist nur Text ohne Format")), FileKind::Unknown);
    QCOMPARE(detectKind(QString::fromUtf8("<svg></svg>").prepend(QChar(0xFEFF)).toUtf8()), FileKind::Svg);
}

void TestImport::utf16UndLatin1Svg() {
    const QString body = S(R"(<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 10 10"><rect width="10" height="10" data-name="Tür"/></svg>)");
    QByteArray utf16("\xFF\xFE", 2);
    utf16.append(reinterpret_cast<const char*>(body.utf16()), body.size() * 2);
    QCOMPARE(detectKind(utf16), FileKind::Svg);
    QCOMPARE(parseSvg(utf16).items.size(), size_t(1));
    const QByteArray latin = QByteArray("<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>") + body.toLatin1();
    const VectorImport r = parseSvg(latin);
    QCOMPARE(*r.items[0].name, QStringLiteral("Tür"));
}

void TestImport::unbekannterVektorIstEinSatz() {
    QCOMPARE(errorOf([] { parseVector(FileKind::Unknown, QByteArray(10, 0)); }), QStringLiteral("Dieses Format wird nicht als Vektor gelesen"));
}

// ---- HPGL ----
void TestImport::hpgl() {
    const PolySet polys = parseHpgl(enc("IN;SP1;PU0,0;PD400,0,400,800,0,800,0,0;PU;"));
    QCOMPARE(polys.size(), size_t(1));
    QVERIFY(boxIs(boundsOf(polys), 0, 0, 10, 20));
    QVERIFY(isClosed(polys[0]));
    QCOMPARE(parseHpgl(enc("IN;PU0,0;PD40,0;PU80,0;PD120,0;")).size(), size_t(2));
    QVERIFY(!errorOf([] { parseHpgl(enc("IN;SP1;")); }).isEmpty());
}

void TestImport::hpglOhneSemikolonUndRelativ() {
    QCOMPARE(parseHpgl(enc("PU0,0PD40,0PU80,0PD120,0")).size(), size_t(2));
    const PolySet r = parseHpgl(enc("IN;PA0,0;PD;PR40,0,0,40;PU;"));
    QVERIFY(boxIs(boundsOf(r), 0, 0, 1, 1));
}

// ---- LightBurn ----
void TestImport::lightburnFormen() {
    const VectorImport r = parseLbrn(enc(R"(<?xml version="1.0" encoding="UTF-8"?>
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
        </LightBurnProject>)"));
    QCOMPARE(r.polys.size(), size_t(4));
    QVERIFY(boxIs(boundsOf(r.polys[0]), 80, 40, 120, 60));
    const Box c = *boundsOf(r.polys[1]);
    QVERIFY(near(c.width(), 20, 0.01));
    QVERIFY(near(c.center().x, 200, 0.01));
    const Box p = *boundsOf(r.polys[2]);
    QVERIFY(near(p.minX, 0));
    QVERIFY(near(p.maxX, 10));
    QVERIFY(r.polys[2].size() > 5);
    QVERIFY(boxIs(boundsOf(r.polys[3]), 10, 0, 20, 10));
    QCOMPARE(*r.skippedSentence(), QStringLiteral("Übersprungen: 1× Text (in Pfade bzw. Bild umwandeln)"));
}

void TestImport::lightburnBitmap() {
    const VectorImport r = parseLbrn((S(R"(<LightBurnProject><Shape Type="Bitmap" W="30" H="20" Data=")") + QString::fromLatin1(b64(40)) +
        S(R"("><XForm>1 0 0 1 50 40</XForm></Shape><Shape Type="Rect" W="1" H="1"><XForm>1 0 0 1 0 0</XForm></Shape></LightBurnProject>)")).toUtf8());
    QCOMPARE(r.images.size(), size_t(1));
    QCOMPARE(r.images[0].box, (Box{35, 30, 65, 50}));
    QCOMPARE(r.images[0].bytes.size(), qsizetype(40));
}

void TestImport::lightburn2KurzformUndUmriss() {
    const VectorImport r = parseLbrn(enc(R"(<LightBurnProject AppVersion="1.7" FormatVersion="1">
        <Shape Type="Path"><XForm>1 0 0 1 0 0</XForm><VertList>V0 0V10 0V10 10</VertList><PrimList>LineClosed</PrimList></Shape>
        <Shape Type="Text" Str="Hi"><XForm>1 0 0 1 20 0</XForm><BackupPath Type="Path"><VertList>V0 0V5 0V5 5</VertList><PrimList>LineClosed</PrimList></BackupPath></Shape>
      </LightBurnProject>)"));
    QCOMPARE(r.polys.size(), size_t(2));
    QVERIFY(isClosed(r.polys[0]));
    QVERIFY(boxIs(boundsOf(r.polys[1]), 20, 0, 25, 5));
    QCOMPARE(r.notes, QStringList{QStringLiteral("Text in Pfade umgewandelt (1)")});
}

void TestImport::lightburnKopienTeilenListen() {
    const VectorImport r = parseLbrn(enc(R"(<LightBurnProject>
        <Shape Type="Path" VertID="3" PrimID="4"><XForm>1 0 0 1 0 0</XForm><VertList>V0 0V10 0V10 10</VertList><PrimList>LineClosed</PrimList></Shape>
        <Shape Type="Path" VertID="3" PrimID="4"><XForm>1 0 0 1 100 0</XForm></Shape>
      </LightBurnProject>)"));
    QCOMPARE(r.polys.size(), size_t(2));
    QVERIFY(boxIs(boundsOf(r.polys[1]), 100, 0, 110, 10));
}

void TestImport::lightburnEhrlicheFehler() {
    QVERIFY(errorOf([] { parseLbrn(enc("<LightBurnProject><Shape Type=\"Text\"/></LightBurnProject>")); }).contains(QStringLiteral("Nur Text gefunden")));
    QVERIFY(!errorOf([] { parseLbrn(enc("<foo/>")); }).isEmpty());
}

// ---- xTool ----
void TestImport::xsTypUndPlatzierung() {
    const QByteArray bytes = xs({display({100, 50, "M 5 5 L 25 5 L 25 15 L 5 15 Z", 0, 0, "#fe0002", false, R"(["g1"])"})});
    QCOMPARE(detectKind(bytes), FileKind::Xs);
    const VectorImport r = parseVector(FileKind::Xs, bytes);
    QCOMPARE(r.items.size(), size_t(1));
    QVERIFY(boxIs(boundsOf(r.items[0].polys), 100, 50, 120, 60));
    QCOMPARE(*r.items[0].layerKey, QStringLiteral("#fe0002"));
    QCOMPARE(r.items[0].groups, QStringList{QStringLiteral("g1")});
    QCOMPARE(r.layers.size(), size_t(1));
    QCOMPARE(r.layers[0].name, QStringLiteral("#FE0002"));
}

void TestImport::xsMitDeflate() {
    const VectorImport r = parseXs(xs({display({100, 50, "M 5 5 L 25 5 L 25 15 L 5 15 Z"})}, true));
    QVERIFY(boxIs(boundsOf(r.items[0].polys), 100, 50, 120, 60));
}

void TestImport::xsSkewPiHebtSichAuf() {
    const double pi = 3.141593;
    const PolySet polys = parseXs(xs({display({200, 100, "M 0 0 L 10 0 L 10 1 L 0 4", pi, pi, "#000000", false, "[]", R"({"x":2,"y":3})"})})).allPolys();
    const Box b = *boundsOf(polys);
    QVERIFY(near(b.width(), 20, 1e-3));
    QVERIFY(near(b.height(), 12, 1e-3));
    QVERIFY(near(b.minX, 200, 1e-3));
    QVERIFY(near(b.minY, 88, 1e-3));
    QVERIFY(near(b.maxY, 100, 1e-3));
    QVERIFY(hasPoint(polys[0], 220, 88));
    QVERIFY(hasPoint(polys[0], 220, 91));
    QVERIFY(hasPoint(polys[0], 200, 100));
}

void TestImport::xsSpiegelBloeckeVersteckt() {
    const PolySet one = parseXs(xs({display({10, 10, "M 0 0 L 10 0 L 10 2 L 0 6", 0, 3.141593})})).allPolys();
    QVERIFY(boxIs(boundsOf(one), 10, 10, 20, 16, 1e-2));
    QVERIFY(hasPoint(one[0], 20, 14));
    const VectorImport r = parseXs(makeZip({{"project.json", PROJECT}, {"canvases/c1.json", CANVAS},
        {"canvases/c1/displays-0.json", "{\"displays\":[" + display({0, 0, "M 0 0 L 5 0"}) + "]}"},
        {"canvases/c1/displays-1.json", "{\"displays\":[" + display({30, 0, "M 0 0 L 5 0", 0, 0, "#000000", true}) +
            R"(,{"id":"t","type":"TEXT","x":0,"y":0,"width":20,"height":5,"text":"Hallo"},{"id":"h","type":"PATH","visible":false,"x":0,"y":0,"dPath":"M 0 0 L 9 9"}]})"}}));
    QCOMPARE(r.items.size(), size_t(2));
    QVERIFY(!r.items[0].fill);
    QVERIFY(r.items[1].fill);
    QCOMPARE(r.skipped, QStringList{QStringLiteral("1× Text")});
    QCOMPARE(*r.skippedSentence(), QStringLiteral("Übersprungen: 1× Text (in Pfade bzw. Bild umwandeln)"));
}

void TestImport::xsRechteckKreisBildKaputt() {
    const QByteArray bmp = QByteArray(R"({"id":"b","type":"BITMAP","x":0,"y":50,"width":15,"height":12,"base64":"data:image/png;base64,)") + b64(80, 3) + "\"}";
    const VectorImport r = parseXs(xs({R"({"id":"r","type":"RECT","x":10,"y":20,"width":30,"height":10,"layerTag":"#000000","fill":{"visible":false}})",
                                       R"({"id":"c","type":"CIRCLE","x":60,"y":20,"width":8,"height":8,"layerTag":"#000000"})", bmp}));
    QCOMPARE(r.items.size(), size_t(2));
    QCOMPARE(r.images.size(), size_t(1));
    QVERIFY(boxIs(boundsOf(r.items[0].polys), 10, 20, 40, 30));
    QCOMPARE(r.images[0].box, (Box{0, 50, 15, 62}));
    QCOMPARE(detectKind(makeZip({{"readme.txt", "hallo"}})), FileKind::Unknown);
    QVERIFY(!errorOf([] { parseXs(makeZip({{"readme.txt", "hallo"}})); }).isEmpty());
    QVERIFY(!errorOf([] { parseXs(makeZip({{"project.json", PROJECT}, {"canvases/c1.json", CANVAS}})); }).isEmpty());
}

void TestImport::xcs() {
    const QByteArray json = QByteArray(R"({"canvas":[{"id":"c1","displays":[
        {"id":"a","type":"PATH","x":10,"y":10,"graphicX":10,"graphicY":10,"width":20,"height":10,"dPath":"M0 0L20 0L20 10L0 10Z"},
        {"id":"b","type":"RECT","x":50,"y":10,"width":10,"height":5},
        {"id":"c","type":"CIRCLE","x":70,"y":10,"width":8,"height":8},
        {"id":"d","type":"BITMAP","x":0,"y":30,"width":15,"height":15,"base64":"data:image/png;base64,)") + b64(64, 7) +
        R"("},{"id":"e","type":"TEXT","x":0,"y":0,"width":30,"height":10,"text":"Hallo"}]}],"device":{}})";
    const VectorImport r = parseVector(FileKind::Xcs, json);
    QCOMPARE(r.items.size(), size_t(3));
    QVERIFY(boxIs(boundsOf(r.items[0].polys), 10, 10, 30, 20));
    QVERIFY(boxIs(boundsOf(r.items[1].polys), 50, 10, 60, 15));
    QVERIFY(near(boundsOf(r.items[2].polys)->width(), 8));
    QCOMPARE(r.images.size(), size_t(1));
    QCOMPARE(r.images[0].box, (Box{0, 30, 15, 45}));
    QCOMPARE(r.skipped, QStringList{QStringLiteral("1× Text")});
    const char* const raw3 = R"({"canvas":[{"displays":[{"type":"TEXT","width":3,"height":3}]}]})";
    QVERIFY(!errorOf([&] { parseXcs(enc(raw3)); }).isEmpty());
    QVERIFY(!errorOf([] { parseXcs(enc("kein json")); }).isEmpty());
}

void TestImport::xcsGleichePlatzierung() {
    const VectorImport r = parseXcs(enc(R"({"canvas":[{"layerData":{"#000000":{"name":"Schwarz","order":1}},"displays":[
        {"type":"PATH","x":40,"y":40,"width":10,"height":10,"layerTag":"#000000","dPath":"M 0 0 L 10 0 L 10 10 Z"}]}]})"));
    QVERIFY(boxIs(boundsOf(r.items[0].polys), 40, 40, 50, 50));
    QCOMPARE(r.layers[0].name, QStringLiteral("Schwarz"));
}

void TestImport::zipBombeWirdAbgelehnt() {
    const QByteArray zeros(60 * 1024 * 1024, 0);
    const QByteArray zip = makeZip({{"project.json", PROJECT}, {"canvases/x", zeros}}, true);
    QVERIFY(zip.size() < 1024 * 1024);
    QVERIFY(errorOf([&] { parseXs(zip); }).contains(QStringLiteral("zu groß")));
}

// ---- SVG, Struktur ----
void TestImport::svgZweiFarbenWerdenEbenen() {
    const VectorImport r = parseSvg(svgDoc(SQUARE + S(R"( stroke="#ff0000" fill="none"/>)") + OTHER + S(R"( fill="#0000ff"/>)")));
    QCOMPARE(*r.items[0].layerKey, QStringLiteral("#ff0000"));
    QCOMPARE(*r.items[1].layerKey, QStringLiteral("#0000ff"));
    QVERIFY(!r.items[0].fill);
    QVERIFY(r.items[1].fill);
    QCOMPARE(r.layers[0].name, QStringLiteral("Rot"));
    QCOMPARE(r.layers[1].name, QStringLiteral("Blau"));
}

void TestImport::svgEineFarbeBleibtAufDerGewaehlten() {
    const VectorImport r = parseSvg(svgDoc(SQUARE + S(R"( fill="#000"/>)") + OTHER + S(R"( fill="black"/>)")));
    QVERIFY(!r.items[0].layerKey && !r.items[1].layerKey);
    QVERIFY(r.layers.empty());
}

void TestImport::svgLinieUndFuellungGleicheFarbe() {
    const VectorImport r = parseSvg(svgDoc(SQUARE + S(R"( stroke="black" fill="none"/>)") + OTHER + S(R"( fill="black"/>)")));
    QVERIFY(!r.items[0].fill);
    QVERIFY(r.items[1].fill);
    QCOMPARE(*r.items[0].layerKey, QStringLiteral("#000000"));
    QCOMPARE(*r.items[1].layerKey, QStringLiteral("#000000"));
}

void TestImport::svgFarbenAusStyleKlasseGruppe() {
    const VectorImport r = parseSvg(svgDoc(QStringLiteral("<style>.a{fill:#00ff00} .b,.c{stroke:rgb(255,0,0);fill:none}</style>") + SQUARE + S(R"( class="a"/>)") + OTHER +
        S(R"( class="c"/><g fill="#0000ff"><circle cx="70" cy="70" r="5"/></g><rect x="1" y="50" width="5" height="5" style="fill:#abc"/>)")));
    QCOMPARE(r.items.size(), size_t(4));
    QCOMPARE(*r.items[0].layerKey, QStringLiteral("#00ff00"));
    QCOMPARE(*r.items[1].layerKey, QStringLiteral("#ff0000"));
    QCOMPARE(*r.items[2].layerKey, QStringLiteral("#0000ff"));
    QCOMPARE(*r.items[3].layerKey, QStringLiteral("#aabbcc"));
}

void TestImport::svgRahmenBleibtEigenesTeil() {
    const char* const raw4 = R"(<rect x="0" y="0" width="90" height="90" fill="none" stroke="#000"/>)";
    const char* const raw5 = R"( fill="none" stroke="#000"/>)";
    QCOMPARE(parseSvg(svgDoc(S(raw4) + SQUARE + S(raw5))).items.size(), size_t(2));
}

void TestImport::svgBuchstabeBehaeltLoch() {
    const VectorImport r = parseSvg(svgDoc(S(R"(<path d="M0 0H20V20H0Z M5 5H15V15H5Z" fill="#000"/>)")));
    QCOMPARE(r.items.size(), size_t(1));
    QCOMPARE(r.items[0].polys.size(), size_t(2));
}

void TestImport::svgGruppeUmAllesEntfaellt() {
    const VectorImport r = parseSvg(svgDoc(QStringLiteral("<g><g>") + SQUARE + QStringLiteral("/>") + OTHER + S(R"(/></g><g><rect x="70" y="70" width="5" height="5"/></g></g>)")));
    QCOMPARE(r.items[0].groups.first(), r.items[1].groups.first());
    QVERIFY(r.items[0].groups.first() != r.items[2].groups.first());
}

void TestImport::svgOhneGruppeEineGruppe() {
    const VectorImport r = parseSvg(svgDoc(SQUARE + QStringLiteral("/>") + OTHER + QStringLiteral("/>")));
    for (const ImportItem& i : r.items) QCOMPARE(i.groups, QStringList{QStringLiteral("*")});
}

void TestImport::svgWeissStartetAusgeblendet() {
    const VectorImport r = parseSvg(svgDoc(S(R"(<rect width="100" height="100" fill="#fff"/>)") + SQUARE + S(R"( stroke="#000" fill="none"/>)")));
    for (const ImportLayerInfo& l : r.layers) QCOMPARE(l.visible, l.key != QLatin1String("#ffffff"));
    QCOMPARE(r.layers.size(), size_t(2));
}

void TestImport::svgAusgelassenesGemeldet() {
    const VectorImport r = parseSvg(svgDoc(SQUARE + S(R"(/><text x="0" y="0">Hallo</text><use href="#a"/><image href="bild.png" width="5" height="5"/>)")));
    QCOMPARE(r.skipped, (QStringList{QStringLiteral("Text (1)"), QStringLiteral("verlinkte Bilder (1)"), QStringLiteral("Klone (1)")}));
    const char* const raw6 = R"(/><rect width="5" height="5" style="display:none"/><rect width="5" height="5" visibility="hidden"/>)";
    QCOMPARE(parseSvg(svgDoc(SQUARE + S(raw6))).items.size(), size_t(1));
}

void TestImport::svgEingebettetesBild() {
    const VectorImport r = parseSvg(svgDoc(SQUARE + S(R"(/><image x="10" y="20" width="30" height="40" href="data:image/png;base64,)") + QString::fromLatin1(b64(20)) + QStringLiteral("\"/>")));
    QCOMPARE(r.images.size(), size_t(1));
    QCOMPARE(r.images[0].box, (Box{10, 20, 40, 60}));
}

void TestImport::svgFarbwerte() {
    QCOMPARE(parseColour("url(#g)", 0), COLOUR_OTHER);
    QCOMPARE(parseColour("rgb(16, 32, 48)", COLOUR_OTHER), 0x102030);
    QCOMPARE(parseColour("rgba(16 32 48 / 0.5)", COLOUR_OTHER), 0x102030);
    QCOMPARE(parseColour("rgb(100%,0%,50%)", COLOUR_OTHER), 0xfe007f);     // wie Kotlin: 100 * 2,55 abgeschnitten
    QCOMPARE(parseColour("none", COLOUR_OTHER), COLOUR_NONE);
    QCOMPARE(parseColour("transparent", COLOUR_OTHER), COLOUR_NONE);
    QCOMPARE(parseColour("inherit", 0x123456), 0x123456);
    QCOMPARE(parseColour(" BLACK ", COLOUR_OTHER), 0);
    QCOMPARE(colourKey(0x00ff00), QStringLiteral("#00ff00"));
    QCOMPARE(colourName(0xfe0002), QStringLiteral("Rot"));
}

void TestImport::svgEinheitenViewBoxTransform() {
    const VectorImport r = parseSvg(enc(R"(<svg xmlns="http://www.w3.org/2000/svg" width="10cm" viewBox="10 10 200 100"><rect x="10" y="10" width="200" height="100" fill="none" stroke="#000"/></svg>)"));
    QVERIFY(boxIs(boundsOf(r.items[0].polys), 0, 0, 100, 50));
    const VectorImport p96 = parseSvg(enc(R"(<svg xmlns="http://www.w3.org/2000/svg"><line x1="0" y1="0" x2="96" y2="0" stroke="#000"/></svg>)"));
    QVERIFY(near(boundsOf(p96.items[0].polys)->maxX, 25.4));
    const Pt q = svgTransform("translate(10 20) rotate(90) scale(2)").apply({1, 0});
    QVERIFY(near(q.x, 10));
    QVERIFY(near(q.y, 22));
}

void TestImport::svgHochskalierteKurveBleibtRund() {
    // viewBox 0..1 auf 100 mm: die Vorlage flachte in Benutzereinheiten ab und bekäme hier nur 2 Sehnen.
    const VectorImport r = parseSvg(enc(R"(<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 1 1"><path stroke="#000" d="M0 0C0 1 1 1 1 0"/></svg>)"));
    QVERIFY(r.items[0].polys[0].size() > 200);
}

void TestImport::svgAllePfadbefehle() {
    const PolySet p = pathData("M0 0 L10 0 H20 V10 C20 20 10 20 10 10 S0 0 0 10 Q5 15 10 10 T20 10 a5 5 0 01 10 0 Z");
    QCOMPARE(p.size(), size_t(1));
    QVERIFY(isClosed(p[0]));
    QVERIFY(near(boundsOf(pathData("M0 0 A10 10 0 0 1 20 0"))->minY, -10, 0.1));
    QVERIFY(!errorOf([] { pathData("10 10"); }).isEmpty());
    QCOMPARE(pathData("M1 1").size(), size_t(0));
    QCOMPARE(pathData("M0 0 L1e2-5").size(), size_t(1));
    QCOMPARE(pathData("M.5.5.5 1").size(), size_t(1));
    QVERIFY(!errorOf([] { pathData("M0 0 L1"); }).isEmpty());
    QVERIFY(!errorOf([] { pathData("M0 0L1 1Z 5"); }).isEmpty());
    QVERIFY(!errorOf([] { pathData("M1e999 0L1 1"); }).isEmpty());
}

void TestImport::svgDoctypeUndFehler() {
    const char* const raw7 = R"(<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg xmlns="http://www.w3.org/2000/svg" width="1mm" height="1mm" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>)";
    QCOMPARE(parseSvg(enc(raw7)).items.size(), size_t(1));
    QCOMPARE(errorOf([] { parseSvg(enc("<svg><rect></svg>")); }), QStringLiteral("SVG konnte nicht gelesen werden"));
    QVERIFY(errorOf([] { parseSvg(enc("<svg xmlns=\"x\"><text>nur</text></svg>")); }).contains(QStringLiteral("Keine Vektoren")));
    QCOMPARE(errorOf([] { parseSvg(enc("<foo/>")); }), QStringLiteral("Keine SVG-Datei"));
}

// ---- DXF ----
void TestImport::dxfLinieKreisYUnten() {
    const VectorImport r = parseDxf(dxfDoc("0\nLINE\n10\n0\n20\n0\n11\n10\n21\n20\n0\nCIRCLE\n10\n50\n20\n50\n40\n5\n"));
    QCOMPARE(r.polys.size(), size_t(2));
    QVERIFY(r.polys[0][0].y > r.polys[0][1].y);
    QVERIFY(near(boundsOf(r.polys)->minY, 0));
}

void TestImport::dxfLwpolylineUndEinheiten() {
    const VectorImport r = parseDxf(dxfDoc("0\nLWPOLYLINE\n90\n4\n70\n1\n10\n0\n20\n0\n10\n1\n20\n0\n10\n1\n20\n1\n10\n0\n20\n1\n", "9\n$INSUNITS\n70\n1\n"));
    QVERIFY(isClosed(r.polys[0]));
    QVERIFY(near(boundsOf(r.polys)->maxX, 25.4));
    const VectorImport bulge = parseDxf(dxfDoc("0\nLWPOLYLINE\n90\n2\n70\n0\n10\n0\n20\n0\n42\n1\n10\n10\n20\n0\n"));
    QVERIFY(near(boundsOf(bulge.polys)->height(), 5, 0.1));
}

void TestImport::dxfBloeckeUndFormen() {
    const QByteArray blocks = "0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nB1\n0\nLINE\n10\n0\n20\n0\n11\n5\n21\n0\n0\nENDBLK\n0\nENDSEC\n";
    const VectorImport r = parseDxf(blocks + "0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nB1\n10\n100\n20\n0\n41\n2\n42\n2\n0\nPOLYLINE\n70\n0\n0\nVERTEX\n10\n0\n20\n0\n0\nVERTEX\n10\n5\n20\n5\n0\nSEQEND\n0\nARC\n10\n0\n20\n0\n40\n3\n50\n0\n51\n90\n0\nELLIPSE\n10\n20\n20\n20\n11\n5\n21\n0\n40\n0.5\n0\nSPLINE\n71\n3\n40\n0\n40\n0\n40\n0\n40\n0\n40\n1\n40\n1\n40\n1\n40\n1\n10\n0\n20\n0\n10\n1\n20\n1\n10\n2\n20\n1\n10\n3\n20\n0\n0\nTEXT\n1\nHallo\n0\nMTEXT\n1\nDu\n0\nENDSEC\n0\nEOF\n");
    QCOMPARE(r.polys.size(), size_t(5));
    QCOMPARE(r.skipped, QStringList{QStringLiteral("2× Text")});
}

void TestImport::dxfCrlfUndLeerzeilenAmEnde() {
    QByteArray d = dxfDoc("0\nLINE\n10\n0\n20\n0\n11\n10\n21\n0\n");
    d.replace("\n", "\r\n");
    QCOMPARE(parseDxf(d + "\r\n\r\n").polys.size(), size_t(1));
}

void TestImport::dxfFehlerSindSaetze() {
    QVERIFY(errorOf([] { parseDxf(enc("AutoCAD Binary DXF\n")); }).contains(QStringLiteral("Binäres DXF")));
    QVERIFY(!errorOf([] { parseDxf(enc("kein\ndxf\n")); }).isEmpty());
    QVERIFY(errorOf([] { parseDxf(dxfDoc("0\nTEXT\n1\nx\n")); }).contains(QStringLiteral("Keine unterstützten")));
}

void TestImport::dxfBlockInSichSelbstBleibtEndlich() {
    const VectorImport r = parseDxf(QByteArray("0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nA\n0\nINSERT\n2\nA\n0\nLINE\n10\n0\n20\n0\n11\n1\n21\n0\n0\nENDBLK\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nA\n0\nENDSEC\n0\nEOF\n"));
    QCOMPARE(r.polys.size(), size_t(8));     // höchstens 8 Ebenen tief, wie die Vorlage
}

// ---- Anordnen ----
void TestImport::anordnenKleinMittig() {
    VectorImport r = result({rectItem(0, 0, 100, 50)});
    const Layout l = arrange(r, unitsOf(r), 360, 340);
    QVERIFY(l.kind == FitKind::AsIs);
    QCOMPARE(*l.offsets[0], (Pt{130, 145}));
    VectorImport r2 = result({rectItem(0, 0, 100, 50)});
    const Layout l2 = arrange(r2, unitsOf(r2));
    QCOMPARE(*l2.offsets[0], (Pt{135, 155}));     // Android: Fläche 370 × 360
}

void TestImport::anordnenNebenDieParkEcke() {
    // 300 × 340 mittig reichte oben rechts hinein; passt links daneben.
    VectorImport r = result({rectItem(0, 0, 280, 340)});
    const Layout l = arrange(r, unitsOf(r));
    QVERIFY(l.kind == FitKind::AsIs);
    const Box b = (*l.units)[0].box;
    const Box placed{b.minX + l.offsets[0]->x, b.minY + l.offsets[0]->y, b.maxX + l.offsets[0]->x, b.maxY + l.offsets[0]->y};
    QVERIFY(!Work::touchesPark(placed));
    QVERIFY(Work::contains(placed));
}

void TestImport::anordnenInReihen() {
    VectorImport r = result({rectItem(0, 0, 170, 150, QStringLiteral("a")), rectItem(500, 0, 170, 150, QStringLiteral("b")), rectItem(0, 500, 170, 150, QStringLiteral("c"))});
    const Units units = unitsOf(r);
    QCOMPARE(units->size(), size_t(3));
    const Layout l = arrange(r, units);
    QVERIFY(l.kind == FitKind::Packed);
    std::vector<Box> placed;
    for (size_t i = 0; i < l.units->size(); ++i) {
        const Box b = (*l.units)[i].box;
        placed.push_back({b.minX + l.offsets[i]->x, b.minY + l.offsets[i]->y, b.maxX + l.offsets[i]->x, b.maxY + l.offsets[i]->y});
    }
    double maxTop = 0;
    for (size_t i = 0; i < placed.size(); ++i) {
        QVERIFY(Work::contains(placed[i]));
        maxTop = std::max(maxTop, placed[i].minY);
        for (size_t j = i + 1; j < placed.size(); ++j) {
            const Box& a = placed[i];
            const Box& b = placed[j];
            QVERIFY(a.maxX + 4.99 <= b.minX || b.maxX + 4.99 <= a.minX || a.maxY + 4.99 <= b.minY || b.maxY + 4.99 <= a.minY);
        }
    }
    QVERIFY(near(maxTop, 156, 1e-9));
}

void TestImport::anordnenUnplatzierbar() {
    VectorImport r = result({rectItem(0, 0, 400, 100, QStringLiteral("a")), rectItem(0, 200, 100, 100, QStringLiteral("b"))});
    const Units units = unitsOf(r);
    const Layout l = arrange(r, units);
    QVERIFY(l.kind == FitKind::Partial);
    QCOMPARE(l.leftOut(), 1);
    QVERIFY(!l.offsets[0]);
    QVERIFY(l.offsets[1].has_value());
    QVERIFY(near(shrinkFactor(*units), (Work::width() - 10) / 400, 1e-9));
}

void TestImport::anordnenEineGruppeFaelltAufTeileZurueck() {
    VectorImport r = result({rectItem(0, 0, 200, 200, QStringLiteral("g")), rectItem(300, 0, 100, 100, QStringLiteral("g"))});
    const Units units = unitsOf(r);
    QCOMPARE(units->size(), size_t(1));
    const Layout l = arrange(r, units);
    QCOMPARE(l.units->size(), size_t(2));
    QVERIFY(l.kind == FitKind::Packed);
}

void TestImport::anordnenOhneStrukturEineGruppe() {
    VectorImport r;
    r.polys.add(PolyView(Shapes::rect(10, 10)));
    Poly second = Shapes::rect(10, 10);
    for (Pt& q : second) q.x += 30;
    r.polys.add(PolyView(second));
    const Units units = unitsOf(r);
    QCOMPARE(units->size(), size_t(1));
    QCOMPARE((*units)[0].items.size(), size_t(2));
}

void TestImport::anordnenVerteilen() {
    std::vector<ImportItem> items;
    for (int i = 0; i < 6; ++i) items.push_back(rectItem(i * 300, 0, 170, 150, QStringLiteral("g%1").arg(i)));
    VectorImport r = result(std::move(items));
    const Spread s = spread(r, unitsOf(r), 360, 340);
    QCOMPARE(s.plates.size(), size_t(2));
    QCOMPARE(s.leftOut, 0);
    int placed = 0;
    for (const Layout& p : s.plates) placed += int(p.offsets.size()) - p.leftOut();
    QCOMPARE(placed, 6);
}

void TestImport::regalSpartParkEckeAus() {
    std::vector<Box> boxes(5, Box{0, 0, 80, 30});
    const auto p = shelf(boxes, 370, 360);
    const Box park = Work::park();
    for (const auto& o : p) {
        QVERIFY(o.has_value());
        QVERIFY(!(o->x + 80 > park.minX && o->y < park.maxY));
    }
}

void TestImport::gesperrterStreifen() {
    // op=work_band: ganze Breite gesperrt.
    Bed::configure(std::nullopt, std::nullopt, 600, 40);
    VectorImport r = result({rectItem(0, 0, 100, 50)});
    const Units units = unitsOf(r);
    const Layout l = arrange(r, units);
    const Box b = (*units)[0].box;
    QVERIFY(b.minY + l.offsets[0]->y >= 40 - 1e-9);
    const auto packed = shelf({Box{0, 0, 80, 30}}, 370, 360);
    QVERIFY(packed[0]->y >= 40 - 1e-9);
    QVERIFY(near(shrinkFactor(*units, std::nullopt, std::nullopt, 5), 1));
    const ImportResult res = importFile(QStringLiteral("g.dxf"), enc("0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n0\n20\n0\n11\n1000\n21\n0\n0\nENDSEC\n0\nEOF\n"), ctx());
    QVERIFY(res.ok());
    QVERIFY(res.elements[0].worldBounds()->minY >= 40);
    Bed::configure(std::nullopt, std::nullopt, 78, 35);
}

// ---- importFile ----
void TestImport::importSvgMittigNeueEbenenWarnsatz() {
    const ImportResult r = importFile(QStringLiteral("a.svg"), enc(R"(<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100"><rect width="10" height="10" stroke="#f00" fill="none"/><rect x="20" width="10" height="10" fill="#00f"/><text>x</text></svg>)"), ctx());
    QVERIFY2(r.ok(), qPrintable(r.error));
    QCOMPARE(r.kind, QStringLiteral("SVG"));
    QCOMPARE(r.elements.size(), size_t(2));
    QCOMPARE(r.layers.size(), size_t(2));
    QCOMPARE(r.layers[0].name, QStringLiteral("Rot"));
    QCOMPARE(r.layers[1].name, QStringLiteral("Blau (Füllen)"));
    QVERIFY(r.layers[0].mode == LayerMode::Line);
    QVERIFY(r.layers[1].mode == LayerMode::Fill);
    QCOMPARE(r.elements[0].layerId, r.layers[0].id);
    QCOMPARE(r.warnings[0], QStringLiteral("Übersprungen: Text (1) (in Pfade bzw. Bild umwandeln)"));
    QVERIFY(r.elements[0].groupId.has_value());
    QCOMPARE(r.elements[0].groupId, r.elements[1].groupId);
    QVERIFY(near((r.elements[0].transform.x + r.elements[1].transform.x + 10) / 2, 185));
    // SVG-Linien beginnen mit den Werten von "Linie", nicht mit Schneiden.
    const Document d;
    QCOMPARE(r.layers[0].powerPct, d.layers[1].powerPct);
    QCOMPARE(r.layers[1].powerPct, d.layers[0].powerPct);
}

void TestImport::importDxfNimmtSchneidenWerte() {
    const Document d;
    ImportContext c = importContextFor(d, d.layers[0].id);
    const QByteArray file = R"({"canvas":[{"layerData":{"#111111":{"name":"Eins","order":1},"#222222":{"name":"Zwei","order":2}},"displays":[
        {"type":"PATH","x":0,"y":0,"width":10,"height":10,"layerTag":"#111111","dPath":"M 0 0 L 10 0"},
        {"type":"PATH","x":0,"y":20,"width":10,"height":10,"layerTag":"#222222","dPath":"M 0 0 L 10 0"}]}]})";
    const ImportResult r = importFile(QStringLiteral("a.xcs"), file, c);
    QVERIFY2(r.ok(), qPrintable(r.error));
    QCOMPARE(r.layers.size(), size_t(2));
    QCOMPARE(r.layers[0].speed, d.layers[2].speed);
    QCOMPARE(r.layers[0].color, 0xFF111111LL);
}

void TestImport::importBestehendeEbeneGleichenNamens() {
    Document d;
    d.layers.push_back(newLayer(QStringLiteral("Rot"), 0xFFFF0000LL, LayerMode::Line));
    const ImportResult r = importFile(QStringLiteral("a.svg"), enc(R"(<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100"><rect width="10" height="10" stroke="#f00" fill="none"/><rect x="20" width="10" height="10" fill="#00f"/></svg>)"), importContextFor(d));
    QVERIFY(r.ok());
    QCOMPARE(r.layers.size(), size_t(1));
    QCOMPARE(r.elements[0].layerId, d.layers.back().id);
}

void TestImport::importGesperrteEbeneWeichtAus() {
    Document d;
    d.layers[1].locked = true;
    const ImportResult r = importFile(QStringLiteral("a.dxf"), dxfDoc("0\nLINE\n10\n0\n20\n0\n11\n10\n21\n0\n"), importContextFor(d, d.layers[1].id));
    QVERIFY(r.ok());
    QCOMPARE(r.elements[0].layerId, d.layers[0].id);
}

void TestImport::importZuGrossVerkleinert() {
    const ImportResult r = importFile(QStringLiteral("g.dxf"), enc("0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n0\n20\n0\n11\n1000\n21\n0\n0\nENDSEC\n0\nEOF\n"), ctx());
    QVERIFY2(r.ok(), qPrintable(r.error));
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("verkleinert")));
    QVERIFY(r.fit == ImportFit::Shrunk);
    QCOMPARE(r.partial.shrinkPercent, 36);
    QVERIFY(boundsOf(r.elements[0].paths)->maxX < 370);
    QVERIFY(near(r.elements[0].worldBounds()->center().x, Work::center().x));
}

void TestImport::importSatzFuerUnbekanntes() {
    QVERIFY(importFile(QStringLiteral("x"), enc("Hallo Welt, das ist Text"), ctx()).error.contains(QStringLiteral("Format kenne ich nicht")));
    const char* const raw8 = R"({"title":"a","layers":[],"elements":[]})";
    QVERIFY(importFile(QStringLiteral("x"), enc(raw8), ctx()).error.contains(QStringLiteral("LumaCut-Projekt")));
    QVERIFY(!importFile(QStringLiteral("x"), QByteArray(), ctx()).ok());
    QVERIFY(importFile(QStringLiteral("x.dxf"), enc("AutoCAD Binary DXF\nmehr"), ctx()).error.contains(QStringLiteral("Binäres DXF")));
}

void TestImport::importAufPlattenVerteilt() {
    Document d;
    d.plateCount = 3;
    d.activePlate = 1;
    QString body;
    for (int i = 0; i < 6; ++i) body += S(R"(<g><rect x="%1" width="170" height="150" stroke="#000" fill="none"/></g>)").arg(i * 300);
    const QByteArray file = (S(R"(<svg xmlns="http://www.w3.org/2000/svg" width="2000mm" height="200mm" viewBox="0 0 2000 200">)") + body + QStringLiteral("</svg>")).toUtf8();
    const ImportResult r = importFile(QStringLiteral("a.svg"), file, importContextFor(d));
    QVERIFY2(r.ok(), qPrintable(r.error));
    QVERIFY(r.fit == ImportFit::Plates);
    QCOMPARE(r.addedPlates, 1);
    QCOMPARE(r.elements.size(), size_t(6));
    std::set<int> plates;
    for (const Element& e : r.elements) plates.insert(e.plate);
    QCOMPARE(plates, (std::set<int>{1, 3}));
    const Document after = applyImport(d, r);
    QCOMPARE(after.plateCount, 4);
    QCOMPARE(after.elements.size(), size_t(6));
    // Dieselbe Datei mit den anderen Entscheidungen.
    ImportContext only = importContextFor(d);
    only.partial = PartialFit::OnlyFitting;
    const ImportResult few = importFile(QStringLiteral("a.svg"), file, only);
    QVERIFY(few.fit == ImportFit::OnlyFitting);
    QCOMPARE(int(few.elements.size()), few.partial.fitting);
    QVERIFY(few.elements.size() < 6);
    ImportContext shrink = importContextFor(d);
    shrink.partial = PartialFit::Shrink;
    const ImportResult small = importFile(QStringLiteral("a.svg"), file, shrink);
    QVERIFY(small.fit == ImportFit::Shrunk);
    QCOMPARE(small.elements.size(), size_t(6));
    QVERIFY(small.addedPlates == 0);
}

void TestImport::importEbenenReihenfolgeWieAndroid() {
    const Document d;
    const ImportResult r = importFile(QStringLiteral("a.svg"), enc(R"(<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100"><rect width="10" height="10" stroke="#f00" fill="none"/><rect x="20" width="10" height="10" fill="#00f"/></svg>)"), importContextFor(d));
    const Document after = applyImport(d, r);
    QStringList names;
    for (const Layer& l : after.layers) names.push_back(l.name);
    QCOMPARE(names, (QStringList{QStringLiteral("Gravieren"), QStringLiteral("Blau (Füllen)"), QStringLiteral("Linie"), QStringLiteral("Schneiden"), QStringLiteral("Rot")}));
}

void TestImport::importWeissAusgeblendetMitSatz() {
    const ImportResult r = importFile(QStringLiteral("a.svg"), svgDoc(S(R"(<rect width="100" height="100" fill="#fff"/>)") + SQUARE + S(R"( stroke="#000" fill="none"/>)")), ctx());
    QVERIFY(r.ok());
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("Weiß gilt als Hintergrund")));
    const auto white = std::find_if(r.layers.begin(), r.layers.end(), [](const Layer& l) { return !l.visible; });
    QVERIFY(white != r.layers.end());
}

void TestImport::importUngueltigeKoordinatenFliegenRaus() {
    const ImportResult r = importFile(QStringLiteral("a.dxf"), dxfDoc("0\nLINE\n10\n0\n20\n0\n11\n10\n21\n0\n0\nLINE\n10\n1e300\n20\n0\n11\n1e301\n21\n0\n"), ctx());
    QVERIFY(!r.ok() || r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("ungültigen Koordinaten")));
    const ImportResult s = importFile(QStringLiteral("a.svg"), svgDoc(S(R"(<path d="M0 0L1e40 0" stroke="#000"/><path d="M0 0L5 0" stroke="#000"/>)")), ctx());
    QVERIFY2(s.ok(), qPrintable(s.error));
    QCOMPARE(s.elements.size(), size_t(1));
    QVERIFY(s.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("ungültigen Koordinaten")));
}

void TestImport::importZuVieleFormenWerdenZusammengefasst() {
    QString body;
    for (int i = 0; i < 50; ++i) body += S(R"(<path d="M%1 0L%1 5" stroke="#f00"/><path d="M%1 10L%1 15" stroke="#00f"/>)").arg(i);
    ImportContext c = ctx();
    c.maxElements = 10;
    const ImportResult r = importFile(QStringLiteral("a.svg"), svgDoc(body), c);
    QVERIFY2(r.ok(), qPrintable(r.error));
    QCOMPARE(r.elements.size(), size_t(2));
    QCOMPARE(r.elements[0].paths.size(), size_t(50));
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("100 Formen")));
}

void TestImport::importAsyncLaeuftImPool() {
    QFuture<ImportResult> f = importFileAsync(QStringLiteral("a.svg"), svgDoc(SQUARE + QStringLiteral("/>")), ctx());
    f.waitForFinished();
    QVERIFY(f.result().ok());
}

void TestImport::dateifilter() {
    const QStringList f = importFilters();
    QVERIFY(f[0].startsWith(QStringLiteral("Alle Motive (")));
    for (const char* e : {"*.svg", "*.dxf", "*.pdf", "*.png", "*.jpg", "*.webp", "*.bmp", "*.gif", "*.lbrn", "*.lbrn2", "*.xs", "*.xcs", "*.hpgl", "*.plt"})
        QVERIFY(f[0].contains(QLatin1String(e)));
}

// ---- Bilder ----
void TestImport::bildTransparenzIstWeissLangesMassBegrenzt() {
    QImage two(2, 1, QImage::Format_RGBA8888);
    two.setPixelColor(0, 0, QColor(0, 0, 0, 255));
    two.setPixelColor(1, 0, QColor(0, 0, 0, 0));
    const Raster r = rasterFromImage(two);
    QCOMPARE(r.width(), 2);
    QCOMPARE(grayAt(r, 0, 0), 0);
    QCOMPARE(grayAt(r, 1, 0), 255);
    QImage big(3000, 100, QImage::Format_RGB32);
    big.fill(Qt::white);
    const Raster s = rasterFromImage(big, 1000);
    QCOMPARE(s.width(), 1000);
    QCOMPARE(s.height(), 33);
}

void TestImport::bildFlaechenmittel() {
    QImage img(4, 2, QImage::Format_RGB32);
    img.fill(Qt::white);
    img.setPixel(0, 0, qRgb(0, 0, 0));
    img.setPixel(1, 0, qRgb(0, 0, 0));
    const Raster s = rasterFromImage(img, 2);
    QCOMPARE(s.width(), 2);
    QCOMPARE(s.height(), 1);
    QVERIFY(std::abs(grayAt(s, 0, 0) - 128) <= 1);
    QCOMPARE(grayAt(s, 1, 0), 255);
}

void TestImport::dpiAusPngUndJpeg() {
    const auto png = [](uint32_t ppm) {
        QByteArray b("\x89PNG\r\n\x1a\n", 8);
        QByteArray data;
        for (int i = 0; i < 2; ++i) { data += char(ppm >> 24); data += char(ppm >> 16 & 255); data += char(ppm >> 8 & 255); data += char(ppm & 255); }
        data += char(1);
        return b + pngChunk("pHYs", data);
    };
    QVERIFY(near(*readDpi(png(11811)), 300, 0.5));
    QVERIFY(!readDpi(png(2835)));
    QByteArray jpg("\xFF\xD8\xFF\xE0\0\x10JFIF\0\x01\x01\x01\x01\x2C\x01\x2C", 18);
    jpg += QByteArray(6, 0);
    QCOMPARE(*readDpi(jpg), 300.0);
    QVERIFY(!readDpi(QByteArray(20, 0)));
}

void TestImport::bildformateMitQImage() {
    const QImage img = halfBlack(40, 20);
    for (const char* format : {"png", "jpg", "bmp", "webp"}) {
        const QByteArray bytes = encodeImage(img, format, 100);
        QVERIFY2(!bytes.isEmpty(), format);
        QCOMPARE(detectKind(bytes), FileKind::Image);
        const ImportResult r = importFile(QString::fromLatin1(format), bytes, ctx());
        QVERIFY2(r.ok(), qPrintable(r.error));
        QCOMPARE(r.kind, QStringLiteral("Bild"));
        QCOMPARE(r.elements.size(), size_t(1));
        const Raster& ras = r.elements[0].raster;
        QCOMPARE(ras.width(), 40);
        QCOMPARE(ras.height(), 20);
        QVERIFY(grayAt(ras, 5, 10) < 40);
        QVERIFY(grayAt(ras, 35, 10) > 215);
        QVERIFY(near(r.elements[0].imageWidthMm, 80));
        QVERIFY(near(r.elements[0].imageHeightMm, 40));
        QVERIFY(near(r.elements[0].transform.x, Work::center().x - 40));
        const Document d;
        QCOMPARE(r.elements[0].layerId, ctx().layers[0].name == QLatin1String("Gravieren") ? r.elements[0].layerId : QString());
    }
    // Ein Pixel, schwarz. Qt schreibt kein GIF, darum von Hand.
    const QByteArray gif("GIF89a\x01\0\x01\0\x80\0\0\0\0\0\xFF\xFF\xFF,\0\0\0\0\x01\0\x01\0\0\x02\x02\x44\x01\0;", 35);
    const ImportResult g = importFile(QStringLiteral("a.gif"), gif, ctx());
    QVERIFY2(g.ok(), qPrintable(g.error));
    QCOMPARE(grayAt(g.elements[0].raster, 0, 0), 0);
}

void TestImport::bildExifDrehung() {
    const QByteArray jpeg = encodeImage(halfBlack(40, 20), "jpg", 100);
    QCOMPARE(exifOrientation(jpeg), 1);
    struct Case { int o, w, h; int blackX, blackY; };
    const Case cases[] = {
        {1, 40, 20, 5, 10}, {2, 40, 20, 35, 10}, {3, 40, 20, 35, 10}, {4, 40, 20, 5, 10},
        {5, 20, 40, 10, 5}, {6, 20, 40, 10, 5}, {7, 20, 40, 10, 35}, {8, 20, 40, 10, 35}};
    for (const Case& c : cases) {
        const QByteArray rotated = jpegWithExif(jpeg, c.o);
        QCOMPARE(exifOrientation(rotated), c.o);
        const DecodedImage d = decodeImage(rotated);
        QCOMPARE(d.raster.width(), c.w);
        QCOMPARE(d.raster.height(), c.h);
        QVERIFY2(grayAt(d.raster, c.blackX, c.blackY) < 60, qPrintable(QStringLiteral("Drehung %1").arg(c.o)));
        QVERIFY2(grayAt(d.raster, c.w - 1 - c.blackX, c.h - 1 - c.blackY) > 200, qPrintable(QStringLiteral("Drehung %1").arg(c.o)));
    }
    // Echte Maße: 40 × 20 hochkant bleibt 80 mm breit, Höhe folgt.
    const ImportResult r = importFile(QStringLiteral("a.jpg"), jpegWithExif(jpeg, 6), ctx());
    QVERIFY(near(r.elements[0].imageWidthMm, 80));
    QVERIFY(near(r.elements[0].imageHeightMm, 160));
}

void TestImport::bildExifInPngUndWebp() {
    const QByteArray png = encodeImage(halfBlack(40, 20), "png");
    const QByteArray tagged = pngWithExif(png, 6);
    QCOMPARE(exifOrientation(tagged), 6);
    const DecodedImage d = decodeImage(tagged);
    QCOMPARE(d.raster.width(), 20);
    QVERIFY(grayAt(d.raster, 10, 5) < 60);
    QByteArray webp = encodeImage(halfBlack(40, 20), "webp", 100);
    const QByteArray tiff = tiffOrientationBlock(8);
    QByteArray chunk("EXIF");
    const uint32_t n = uint32_t(tiff.size());
    chunk += char(n & 255); chunk += char(n >> 8 & 255); chunk += char(n >> 16 & 255); chunk += char(n >> 24);
    chunk += tiff;
    if (n & 1) chunk += char(0);
    webp += chunk;
    const uint32_t size = uint32_t(webp.size() - 8);
    webp[4] = char(size & 255); webp[5] = char(size >> 8 & 255); webp[6] = char(size >> 16 & 255); webp[7] = char(size >> 24);
    QCOMPARE(exifOrientation(webp), 8);
    const DecodedImage w = decodeImage(webp);
    QCOMPARE(w.raster.width(), 20);
}

void TestImport::bildAufloesungGibtMm() {
    QImage img = halfBlack(600, 300);
    img.setDotsPerMeterX(11811);
    img.setDotsPerMeterY(11811);
    const ImportResult r = importFile(QStringLiteral("a.png"), encodeImage(img, "png"), ctx());
    QVERIFY(r.ok());
    QVERIFY(near(r.elements[0].imageWidthMm, 600 / 300.0 * 25.4, 0.05));
}

void TestImport::bildZuGrossWirdVerkleinertUndGesagt() {
    QImage img(3200, 1600, QImage::Format_Grayscale8);
    img.fill(0);
    const ImportResult r = importFile(QStringLiteral("a.png"), encodeImage(img, "png"), ctx());
    QVERIFY(r.ok());
    QCOMPARE(r.elements[0].raster.width(), MAX_RASTER_SIDE);
    QCOMPARE(r.warnings.first(), QStringLiteral("Das Bild wurde von 3200 auf 1600 Pixel Breite verkleinert."));
    // 1000 mm Druckbreite passen nicht: Fläche minus Rand, mit Satz; außerdem reicht es in die Park-Ecke.
    QImage wide = halfBlack(1000, 900);
    wide.setDotsPerMeterX(2000);
    wide.setDotsPerMeterY(2000);
    const ImportResult w = importFile(QStringLiteral("a.png"), encodeImage(wide, "png"), ctx());
    QVERIFY(w.ok());
    QVERIFY(near(w.elements[0].imageWidthMm, Work::width() - 10));
    QVERIFY(w.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("verkleinert")));
    QVERIFY(w.warnings.join(QLatin1Char(' ')).contains(Work::parkName()));
}

void TestImport::bildKaputtIstEinSatz() {
    QVERIFY(importFile(QStringLiteral("a.png"), QByteArray("\x89PNG\r\n\x1a\nkaputt", 14), ctx()).error.contains(QStringLiteral("Bildformat")));
    QVERIFY(importFile(QStringLiteral("a.heic"), QByteArray("\0\0\0\x18" "ftypheic\0\0\0\0xxxx", 20), ctx()).error.contains(QStringLiteral("Bildformat")));
}

void TestImport::svgMitKaputtemEingebettetenBildWarnt() {
    const QByteArray png = encodeImage(halfBlack(10, 10), "png");
    const QString good = QString::fromLatin1(png.toBase64());
    const ImportResult r = importFile(QStringLiteral("a.svg"), svgDoc(SQUARE + S(R"( stroke="#000" fill="none"/><image x="50" y="0" width="30" height="30" href="data:image/png;base64,)") + good +
        S(R"("/><image x="0" y="50" width="30" height="30" href="data:image/png;base64,)") + QString::fromLatin1(b64(20)) + QStringLiteral("\"/>")), ctx());
    QVERIFY2(r.ok(), qPrintable(r.error));
    int images = 0;
    for (const Element& e : r.elements) if (e.isImage()) { ++images; QVERIFY(near(e.imageWidthMm, 30)); }
    QCOMPARE(images, 1);
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("eingebettetes Bild")));
}

// ---- PDF: nur als Bild ----
void TestImport::pdfWirdBildMitWarnung() {
    if (!QImageReader::supportedImageFormats().contains("pdf")) QSKIP("Qt-PDF-Bildformat fehlt in dieser Installation");
    const QByteArray file = pdfDoc("0 0 0 rg 72 72 72 72 re f", 2);
    QCOMPARE(detectKind(file), FileKind::Pdf);
    const ImportResult r = importFile(QStringLiteral("a.pdf"), file, ctx());
    QVERIFY2(r.ok(), qPrintable(r.error));
    QCOMPARE(r.elements.size(), size_t(1));
    QVERIFY(r.elements[0].isImage());
    QVERIFY(near(r.elements[0].imageWidthMm, 100, 0.5));
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("als Bild übernommen")));
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("Von 2 Seiten")));
    // Schwarzes Quadrat: 1 Zoll von links unten, 1 Zoll groß. Seite 100 mm, 10 px/mm.
    const Raster& ras = r.elements[0].raster;
    const double pxPerMm = double(ras.width()) / 100;
    QVERIFY(grayAt(ras, int(38 * pxPerMm), ras.height() - 1 - int(38 * pxPerMm)) < 40);
    QVERIFY(grayAt(ras, int(10 * pxPerMm), int(10 * pxPerMm)) > 215);
}

void TestImport::pdfKaputtIstEinSatz() {
    const ImportResult r = importFile(QStringLiteral("a.pdf"), enc("%PDF-1.5\nkaputt"), ctx());
    QVERIFY(!r.ok());
    QVERIFY(r.error.contains(QStringLiteral("PDF")));
}

// ---- Export ----
void TestImport::exportSvgGrundgeruest() {
    const Document d = sampleDoc();
    const QByteArray svg = exportSvg(d);
    QVERIFY(svg.contains("width=\"370mm\" height=\"360mm\" viewBox=\"0 0 370 360\""));
    QVERIFY(svg.contains("data-name=\"Schneiden\""));
    QVERIFY(svg.contains("stroke=\"#ff6b70\""));
    QVERIFY(svg.contains("fill=\"#4fd8b4\" fill-rule=\"evenodd\""));
    QVERIFY(svg.contains("M20 30L120 30L120 80L20 80Z"));
    Document t = d;
    t.title = QStringLiteral("A & <B>");
    QVERIFY(exportSvg(t).contains("<title>A &amp; &lt;B&gt;</title>"));
}

void TestImport::exportSvgRueckimport() {
    const Document d = sampleDoc();
    const VectorImport r = parseSvg(exportSvg(d));
    QCOMPARE(r.items.size(), size_t(3));
    // Der Export ordnet nach Ebenen: Gravieren (Kreis), Linie, Schneiden (Rechteck).
    const Box circle = *boundsOf(r.items[0].polys);
    const Box line = *boundsOf(r.items[1].polys);
    const Box rect = *boundsOf(r.items[2].polys);
    QVERIFY(near(rect.minX, 20, 1e-3));
    QVERIFY(near(rect.minY, 30, 1e-3));
    QVERIFY(near(rect.width(), 100, 1e-3));
    QVERIFY(near(rect.height(), 50, 1e-3));
    QVERIFY(near(circle.width(), 40, 2e-2));
    QVERIFY(near(circle.minX, 150, 2e-2));
    QVERIFY(near(line.width(), 60, 1e-3));
    QVERIFY(near(line.height(), 20, 1e-3));
    QVERIFY(isClosed(r.items[2].polys[0]));
    QVERIFY(r.items[0].fill);
    QVERIFY(!r.items[2].fill);
    QCOMPARE(*r.items[2].layerKey, QStringLiteral("#ff6b70"));
    // Über den ganzen Weg bleiben Abstände zueinander erhalten.
    const ImportResult full = importFile(QStringLiteral("x.svg"), exportSvg(d), ctx());
    QVERIFY2(full.ok(), qPrintable(full.error));
    QVERIFY(near(full.elements[2].transform.y - full.elements[0].transform.y, 0, 2e-2));
}

void TestImport::exportSvgBildRueckimport() {
    Document d;
    QImage img = halfBlack(20, 10);
    Element e = newElement(d.layers[0].id, QStringLiteral("Bild"));
    e.transform = Transform{30, 40};
    e.raster = rasterFromImage(img);
    e.imageWidthMm = 60;
    e.imageHeightMm = 30;
    d.elements = {e};
    const QByteArray svg = exportSvg(d);
    const VectorImport r = parseSvg(svg);
    QCOMPARE(r.images.size(), size_t(1));
    QCOMPARE(r.images[0].box, (Box{30, 40, 90, 70}));
    const ImportResult full = importFile(QStringLiteral("x.svg"), svg, ctx());
    QVERIFY2(full.ok(), qPrintable(full.error));
    QVERIFY(full.elements[0].isImage());
    QVERIFY(near(full.elements[0].imageWidthMm, 60));
    QCOMPARE(full.elements[0].raster.width(), 20);
    QCOMPARE(grayAt(full.elements[0].raster, 2, 5), 0);
    QCOMPARE(grayAt(full.elements[0].raster, 18, 5), 255);
}

void TestImport::exportDxfRueckimport() {
    const Document d = sampleDoc();
    const QByteArray dxf = exportDxf(d);
    QVERIFY(dxf.contains("$INSUNITS\n70\n4\n"));
    QCOMPARE(detectKind(dxf), FileKind::Dxf);
    const VectorImport r = parseDxf(dxf);
    QCOMPARE(r.polys.size(), size_t(3));
    const Box rect = *boundsOf(r.polys[2]);
    QVERIFY(near(rect.width(), 100, 1e-3));
    QVERIFY(near(rect.height(), 50, 1e-3));
    QVERIFY(isClosed(r.polys[2]));
    const Box line = *boundsOf(r.polys[1]);
    QVERIFY(near(line.width(), 60, 1e-3));
    QVERIFY(near(line.height(), 20, 1e-3));
    QVERIFY(near(boundsOf(r.polys[0])->width(), 40, 2e-2));
    // Gesamtgröße: von x 20 bis 190, y 30 bis 120. Y steht im DXF nach oben, zurück wieder nach unten.
    const Box all = *boundsOf(r.polys);
    QVERIFY(near(all.width(), 170, 2e-2));
    QVERIFY(near(all.height(), 90, 2e-2));
    QVERIFY(near(rect.minY, 0, 2e-2));
    const ImportResult full = importFile(QStringLiteral("x.dxf"), dxf, ctx());
    QVERIFY2(full.ok(), qPrintable(full.error));
}

void TestImport::exportDxfEbenenNamen() {
    Document d;
    Layer l = newLayer(QStringLiteral("Grün & Füße ß"), 0xFF00FF00LL, LayerMode::Line);
    Layer l2 = newLayer(QStringLiteral("Grün & Füße ß"), 0xFF00FF00LL, LayerMode::Line);
    d.layers = {l, l2};
    Element a = newElement(l.id, QStringLiteral("a")), b = newElement(l2.id, QStringLiteral("b"));
    a.paths.add({{0, 0}, {1, 1}});
    b.paths.add({{0, 0}, {1, 1}});
    d.elements = {a, b};
    const QByteArray dxf = exportDxf(d);
    QVERIFY(dxf.contains("Gruen_Fuesse_ss\n"));
    QVERIFY(dxf.contains("Gruen_Fuesse_ss_2\n"));
    QVERIFY(dxf.contains("62\n3\n"));
}

void TestImport::exportWarnsaetze() {
    Document d = sampleDoc();
    Element pic = newElement(d.layers[0].id, QStringLiteral("Bild"));
    pic.raster = Raster::ofGray(1, 1, {0});
    pic.imageWidthMm = pic.imageHeightMm = 1;
    d.elements.push_back(pic);
    d.layers[1].visible = false;
    const QStringList w = exportWarnings(d, ExportFormat::Dxf);
    QCOMPARE(w.size(), 2);
    QCOMPARE(w[0], QStringLiteral("DXF kennt keine Bilder: 1 Bild fehlt in der Datei. Für Bilder SVG wählen."));
    QCOMPARE(w[1], QStringLiteral("1 Elemente auf ausgeblendeten Ebenen wurden nicht exportiert."));
    QCOMPARE(exportWarnings(d, ExportFormat::Svg).size(), 1);
    QVERIFY(!exportSvg(d).contains("data-name=\"Linie\""));
}

void TestImport::exportNurDiePlatte() {
    Document d = sampleDoc();
    d.plateCount = 2;
    d.elements[0].plate = 1;
    QVERIFY(!exportSvg(d, 0).contains("M20 30L"));
    QVERIFY(exportSvg(d, 1).contains("M20 30L"));
}

void TestImport::exportPngMm() {
    const Document d = sampleDoc();
    const QByteArray png = exportPng(d, std::nullopt, 10);
    QCOMPARE(detectKind(png), FileKind::Image);
    // Auflösung in der Datei: 10 px/mm = 254 dpi. Ganze Platte 370 × 360 mm.
    QVERIFY(near(*readDpi(png), 254, 0.1));
    QImage img;
    QVERIFY(img.loadFromData(png, "PNG"));
    QCOMPARE(img.width(), 3700);
    QCOMPARE(img.height(), 3600);
    const auto dark = [&](int x, int y) { return qGray(img.pixel(x, y)) < 245; };
    // Kante des Rechtecks: x = 20 mm, y = 30 bis 80 mm.
    QVERIFY(dark(200, 500));
    QVERIFY(!dark(180, 500));
    QVERIFY(!dark(220, 500));
    QVERIFY(dark(1200, 500));
    QVERIFY(dark(600, 300));
    QVERIFY(dark(600, 800));
    QVERIFY(!dark(600, 500));
    // Gefüllter Kreis, Mitte (170, 50).
    QVERIFY(qGray(img.pixel(1700, 500)) != 255);
    QVERIFY(qGray(img.pixel(1700, 280)) == 255);
    // Rückimport: die Auflösung führt zu echten mm, die Platte passt nur knapp nicht und wird genannt.
    const ImportResult r = importFile(QStringLiteral("p.png"), png, ctx());
    QVERIFY2(r.ok(), qPrintable(r.error));
    QVERIFY(r.elements[0].isImage());
    const double width = r.elements[0].imageWidthMm;
    QVERIFY(near(width, 370.0 * (360 - 10) / 360));
    QVERIFY(r.warnings.join(QLatin1Char(' ')).contains(QStringLiteral("verkleinert")));
}

void TestImport::exportPngBild() {
    Document d;
    Element e = newElement(d.layers[0].id, QStringLiteral("Bild"));
    e.transform = Transform{100, 100, 1, 1, 90};
    e.raster = rasterFromImage(halfBlack(20, 10));
    e.imageWidthMm = 40;
    e.imageHeightMm = 20;
    d.elements = {e};
    QImage img;
    QVERIFY(img.loadFromData(exportPng(d, std::nullopt, 5), "PNG"));
    // 90° um die linke obere Ecke (100, 100): zeigt nach unten, Bild links davon, schwarze Hälfte oben.
    QVERIFY(qGray(img.pixel(int(90 * 5), int(110 * 5))) < 40);
    QVERIFY(qGray(img.pixel(int(90 * 5), int(130 * 5))) > 215);
}

void TestImport::graustufenPng() {
    const Gray g{0, 128, 255, 10};
    const QByteArray png = encodeGrayPng(g, 2, 2);
    QImage img;
    QVERIFY(img.loadFromData(png, "PNG"));
    QCOMPARE(img.width(), 2);
    QCOMPARE(qGray(img.pixel(1, 0)), 128);
    QCOMPARE(qGray(img.pixel(1, 1)), 10);
}

#endif  // Q_MOC_RUN

QTEST_GUILESS_MAIN(TestImport)
#include "test_import.moc"
