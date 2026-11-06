#include "SegmentsItem.h"
#include <QFile>
#include <QMatrix4x4>
#include <QQuickWindow>
#include <rhi/qrhi.h>
#include <rhi/qshader.h>
#include <cmath>
#include <memory>

namespace {
QShader loadShader(const char* path) {
    QFile f(QString::fromLatin1(path));
    return f.open(QIODevice::ReadOnly) ? QShader::fromSerialized(f.readAll()) : QShader();
}
struct Ubo {
    float mmToClip[16];
    float viewportPx[2];
    float halfWidthPx;
    float showTravel;
    float cutColor[4];
    float travelColor[4];
};
const float kCorners[] = {0, -1, 1, -1, 1, 1, 0, 1};
const quint16 kIndices[] = {0, 1, 2, 0, 2, 3};
}

class SegmentsRenderer : public QQuickRhiItemRenderer {
public:
    void initialize(QRhiCommandBuffer*) override {
        if (m_rhi != rhi()) { m_pipeline.reset(); m_rhi = rhi(); m_uploadedVersion = quint64(-1); }
        if (!m_pipeline) build();
        else if (m_rpFormat != renderTarget()->renderPassDescriptor()->serializedFormat()) m_pipeline.reset(), build();
    }
    void synchronize(QQuickRhiItem* item) override {
        auto* it = static_cast<SegmentsItem*>(item);
        m_item = it;
        m_visible = it->m_visible;
        m_bedW = it->m_bedW; m_bedH = it->m_bedH; m_zoom = it->m_zoom; m_pan = it->m_pan;
        m_showTravel = it->m_showTravel; m_cut = it->m_cut; m_travel = it->m_travel;
        m_dpr = it->window() ? it->window()->effectiveDevicePixelRatio() : 1.0;
        if (it->m_dataVersion != m_uploadedVersion) {
            m_pending = it->m_segs;                 // the GUI thread is blocked during synchronize
            m_pendingVersion = it->m_dataVersion;
            m_hasPending = true;
        }
    }
    void render(QRhiCommandBuffer* cb) override {
        auto* rub = m_rhi->nextResourceUpdateBatch();
        if (m_initBatch) { rub->merge(m_initBatch); m_initBatch->release(); m_initBatch = nullptr; }
        if (m_hasPending) {
            const qsizetype bytes = qsizetype(m_pending.size() * sizeof(GpuSegment));
            if (!m_instances || m_instances->size() < bytes) {
                m_instances.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::VertexBuffer, std::max<qsizetype>(bytes, 64)));
                m_instances->create();
            }
            if (bytes) rub->uploadStaticBuffer(m_instances.get(), 0, bytes, m_pending.data());
            m_count = int(m_pending.size());
            std::vector<GpuSegment>().swap(m_pending);
            m_uploadedVersion = m_pendingVersion;
            m_hasPending = false;
        }
        const QSize px = renderTarget()->pixelSize();
        const float w = px.width(), h = px.height();
        float zoom = float(m_zoom * m_dpr);
        float panX = float(m_pan.x() * m_dpr), panY = float(m_pan.y() * m_dpr);
        if (m_zoom <= 0) {                           // fit the whole bed
            zoom = std::min(w / float(m_bedW), h / float(m_bedH)) * 0.96f;
            panX = (w - float(m_bedW) * zoom) * 0.5f;
            panY = (h - float(m_bedH) * zoom) * 0.5f;
        }
        QMatrix4x4 m;
        m.translate(-1, m_rhi->isYUpInNDC() ? 1 : -1);
        m.scale(2.0f / w, (m_rhi->isYUpInNDC() ? -2.0f : 2.0f) / h);
        m.translate(panX, panY);
        m.scale(zoom, zoom);
        Ubo u{};
        memcpy(u.mmToClip, m.constData(), sizeof u.mmToClip);
        u.viewportPx[0] = w; u.viewportPx[1] = h;
        u.halfWidthPx = 0.5f * float(m_dpr);
        u.showTravel = m_showTravel ? 1 : 0;
        const auto color = [](float* o, const QColor& c) { o[0] = c.redF(); o[1] = c.greenF(); o[2] = c.blueF(); o[3] = c.alphaF(); };
        color(u.cutColor, m_cut); color(u.travelColor, m_travel);
        rub->updateDynamicBuffer(m_ubo.get(), 0, sizeof u, &u);

        const int n = std::clamp(m_visible <= 0 ? m_count : m_visible, 0, m_count);
        cb->beginPass(renderTarget(), QColor(0, 0, 0, 0), {1.0f, 0}, rub);
        if (n > 0 && m_instances) {
            cb->setGraphicsPipeline(m_pipeline.get());
            cb->setViewport({0, 0, w, h});
            cb->setShaderResources();
            const QRhiCommandBuffer::VertexInput inputs[] = {{m_corners.get(), 0}, {m_instances.get(), 0}};
            cb->setVertexInput(0, 2, inputs, m_indices.get(), 0, QRhiCommandBuffer::IndexUInt16);
            cb->drawIndexed(6, quint32(n));
        }
        cb->endPass();
    }

