/**
 * Papier und Karton: jede Vorlage mit Standardwerten und mit jeder Auswahl, Bögen und Ebenen, Laschen ohne
 * Überlappung, Maße von Faltschachtel und Umschlag, Motive, Ränder, Falzlinien, Schneeflocke, Kalender.
 */
#include "core/boolean.h"
#include "core/papier/papier.h"
#include "core/papier/papier_net.h"

#include <QtTest>
#include <cmath>

using namespace lumacut;
namespace P = lumacut::Papier;

namespace {
PolySet fakeShape(const QString& text, double h, bool) {
    PolySet out;
    for (int i = 0; i < text.size(); ++i) {
        if (text[i] == QLatin1Char(' ')) continue;
        const double x = i * h * 0.7, w = h * 0.6;
        out.add({Pt{x, 0}, Pt{x + w, 0}, Pt{x + w, h}, Pt{x, h}, Pt{x, 0}});
    }
    return out;
}
double areaOf(const PolySet& s) {
    double a = 0;
    for (PolyView v : s) {
        double q = 0;
        for (size_t i = 1; i < v.size(); ++i) q += v[i - 1].x * v[i].y - v[i].x * v[i - 1].y;
        a += q / 2;
    }
    return std::abs(a);
}
int rank(const QString& layer) {
    if (layer == P::L_SHEET) return 0;
    if (layer == P::L_ENGRAVE) return 1;
    if (layer == P::L_MARK) return 2;
    if (layer == P::L_FOLD) return 3;
    return 4;
}
}  // namespace

namespace W_ = lumacut::Werkstatt;
namespace {
/** Every part inside its sheet, layers in order, a cut part and the paper layers present. */
void checkResult(const W_::GenResult& r, const QVariantMap& p, const QString& id) {
    QVERIFY2(!r.parts.empty(), qPrintable(id));
    const P::Sheet& sh = P::sheetById(p.value("sheet").toString());
    const double W = sh.w > 0 ? sh.w : Work::width(), H = sh.w > 0 ? sh.h : Work::height();
    bool cut = false;
    for (const auto& part : r.parts) {
        if (part.layer != P::L_SHEET && !part.paths.empty()) cut = true;
        // The preview draws these on the GPU: no invalid numbers, no runaway point counts.
        for (const Pt& q : part.paths.allPoints()) QVERIFY2(std::isfinite(q.x) && std::isfinite(q.y), qPrintable(id + ": " + part.name));
        QVERIFY2(part.paths.pointCount() < 200000, qPrintable(QStringLiteral("%1: %2 hat %3 Punkte").arg(id, part.name).arg(part.paths.pointCount())));
        const auto b = boundsOf(part.paths);
        if (!b) continue;
        QVERIFY2(b->minX >= -0.05 && b->minY >= -0.05 && b->maxX <= W + 0.05 && b->maxY <= H + 0.05,
                 qPrintable(QStringLiteral("%1: %2 außerhalb des Bogens (%3, %4, %5, %6)").arg(id, part.name).arg(b->minX).arg(b->minY).arg(b->maxX).arg(b->maxY)));
    }
    // Ranks over the whole list never go down: Schneiden comes last in the project.
    int prev = 0;
    for (const auto& part : r.parts) { QVERIFY2(rank(part.layer) >= prev, qPrintable(id + QStringLiteral(": Ebenenfolge"))); prev = rank(part.layer); }
    QVERIFY2(cut, qPrintable(id + QStringLiteral(": nichts zum Lasern")));
    QStringList names;
    for (const auto& l : r.layers) names << l.name;
    for (const QString& n : {P::L_SHEET, P::L_ENGRAVE, P::L_MARK, P::L_FOLD, P::L_CUT}) QVERIFY2(names.contains(n), qPrintable(n));
    for (const auto& l : r.layers) if (l.name == P::L_SHEET) QVERIFY(!l.output); else QVERIFY(l.powerPct >= 8);
}
}  // namespace

