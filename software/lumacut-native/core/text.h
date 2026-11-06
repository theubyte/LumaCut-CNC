#pragma once
/**
 * Text als Umrisse über die Systemschriften (QPainterPath, Qt-Gui). sizeMm ist die Em-Größe wie auf Android.
 * Ergebnis in mm, y nach unten, Ecke oben links der Umrisse auf (0, 0), geschlossene Linienzüge (even-odd).
 * Zeilen trennt `\n`. Leerer Text ergibt nichts. Braucht eine laufende QGuiApplication; Aufruf aus Workern ist erlaubt.
 */
#include "core/model.h"
#include <QString>
#include <QStringList>

namespace lumacut {

/** Androids allgemeine Namen ("sans-serif", "serif", "monospace") und jede installierte Familie. Fehlt sie: Standardschrift. */
PolySet textPaths(const QString& text, double sizeMm, bool bold = false, const QString& family = QStringLiteral("sans-serif"), double tolMm = 0.02);
/** Installierte Familien, alphabetisch, ohne senkrechte Varianten. */
QStringList fontFamilies();

}  // namespace lumacut
