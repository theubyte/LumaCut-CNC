/**
 * Der Import darf nicht abstürzen und nie etwas Ungültiges liefern: abgeschnittene Dateien, zufällig veränderte Bytes,
 * gezielt bösartige Dateien (Verschachtelung, Bomben, absurde Zahlen). Fester Startwert, also wiederholbar.
 * LUMACUT_FUZZ_FACTOR=10 lässt die Zufallsrunden länger laufen.
 */
#include "core/export.h"
#include "core/import/import.h"
#include "core/import/vector.h"
#include "core/import/xml.h"

#include <QBuffer>
#include <QElapsedTimer>
#include <QImage>
#include <QImageWriter>
#include <QLoggingCategory>
#include <QtTest>
#include <cmath>
#include <random>

using namespace lumacut;
using namespace lumacut::import;

// moc versteht Rohstrings nicht; was es nicht zu sehen braucht, sieht es nicht.
#ifndef Q_MOC_RUN
namespace {

/** QStringLiteral verschluckt in moc die Rohstrings. */
QString S(const char* s) { return QString::fromUtf8(s); }

ImportContext ctx() { return importContextFor(Document{}); }

int fuzzFactor() {
    const int f = qEnvironmentVariableIntValue("LUMACUT_FUZZ_FACTOR");
    return f > 0 ? f : 1;
}

/** Was herauskommt, muss stimmen: entweder ein Satz oder endliche Geometrie auf bekannten Ebenen. */
bool sane(const ImportResult& r, const ImportContext& c, QString* why) {
    if (!r.ok()) {
        if (!r.elements.empty()) { *why = QStringLiteral("Fehler mit Elementen"); return false; }
        return true;
    }
    if (r.elements.empty()) { *why = QStringLiteral("gelungen, aber leer"); return false; }
    for (const Element& e : r.elements) {
        const auto layerKnown = [&](const QString& id) {
            for (const Layer& l : c.layers) if (l.id == id) return true;
            for (const Layer& l : r.layers) if (l.id == id) return true;
            return false;
        };
        if (!layerKnown(e.layerId)) { *why = QStringLiteral("unbekannte Ebene"); return false; }
        if (!std::isfinite(e.transform.x) || !std::isfinite(e.transform.y)) { *why = QStringLiteral("Lage nicht endlich"); return false; }
        for (const Pt& p : e.paths.allPoints()) if (!std::isfinite(p.x) || !std::isfinite(p.y)) { *why = QStringLiteral("Punkt nicht endlich"); return false; }
        if (e.isImage() && (!(e.imageWidthMm > 0) || !(e.imageHeightMm > 0))) { *why = QStringLiteral("Bild ohne Maß"); return false; }
    }
    return true;
}
#define CHECK_SANE(r, c) do { QString why; const ImportContext& cc = (c); QVERIFY2(sane((r), cc, &why), qPrintable(why)); } while (false)

QByteArray encodeImage(const QImage& img, const char* format) {
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    QImageWriter w(&buf, format);
    w.write(img);
    return out;
}

QByteArray stored(const std::vector<std::pair<QByteArray, QByteArray>>& files, bool deflate) {
    QByteArray body, central;
    const auto le16 = [](QByteArray& o, uint32_t v) { o += char(v & 255); o += char(v >> 8 & 255); };
    const auto le32 = [&](QByteArray& o, uint32_t v) { le16(o, v & 0xFFFF); le16(o, v >> 16); };
    for (const auto& [name, content] : files) {
        QByteArray data = content;
        uint32_t method = 0;
        if (deflate) { const QByteArray z = qCompress(content, 9); data = z.mid(6, z.size() - 10); method = 8; }
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

QByteArray sampleSvg(const QByteArray& png) {
    return QByteArray(R"svg(<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE svg PUBLIC "x" "y"><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:inkscape="i" width="100mm" height="50mm" viewBox="-5 -5 200 100">
<style>/* k */ .a{fill:#00ff00} .b,.c{stroke:rgb(255,0,0);fill:none} @media print { .d { fill: red !important } }</style>
<defs><linearGradient id="g"/></defs>
<g id="Ebene" inkscape:label="Ebene 1" transform="translate(1 2) rotate(30 5 5) scale(2 1) skewX(10) skewY(5) matrix(1 0 0 1 1 1)">
<rect x="1" y="2" width="30" height="20" rx="3" ry="2" class="a"/><circle cx="50" cy="20" r="10" class="c"/><ellipse cx="80" cy="20" rx="10" ry="5" style="fill:url(#g);stroke:none"/>
<line x1="0" y1="0" x2="10" y2="10" stroke="#abc" stroke-width="0"/><polyline points="1,1 2,5 3,3" fill="none" stroke="black"/><polygon points="10,10 20,10 15,20" fill="blue"/>
<path d="M0 0L10 0H20V10C20 20 10 20 10 10S0 0 0 10Q5 15 10 10T20 10a5 5 0 01 10 0Z M5 5h3v3h-3zM40 40A10 12 30 1 0 60 60l1e1-2.5.5 1" data-name="Teil &amp; Stück"/>
<g display="none"><rect width="9" height="9"/></g><text>Hallo</text><use xlink:href="#g"/>
<image x="5" y="5" width="20" height="20" xlink:href="data:image/png;base64,)svg") + png.toBase64() + R"("/></g></svg>)";
}
const char* const SAMPLE_DXF =
    "999\nkommentar\n0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nB1\n0\nLINE\n10\n0\n20\n0\n11\n5\n21\n0\n0\nINSERT\n2\nB2\n41\n2\n0\nENDBLK\n0\nBLOCK\n2\nB2\n0\nCIRCLE\n10\n1\n20\n1\n40\n1\n0\nENDBLK\n0\nENDSEC\n"
    "0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nB1\n10\n100\n20\n0\n41\n2\n42\n2\n50\n30\n0\nPOLYLINE\n70\n1\n0\nVERTEX\n10\n0\n20\n0\n42\n0.5\n0\nVERTEX\n10\n5\n20\n5\n0\nSEQEND\n0\nARC\n10\n0\n20\n0\n40\n3\n50\n0\n51\n90\n0\nELLIPSE\n10\n20\n20\n20\n11\n5\n21\n0\n40\n0.5\n"
    "0\nSPLINE\n71\n3\n40\n0\n40\n0\n40\n0\n40\n0\n40\n1\n40\n1\n40\n1\n40\n1\n10\n0\n20\n0\n10\n1\n20\n1\n10\n2\n20\n1\n10\n3\n20\n0\n0\nLWPOLYLINE\n90\n3\n70\n1\n10\n0\n20\n0\n42\n1\n10\n10\n20\n0\n10\n10\n20\n10\n0\nTEXT\n1\nHallo\n0\nHATCH\n0\nLINE\n10\n1\n20\n1\n11\n2\n21\n2\n0\nENDSEC\n0\nEOF\n";
const char* const SAMPLE_HPGL = "IN;SP1;PU0,0;PD400,0,400,800,0,800,0,0;PU;PA100,100;PD;PR10,10,-5,20;PU1000,1000;LBtext\x03;SP0;";
QByteArray sampleLbrn(const QByteArray& png) {
    return QByteArray(R"(<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="1.7" FormatVersion="1"><CutSetting type="Cut"><index Value="0"/></CutSetting>
<Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="2"><XForm>1 0 0 1 100 50</XForm></Shape><Shape Type="Ellipse" Rx="10" Ry="5"><XForm>0.7 0.7 -0.7 0.7 200 50</XForm></Shape>
<Shape Type="Path" VertID="1" PrimID="1"><XForm>1 0 0 1 0 0</XForm><VertList>V0 0c0x0c0y0c1x0c1y10V10 10c0x0c0y10c1x10c1y10V20 0</VertList><PrimList>B0 1L1 2L2 0</PrimList></Shape>
<Shape Type="Path" VertID="1" PrimID="1"><XForm>1 0 0 1 50 0</XForm></Shape><Shape Type="Group"><XForm>1 0 0 1 10 0</XForm><Children><Shape Type="Rect" W="10" H="10"/></Children></Shape>
<Shape Type="Text" Str="Hi"><XForm>1 0 0 1 20 0</XForm><BackupPath Type="Path"><VertList>V0 0V5 0V5 5</VertList><PrimList>LineClosed</PrimList></BackupPath></Shape><Shape Type="Text"/>
<Shape Type="Bitmap" W="30" H="20" Data=")") + png.toBase64() + R"("><XForm>1 0 0 1 50 40</XForm></Shape></LightBurnProject>)";
}
QByteArray sampleDisplays(const QByteArray& png) {
    return QByteArray(R"([
 {"id":"a","type":"PATH","x":10,"y":10,"angle":30,"scale":{"x":2,"y":3},"skew":{"x":3.141593,"y":0},"localSkew":{"x":3.141593,"y":0},"layerTag":"#fe0002","groupTags":["g1","g2"],"fill":{"visible":true},"dPath":"M0 0L20 0L20 10C10 10 5 5 0 10Z","name":"Teil"},
 {"id":"b","type":"RECT","x":50,"y":10,"width":10,"height":5,"radius":1,"layerTag":"#000000"},{"id":"c","type":"CIRCLE","x":70,"y":10,"width":8,"height":8,"layerColor":"#00ff00"},
 {"id":"d","type":"BITMAP","x":0,"y":30,"width":15,"height":15,"base64":"data:image/png;base64,)") + png.toBase64() + R"("},
 {"id":"e","type":"TEXT","x":0,"y":0,"width":30,"height":10,"text":"Hallo"},{"id":"f","type":"PATH","visible":false,"x":0,"y":0,"dPath":"M0 0L9 9"}])";
}

