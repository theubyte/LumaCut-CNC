#pragma once
/**
 * Papier und Karton: Vorlagen für Verpackungen, Umschläge, Karten, Pop-ups, Deko und Körper. Rein wie die
 * Werkstatt-Generatoren: Werte hinein, Geometrie heraus. Die App legt das Ergebnis als Teile ins Projekt.
 *
 * Jede Vorlage ist von der gelaserten Seite aus gezeichnet, meist der späteren Außenseite. Bergfalz heißt: das Papier
 * geht von der gelaserten Seite weg, die Kante zeigt zu ihr. Ebenen: Papier gravieren, Papier markieren,
 * Papier falzen, Papier schneiden (in dieser Reihenfolge, Schneiden zuletzt) und der Bogen nur zur Anzeige.
 */
#include "core/werkstatt/generators.h"
#include <QVariantList>
#include <QVariantMap>
#include <functional>
#include <vector>

namespace lumacut::Papier {

using Werkstatt::GenError;
using Werkstatt::GenResult;
using Werkstatt::TextShaper;

inline const QString L_SHEET = QStringLiteral("Papierbogen (nur Anzeige)");
inline const QString L_ENGRAVE = QStringLiteral("Papier gravieren");
inline const QString L_MARK = QStringLiteral("Papier markieren");
inline const QString L_FOLD = QStringLiteral("Papier falzen");
inline const QString L_CUT = QStringLiteral("Papier schneiden");

/** Papiersorte mit Dicke und vorgeschlagenen, ungeprüften Laserwerten (Leistung %, Tempo mm/min). */
struct Stock {
    QString id, name;
    double t;
    double cutP, cutS, scoreP, scoreS, markP, markS, engP, engS;
};
const std::vector<Stock>& stocks();
/** Unbekannte Kennung: Fotokarton 300 g. */
const Stock& stockById(const QString& id);

/** Bogen; w = 0 heißt ganze Arbeitsfläche ohne Bogenrahmen. */
struct Sheet { QString id, name; double w, h; };
const std::vector<Sheet>& sheets();
const Sheet& sheetById(const QString& id);

/** Eine Vorlage: Formularbeschreibung wie die Werkstatt (num, seg, select, text, check, row, section, note). */
struct Template {
    QString id, group, title, blurb, icon;
    std::function<QVariantMap()> defaults;
    std::function<QVariantList(const QVariantMap&)> fields;
    std::function<GenResult(const QVariantMap&, const TextShaper&)> run;
};
const std::vector<Template>& templates();
const Template* findTemplate(const QString& id);
/** Gruppen in der Reihenfolge der Galerie. */
QStringList groupNames();

/** Motive für Fenster, Anhänger und Muster: geschlossener Umriss genau in [0,w] × [0,h]. */
QStringList motifIds();
QString motifLabel(const QString& id);
Poly motif(const QString& id, double w, double h);

enum class Edge { Straight, Wave, Scallop, Zigzag, Lace };
Edge edgeFromId(const QString& id);
struct EdgeLine { Poly line; std::vector<Poly> holes; };
/** Linie von a nach b; Wellen, Bögen und Zacken liegen links von a→b (am Schirm, y nach unten), also außen,
 *  wenn ein Umriss im Uhrzeigersinn läuft. Spitze: Bögen mit kleinen Löchern. */
EdgeLine decoratedEdge(Pt a, Pt b, Edge e, double size);

/** Schneeflocke: geschlossener Umriss um (0, 0), Durchmesser etwa d, aus dem Startwert seed. */
PolySet snowflake(double d, int seed, int arms = 6, double minWidth = 1.2);

}  // namespace lumacut::Papier
