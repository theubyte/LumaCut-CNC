#pragma once
#include <QElapsedTimer>
#include <QJsonObject>
#include <QMutex>
#include <QObject>
#include <vector>

class QQuickWindow;

/**
 * Frame times measured on the render thread: distance between finished frames, CPU time of a frame on the render
 * thread (recording and present), and GPU time from QRhi timestamps. Snapshot from the GUI thread.
 * GPU time needs QQuickGraphicsConfiguration::setTimestamps(true) before the window is first shown.
 */
class FrameStats : public QObject {
    Q_OBJECT
public:
    explicit FrameStats(QQuickWindow* window, QObject* parent = nullptr);
    /** {frames, frameMs{avg,p50,p95,p99,max}, cpuMs{...}, gpuMs{...}, gpuName, gpuType, api, compute, timestamps, vsync}. */
    QJsonObject snapshot(bool reset);

private:
    QQuickWindow* m_window;
    QMutex m_mutex;
    std::vector<float> m_frame, m_cpu, m_gpu;
    QElapsedTimer m_clock;
    qint64 m_frameStart = 0, m_lastEnd = -1;
};
