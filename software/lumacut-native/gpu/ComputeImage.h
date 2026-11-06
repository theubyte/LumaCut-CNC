#pragma once
#include <QAtomicInteger>
#include <QFutureWatcher>
#include <QImage>
#include <QJsonObject>
#include <QQuickRhiItem>
#include <QtQml/qqmlregistration.h>

/**
 * Instant image preview: grey, contrast and brightness (the same arithmetic as adjustGray() in the job), then threshold,
 * ordered dither, or edge strength as a preliminary step for vectorising. Runs as a compute shader, or on all CPU cores
 * where the adapter has no compute (results agree to within one grey level).
 *
 * Not a job calculation. Error diffusion (Floyd-Steinberg, Jarvis, Stucki) is serial and has to match Android in the G-code
 * character for character, so that lives in core/image on the CPU. The job never uses the output of this class.
 *
 * Use as an item (setImage plus properties, redrawn on each change without readback) or without a window through
 * process(), which brings its own GPU device and is meant for a worker thread.
 */
struct ComputeParams {
    enum Mode { Grey = 0, Threshold = 1, Ordered = 2, Edges = 3 };
    int mode = Grey;
    int brightness = 0;      // -100..100
    int contrast = 0;        // -100..100
    int threshold = 128;     // 0..255
    bool invert = false;
};

class ComputeImage : public QQuickRhiItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(int mode READ mode WRITE setMode NOTIFY paramsChanged)              // 0 grey, 1 threshold, 2 ordered, 3 edges
    Q_PROPERTY(int brightness READ brightness WRITE setBrightness NOTIFY paramsChanged)
    Q_PROPERTY(int contrast READ contrast WRITE setContrast NOTIFY paramsChanged)
    Q_PROPERTY(int threshold READ threshold WRITE setThreshold NOTIFY paramsChanged)
    Q_PROPERTY(bool invert READ invert WRITE setInvert NOTIFY paramsChanged)
    Q_PROPERTY(bool continuous MEMBER m_continuous NOTIFY continuousChanged)       // benchmarks only
    Q_PROPERTY(QString backend READ backend)                                       // poll: "gpu" or "cpu", empty before the first frame
    Q_PROPERTY(QString benchResult READ benchResult NOTIFY benchFinished)          // JSON, after startBenchmark()
public:
    explicit ComputeImage(QQuickItem* parent = nullptr);
    ~ComputeImage() override;
    QQuickRhiItemRenderer* createRenderer() override;

    void setImage(const QImage& image);
    QImage image() const { return m_image; }
    /** Test content: a photo-like picture of about `megapixels`, built on a worker. */
    Q_INVOKABLE void loadTestImage(int megapixels);

    int mode() const { return m_p.mode; }
    void setMode(int v) { if (v != m_p.mode) { m_p.mode = v; paramsTouched(); } }
    int brightness() const { return m_p.brightness; }
    void setBrightness(int v) { if (v != m_p.brightness) { m_p.brightness = v; paramsTouched(); } }
    int contrast() const { return m_p.contrast; }
    void setContrast(int v) { if (v != m_p.contrast) { m_p.contrast = v; paramsTouched(); } }
    int threshold() const { return m_p.threshold; }
    void setThreshold(int v) { if (v != m_p.threshold) { m_p.threshold = v; paramsTouched(); } }
    bool invert() const { return m_p.invert; }
    void setInvert(bool v) { if (v != m_p.invert) { m_p.invert = v; paramsTouched(); } }
    QString backend() const { const int b = m_backend.loadRelaxed(); return b == 1 ? QStringLiteral("gpu") : b == 2 ? QStringLiteral("cpu") : QString(); }
    QString benchResult() const { return m_benchResult; }

    struct Result { QImage image; bool gpu = false; double uploadMs = 0, computeMs = 0, readbackMs = 0; QString error; };
    /** With its own device on the calling thread; falls back to the CPU. Output: Format_RGBA8888. */
    static Result process(const QImage& image, const ComputeParams& params);
    /** All cores. threads = 1 for the serial comparison. */
    static QImage processCpu(const QImage& image, const ComputeParams& params, int threads = 0);
    /** Same picture and steps through GPU and CPU on a worker; benchResult holds the numbers, benchFinished says when. */
    Q_INVOKABLE void startBenchmark(int megapixels);
    /** Largest channel difference between two pictures. */
    static int maxDifference(const QImage& a, const QImage& b);
    static QImage makeTestImage(int megapixels);

signals:
    void paramsChanged();
    void continuousChanged();
    void benchFinished();

private:
    friend class ComputeRenderer;
    void paramsTouched();
    void runCpuFallback();

    QImage m_image, m_cpuResult;
    quint64 m_imageVersion = 0, m_paramsVersion = 1, m_cpuVersion = 0;
    ComputeParams m_p;
    bool m_continuous = false, m_cpuBusy = false, m_cpuAgain = false;
    QString m_benchResult;
    QAtomicInt m_backend = 0;
    QFutureWatcher<QImage> m_cpuWatcher, m_loadWatcher;
    QFutureWatcher<QString> m_benchWatcher;
};