struct Sample {
    QString name;
    QByteArray bytes;
};
std::vector<Sample> samples() {
    QImage img(32, 16, QImage::Format_RGB32);
    for (int y = 0; y < img.height(); ++y) for (int x = 0; x < img.width(); ++x) img.setPixel(x, y, qRgb(x * 8, y * 16, (x ^ y) * 8));
    const QByteArray png = encodeImage(img, "png");
    const QByteArray displays = sampleDisplays(png);
    const QByteArray canvas = R"({"id":"c1","layerData":{"#fe0002":{"name":"Rot","order":1,"visible":true},"#000000":{"name":"Schwarz","order":2,"visible":false}}})";
    const QByteArray project = R"({"activeCanvasId":"c1","modules":{"canvases":["c1"]}})";
    const std::vector<std::pair<QByteArray, QByteArray>> files{{".format", "v2"}, {"project.json", project}, {"canvases/c1.json", canvas}, {"canvases/c1/displays-0.json", "{\"displays\":" + displays + "}"}};
    QByteArray pdf = "%PDF-1.5\n1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R/Resources<<>>>>\nendobj\n4 0 obj\n<</Length 24>>\nstream\n0 0 0 rg 10 10 20 20 re f\nendstream\nendobj\ntrailer\n<</Root 1 0 R>>\n";
    return {
        {QStringLiteral("a.svg"), sampleSvg(png)},
        {QStringLiteral("a.dxf"), QByteArray(SAMPLE_DXF)},
        {QStringLiteral("a.hpgl"), QByteArray(SAMPLE_HPGL)},
        {QStringLiteral("a.lbrn2"), sampleLbrn(png)},
        {QStringLiteral("a.xcs"), "{\"canvas\":[{\"id\":\"c1\",\"layerData\":{\"#fe0002\":{\"name\":\"Rot\",\"order\":1}},\"displays\":" + displays + "}],\"device\":{}}"},
        {QStringLiteral("a.xs"), stored(files, false)},
        {QStringLiteral("b.xs"), stored(files, true)},
        {QStringLiteral("a.png"), png},
        {QStringLiteral("a.jpg"), encodeImage(img, "jpg")},
        {QStringLiteral("a.webp"), encodeImage(img, "webp")},
        {QStringLiteral("a.bmp"), encodeImage(img, "bmp")},
        {QStringLiteral("a.gif"), QByteArray("GIF89a\x01\0\x01\0\x80\0\0\0\0\0\xFF\xFF\xFF,\0\0\0\0\x01\0\x01\0\0\x02\x02\x44\x01\0;", 35)},
        {QStringLiteral("a.pdf"), pdf},
    };
}

}  // namespace