private:
    void build() {
        m_corners.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::VertexBuffer, sizeof kCorners));
        m_corners->create();
        m_indices.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::IndexBuffer, sizeof kIndices));
        m_indices->create();
        m_ubo.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(Ubo)));
        m_ubo->create();
        auto* rub = m_rhi->nextResourceUpdateBatch();
        rub->uploadStaticBuffer(m_corners.get(), kCorners);
        rub->uploadStaticBuffer(m_indices.get(), kIndices);
        m_srb.reset(m_rhi->newShaderResourceBindings());
        m_srb->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, m_ubo.get())});
        m_srb->create();
        m_pipeline.reset(m_rhi->newGraphicsPipeline());
        QRhiGraphicsPipeline::TargetBlend blend;
        blend.enable = true;
        blend.srcColor = QRhiGraphicsPipeline::One;
        blend.dstColor = QRhiGraphicsPipeline::OneMinusSrcAlpha;
        blend.srcAlpha = QRhiGraphicsPipeline::One;
        blend.dstAlpha = QRhiGraphicsPipeline::OneMinusSrcAlpha;
        m_pipeline->setTargetBlends({blend});
        m_pipeline->setShaderStages({{QRhiShaderStage::Vertex, loadShader(":/gpu/shaders/segments.vert.qsb")},
                                     {QRhiShaderStage::Fragment, loadShader(":/gpu/shaders/segments.frag.qsb")}});
        QRhiVertexInputLayout layout;
        layout.setBindings({{2 * sizeof(float)}, {sizeof(GpuSegment), QRhiVertexInputBinding::PerInstance}});
        layout.setAttributes({{0, 0, QRhiVertexInputAttribute::Float2, 0},
                              {1, 1, QRhiVertexInputAttribute::Float4, 0},
                              {1, 2, QRhiVertexInputAttribute::Float, 4 * sizeof(float)}});
        m_pipeline->setVertexInputLayout(layout);
        m_pipeline->setSampleCount(renderTarget()->sampleCount());
        m_pipeline->setShaderResourceBindings(m_srb.get());
        m_pipeline->setRenderPassDescriptor(renderTarget()->renderPassDescriptor());
        m_pipeline->create();
        m_rpFormat = renderTarget()->renderPassDescriptor()->serializedFormat();
        // The first frame's pass consumes it through a separate command.
        commandBufferFlush(rub);
    }
    void commandBufferFlush(QRhiResourceUpdateBatch* rub) { m_initBatch = rub; }

    QRhi* m_rhi = nullptr;
    SegmentsItem* m_item = nullptr;
    std::unique_ptr<QRhiBuffer> m_corners, m_indices, m_ubo, m_instances;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipeline;
    QVector<quint32> m_rpFormat;
    QRhiResourceUpdateBatch* m_initBatch = nullptr;
    std::vector<GpuSegment> m_pending;
    quint64 m_pendingVersion = 0, m_uploadedVersion = quint64(-1);
    bool m_hasPending = false, m_showTravel = true;
    int m_count = 0, m_visible = 0;
    qreal m_bedW = 370, m_bedH = 360, m_zoom = 0, m_dpr = 1;
    QPointF m_pan;
    QColor m_cut, m_travel;
};

SegmentsItem::SegmentsItem(QQuickItem* parent) : QQuickRhiItem(parent) { setAlphaBlending(true); }
QQuickRhiItemRenderer* SegmentsItem::createRenderer() { return new SegmentsRenderer; }

void SegmentsItem::setSegments(std::vector<GpuSegment> segs) {
    m_segs = std::move(segs);
    ++m_dataVersion;
    emit segmentsChanged();
    update();
}
void SegmentsItem::setZoom(qreal z) { if (z != m_zoom) { m_zoom = z; emit viewChanged(); update(); } }
void SegmentsItem::setPan(QPointF p) { if (p != m_pan) { m_pan = p; emit viewChanged(); update(); } }
void SegmentsItem::setVisibleCount(int n) { if (n != m_visible) { m_visible = n; emit visibleCountChanged(); update(); } }
void SegmentsItem::setShowTravel(bool v) { if (v != m_showTravel) { m_showTravel = v; emit viewChanged(); update(); } }

void SegmentsItem::loadBenchmark(int count) {
    std::vector<GpuSegment> s;
    s.reserve(size_t(count));
    const int rows = std::max(1, int(std::sqrt(double(count) / 4)));
    const int perRow = std::max(1, count / rows);
    const float w = float(m_bedW) - 40, h = float(m_bedH) - 80;
    for (int r = 0; r < rows && int(s.size()) < count; ++r) {
        const float y = 60 + h * float(r) / float(rows);
        const float dx = w / float(perRow);
        for (int i = 0; i < perRow && int(s.size()) < count; ++i) {
            const float x = 20 + dx * float(i);
            const float d = std::hypot(x - float(m_bedW) / 2, y - float(m_bedH) / 2) / 180.0f;
            const float p = std::clamp(0.5f + 0.5f * std::sin(d * 18.0f), 0.0f, 1.0f);
            s.push_back({x, y, x + dx, y, p < 0.05f ? 0.0f : p});
        }
    }
    setSegments(std::move(s));
}
