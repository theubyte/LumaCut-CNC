#pragma once
/**
 * G-Code wie android/core MarlinWriter.kt, für dieselbe Eingabe bis aufs Zeichen gleich
 * (tests/test_golden.cpp gegen Dateien, die der Kotlin-Code erzeugt hat).
 * Eine M3-I-Klammer für den ganzen Auftrag, jedes G1 trägt F und S0..255. Maschinen-X = Breite - x.
 * Nichts verlässt die Arbeitsfläche, auch kein Auslauf ohne Laser; nichts reicht in die Park-Ecke.
 * Aufruf nie im Oberflächen-Thread: Rasterzeilen laufen über den QThreadPool, die Funktion blockiert.
 */
#include "core/model.h"
#include <QByteArray>
#include <QString>
#include <stdexcept>

namespace lumacut {

/** Der Auftrag lässt sich nicht bauen. message() ist fertiger deutscher Text für den Bediener. */
class JobBuildError : public std::runtime_error {
public:
    explicit JobBuildError(const QString& message) : std::runtime_error(message.toStdString()), m_message(message) {}
    const QString& message() const { return m_message; }
private:
    QString m_message;
};

/** Beschleunigung (mm/s²) und Höchsttempo (mm/s): config.motion vom Pi, sonst Firmware. */
struct Motion {
    double accel = 500, speed = 150;
    double maxFeed() const { return speed * 60; }
    /** Anlauf ohne Laser für Vorschub mm/min: Weg v²/2a plus 15 % und 0,3 mm. */
    double runUp(double feed) const { const double v = feed / 60; return v * v / (2 * accel) * 1.15 + 0.3; }
};

struct WriteOptions {
    QByteArray appVersion = "dev";
    Motion motion;
};

/** UTF-8, Zeilenende \n. Wirft JobBuildError mit denselben Texten wie Android. */
QByteArray writeMarlin(const Document& doc, const WriteOptions& options = {});

}  // namespace lumacut