#endif  // Q_MOC_RUN

class TestImportRobust : public QObject {
    Q_OBJECT
private slots:
    void initTestCase();
    void beispieleSindGueltig();
    void abgeschnitten();
    void zufaelligVeraendert();
    void zufaelligeZahlenInGueltigerStruktur();
    void reinerZufall();
    void tiefVerschachteltesXml();
    void tiefVerschachteltesJson();
    void entitaetenBombe();
    void dxfBlockBombeEndetMitSatz();
    void pfadBombeEndetMitSatz();
    void splineMitZuWenigPunkten();
    void riesigeKreiseSindEndlich();
    void bildMitAbsurdemKopf();
    void exifUndDpiMitKaputtenLaengen();
    void zipMitLuegendenVerzeichnis();
    void paralleleImporteStoerenSichNicht();
    void exportMitLeeremProjekt();
};

#ifndef Q_MOC_RUN
void TestImportRobust::initTestCase() {
    // libpng und Freunde kommentieren jede kaputte Datei; hier ist das gewollt.
    QLoggingCategory::setFilterRules(QStringLiteral("qt.gui.imageio*=false"));
}

void TestImportRobust::beispieleSindGueltig() {
    for (const Sample& s : samples()) {
        const ImportContext c = ctx();
        const ImportResult r = importFile(s.name, s.bytes, c);
        if (s.name == QLatin1String("a.pdf") && !r.ok()) continue;      // das Mini-PDF hat keine xref; Hauptsache kein Absturz
        QVERIFY2(r.ok(), qPrintable(s.name + QStringLiteral(": ") + r.error));
        CHECK_SANE(r, c);
    }
}

