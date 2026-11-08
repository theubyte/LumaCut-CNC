#pragma once
/** Intern: Netz-Baukasten für die Papier-Vorlagen (Flächen, Löcher, Falze, Laschen, Text) und Formularhelfer. */
#include "core/papier/papier.h"
#include <QStringList>
#include <cmath>
#include <numbers>
#include <optional>

namespace lumacut::Papier {

inline constexpr double PI = std::numbers::pi;
inline double rad(double deg) { return deg * PI / 180; }

inline Pt padd(Pt a, Pt b) { return {a.x + b.x, a.y + b.y}; }
inline Pt psub(Pt a, Pt b) { return {a.x - b.x, a.y - b.y}; }
inline Pt pmul(Pt a, double k) { return {a.x * k, a.y * k}; }
inline double plen(Pt a) { return std::sqrt(a.x * a.x + a.y * a.y); }
inline Pt punit(Pt a) { const double l = plen(a); return l > 0 ? Pt{a.x / l, a.y / l} : Pt{1, 0}; }
/** Links von a→b am Schirm (y nach unten). */
inline Pt leftN(Pt a, Pt b) { const Pt u = punit(psub(b, a)); return {u.y, -u.x}; }
inline Pt plerp(Pt a, Pt b, double t) { return {a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t}; }
inline Pt prot(Pt p, double ang, Pt c = {}) {
    const double s = std::sin(ang), co = std::cos(ang), x = p.x - c.x, y = p.y - c.y;
    return {c.x + x * co - y * s, c.y + x * s + y * co};
}
inline Pt polar(Pt c, double r, double ang) { return {c.x + r * std::cos(ang), c.y + r * std::sin(ang)}; }

Poly movedP(Poly p, double dx, double dy);
Poly rotatedP(Poly p, double ang, Pt c = {});
Poly closedP(Poly p);
Poly fitTo(const Poly& p, double x, double y, double w, double h);
double areaP(const Poly& p);
bool insideP(Pt q, const Poly& poly);
/** Kreis um c, Durchmesser dia. */
Poly circleP(Pt c, double dia);
Poly rectP(double x, double y, double w, double h, double r = 0);
/** Regelmäßiges n-Eck, Ecken im Uhrzeigersinn (am Schirm), eine Kante waagrecht oben. */
std::vector<Pt> regular(int n, double side, Pt c);
/** Bogen um c von a0 nach a1 (Bogenmaß, am Schirm im Uhrzeigersinn steigend). */
Poly arcP(Pt c, double r, double a0, double a1, double seg = 0.5);
/** Kreisbogen von a nach b mit Stichhöhe sag; positiv wölbt nach links von a→b. */
Poly bulge(Pt a, Pt b, double sag);
/** Teile der Strecke a-b außerhalb der Fläche poly. */
std::vector<std::pair<Pt, Pt>> outsideOf(Pt a, Pt b, const Poly& poly);
/** Teile des Linienzugs mit y < yMax. */
std::vector<Poly> aboveY(const Poly& line, double yMax);
/** Ein geschlossener Umriss aus mehreren vereinigten Flächen (die größte Kontur). */
Poly unionOutline(const std::vector<Poly>& polys);

/** Ein Teil des Bogens: Flächen werden vereinigt, Löcher abgezogen, dazu Schnitte, Falze, Gravur und Markierung. */
struct Net {
    QString name;
    std::vector<Poly> solids, holes;
    PolySet cuts, valley, mountain, engrave, mark;
    /** false: the outline only sets the size (a letter the size of the sheet); holes are still cut. */
    bool outputOutline = true;