class TestPapier : public QObject {
    Q_OBJECT
private slots:
    void catalogue() {
        const auto& t = P::templates();
        QVERIFY(t.size() >= 40);
        QSet<QString> ids;
        for (const P::Template& x : t) {
            QVERIFY2(!ids.contains(x.id), qPrintable(x.id));
            ids.insert(x.id);
            QVERIFY(P::groupNames().contains(x.group));
            // Every field the form shows has a default.
            const QVariantMap d = x.defaults();
            std::function<void(const QVariantList&)> walk = [&](const QVariantList& fs) {
                for (const QVariant& v : fs) {
                    const QVariantMap f = v.toMap();
                    if (f.value("type") == "row") { walk(f.value("fields").toList()); continue; }
                    if (f.value("type") == "section" || f.value("type") == "note") continue;
                    QVERIFY2(d.contains(f.value("key").toString()), qPrintable(x.id + ": " + f.value("key").toString()));
                }
            };
            walk(x.fields(d));
        }
        for (const QString& g : P::groupNames()) {
            int n = 0;
            for (const P::Template& x : t) n += x.group == g;
            QVERIFY2(n >= 4, qPrintable(g));
        }
    }
    void everyTemplateDefaults() {
        for (const P::Template& t : P::templates()) {
            const QVariantMap d = t.defaults();
            W_::GenResult r;
            try { r = t.run(d, fakeShape); }
            catch (const std::exception& e) { QFAIL(qPrintable(t.id + ": " + QString::fromUtf8(e.what()))); }
            checkResult(r, d, t.id);
            QVERIFY2(W_::plateCount(r) <= 3, qPrintable(t.id));
        }
    }
    void everyOption() {
        // Every choice of every select and segment runs: either a result or a sentence, never anything else.
        int runs = 0, refused = 0;
        for (const P::Template& t : P::templates()) {
            const QVariantMap d = t.defaults();
            QList<QVariantMap> choices;
            std::function<void(const QVariantList&)> walk = [&](const QVariantList& fs) {
                for (const QVariant& v : fs) {
                    const QVariantMap f = v.toMap();
                    if (f.value("type") == "row") { walk(f.value("fields").toList()); continue; }
                    if (f.value("type") == "select" || f.value("type") == "seg") choices << f;
                    if (f.value("type") == "check") choices << QVariantMap{{"key", f.value("key")}, {"options", QVariantList{QVariantMap{{"value", true}}, QVariantMap{{"value", false}}}}};
                }
            };
            walk(t.fields(d));
            for (const QVariantMap& c : choices) {
                if (c.value("key") == "stock") continue;   // below, once for all
                for (const QVariant& o : c.value("options").toList()) {
                    QVariantMap p = d;
                    p.insert(c.value("key").toString(), o.toMap().value("value"));
                    ++runs;
                    try {
                        const W_::GenResult r = t.run(p, fakeShape);
                        checkResult(r, p, t.id + "/" + c.value("key").toString() + "=" + o.toMap().value("value").toString());
                    } catch (const W_::GenError& e) {
                        ++refused;
                        if (qEnvironmentVariableIsSet("PAPIER_WHY")) qInfo().noquote() << t.id << c.value("key").toString() << o.toMap().value("value").toString() << e.what();
                    } catch (const std::exception& e) {
                        QFAIL(qPrintable(t.id + ": " + QString::fromUtf8(e.what())));
                    }
                }
            }
        }
        qInfo() << runs << "Läufe," << refused << "mit Begründung abgelehnt";
        QVERIFY(refused < runs / 10);
    }
    void stocksAndFolds() {
        const P::Template* t = P::findTemplate("faltschachtel");
        QVERIFY(t);
        for (const P::Stock& s : P::stocks()) {
            QVariantMap p = t->defaults();
            p.insert("stock", s.id);
            const W_::GenResult r = t->run(p, fakeShape);
            for (const auto& l : r.layers) if (l.name == P::L_CUT) { QCOMPARE(l.powerPct, std::max(8.0, s.cutP)); QCOMPARE(l.thicknessMm, s.t); }
        }
        // Perforation: about 2.5 of every 4 mm cut; scoring: the whole length.
        QVariantMap p = t->defaults();
        double scored = 0, perf = 0;
        for (const QString& f : {QStringLiteral("rillen"), QStringLiteral("perf")}) {
            p.insert("fold", f);
            const W_::GenResult r = t->run(p, fakeShape);
            double len = 0;
            for (const auto& part : r.parts)
                if (part.layer == P::L_FOLD)
                    for (PolyView v : part.paths) for (size_t i = 1; i < v.size(); ++i) len += std::hypot(v[i].x - v[i - 1].x, v[i].y - v[i - 1].y);
            (f == QLatin1String("rillen") ? scored : perf) = len;
        }
        QVERIFY(scored > 0);
        QVERIFY2(perf > scored * 0.5 && perf < scored * 0.7, qPrintable(QStringLiteral("%1 von %2").arg(perf).arg(scored)));
    }
    void faltschachtelSize() {
        const P::Template* t = P::findTemplate("faltschachtel");
        QVariantMap p = t->defaults();
        p.insert("sheet", "bett");
        p.insert("w", 50); p.insert("d", 35); p.insert("h", 80);
        const W_::GenResult r = t->run(p, fakeShape);
        const auto b = W_::partsBounds(r);
        QVERIFY(b);
        // 2 × 50 + 2 × 35 + glue tab 15 wide, 80 + 2 × (35 + tuck 21) high.
        QVERIFY2(std::abs(b->width() - 185) < 0.5 || std::abs(b->height() - 185) < 0.5, qPrintable(QString::number(b->width())));
        QVERIFY(std::abs(std::max(b->width(), b->height()) - 192) < 0.5);
    }
    void envelope() {
        const P::Template* t = P::findTemplate("umschlag");
        QVariantMap p = t->defaults();
        p.insert("format", "q120");
        p.insert("sheet", "bett");
        const W_::GenResult r = t->run(p, fakeShape);
        const auto b = W_::partsBounds(r);
        // 120 wide plus two side flaps of 14.4, 120 high plus top 50.4 and bottom 66.
        QVERIFY2(std::abs(b->width() - (120 + 2 * 14.4)) < 1, qPrintable(QString::number(b->width())));
        QVERIFY2(std::abs(b->height() - (120 + 120 * 0.42 + 120 * 0.55)) < 1, qPrintable(QString::number(b->height())));
        // DIN lang does not fit A4 and says so.
        p.insert("format", "dl");
        p.insert("sheet", "a4");
        QVERIFY_THROWS_EXCEPTION(W_::GenError, t->run(p, fakeShape));
    }
    void solidsTabsOnceAndNoOverlap() {
        // Edges: tetra 6, okta 12, ikosa 30, dodeka 30; seams = edges − (faces − 1).
        const QList<std::tuple<QString, int, int>> cases = {{"tetra", 4, 6}, {"okta", 8, 12}, {"ikosa", 20, 30}, {"dodeka", 12, 30}, {"prisma", 8, 18}, {"pyramide", 6, 10}};
        for (const auto& [kind, faces, edges] : cases) {
            const auto f = P::solidFaces(kind, 30, kind == "prisma" ? 6 : 5);
            QVERIFY2(int(f.size()) == faces, qPrintable(QStringLiteral("%1: %2 Flächen").arg(kind).arg(f.size())));
            P::Net n;
            const int tabs = P::facesNet(n, f, 8, true);
            QVERIFY2(int(n.mountain.size()) - tabs == faces - 1, qPrintable(QStringLiteral("%1: %2 Falze, %3 Laschen").arg(kind).arg(n.mountain.size()).arg(tabs)));
            QVERIFY2(tabs == edges - (faces - 1), qPrintable(QStringLiteral("%1: %2 Laschen").arg(kind).arg(tabs)));
            // Union area equals the sum of all faces and tabs: nothing overlaps.
            double sum = 0;
            std::vector<PolySet> sets;
            for (const Poly& s : n.solids) { PolySet ps; ps.add(s); sum += areaOf(ps); sets.push_back(ps); }
            const double uni = areaOf(booleanShapes(BooleanOp::Union, sets));
            QVERIFY2(std::abs(sum - uni) < sum * 0.002, qPrintable(QStringLiteral("%1: %2 gegen %3").arg(kind).arg(sum).arg(uni)));
        }
    }
    void cubeTabs() {
        const P::Template* t = P::findTemplate("wuerfel");
        const W_::GenResult r = t->run(t->defaults(), fakeShape);
        int folds = 0;
        for (const auto& part : r.parts) if (part.layer == P::L_FOLD) folds = int(part.paths.size());
        QCOMPARE(folds, 5 + 7);   // 5 between faces, 7 tab folds
    }
    void motifs() {
        for (const QString& id : P::motifIds()) {
            const Poly m = P::motif(id, 40, 30);
            QVERIFY2(m.size() >= 4 && m.front() == m.back(), qPrintable(id));
            double x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
            for (const Pt& q : m) { x0 = std::min(x0, q.x); y0 = std::min(y0, q.y); x1 = std::max(x1, q.x); y1 = std::max(y1, q.y); }
            QVERIFY2(std::abs(x0) < 0.01 && std::abs(y0) < 0.01 && std::abs(x1 - 40) < 0.01 && std::abs(y1 - 30) < 0.01, qPrintable(id));
            QVERIFY2(std::abs(P::areaP(m)) > 40 * 30 * 0.2, qPrintable(id));
            QVERIFY(!P::motifLabel(id).isEmpty());
        }
    }
    void edges() {
        for (P::Edge e : {P::Edge::Straight, P::Edge::Wave, P::Edge::Scallop, P::Edge::Zigzag, P::Edge::Lace}) {
            const P::EdgeLine el = P::decoratedEdge({0, 0}, {100, 0}, e, 10);
            QCOMPARE(el.line.front(), (Pt{0, 0}));
            QCOMPARE(el.line.back(), (Pt{100, 0}));
            for (const Pt& q : el.line) QVERIFY(q.y <= 1e-9);   // left of a→b is up on screen
            QCOMPARE(int(el.holes.size()), e == P::Edge::Lace ? 10 : 0);
        }
    }
    void snowflakeSeeds() {
        const PolySet a = P::snowflake(80, 7), b = P::snowflake(80, 7), c = P::snowflake(80, 8);
        QVERIFY(a == b);
        QVERIFY(!(a == c));
        const auto bb = boundsOf(a);
        QVERIFY(bb && bb->width() < 84 && bb->width() > 50);
    }
    void popupMotifStandsFree() {
        const P::Template* t = P::findTemplate("popupmotiv");
        QVariantMap p = t->defaults();
        p.insert("cover", false);
        const W_::GenResult r = t->run(p, fakeShape);
        // The mountain fold on the middle line stops at the motif: no fold piece crosses the motif's centre column.
        const double W = p.value("w").toDouble(), H = p.value("h").toDouble();
        bool crosses = false;
        Pt off{};
        for (const auto& part : r.parts) if (part.layer == P::L_CUT) { const auto b = boundsOf(part.paths); off = {b->minX, b->minY}; }
        for (const auto& part : r.parts)
            if (part.layer == P::L_FOLD)
                for (PolyView v : part.paths)
                    for (size_t i = 1; i < v.size(); ++i) {
                        const double y = v[i].y - off.y, xa = std::min(v[i - 1].x, v[i].x) - off.x, xb = std::max(v[i - 1].x, v[i].x) - off.x;
                        if (std::abs(y - H) < 0.01 && xa < W / 2 - 1 && xb > W / 2 + 1) crosses = true;
                    }
        QVERIFY(!crosses);
    }
    void calendar() {
        const P::Template* t = P::findTemplate("kalender");
        QVariantMap p = t->defaults();
        p.insert("month", 11); p.insert("year", 2026);
        const W_::GenResult r = t->run(p, fakeShape);
        QVERIFY2(r.notes.join(' ').contains("30 Tage"), qPrintable(r.notes.join(' ')));
        QVERIFY(r.notes.join(' ').contains("Sonntag"));
    }
    void namesMakeOnePieceEach() {
        const P::Template* t = P::findTemplate("tischkarte");
        QVariantMap p = t->defaults();
        p.insert("names", "Anna, Ben, Clara, Dora");
        const W_::GenResult r = t->run(p, fakeShape);
        int cuts = 0;
        for (const auto& part : r.parts) cuts += part.layer == P::L_CUT;
        QCOMPARE(cuts, 4);
        const P::Template* g = P::findTemplate("girlande");
        p = g->defaults();
        p.insert("text", "HALLO");
        cuts = 0;
        for (const auto& part : g->run(p, fakeShape).parts) cuts += part.layer == P::L_CUT;
        QCOMPARE(cuts, 5);
    }
    void sheetEqualsLetter() {
        const P::Template* t = P::findTemplate("faltbrief");
        QVariantMap p = t->defaults();
        const W_::GenResult r = t->run(p, fakeShape);
        // A4 on A4: only the ribbon holes are cut, not the sheet edge.
        int holes = 0;
        for (const auto& part : r.parts) if (part.layer == P::L_CUT) holes += int(part.paths.size());
        QCOMPARE(holes, 6);
    }
};

QTEST_GUILESS_MAIN(TestPapier)
#include "test_papier.moc"
