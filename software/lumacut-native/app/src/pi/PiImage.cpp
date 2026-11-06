#include "PiImage.h"
#include "PiClient.h"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QQuickWindow>
#include <QSGImageNode>
#include <QThreadPool>
#include <QTimer>

PiImage::PiImage(QQuickItem* parent) : QQuickItem(parent), m_timer(new QTimer(this)), m_alive(std::make_shared<std::atomic<bool>>(true)) {
    setFlag(ItemHasContents);
    m_timer->setSingleShot(true);
    connect(m_timer, &QTimer::timeout, this, &PiImage::fetch);
}
PiImage::~PiImage() { *m_alive = false; }
void PiImage::setPath(const QString& p) {
    if (p == m_path) return;
    m_path = p;
    m_done = false;
    m_notFound = false;
    ++m_gen;
    emit pathChanged();
    evaluate();
}
void PiImage::setGapMs(int v) { if (v != m_gap) { m_gap = v; emit pathChanged(); evaluate(); } }
void PiImage::setRunning(bool v) { if (v != m_running) { m_running = v; emit pathChanged(); evaluate(); } }
void PiImage::reload() { m_done = false; evaluate(); }

bool PiImage::shouldRun() const {
    if (!m_running || m_path.isEmpty() || !isVisible() || !window()) return false;
    const auto vis = window()->visibility();
    if (vis == QWindow::Hidden || vis == QWindow::Minimized) return false;
    return m_gap > 0 || !m_done;
}
void PiImage::evaluate() {
    if (!shouldRun()) { m_timer->stop(); return; }
    if (!m_inFlight && !m_timer->isActive()) m_timer->start(0);
}
void PiImage::itemChange(ItemChange change, const ItemChangeData& data) {
    QQuickItem::itemChange(change, data);
    if (change == ItemSceneChange && data.window) connect(data.window, &QWindow::visibilityChanged, this, &PiImage::evaluate);
    if (change == ItemVisibleHasChanged || change == ItemSceneChange) evaluate();
}
void PiImage::geometryChange(const QRectF& n, const QRectF& o) {
    QQuickItem::geometryChange(n, o);
    update();
}
void PiImage::fetch() {
    if (!shouldRun() || m_inFlight) return;
    m_inFlight = true;
    emit stateChanged();
    const int gen = m_gen;
    auto timer = std::make_shared<QElapsedTimer>();
    timer->start();
    QPointer<PiImage> self(this);
    PiClient::instance()->request("GET", m_path, {}, {}, 30000, [self, gen, timer](const PiReply& r) {
        if (!self) return;
        if (gen != self->m_gen) { self->m_inFlight = false; self->evaluate(); return; }
        if (!r.ok()) {
            self->m_inFlight = false;
            self->m_done = true;
            self->m_notFound = r.status == 404;
            self->m_error = r.status == 404 ? QString() : r.error;
            emit self->stateChanged();
            if (self->m_gap > 0 && self->shouldRun()) self->m_timer->start(3000);
            return;
        }
        // Decoding a 1280x720 JPEG or a whole scan takes long enough to matter: never on the UI thread.
        const QByteArray bytes = r.body;
        auto alive = self->m_alive;
        PiImage* raw = self;
        const double ms = double(timer->elapsed());
        QThreadPool::globalInstance()->start([bytes, alive, raw, ms] {
            QImage img = QImage::fromData(bytes);
            QMetaObject::invokeMethod(QCoreApplication::instance(), [alive, raw, img = std::move(img), ms] {
                if (*alive) raw->takeDecoded(img, ms);
            }, Qt::QueuedConnection);
        });
    });
}
void PiImage::takeDecoded(const QImage& img, double ms) {
    m_inFlight = false;
    m_done = true;
    if (img.isNull()) {
        m_error = QStringLiteral("Das Bild ließ sich nicht lesen.");
    } else {
        m_error.clear();
        m_image = img;
        m_newImage = true;
        m_frameMs = ms;
        ++m_frames;
        update();
    }
    emit stateChanged();
    if (m_gap > 0 && shouldRun()) m_timer->start(m_gap);
}
QSGNode* PiImage::updatePaintNode(QSGNode* old, UpdatePaintNodeData*) {
    auto* node = static_cast<QSGImageNode*>(old);
    if (m_newImage && !m_image.isNull()) {
        QSGTexture* tex = window()->createTextureFromImage(m_image);
        if (!node) {
            node = window()->createImageNode();
            node->setOwnsTexture(true);
            node->setFiltering(QSGTexture::Linear);
        }
        node->setTexture(tex);
        m_size = m_image.size();
        m_hasTexture = true;
        m_newImage = false;
        m_image = QImage();   // the copy lives on the GPU now
    }
    if (!node) return nullptr;
    const qreal s = qMin(width() / qMax(1, m_size.width()), height() / qMax(1, m_size.height()));
    const QSizeF fit = QSizeF(m_size) * s;
    node->setRect(QRectF((width() - fit.width()) / 2, (height() - fit.height()) / 2, fit.width(), fit.height()));
    return node;
}
