#pragma once
/** Gespeicherte Laser-Werte für Material und Vorgang, wie `Material` in Design.kt. Die Liste selbst liegt auf dem Pi. */
#include "core/model.h"
#include <QString>
#include <optional>
#include <vector>

namespace lumacut {

struct Material {
    QString id;
    QString name;
    double thicknessMm = 0;
    QString process;   /// Gravieren, Markieren, Schneiden
    LayerMode mode = LayerMode::Line;
    double powerPct = 0, speed = 0;
    int passes = 1;
    double intervalMm = 0.1, depthPerPassMm = 0, zStepMm = 0;
    bool builtin = false;
    std::optional<DarknessCurve> darkness;

    /** Aus Stärke und Tiefe je Durchgang, wenn gesetzt, sonst die gespeicherten. */
    int effectivePasses() const;
    /** Die Fokus-Absenkung über alle Durchgänge bleibt in der Grenze. */
    Layer applyTo(const Layer& layer) const;
    /** Nur Startwerte; jedes Material muss auf der Maschine getestet werden. */
    static std::vector<Material> defaults();
};

}  // namespace lumacut
