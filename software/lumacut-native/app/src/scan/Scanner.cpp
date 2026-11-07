#include "Scanner.h"
#include <QBuffer>
#include <QDateTime>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTransform>
#include <QtConcurrent>
#include <cmath>
#include "Machine.h"
#include "MachineActions.h"
#include "PiClient.h"
#include "Toast.h"
#include "Workspace.h"
#include "doc/Document.h"
#include "gpu/StageItem.h"
#include "motiv/Editor.h"

namespace lc = lumacut;
namespace cam = lumacut::Camera;

namespace {
constexpr quint64 kLiveImageId = 0x5CA7'0000'0001ull;
constexpr int kLiveGapMs = 250;

QImage toArgb(const QImage& img, int w, int h) {
    QImage out = img.convertToFormat(QImage::Format_ARGB32);
    if (w > 0 && h > 0 && (out.width() != w || out.height() != h)) out = out.scaled(w, h, Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
    return out;
}
const uint32_t* bitsOf(const QImage& img) { return reinterpret_cast<const uint32_t*>(img.constBits()); }
QString nowText() { return QDateTime::currentDateTime().toString(QStringLiteral("HH:mm")); }
}  // namespace

Scanner::Scanner(QObject* parent) : QObject(parent) {
    m_liveTimer.setSingleShot(true);
    connect(&m_liveTimer, &QTimer::timeout, this, &Scanner::liveTick);
    // Another device scanned: take the new picture over.
    connect(Workspace::instance(), &Workspace::changed, this, [this] { fetchBackground(false); });
    connect(Editor::instance(), &Editor::backgroundChanged, this, &Scanner::backgroundChanged);
    loadCalibration();
    fetchBackground(false);
}

void Scanner::setRegion(const QString& r) {
    if (r == m_region) return;
    m_region = r;
    emit regionChanged();
}

void Scanner::loadCalibration() {
    PiClient::instance()->get(QStringLiteral("/api/camera/calibration"), PiCallback([this](const PiReply& r) {
        QString why;
        m_cal.reset();
        if (!r.ok()) why = QStringLiteral("Kamera-Kalibrierung nicht geladen: ") + r.error;
        else {
            const QJsonObject root = QJsonDocument::fromJson(r.body).object();
            m_cal = cam::Calibration::fromJson(root.value("android").toObject(), &why);
        }
        m_calNote = m_cal ? QString() : why + QStringLiteral(" Unter Maschine, Kalibrieren die Kopfkamera einmessen.");
        emit calibrationChanged();
        if (!m_cal && m_overlay) showOverlay();
    }));
}

QString Scanner::lock(const QVariant&) const {
    auto* m = Machine::instance();
    if (m_running) return QStringLiteral("Ein Scan läuft schon.");
    if (!m->online()) return QStringLiteral("Kein Kontakt zum Pi.");
    if (!m->cameraAvailable()) return QStringLiteral("Am Pi ist keine Kopfkamera angeschlossen.");
    if (!m_cal) return m_calNote;
    if (!m->homed()) return QStringLiteral("Erst referenzieren: ohne Referenz kennt der Pi die Kopfposition nicht.");
    if (m->jobActive()) return QStringLiteral("Es läuft gerade ein Auftrag.");
    return height().lock;
}

cam::ScanHeight Scanner::height() const {
    auto* m = Machine::instance();
    const QVariant s = m->status().value("workpiece_surface_z");
    const std::optional<double> surface = s.isNull() || !s.isValid() ? std::nullopt : std::optional<double>(s.toDouble());
    return cam::scanHeight(*m_cal, surface, m->z());
}

void Scanner::scan() {
    const double W = lc::Work::width(), H = lc::Work::height();
    if (m_region == QLatin1String("motif")) {
        const auto b = Document::instance()->doc().plateView().bounds();
        if (!b) { Toast::instance()->show(QStringLiteral("Auf der Platte ist noch kein Motiv. „Ganze Fläche“ wählen."), QStringLiteral("warn")); return; }
        startPlan({b->minX - 10, b->minY - 10, b->maxX + 10, b->maxY + 10}, QStringLiteral("Bereich unter dem Motiv"));
    } else if (m_region == QLatin1String("view")) {
        if (!m_view) { Toast::instance()->show(QStringLiteral("Erst das Motiv öffnen, dann den sichtbaren Ausschnitt scannen."), QStringLiteral("warn")); return; }
        startPlan(*m_view, QStringLiteral("Sichtbarer Ausschnitt"));
    } else {
        startPlan({0, 0, W, H}, QStringLiteral("Arbeitsfläche"));
    }
}
void Scanner::scanArea(double x0, double y0, double x1, double y1) {
    startPlan({std::min(x0, x1), std::min(y0, y1), std::max(x0, x1), std::max(y0, y1)}, QStringLiteral("Ausschnitt"));
}

void Scanner::startPlan(const lc::Box& area, const QString& what) {
    const QString why = lock();
    if (!why.isEmpty()) { Toast::instance()->show(why, QStringLiteral("warn")); return; }
    cam::TilePlan plan;
    try {
        plan = cam::plan(*m_cal, area);
    } catch (const std::exception& e) {
        Toast::instance()->show(QString::fromUtf8(e.what()), QStringLiteral("bad"));
        return;
    }
    const bool whole = area.width() >= lc::Work::width() - 1 && area.height() >= lc::Work::height() - 1;
    // A part scan goes into the earlier one, everything around it stays.
    std::vector<uint32_t> base;
    const QImage bg = Editor::instance()->background();
    const double ppm = cam::mosaicResolution(*m_cal);
    if (!whole && !bg.isNull() && bg.width() == int(lc::Work::width() * ppm) && bg.height() == int(lc::Work::height() * ppm)) {
        const QImage b = bg.convertToFormat(QImage::Format_ARGB32);
        base.assign(bitsOf(b), bitsOf(b) + size_t(b.width()) * size_t(b.height()));
    }
    m_heads = plan.heads;
    m_notes = plan.uncovered.isEmpty() ? QStringList() : QStringList{QStringLiteral("Nicht erreichbar: ") + plan.uncovered.join(QStringLiteral(", "))};
    m_what = what;
    const int n = int(m_heads.size());
    const cam::ScanHeight h = height();
    if (!h.z) { Toast::instance()->show(h.lock, QStringLiteral("warn")); return; }
    const auto mm = [](double v) { return QString::number(v, 'f', 1).replace(QLatin1Char('.'), QLatin1Char(',')); };
    const QString zText = h.jog ? QStringLiteral("Zuerst geht der Kopf von Z %1 auf die Scanhöhe Z %2, ").arg(mm(Machine::instance()->z()), mm(*h.z))
                                : QStringLiteral("Scanhöhe Z %1, ").arg(mm(*h.z));
    MachineActions::instance()->askGo(
        QVariantMap{{"title", QStringLiteral("Arbeitsplatz scannen?")},
                    {"detail", QStringLiteral("%1: %2dann fährt er %3 %4 ab, ohne Laser. Das Kamera-Licht schaltet der Pi. Nichts unter dem Kopf ablegen, Hände raus.")
                                   .arg(what, zText).arg(n).arg(n == 1 ? QStringLiteral("Bild") : QStringLiteral("Bilder"))},
                    {"kind", "move"}, {"okLabel", QStringLiteral("Scannen")}},
        [this, base = std::move(base), ppm, target = *h.z](bool yes) mutable {
            if (!yes) return;
            m_mosaic = std::make_shared<cam::Mosaic>(*m_cal, ppm, base.empty() ? nullptr : &base);
            m_running = true;
            m_cancel = false;
            m_step = 0;
            m_scanZ = target;
            m_lastResult.clear();
            m_stepText = QStringLiteral("Kopf auf Scanhöhe …");
            emit progressChanged();
            // Same distance to the material as at the calibration: same scale, sharp, and clear of objects.
            zTo(m_scanZ, [this](bool ok) { if (ok) nextStep(); });
        });
}

void Scanner::zTo(double target, std::function<void(bool)> done) {
    PiClient::instance()->get(QStringLiteral("/api/status"), PiCallback([this, target, done](const PiReply& r) {
        if (m_cancel) { fail(QStringLiteral("Scan abgebrochen. Der Hintergrund ist unverändert.")); done(false); return; }
        const QVariantList pos = r.map().value("position").toList();
        if (!r.ok() || pos.size() < 3) { fail(QStringLiteral("Scan abgebrochen: Z-Position unbekannt.")); done(false); return; }
        const double z = pos[2].toDouble();
        if (target > lc::Limits::Z_MAX_MM + 0.01) { fail(QStringLiteral("Scan abgebrochen: Material zu hoch für die Kamera.")); done(false); return; }
        const std::vector<double> steps = cam::jogSteps(target - z);
        if (steps.empty()) { done(true); return; }
        auto rest = std::make_shared<std::vector<double>>(steps);
        auto next = std::make_shared<std::function<void()>>();
        *next = [this, rest, next, target, done] {
            if (m_cancel) { fail(QStringLiteral("Scan abgebrochen. Der Hintergrund ist unverändert.")); done(false); return; }
            if (rest->empty()) {
                // What the Pi reports counts, not what was asked for.
                PiClient::instance()->get(QStringLiteral("/api/status"), PiCallback([this, target, done](const PiReply& r2) {
                    const QVariantList p = r2.map().value("position").toList();
                    if (p.size() < 3 || std::abs(p[2].toDouble() - target) > 0.11) {
                        fail(QStringLiteral("Scan abgebrochen: Z steht nicht auf der Scanhöhe Z %1.").arg(target, 0, 'f', 1));
                        done(false);
                        return;
                    }
                    done(true);
                }));
                return;
            }
            const double step = rest->front();
            rest->erase(rest->begin());
            MachineActions::instance()->run(QStringLiteral("jog"), QVariantMap{{"axis", "Z"}, {"distance", QString::number(step)}}, QVariantMap{{"quiet", true}, {"timeoutMs", 60000}},
                MachineActions::Done([this, next, done](bool ok, const QVariantMap& reply) {
                    if (!ok) { fail(QStringLiteral("Scan abgebrochen: Z-Fahrt abgelehnt (%1).").arg(reply.value("error").toString())); done(false); return; }
                    (*next)();
                }));
        };
        (*next)();
    }));
}

void Scanner::cancel() {
    if (!m_running) return;
    m_cancel = true;
    m_stepText = QStringLiteral("Wird abgebrochen …");
    emit progressChanged();
}

void Scanner::fail(const QString& why) {
    m_running = false;
    m_mosaic.reset();
    m_lastResult = why;
    emit progressChanged();
    Toast::instance()->show(why, QStringLiteral("bad"));
}

void Scanner::nextStep() {
    if (m_cancel) { fail(QStringLiteral("Scan abgebrochen. Der Hintergrund ist unverändert.")); return; }
    if (m_step >= int(m_heads.size())) { finish(); return; }
    const lc::Pt head = m_heads[size_t(m_step)];
    m_stepText = QStringLiteral("Bild %1 von %2").arg(m_step + 1).arg(m_heads.size());
    emit progressChanged();
    const lc::Pt m = lc::Work::toMachine(head);
    const double mx = std::clamp(m.x, 0.0, lc::Bed::width()), my = std::clamp(m.y, 0.0, lc::Bed::height());
    const lc::Pt at = lc::Work::fromMachine({mx, my});
    MachineActions::instance()->runApproved(QStringLiteral("moveto"), QVariantMap{{"x", std::round(mx * 100) / 100}, {"y", std::round(my * 100) / 100}},
        QVariantMap{{"quiet", true}, {"timeoutMs", 60000}}, [this, at](bool ok, const QVariantMap&) {
            if (!ok) { fail(QStringLiteral("Scan abgebrochen: der Kopf ist nicht angekommen.")); return; }
            if (m_cancel) { nextStep(); return; }
            // The Pi may lift Z for the XY move: back to the scan height, then let the gantry settle.
            zTo(m_scanZ, [this, at](bool okZ) { if (okZ) QTimer::singleShot(300, this, [this, at] { shot(at); }); });
        });
}

void Scanner::shot(lc::Pt at) {
    const int w = m_cal->photoWidth, h = m_cal->photoHeight;
    PiClient::instance()->get(QStringLiteral("/api/camera/snapshot?w=%1&h=%2").arg(w).arg(h), PiCallback([this, at, w, h](const PiReply& r) {
        if (!r.ok()) { fail(QStringLiteral("Scan abgebrochen: kein Kamerabild (%1).").arg(r.error)); return; }
        const QByteArray body = r.body;
        auto mosaic = m_mosaic;
        QtConcurrent::run([body, w, h, at, mosaic] {
            const QImage img = QImage::fromData(body);
            if (img.isNull()) return false;
            const QImage px = toArgb(img, w, h);
            mosaic->add(bitsOf(px), px.width(), px.height(), at);
            return true;
        }).then(this, [this](bool ok) {
            if (!ok) { fail(QStringLiteral("Scan abgebrochen: Kamerabild nicht lesbar.")); return; }
            ++m_step;
            nextStep();
        });
    }), 20000);
}

void Scanner::finish() {
    m_stepText = QStringLiteral("Mosaik wird berechnet …");
    emit progressChanged();
    auto mosaic = m_mosaic;
    QtConcurrent::run([mosaic] {
        const std::vector<uint32_t> px = cam::level(mosaic->pixels(), mosaic->width(), mosaic->height(), mosaic->pxPerMm());
        QImage img(mosaic->width(), mosaic->height(), QImage::Format_ARGB32);
        for (int y = 0; y < img.height(); ++y) std::memcpy(img.scanLine(y), px.data() + size_t(y) * size_t(img.width()), size_t(img.width()) * 4);
        QByteArray png;
        QBuffer buf(&png);
        buf.open(QIODevice::WriteOnly);
        img.save(&buf, "PNG");
        return std::make_pair(img, png);
    }).then(this, [this](std::pair<QImage, QByteArray> out) {
        const int n = int(m_heads.size());
        Editor::instance()->setBackground(out.first, true);
        m_bgStamp = QStringLiteral("gescannt %1").arg(nowText());
        m_mosaic.reset();
        m_stepText = QStringLiteral("Wird auf dem Pi gespeichert …");
        emit progressChanged();
        const QByteArray png = out.second;
        // The newest scan wins: on a conflict save once more on top of the other device's revision.
        auto save = std::make_shared<std::function<void(int, bool)>>();
        *save = [this, png, n, save](int base, bool again) {
            PiClient::instance()->request("PUT", QStringLiteral("/api/workspace/scan?base_revision=%1&by=Windows").arg(base), "image/png", png, 60000,
                PiCallback([this, n, save, again](const PiReply& r) {
                    if (r.status == 409 && !again) { (*save)(r.map().value("revision").toInt(), true); return; }
                    m_running = false;
                    if (!r.ok()) {
                        m_lastResult = QStringLiteral("Gescannt, aber nicht auf dem Pi gespeichert: %1").arg(r.error);
                        Toast::instance()->show(m_lastResult, QStringLiteral("bad"));
                    } else {
                        m_bgRev = r.map().value("revision").toInt();
                        m_lastResult = QStringLiteral("%1 gescannt (%2 %3), auf dem Pi gespeichert.").arg(m_what).arg(n).arg(n == 1 ? QStringLiteral("Bild") : QStringLiteral("Bilder"));
                        if (!m_notes.isEmpty()) m_lastResult += QLatin1Char(' ') + m_notes.join(QLatin1Char(' '));
                        Toast::instance()->show(m_lastResult, m_notes.isEmpty() ? QStringLiteral("ok") : QStringLiteral("warn"));
                    }
                    emit progressChanged();
                    emit backgroundChanged();
                }));
        };
        (*save)(Workspace::instance()->scanRevision(), false);
    });
}

// ---- Background from the Pi ----

void Scanner::reloadBackground() { fetchBackground(true); }

void Scanner::fetchBackground(bool force) {
    const int rev = Workspace::instance()->scanRevision();
    if (m_bgLoading || m_running) return;
    if (!force && (rev <= 0 || rev == m_bgRev)) return;
    m_bgLoading = true;
    PiClient::instance()->get(QStringLiteral("/api/workspace/scan"), PiCallback([this, rev, force](const PiReply& r) {
        m_bgLoading = false;
        if (r.status == 404) {
            if (force) Toast::instance()->show(QStringLiteral("Auf dem Pi liegt noch kein Scan. Im Motiv unter Kamera scannen."));
            return;
        }
        if (!r.ok()) { if (force) Toast::instance()->show(QStringLiteral("Scan nicht geladen: ") + r.error, QStringLiteral("bad")); return; }
        const QByteArray body = r.body;
        QtConcurrent::run([body] { return QImage::fromData(body); }).then(this, [this, rev, force](QImage img) {
            if (img.isNull()) { if (force) Toast::instance()->show(QStringLiteral("Scan nicht lesbar."), QStringLiteral("bad")); return; }
            auto* ed = Editor::instance();
            const bool show = ed->bgLoaded() ? ed->bgOn() : true;
            m_bgRev = rev;
            m_bgStamp = QStringLiteral("vom Pi, Stand %1, geladen %2").arg(rev).arg(nowText());
            ed->setBackground(std::move(img), show || force);
            emit backgroundChanged();
        });
    }), 30000);
}

// ---- Live picture ----

QString Scanner::snapshotPath(bool light) const {
    const int w = m_cal ? m_cal->photoWidth : 1280, h = m_cal ? m_cal->photoHeight : 720;
    return QStringLiteral("/api/camera/snapshot?w=%1&h=%2").arg(w).arg(h) + (light ? QString() : QStringLiteral("&light=keep"));
}
void Scanner::setLiveOn(bool v) {
    if (v == m_liveOn) return;
    m_liveOn = v;
    if (!v && m_overlay) { m_overlay = false; showOverlay(); }
    emit liveChanged();
    if (v && !m_liveBusy) liveTick();
}
void Scanner::setLiveOverlay(bool v) {
    if (v == m_overlay) return;
    m_overlay = v;
    if (v && !m_liveOn) { m_liveOn = true; if (!m_liveBusy) liveTick(); }
    emit liveChanged();
    showOverlay();
}
void Scanner::attachMotivStage(QQuickItem* stage) {
    m_stage = qobject_cast<StageItem*>(stage);
    showOverlay();
}

void Scanner::liveTick() {
    if (!m_liveOn || m_liveBusy) return;
    auto* m = Machine::instance();
    if (!m->online() || !m->cameraAvailable()) {
        m_liveError = !m->online() ? QStringLiteral("Kein Kontakt zum Pi.") : QStringLiteral("Am Pi ist keine Kopfkamera angeschlossen.");
        emit liveFrame();
        m_liveTimer.start(1500);
        return;
    }
    if (m->jobActive() || m_running) {
        // A job or the scan needs the camera and the head itself.
        m_liveNote = m_running ? QStringLiteral("Pause, der Scan braucht die Kamera.") : QStringLiteral("Pause während des Auftrags.");
        emit liveFrame();
        m_liveTimer.start(1500);
        return;
    }
    m_liveBusy = true;
    const lc::Pt before{m->workX(), m->workY()};
    const int w = m_cal ? m_cal->photoWidth : 0, h = m_cal ? m_cal->photoHeight : 0;
    PiClient::instance()->get(snapshotPath(m_liveLight), PiCallback([this, before, w, h](const PiReply& r) {
        if (!r.ok()) {
            m_liveBusy = false;
            m_liveError = r.error;
            emit liveFrame();
            if (m_liveOn) m_liveTimer.start(1500);
            return;
        }
        const QByteArray body = r.body;
        QtConcurrent::run([body, w, h] { const QImage img = QImage::fromData(body); return img.isNull() ? img : toArgb(img, w, h); })
            .then(this, [this, before](QImage img) {
                m_liveBusy = false;
                if (img.isNull()) m_liveError = QStringLiteral("Kamerabild nicht lesbar.");
                else {
                    auto* m = Machine::instance();
                    const lc::Pt after{m->workX(), m->workY()};
                    m_liveError.clear();
                    m_liveImage = std::move(img);
                    ++m_liveFrames;
                    // Only a picture taken standing still belongs to one head position.
                    const bool still = lc::dist(before, after) < 0.5;
                    m_liveNote = still ? QString() : QStringLiteral("Der Kopf fährt, das Bild auf der Bühne wartet.");
                    if (still) m_liveHead = after;
                    if (m_overlay && still) showOverlay();
                }
                emit liveFrame();
                if (m_liveOn) m_liveTimer.start(kLiveGapMs);
            });
    }), 15000);
}

void Scanner::showOverlay() {
    if (!m_stage) return;
    if (!m_overlay || !m_cal || m_liveImage.isNull()) {
        m_stage->removeImage(kLiveImageId);
        if (!m_overlayArea.isEmpty()) { m_overlayArea.clear(); emit liveFrame(); }
        return;
    }
    const QImage img = m_liveImage;
    const auto cal = *m_cal;
    const lc::Pt head = m_liveHead;
    QPointer<StageItem> stage = m_stage;
    QtConcurrent::run([img, cal, head] {
        const QImage px = img.convertToFormat(QImage::Format_ARGB32);
        const cam::Rectified r = cam::rectify(cal, bitsOf(px), px.width(), px.height(), head, 4);
        QImage out(r.width, r.height, QImage::Format_ARGB32);
        for (int y = 0; y < r.height; ++y) std::memcpy(out.scanLine(y), r.argb.data() + size_t(y) * size_t(r.width), size_t(r.width) * 4);
        return std::make_pair(out, r.area);
    }).then(this, [this, stage](std::pair<QImage, lc::Box> res) {
        if (!stage || !m_overlay) return;
        StageImage si;
        si.id = kLiveImageId;
        si.image = std::move(res.first);
        QTransform t;
        t.translate(res.second.minX, res.second.minY);
        t.scale(res.second.width(), res.second.height());
        si.transform = t;
        si.opacity = 0.85f;
        stage->setImage(std::move(si));
        const lc::Box& a = res.second;
        m_overlayArea = QStringLiteral("X %1–%2, Y %3–%4").arg(std::lround(a.minX)).arg(std::lround(a.maxX)).arg(std::lround(a.minY)).arg(std::lround(a.maxY));
        emit liveFrame();
    });
}
