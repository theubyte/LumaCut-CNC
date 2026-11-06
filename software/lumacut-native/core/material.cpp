#include "core/material.h"

#include <algorithm>

namespace lumacut {

int Material::effectivePasses() const {
    return depthPerPassMm > 0 ? Document::passesFor(thicknessMm, depthPerPassMm) : passes;
}

Layer Material::applyTo(const Layer& layer) const {
    Layer l = layer;
    const int p = effectivePasses();
    l.mode = mode;
    l.powerPct = powerPct;
    l.speed = speed;
    l.passes = p;
    l.intervalMm = intervalMm;
    l.zStepMm = p > 1 ? std::min(zStepMm, Limits::MAX_FOCUS_DROP_MM / (p - 1)) : 0.0;
    l.materialName = name;
    l.thicknessMm = thicknessMm;
    l.depthPerPassMm = depthPerPassMm;
    l.darkness = darkness;
    return l;
}

std::vector<Material> Material::defaults() {
    const auto make = [](const char* name, double t, const char* process, LayerMode mode, double power, double speed, double depth = 0, double z = 0, double interval = 0.1) {
        Material m;
        m.id = newId();
        m.name = QString::fromUtf8(name);
        m.thicknessMm = t;
        m.process = QString::fromUtf8(process);
        m.mode = mode;
        m.powerPct = power;
        m.speed = speed;
        m.depthPerPassMm = depth;
        m.zStepMm = z;
        m.intervalMm = interval;
        return m;
    };
    return {
        make("Pappelsperrholz", 3, "Schneiden", LayerMode::Line, 90, 350, 1.5, 0.5),
        make("Pappelsperrholz", 3, "Gravieren", LayerMode::Fill, 25, 3000),
        make("MDF", 3, "Schneiden", LayerMode::Line, 95, 300, 1.5, 0.5),
        make("Acryl schwarz", 3, "Schneiden", LayerMode::Line, 100, 200, 1.0, 0.5),
        make("Leder", 2, "Gravieren", LayerMode::Fill, 18, 3000),
        make("Karton", 1, "Schneiden", LayerMode::Line, 45, 1200),
        make("Schiefer", 5, "Gravieren", LayerMode::Fill, 40, 2500, 0, 0, 0.08),
    };
}

}  // namespace lumacut
