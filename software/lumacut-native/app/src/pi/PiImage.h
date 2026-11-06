#pragma once
#include <QImage>
#include <QPointer>
#include <QQuickItem>
#include <QtQml/qqmlregistration.h>
#include <atomic>
#include <memory>

class QTimer;

/**
 * An image from the Pi as a GPU texture, aspect-fit into the item. Decoding runs off the UI thread.
 * gapMs > 0: live preview, the next request goes out that long after the last answer, because the Pi needs 1 to 2 s per picture.
 * It stops by itself while the item or the window is not visible, and with running = false. gapMs = 0: fetched once per path.
 *   PiImage { path: "/api/camera/snapshot?w=1280&h=720"; gapMs: 250; running: ... }
 * Results: hasImage, error, frameMs, frames, notFound (404).
 */
class PiImage : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString path READ path WRITE setPath NOTIFY pathChanged)
    Q_PROPERTY(int gapMs READ gapMs WRITE setGapMs NOTIFY pathChanged)
    Q_PROPERTY(bool running READ running WRITE setRunning NOTIFY pathChanged)
    Q_PROPERTY(bool hasImage READ hasImage NOTIFY stateChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY stateChanged)
    Q_PROPERTY(bool notFound READ notFound NOTIFY stateChanged)
    Q_PROPERTY(QString error READ error NOTIFY stateChanged)
    Q_PROPERTY(double frameMs READ frameMs NOTIFY stateChanged)
    Q_PROPERTY(int frames READ frames NOTIFY stateChanged)
public:
    explicit PiImage(QQuickItem* parent = nullptr);
    ~PiImage() override;
    QString path() const { return m_path; }
    void setPath(const QString& p);
    int gapMs() const { return m_gap; }
    void setGapMs(int v);
    bool running() const { return m_running; }
    void setRunning(bool v);
    bool hasImage() const { return !m_image.isNull() || m_hasTexture; }
    bool loading() const { return m_inFlight; }
    bool notFound() const { return m_notFound; }
    QString error() const { return m_error; }
    double frameMs() const { return m_frameMs; }
    int frames() const { return m_frames; }
    Q_INVOKABLE void reload();
protected:
    QSGNode* updatePaintNode(QSGNode* old, UpdatePaintNodeData*) override;
    void itemChange(ItemChange change, const ItemChangeData& data) override;
    void geometryChange(const QRectF& n, const QRectF& o) override;
signals:
    void pathChanged();
    void stateChanged();
private:
    bool shouldRun() const;
    void evaluate();
    void fetch();
    void takeDecoded(const QImage& img, double ms);
    QString m_path;
    int m_gap = 0;
    bool m_running = true;
    bool m_inFlight = false;
    bool m_done = false;       // one-shot fetched
    bool m_notFound = false;
    bool m_hasTexture = false;
    bool m_newImage = false;
    QImage m_image;
    QSize m_size;
    QString m_error;
    double m_frameMs = 0;
    int m_frames = 0;
    int m_gen = 0;
    QTimer* m_timer;
    std::shared_ptr<std::atomic<bool>> m_alive;
};
