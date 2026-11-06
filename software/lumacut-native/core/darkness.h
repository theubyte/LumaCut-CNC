#pragma once
/** Wie Darkness.kt: Tempo und Leistung gemeinsam bewegen, Schwärze-Kurve aus der Kamera-Kalibrierung. */
#include "core/model.h"
#include <QString>
#include <optional>
#include <utility>

namespace lumacut {

namespace CurveTools {
bool usable(const DarknessCurve& c);
/** Niedrigster und höchster gemessener Ton (nur bei usable). */
std::pair<double, double> toneRange(const DarknessCurve& c);
/** Ton für Energie je Fläche (Leistung % / mm/min beim Zeilenabstand der Kurve); auf den Messbereich begrenzt. */
double tone(const DarknessCurve& c, double energy);
double energyFor(const DarknessCurve& c, double tone);
}

namespace Darkness {
inline constexpr double RELIABLE_POWER_PCT = 8;
/** Langsamstes Tempo ohne Kurve. */
inline constexpr double SPEED_FLOOR = 300;

struct Result {
    Layer layer;
    std::optional<QString> limit;  /// fertiger Text für den Bediener, wenn eine Grenze griff
};
/** Mit gleicher Energie je mm erreichbare Tempi; die Leistung bleibt zwischen Zündgrenze und 100 %. */
std::pair<double, double> speedRange(const Layer& layer, double maxFeed);
Result atSpeed(const Layer& layer, double speed, double maxFeed);
/** Schieberstellung 0..1 (logarithmisch) des Tempos in speedRange. */
double speedPosition(const Layer& layer, double maxFeed);
double speedAt(const Layer& layer, double position, double maxFeed);
/** Ton der Ebene; nichts ohne Kurve oder bei Linien. */
std::optional<double> tone(const Layer& layer);
Result atTone(const Layer& layer, double tone, double maxFeed);
}

}  // namespace lumacut
