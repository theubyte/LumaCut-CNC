#include "FrameStats.h"
#include <QQuickGraphicsConfiguration>
#include <QQuickWindow>
#include <rhi/qrhi.h>
#include <algorithm>

namespace {
constexpr size_t kKeep = 20000;
QJsonObject summary(std::vector<float> v) {
    if (v.empty()) return {{"n", 0}};
    std::sort(v.begin(), v.end());
    double sum = 0;
    for (float x : v) sum += x;
    const auto pct = [&](double q) { return double(v[std::min(v.size() - 1, size_t(q * double(v.size())))]); };
    return {{"n", double(v.size())}, {"avg", sum / double(v.size())}, {"p50", pct(0.5)}, {"p95", pct(0.95)}, {"p99", pct(0.99)}, {"max", double(v.back())}};
}
}

FrameStats::FrameStats(QQuickWindow* window, QObject* parent) : QObject(parent), m_window(window) {
    m_clock.start();
    // Direct connections: these run on the render thread, which is the point.
    connect(window, &QQuickWindow::beforeFrameBegin, this, [this] { m_frameStart = m_clock.nsecsElapsed(); }, Qt::DirectConnection);
    connect(window, &QQuickWindow::afterRendering, this, [this] {
        auto* sc = m_window->swapChain();
        if (!sc) return;
        const double gpu = sc->currentFrameCommandBuffer()->lastCompletedGpuTime();
        if (gpu > 0) { QMutexLocker l(&m_mutex); if (m_gpu.size() < kKeep) m_gpu.push_back(float(gpu * 1000.0)); }
    }, Qt::DirectConnection);
    connect(window, &QQuickWindow::afterFrameEnd, this, [this] {
        const qint64 now = m_clock.nsecsElapsed();
        QMutexLocker l(&m_mutex);
        if (m_cpu.size() < kKeep) m_cpu.push_back(float(double(now - m_frameStart) / 1e6));
        if (m_lastEnd >= 0 && m_frame.size() < kKeep) m_frame.push_back(float(double(now - m_lastEnd) / 1e6));
        m_lastEnd = now;
    }, Qt::DirectConnection);
}

QJsonObject FrameStats::snapshot(bool reset) {
    QJsonObject r;
    {
        QMutexLocker l(&m_mutex);
        r["frameMs"] = summary(m_frame);
        r["cpuMs"] = summary(m_cpu);
        r["gpuMs"] = summary(m_gpu);
        if (reset) { m_frame.clear(); m_cpu.clear(); m_gpu.clear(); m_lastEnd = -1; }
    }
    r["vsync"] = m_window->requestedFormat().swapInterval() != 0;
    r["timestamps"] = m_window->graphicsConfiguration().timestampsEnabled();
    if (QRhi* rhi = m_window->rhi()) {
        const QRhiDriverInfo info = rhi->driverInfo();
        r["gpuName"] = QString::fromUtf8(info.deviceName);
        r["gpuType"] = info.deviceType == QRhiDriverInfo::CpuDevice ? "software" : info.deviceType == QRhiDriverInfo::DiscreteDevice ? "discrete"
                     : info.deviceType == QRhiDriverInfo::IntegratedDevice ? "integrated" : "other";
        r["api"] = QString::fromLatin1(rhi->backendName());
        r["compute"] = rhi->isFeatureSupported(QRhi::Compute);
        r["maxTexture"] = rhi->resourceLimit(QRhi::TextureSizeMax);
    }
    return r;
}