void TestImportRobust::abgeschnitten() {
    const ImportContext c = ctx();
    for (const Sample& s : samples()) {
        const qsizetype n = s.bytes.size();
        const qsizetype step = std::max<qsizetype>(1, n / (s.name.endsWith(QLatin1String(".pdf")) ? 60 : 400));
        int failed = 0, ok = 0;
        for (qsizetype len = 0; len < n; len += step) {
            const ImportResult r = importFile(s.name, s.bytes.left(len), c);
            CHECK_SANE(r, c);
            (r.ok() ? ok : failed)++;
        }
        qInfo("%s: %lld Bytes, abgeschnitten %d gelesen, %d mit Satz abgelehnt", qPrintable(s.name), qlonglong(n), ok, failed);
    }
}

void TestImportRobust::zufaelligVeraendert() {
    const ImportContext c = ctx();
    std::mt19937 rng(20261106);
    QElapsedTimer t;
    for (const Sample& s : samples()) {
        t.start();
        const bool slow = s.name.endsWith(QLatin1String(".pdf"));
        const int rounds = (slow ? 150 : 1500) * fuzzFactor();
        int failed = 0, ok = 0;
        for (int round = 0; round < rounds; ++round) {
            QByteArray b = s.bytes;
            const int edits = 1 + int(rng() % 4 == 0 ? rng() % 16 : rng() % 2);
            for (int e = 0; e < edits && !b.isEmpty(); ++e) {
                const qsizetype at = qsizetype(rng() % uint64_t(b.size()));
                switch (rng() % 5) {
                case 0: b[at] = char(rng() & 255); break;                                   // Byte
                case 1: b[at] = char(uint8_t(b[at]) ^ (1u << (rng() % 8))); break;          // Bit
                case 2: b.remove(at, qsizetype(rng() % 32)); break;                         // Loch
                case 3: b.insert(at, QByteArray(int(rng() % 8) + 1, char(rng() & 255))); break;
                default: {                                                                  // Stück woanders hin kopieren
                    const QByteArray part = b.mid(qsizetype(rng() % uint64_t(b.size())), qsizetype(rng() % 64));
                    b.insert(at, part);
                }
                }
            }
            const ImportResult r = importFile(s.name, b, c);
            CHECK_SANE(r, c);
            (r.ok() ? ok : failed)++;
        }
        qInfo("%s: %d Runden in %lld ms, %d gelesen, %d mit Satz abgelehnt", qPrintable(s.name), rounds, qlonglong(t.elapsed()), ok, failed);
    }
}