    void solid(Poly p) { solids.push_back(closedP(std::move(p))); }
    void rect(double x, double y, double w, double h, double r = 0) { solid(rectP(x, y, w, h, r)); }
    void hole(Poly p) { holes.push_back(closedP(std::move(p))); }
    void cut(const Poly& p) { cuts.add(p); }
    /** Bergfalz (Standard): vom Betrachter weg. */
    void fold(Pt a, Pt b, bool mountainFold = true) { (mountainFold ? mountain : valley).add({a, b}); }
    void foldPath(const Poly& p, bool mountainFold = true) { (mountainFold ? mountain : valley).add(p); }
    /**
     * Lasche links von a→b mit Falz auf a-b. angA/angB: Schräge an den Enden in Grad zur Kante (45 = Gehrung).
     * Zu tiefe Laschen werden flacher, damit die Schrägen sich nicht kreuzen.
     */
    void tab(Pt a, Pt b, double depth, double angA = 45, double angB = 45, bool mountainFold = true, bool withFold = true);
    /** Text zentriert auf c, höchstens maxW breit, gedreht um rotDeg. Leerer Text: nichts. */
    void text(const TextShaper& sh, const QString& t, double h, Pt c, double maxW, double rotDeg = 0, bool bold = false);
    void engraveShape(const Poly& p) { engrave.add(closedP(p)); }
    void markLine(Pt a, Pt b) { mark.add({a, b}); }
    void markPoly(const Poly& p) { mark.add(p); }
    /** Fenster in Motivform, zentriert auf c. "none" oder leer: nichts. */
    void window(const QString& motifId, Pt c, double w, double h);

    void transform(const std::function<Pt(Pt)>& f);
    void move(double dx, double dy) { transform([&](Pt p) { return Pt{p.x + dx, p.y + dy}; }); }
    void append(const Net& o);
    std::optional<Box> bounds() const;
};

/** Laschen auf jede zweite Außenkante eines Netzes aus Flächen (Baum aus Flächen: dann hat jede Naht genau eine
 *  Lasche). Gemeinsame Kanten werden Bergfalze. Liefert die Zahl der Laschen. */
int facesNet(Net& n, const std::vector<std::vector<Pt>>& faces, double tabDepth, bool withTabs);

/** Flächen der Körpernetze: tetra, okta, ikosa, dodeka, prisma, pyramide (für Tests und die Vorlage). */
std::vector<std::vector<Pt>> solidFaces(const QString& kind, double a, int sides);

/** Gemeinsame Werte aller Vorlagen und das fertige Ergebnis mit Ebenen, Bögen und Hinweisen. */
GenResult finish(std::vector<Net> nets, const QVariantMap& p, QStringList notes = {}, QStringList warnings = {});

// ---- Formular ----
QVariantMap fNum(const QString& key, const QString& label, const QString& unit, double min, double max, double step = 1, int digits = 1, const QString& hint = {});
QVariantMap fMm(const QString& key, const QString& label, double min, double max, double step = 1, int digits = 1, const QString& hint = {});
QVariantMap fSeg(const QString& key, const QString& label, const QList<std::pair<QString, QString>>& opts, const QString& hint = {});
QVariantMap fSelect(const QString& key, const QString& label, const QList<std::pair<QString, QString>>& opts, const QString& hint = {});
QVariantMap fText(const QString& key, const QString& label, const QString& hint = {}, const QString& placeholder = {});
QVariantMap fCheck(const QString& key, const QString& label);
QVariantMap fRow(const QVariantList& f);
QVariantMap fSection(const QString& label);
QVariantMap fNote(const QString& t, const QString& tone = QStringLiteral("info"));
/** Motiv-Auswahl; withNone: "Keins" zuerst. */
QVariantMap fMotif(const QString& key, const QString& label, bool withNone = true);
QVariantMap fEdge(const QString& key, const QString& label);
/** Papier, Falzart, Bogen. */
QVariantList commonFields(bool folds = true);
QVariantMap commonDefaults(const QString& stock = QStringLiteral("karton300"), const QString& sheet = QStringLiteral("a4"));

double pd(const QVariantMap& p, const char* k);
int pi(const QVariantMap& p, const char* k);
QString ps(const QVariantMap& p, const char* k);
bool pb(const QVariantMap& p, const char* k);
/** Wirft GenError, wenn v nicht in [lo, hi] liegt. */
double need(double v, double lo, double hi, const QString& what);
/** Kommagetrennte Liste, ohne leere Einträge. */
QStringList listOf(const QString& s);
double thickness(const QVariantMap& p);

}  // namespace lumacut::Papier