void TestImportRobust::zufaelligeZahlenInGueltigerStruktur() {
    // Gültige Syntax, aber Werte aus der Hölle: das trifft die Rechnungen statt des Einlesens.
    const ImportContext c = ctx();
    std::mt19937 rng(42);
    const char* const values[] = {"0", "-0", "1e308", "-1e308", "1e-320", "NaN", "Infinity", "1e400", "-1e400", "99999999999999999999", ".", "-", "1e", "0.000000001", "2147483648", "-2147483649", "4294967296", "1e9", ""};
    const auto v = [&] { return QString::fromLatin1(values[rng() % std::size(values)]); };
    for (int i = 0; i < 2000 * fuzzFactor(); ++i) {
        const QString svg = S(R"x(<svg xmlns="http://www.w3.org/2000/svg" width="%1mm" height="%2" viewBox="%3 %4 %5 %6"><g transform="scale(%7) rotate(%8)"><circle r="%9" stroke="#000"/>)x").arg(v(), v(), v(), v(), v(), v(), v(), v(), v()) +
            S(R"(<ellipse rx="%1" ry="%2" cx="%3" stroke="#00f"/><rect width="%4" height="%5" rx="%6"/><path d="M%7 %8 C%9 1 2 3 4 5" stroke="#000"/>)").arg(v(), v(), v(), v(), v(), v(), v(), v(), v()) +
            S(R"(<path d="M0 0 A%1 %2 %3 0 1 %4 %5" stroke="#000"/><polygon points="%6 %7 %8 %9 1 1"/></g></svg>)").arg(v(), v(), v(), v(), v(), v(), v(), v(), v());
        const ImportResult a = importFile(QStringLiteral("a.svg"), svg.toUtf8(), c);
        CHECK_SANE(a, c);
        const QString dxf = QStringLiteral("0\nSECTION\n2\nENTITIES\n0\nCIRCLE\n10\n%1\n20\n%2\n40\n%3\n0\nARC\n10\n%4\n20\n%5\n40\n%6\n50\n%7\n51\n%8\n0\nELLIPSE\n11\n%9\n").arg(v(), v(), v(), v(), v(), v(), v(), v(), v()) +
            QStringLiteral("21\n%1\n40\n%2\n41\n%3\n42\n%4\n0\nLWPOLYLINE\n70\n%5\n10\n%6\n20\n%7\n42\n%8\n10\n%9\n20\n1\n").arg(v(), v(), v(), v(), v(), v(), v(), v(), v()) +
            QStringLiteral("0\nSPLINE\n71\n%1\n10\n0\n20\n0\n10\n1\n20\n1\n40\n%2\n40\n%3\n40\n%4\n40\n%5\n40\n%6\n40\n%7\n0\nENDSEC\n0\nEOF\n").arg(v(), v(), v(), v(), v(), v(), v());
        const ImportResult b = importFile(QStringLiteral("a.dxf"), dxf.toUtf8(), c);
        CHECK_SANE(b, c);
        const QString lb = S(R"(<LightBurnProject><Shape Type="Rect" W="%1" H="%2" Cr="%3"><XForm>%4 0 0 %5 %6 %7</XForm></Shape><Shape Type="Ellipse" Rx="%8" Ry="%9"/></LightBurnProject>)").arg(v(), v(), v(), v(), v(), v(), v(), v(), v());
        const ImportResult d = importFile(QStringLiteral("a.lbrn"), lb.toUtf8(), c);
        CHECK_SANE(d, c);
        const QString xcs = S(R"({"canvas":[{"displays":[{"type":"RECT","x":"%1","y":"%2","width":"%3","height":"%4","angle":"%5","scale":{"x":"%6","y":"%7"},"skew":{"x":"%8","y":"%9"}},)").arg(v(), v(), v(), v(), v(), v(), v(), v(), v()) +
            S(R"({"type":"CIRCLE","width":"%1","height":"%2"},{"type":"BITMAP","width":"%3","height":"%4","base64":"x"}]}]})").arg(v(), v(), v(), v());
        const ImportResult e = importFile(QStringLiteral("a.xcs"), xcs.toUtf8(), c);
        CHECK_SANE(e, c);
    }
}

void TestImportRobust::reinerZufall() {
    const ImportContext c = ctx();
    std::mt19937 rng(7);
    const QStringList names{QStringLiteral("x"), QStringLiteral("x.svg"), QStringLiteral("x.dxf"), QStringLiteral("x.plt"), QStringLiteral("x.lbrn2"), QStringLiteral("x.xs"), QStringLiteral("x.xcs")};
    for (int i = 0; i < 3000 * fuzzFactor(); ++i) {
        QByteArray b(int(rng() % 512), 0);
        for (char& ch : b) ch = char(rng() & 255);
        const ImportResult r = importFile(names[qsizetype(rng() % uint64_t(names.size()))], b, c);
        CHECK_SANE(r, c);
    }
}

// ---- gezielt bösartig ----
void TestImportRobust::tiefVerschachteltesXml() {
    const QByteArray open = QByteArray("<svg>") + QByteArray("<g>").repeated(200000);
    const ImportResult r = importFile(QStringLiteral("a.svg"), open + "<rect width=\"1\" height=\"1\"/>" + QByteArray("</g>").repeated(200000) + "</svg>", ctx());
    QVERIFY(!r.ok());
    // Knapp unter der Grenze geht es, ohne dass der Stapel platzt.
    const ImportResult deep = importFile(QStringLiteral("a.svg"), QByteArray("<svg>") + QByteArray("<g>").repeated(XmlDoc::MAX_DEPTH - 2) + "<rect width=\"1\" height=\"1\"/>" + QByteArray("</g>").repeated(XmlDoc::MAX_DEPTH - 2) + "</svg>", ctx());
    QVERIFY2(deep.ok(), qPrintable(deep.error));
}

void TestImportRobust::tiefVerschachteltesJson() {
    const ImportResult r = importFile(QStringLiteral("a.xcs"), QByteArray("{\"canvas\":") + QByteArray("[").repeated(100000) + QByteArray("]").repeated(100000) + "}", ctx());
    QVERIFY(!r.ok());
    const QByteArray a = QByteArray("{\"canvas\":") + QByteArray("{\"a\":").repeated(5000) + "1" + QByteArray("}").repeated(5000) + "}";
    QVERIFY(!importFile(QStringLiteral("a.xcs"), a, ctx()).ok());
}

void TestImportRobust::entitaetenBombe() {
    QByteArray s = "<!DOCTYPE svg [<!ENTITY a \"xxxxxxxxxx\">";
    for (int i = 0; i < 30; ++i) s += "<!ENTITY b" + QByteArray::number(i) + " \"&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;\">";
    s += "]><svg xmlns=\"http://www.w3.org/2000/svg\"><rect width=\"1\" height=\"1\" data-name=\"&b29;\"/></svg>";
    const ImportResult r = importFile(QStringLiteral("a.svg"), s, ctx());
    QVERIFY2(r.ok(), qPrintable(r.error));
    QVERIFY(r.elements[0].kind.size() < 100);
}

void TestImportRobust::dxfBlockBombeEndetMitSatz() {
    // Jeder Block ruft den nächsten zehnmal auf: 10^8 Linien aus wenigen Zeilen.
    QByteArray s = "0\nSECTION\n2\nBLOCKS\n";
    for (int i = 0; i < 8; ++i) {
        s += "0\nBLOCK\n2\nB" + QByteArray::number(i) + "\n";
        for (int k = 0; k < 10; ++k) s += "0\nINSERT\n2\nB" + QByteArray::number(i + 1) + "\n";
        s += "0\nENDBLK\n";
    }
    s += "0\nBLOCK\n2\nB8\n0\nLINE\n10\n0\n20\n0\n11\n1\n21\n1\n0\nENDBLK\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n0\nINSERT\n2\nB0\n0\nENDSEC\n0\nEOF\n";
    QElapsedTimer t;
    t.start();
    const ImportResult r = importFile(QStringLiteral("a.dxf"), s, ctx());
    QVERIFY(!r.ok());
    QCOMPARE(r.error, QStringLiteral("DXF zu komplex"));
    QVERIFY(t.elapsed() < 120000);      // grob: Release wenige Sekunden, mit Asan länger
}

void TestImportRobust::pfadBombeEndetMitSatz() {
    // Kurze Kurven mit riesiger Länge: 400 Punkte je 12 Bytes.
    const QByteArray d = QByteArray("M0 0") + QByteArray("c9 9 9 9 9 9").repeated(200000);
    const ImportResult r = importFile(QStringLiteral("a.svg"), QByteArray("<svg xmlns=\"http://www.w3.org/2000/svg\"><path stroke=\"#000\" d=\"") + d + "\"/></svg>", ctx());
    QVERIFY(r.ok() || !r.error.isEmpty());
    const QByteArray many = QByteArray("<circle r=\"1e9\" stroke=\"#000\"/>").repeated(5000);
    const ImportResult b = importFile(QStringLiteral("a.svg"), QByteArray("<svg xmlns=\"http://www.w3.org/2000/svg\">") + many + "</svg>", ctx());
    QVERIFY(!b.ok());
}

void TestImportRobust::splineMitZuWenigPunkten() {
    // Grad 3, zwei Kontrollpunkte, Knotenzahl passt: las in Asan hinter dem Feld.
    const ImportContext c = ctx();
    const ImportResult r = importFile(QStringLiteral("a.dxf"), QByteArray("0\nSECTION\n2\nENTITIES\n0\nSPLINE\n71\n3\n40\n0\n40\n0\n40\n0\n40\n1\n40\n1\n40\n1\n10\n0\n20\n0\n10\n5\n20\n5\n0\nENDSEC\n0\nEOF\n"), c);
    QVERIFY2(r.ok(), qPrintable(r.error));
    CHECK_SANE(r, c);
}

void TestImportRobust::riesigeKreiseSindEndlich() {
    const QByteArray s = R"(<svg xmlns="http://www.w3.org/2000/svg"><circle r="1e300" stroke="#000"/><ellipse rx="1e308" ry="1e308" stroke="#000"/><path d="M0 0A1e300 1e300 0 0 1 1 1" stroke="#000"/></svg>)";
    const ImportContext c = ctx();
    const ImportResult r = importFile(QStringLiteral("a.svg"), s, c);
    CHECK_SANE(r, c);
}

void TestImportRobust::bildMitAbsurdemKopf() {
    QImage img(8, 8, QImage::Format_RGB32);
    img.fill(Qt::red);
    QByteArray png = encodeImage(img, "png");
    // Breite und Höhe im IHDR auf 2^31-1: Prüfsumme stimmt nicht, Größe ist absurd.
    png[16] = 0x7F; png[17] = char(0xFF); png[18] = char(0xFF); png[19] = char(0xFF);
    png[20] = 0x7F; png[21] = char(0xFF); png[22] = char(0xFF); png[23] = char(0xFF);
    QVERIFY(!importFile(QStringLiteral("a.png"), png, ctx()).ok());
    QByteArray bmp = encodeImage(img, "bmp");
    bmp[18] = char(0xFF); bmp[19] = char(0xFF); bmp[20] = char(0xFF); bmp[21] = 0x7F;
    QVERIFY(!importFile(QStringLiteral("a.bmp"), bmp, ctx()).ok());
}

void TestImportRobust::exifUndDpiMitKaputtenLaengen() {
    QByteArray j("\xFF\xD8\xFF\xE1\xFF\xFF" "Exif\0\0II*\0\xFF\xFF\xFF\xFF", 18);
    QCOMPARE(exifOrientation(j), 1);
    QByteArray p("\x89PNG\r\n\x1a\n\xFF\xFF\xFF\xFFpHYs", 16);
    QVERIFY(!readDpi(p));
    QCOMPARE(exifOrientation(p), 1);
    QByteArray w("RIFF\xFF\xFF\xFF\xFFWEBPEXIF\xFF\xFF\xFF\xFF", 20);
    QCOMPARE(exifOrientation(w), 1);
    QByteArray t = QByteArray("\xFF\xD8\xFF\xE1\0\x12" "Exif\0\0", 12) + QByteArray("II*\0\x08\0\0\0\xFF\xFF", 10);
    QCOMPARE(exifOrientation(t), 1);
}

void TestImportRobust::zipMitLuegendenVerzeichnis() {
    QByteArray z = stored({{"project.json", "{}"}, {"canvases/x", "y"}}, false);
    for (qsizetype i = 0; i < z.size(); ++i) {
        QByteArray b = z;
        b[i] = char(0xFF);
        const ImportResult r = importFile(QStringLiteral("a.xs"), b, ctx());
        QVERIFY(!r.ok());
    }
}

void TestImportRobust::paralleleImporteStoerenSichNicht() {
    std::vector<Sample> list = samples();
    std::vector<QFuture<ImportResult>> runs;
    const ImportContext c = ctx();
    for (int i = 0; i < 40; ++i) for (const Sample& s : list) runs.push_back(importFileAsync(s.name, s.bytes, c));
    for (QFuture<ImportResult>& f : runs) { f.waitForFinished(); QString why; QVERIFY(sane(f.result(), c, &why)); }
}

void TestImportRobust::exportMitLeeremProjekt() {
    const Document d;
    QVERIFY(exportSvg(d).contains("</svg>"));
    QVERIFY(exportDxf(d).endsWith("EOF\n"));
    QVERIFY(!exportPng(d, std::nullopt, 1).isEmpty());
    QVERIFY(!importFile(QStringLiteral("x.svg"), exportSvg(d), ctx()).ok());
}

#endif  // Q_MOC_RUN

QTEST_GUILESS_MAIN(TestImportRobust)
#include "test_import_robust.moc"
