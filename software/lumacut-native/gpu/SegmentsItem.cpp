#include "SegmentsItem.h"
#include <QMetaObject>
#include <QQuickWindow>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <climits>
#include <cmath>
#include "RhiCommon.h"

using namespace rhiutil;

namespace {
struct Ubo {
    float mmToClip[16];
    float viewportPx[2];
    float halfWidthPx, spotPx;
    float high[4], low[4], travel[4], sheet[4];
    float showTravel, opacity, pad[2];
};
struct ShowUbo {
    float mmToClip[16];
    float rect[4];
    float opacity, lod, pad[2];
};
// A raster job covers much of its own bounding box with burnt line; an outline hardly any.
constexpr double kRasterDensity = 0.10;
constexpr int kMapMaxSize = 4096;
constexpr double kMapMaxPxPerMm = 20.0;
constexpr qsizetype kUploadBytesPerFrame = 32 * 1024 * 1024;

/** Thin an over-long job on the worker: connected neighbours of one kind become one straight piece. */
void decimate(std::vector<GpuSegment>& s) {
    for (int pass = 0; pass < 8 && int(s.size()) > SegmentsItem::kMaxSegments; ++pass) {
        // Spread evenly: of every input segment, this share has to disappear into its predecessor.
        const double rate = double(s.size() - SegmentsItem::kMaxSegments) / double(s.size());
        const bool anyPower = pass > 0;     // first keep travel and burn apart, then force it
        double owed = 0;
        size_t out = 0, i = 0;
        while (i < s.size()) {
            GpuSegment m = s[i++];
            owed += rate;
            while (owed >= 1.0 && i < s.size()) {
                const GpuSegment& n = s[i];
                const bool sameKind = (m.power <= 0) == (n.power <= 0);
                const bool joined = std::abs(n.x0 - m.x1) < 1e-3f && std::abs(n.y0 - m.y1) < 1e-3f;
                if (!joined || (!sameKind && !anyPower)) break;
                m.x1 = n.x1; m.y1 = n.y1; m.power = std::max(m.power, n.power);
                ++i;
                owed += rate - 1.0;
            }
            s[out++] = m;
        }
        s.resize(out);
    }
    if (int(s.size()) > SegmentsItem::kMaxSegments) s.resize(SegmentsItem::kMaxSegments);   // not connected at all: the limit holds
}

std::shared_ptr<const SegmentsItem::Data> prepare(std::vector<GpuSegment> segs) {
    auto d = std::make_shared<SegmentsItem::Data>();
    d->sourceCount = int(std::min<size_t>(segs.size(), size_t(INT_MAX)));
    d->decimated = int(segs.size()) > SegmentsItem::kMaxSegments;
    if (d->decimated) decimate(segs);
    d->segs = std::move(segs);
    const int n = int(d->segs.size());
    d->chunkBoxes.resize(size_t((n + SegmentsItem::kChunk - 1) / SegmentsItem::kChunk) * 4);
    double burnt = 0;
    float allMinX = 1e30f, allMinY = 1e30f, allMaxX = -1e30f, allMaxY = -1e30f;
    for (int c = 0; c * SegmentsItem::kChunk < n; ++c) {
        float x0 = 1e30f, y0 = 1e30f, x1 = -1e30f, y1 = -1e30f;
        const int end = std::min(n, (c + 1) * SegmentsItem::kChunk);
        for (int i = c * SegmentsItem::kChunk; i < end; ++i) {
            const GpuSegment& g = d->segs[size_t(i)];
            x0 = std::min({x0, g.x0, g.x1}); x1 = std::max({x1, g.x0, g.x1});
            y0 = std::min({y0, g.y0, g.y1}); y1 = std::max({y1, g.y0, g.y1});
            if (g.power > 0) burnt += std::hypot(double(g.x1 - g.x0), double(g.y1 - g.y0));
        }
        float* b = d->chunkBoxes.data() + c * 4;
        b[0] = x0; b[1] = y0; b[2] = x1; b[3] = y1;
        allMinX = std::min(allMinX, x0); allMinY = std::min(allMinY, y0);
        allMaxX = std::max(allMaxX, x1); allMaxY = std::max(allMaxY, y1);
    }
    if (n > 0) { d->minX = allMinX; d->minY = allMinY; d->maxX = allMaxX; d->maxY = allMaxY; }
    const double area = std::max(1.0, double(d->maxX - d->minX) * double(d->maxY - d->minY));
    d->raster = n > 2000 && burnt * 0.1 / area >= kRasterDensity;
    return d;
}
}

/** Accumulated coverage of a prefix of the job, rendered by the GPU, a slice per frame. */
struct BurnMap {
    std::unique_ptr<QRhiTexture> tex;
    std::unique_ptr<QRhiTextureRenderTarget> rtClear, rtKeep;
    std::unique_ptr<QRhiRenderPassDescriptor> rp;
    std::unique_ptr<QRhiShaderResourceBindings> showSrb;
    std::unique_ptr<QRhiBuffer> showUbo;
    int built = 0;
    bool needClear = true;
    void reset() { built = 0; needClear = true; }
};

class SegmentsRenderer : public QQuickRhiItemRenderer {
public:
    void initialize(QRhiCommandBuffer*) override {
        if (m_rhi != rhi()) { releaseAll(); m_rhi = rhi(); m_uploaded = 0; m_uploadedData = nullptr; }
        const auto fmt = renderTarget()->renderPassDescriptor()->serializedFormat();
        if (!m_pipeline || m_rpFormat != fmt) { buildPipelines(); m_rpFormat = fmt; }
    }

    void synchronize(QQuickRhiItem* item) override {
        auto* it = static_cast<SegmentsItem*>(item);
        m_item = it;
        m_view = it->snapshot();
        m_visibleWanted = it->m_visible;
        m_showTravel = it->m_showTravel;
        m_useBurnMap = it->m_burnMap;
        m_lineWidth = it->m_lineWidth; m_spotMm = it->m_spotMm; m_pendingOpacity = it->m_pendingOpacity;
        m_cut = it->m_cut; m_low = it->m_low; m_travel = it->m_travel;
        m_data = it->m_data;
        const QByteArray look = QByteArray::number(m_showTravel) + m_cut.name(QColor::HexArgb).toLatin1() + m_low.name(QColor::HexArgb).toLatin1()
                              + m_travel.name(QColor::HexArgb).toLatin1() + m_view.sheet.name(QColor::HexArgb).toLatin1() + QByteArray::number(m_spotMm);
        if (look != m_look) { m_look = look; m_done.reset(); m_all.reset(); }
    }

    void render(QRhiCommandBuffer* cb) override {
        const QSize px = renderTarget()->pixelSize();
        auto* rub = m_rhi->nextResourceUpdateBatch();
        const int count = m_data ? int(m_data->segs.size()) : 0;
        uploadSlice(rub, count);

        const int visible = m_visibleWanted < 0 ? m_uploaded : std::clamp(m_visibleWanted, 0, m_uploaded);
        const double spotPx = m_spotMm * m_view.zoom;
        const bool raster = m_data && m_data->raster;
        ensureMapSize();
        const bool useMap = raster && m_useBurnMap && m_mapZoom > 0 && m_view.zoom <= m_mapZoom;

        // Uniforms for this frame: slot 0 finished part, slot 1 what is to come, slot 2 into the map.
        writeUbo(rub, 0, mmToClip(m_rhi, px, m_view.zoom, m_view.panX, m_view.panY), QSizeF(px), raster ? spotPx : 0, 1.0f);
        writeUbo(rub, 1, mmToClip(m_rhi, px, m_view.zoom, m_view.panX, m_view.panY), QSizeF(px), raster ? spotPx : 0, float(m_pendingOpacity));
        m_bed.prepare(rub, m_view, px);

        int building = 0;
        if (useMap) {
            ensureMaps(rub);
            writeMapUbo(rub);
            building += buildMap(cb, rub, m_done, visible);
            const bool wantAll = m_pendingOpacity > 0 && visible < count;
            if (wantAll) building += buildMap(cb, rub, m_all, m_uploaded);
            if (!rub) rub = m_rhi->nextResourceUpdateBatch();
            writeShowUbo(rub, m_done, px, 1.0f);
            if (wantAll) writeShowUbo(rub, m_all, px, float(m_pendingOpacity));
        }

        const QColor clear = premul(m_view.canvas);
        cb->beginPass(renderTarget(), clear, {1.0f, 0}, rub);
        cb->setViewport({0, 0, float(px.width()), float(px.height())});
        m_bed.draw(cb, px);
        int drawn = 0;
        if (count > 0 && m_instances) {
            if (useMap) {
                if (m_pendingOpacity > 0 && visible < count && m_all.built > 0) showMap(cb, m_all, px);
                if (m_done.built > 0) showMap(cb, m_done, px);
                // Whatever the map has not reached yet is drawn for real, so the picture is right on every frame.
                drawn = drawRange(cb, m_done.built, visible, px, 0);
            } else {
                if (m_pendingOpacity > 0 && visible < m_uploaded) drawn += drawRange(cb, visible, m_uploaded, px, 1);
                drawn += drawRange(cb, 0, visible, px, 0);
            }
        }
        cb->endPass();

        if (auto* it = m_item) {
            it->m_uploaded.storeRelaxed(m_uploaded);
            it->m_drawn.storeRelaxed(drawn);
            it->m_mapShown.storeRelaxed(useMap ? 1 : 0);
        }
        const bool busy = m_uploaded < count || building > 0;
        if (!busy && m_uploaded == count && m_reportedData != m_data.get() && m_item) {
            m_reportedData = m_data.get();
            QMetaObject::invokeMethod(m_item, [it = m_item, d = m_reportedData] { it->uploadFinished(d); }, Qt::QueuedConnection);
        }
        if (busy || m_view.continuous) update();
    }

private:
    void releaseAll() {
        m_pipeline.reset(); m_pipeMap.reset(); m_pipeShow.reset(); m_srb.reset(); m_ubo.reset();
        m_corners.reset(); m_indices.reset(); m_instances.reset(); m_sampler.reset();
        m_done = {}; m_all = {};
        m_capacity = 0;
        m_mapSize = {}; m_mapZoom = 0;
    }

    void buildPipelines() {
        const bool first = !m_corners;
        if (first) {
            m_corners.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::VertexBuffer, sizeof kLineCorners));
            m_corners->create();
            m_indices.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::IndexBuffer, sizeof kLineIndices));
            m_indices->create();
            auto* rub = m_rhi->nextResourceUpdateBatch();
            rub->uploadStaticBuffer(m_corners.get(), kLineCorners);
            rub->uploadStaticBuffer(m_indices.get(), kLineIndices);
            m_initBatch = rub;
            m_uboStride = m_rhi->ubufAligned(sizeof(Ubo));
            m_ubo.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, m_uboStride * 3));
            m_ubo->create();
            m_sampler.reset(m_rhi->newSampler(QRhiSampler::Linear, QRhiSampler::Linear, QRhiSampler::Linear, QRhiSampler::ClampToEdge, QRhiSampler::ClampToEdge));
            m_sampler->create();
            m_srb.reset(m_rhi->newShaderResourceBindings());
            m_srb->setBindings({QRhiShaderResourceBinding::uniformBufferWithDynamicOffset(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, m_ubo.get(), sizeof(Ubo))});
            m_srb->create();
        }
        m_pipeline = linePipeline(renderTarget()->renderPassDescriptor(), renderTarget()->sampleCount(), premulOver());
        m_pipeShow.reset();
        m_bed.create(m_rhi, renderTarget()->renderPassDescriptor(), renderTarget()->sampleCount());
    }

    std::unique_ptr<QRhiGraphicsPipeline> linePipeline(QRhiRenderPassDescriptor* rp, int samples, QRhiGraphicsPipeline::TargetBlend blend) {
        std::unique_ptr<QRhiGraphicsPipeline> p(m_rhi->newGraphicsPipeline());
        p->setTargetBlends({blend});
        p->setShaderStages({{QRhiShaderStage::Vertex, shader("segments.vert")}, {QRhiShaderStage::Fragment, shader("line.frag")}});
        QRhiVertexInputLayout layout;
        layout.setBindings({{2 * sizeof(float)}, {sizeof(GpuSegment), QRhiVertexInputBinding::PerInstance}});
        layout.setAttributes({{0, 0, QRhiVertexInputAttribute::Float2, 0},
                              {1, 1, QRhiVertexInputAttribute::Float4, 0},
                              {1, 2, QRhiVertexInputAttribute::Float, 4 * sizeof(float)}});
        p->setVertexInputLayout(layout);
        p->setSampleCount(samples);
        p->setShaderResourceBindings(m_srb.get());
        p->setRenderPassDescriptor(rp);
        p->create();
        return p;
    }

    void uploadSlice(QRhiResourceUpdateBatch* rub, int count) {
        if (m_initBatch) { rub->merge(m_initBatch); m_initBatch->release(); m_initBatch = nullptr; }
        if (m_uploadedData != m_data.get()) {
            m_uploadedData = m_data.get();
            m_reportedData = nullptr;
            m_uploaded = 0;
            m_done.reset(); m_all.reset();
            m_mapSize = {};   // resized for the new job's bounds on demand
            m_mapZoom = 0;
            m_holdData = m_data;
            const qsizetype bytes = qsizetype(count) * qsizetype(sizeof(GpuSegment));
            if (!m_instances || m_capacity < bytes) {
                m_instances.reset(m_rhi->newBuffer(QRhiBuffer::Static, QRhiBuffer::VertexBuffer, std::max<qsizetype>(bytes, 4096)));
                if (!m_instances->create()) { m_instances.reset(); m_capacity = 0; return; }
                m_capacity = bytes;
            }
        }
        if (m_uploaded >= count || !m_instances) return;
        const qsizetype budget = softwareAdapter(m_rhi) ? kUploadBytesPerFrame / 4 : kUploadBytesPerFrame;
        const int n = std::min<qsizetype>(count - m_uploaded, budget / qsizetype(sizeof(GpuSegment)));
        rub->uploadStaticBuffer(m_instances.get(), qsizetype(m_uploaded) * sizeof(GpuSegment), qsizetype(n) * sizeof(GpuSegment), m_data->segs.data() + m_uploaded);
        m_uploaded += n;
    }

    void writeUbo(QRhiResourceUpdateBatch* rub, int slot, const QMatrix4x4& m, QSizeF px, double spotPx, float opacity) {
        Ubo u{};
        memcpy(u.mmToClip, m.constData(), sizeof u.mmToClip);
        u.viewportPx[0] = float(px.width()); u.viewportPx[1] = float(px.height());
        u.halfWidthPx = float(0.5 * m_lineWidth * m_view.dpr);
        u.spotPx = float(spotPx);
        color(u.high, m_cut); color(u.low, m_low); color(u.travel, m_travel); color(u.sheet, m_view.sheet);
        u.showTravel = m_showTravel ? 1 : 0;
        u.opacity = opacity;
        rub->updateDynamicBuffer(m_ubo.get(), slot * m_uboStride, sizeof u, &u);
    }

    int drawRange(QRhiCommandBuffer* cb, int from, int to, QSize px, int slot) {
        if (to <= from) return 0;
        cb->setGraphicsPipeline(m_pipeline.get());
        const QRhiCommandBuffer::DynamicOffset off(0, quint32(slot * m_uboStride));
        cb->setShaderResources(m_srb.get(), 1, &off);
        const QRhiCommandBuffer::VertexInput inputs[] = {{m_corners.get(), 0}, {m_instances.get(), 0}};
        cb->setVertexInput(0, 2, inputs, m_indices.get(), 0, QRhiCommandBuffer::IndexUInt16);
        // Keep what is in view. Zoomed out everything stays and this is one draw call.
        const float margin = float(4.0 / m_view.zoom);
        const float vx0 = float(-m_view.panX / m_view.zoom) - margin, vy0 = float(-m_view.panY / m_view.zoom) - margin;
        const float vx1 = float((px.width() - m_view.panX) / m_view.zoom) + margin, vy1 = float((px.height() - m_view.panY) / m_view.zoom) + margin;
        const float* boxes = m_data->chunkBoxes.data();
        int drawn = 0, runFrom = -1;
        const int firstChunk = from / SegmentsItem::kChunk, lastChunk = (to - 1) / SegmentsItem::kChunk;
        for (int c = firstChunk; c <= lastChunk + 1; ++c) {
            const bool inView = c <= lastChunk && boxes[c * 4] <= vx1 && boxes[c * 4 + 2] >= vx0 && boxes[c * 4 + 1] <= vy1 && boxes[c * 4 + 3] >= vy0;
            if (inView && runFrom < 0) runFrom = std::max(from, c * SegmentsItem::kChunk);
            if (!inView && runFrom >= 0) {
                const int end = std::min(to, c * SegmentsItem::kChunk);
                cb->drawIndexed(6, quint32(end - runFrom), 0, 0, quint32(runFrom));
                drawn += end - runFrom;
                runFrom = -1;
            }
        }
        return drawn;
    }

    // --- burn map ------------------------------------------------------------------------------------------------
    void ensureMapSize() {
        if (!m_data || !m_data->raster || m_mapSize.isValid()) return;
        const double w = std::max(1.0f, m_data->maxX - m_data->minX), h = std::max(1.0f, m_data->maxY - m_data->minY);
        const int cap = softwareAdapter(m_rhi) ? kMapMaxSize / 2 : kMapMaxSize;
        m_mapZoom = std::min(kMapMaxPxPerMm, cap / std::max(w, h));
        m_mapSize = QSize(std::max(1, int(std::ceil(w * m_mapZoom))), std::max(1, int(std::ceil(h * m_mapZoom))));
        m_pipeMap.reset(); m_pipeShow.reset();     // they refer to the old maps
        m_done = {}; m_all = {};
    }

    bool createMap(BurnMap& map) {
        const auto format = m_rhi->isTextureFormatSupported(QRhiTexture::RGBA16F) ? QRhiTexture::RGBA16F : QRhiTexture::RGBA8;
        map.tex.reset(m_rhi->newTexture(format, m_mapSize, 1, QRhiTexture::RenderTarget | QRhiTexture::MipMapped | QRhiTexture::UsedWithGenerateMips));
        if (!map.tex->create()) { map.tex.reset(); return false; }
        map.rtClear.reset(m_rhi->newTextureRenderTarget({QRhiColorAttachment(map.tex.get())}));
        map.rp.reset(map.rtClear->newCompatibleRenderPassDescriptor());
        map.rtClear->setRenderPassDescriptor(map.rp.get());
        map.rtClear->create();
        map.rtKeep.reset(m_rhi->newTextureRenderTarget({QRhiColorAttachment(map.tex.get())}, QRhiTextureRenderTarget::PreserveColorContents));
        map.rtKeep->setRenderPassDescriptor(map.rp.get());
        map.rtKeep->create();
        map.showUbo.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(ShowUbo)));
        map.showUbo->create();
        map.showSrb.reset(m_rhi->newShaderResourceBindings());
        map.showSrb->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, map.showUbo.get()),
                                  QRhiShaderResourceBinding::sampledTexture(1, QRhiShaderResourceBinding::FragmentStage, map.tex.get(), m_sampler.get())});
        map.showSrb->create();
        map.reset();
        return true;
    }

    void ensureMaps(QRhiResourceUpdateBatch*) {
        if (!m_done.tex) createMap(m_done);
        if (m_pendingOpacity > 0 && !m_all.tex) createMap(m_all);
        if (!m_pipeMap && m_done.tex) {
            QRhiGraphicsPipeline::TargetBlend add;
            add.enable = true;
            add.srcColor = add.dstColor = add.srcAlpha = add.dstAlpha = QRhiGraphicsPipeline::One;
            m_pipeMap = linePipeline(m_done.rp.get(), 1, add);
        }
        if (!m_pipeShow && m_done.tex) {
            m_pipeShow.reset(m_rhi->newGraphicsPipeline());
            m_pipeShow->setTargetBlends({premulOver()});
            m_pipeShow->setTopology(QRhiGraphicsPipeline::TriangleStrip);
            m_pipeShow->setShaderStages({{QRhiShaderStage::Vertex, shader("mapshow.vert")}, {QRhiShaderStage::Fragment, shader("mapshow.frag")}});
            m_pipeShow->setVertexInputLayout({});
            m_pipeShow->setSampleCount(renderTarget()->sampleCount());
            m_pipeShow->setShaderResourceBindings(m_done.showSrb.get());
            m_pipeShow->setRenderPassDescriptor(renderTarget()->renderPassDescriptor());
            m_pipeShow->create();
        }
    }

    void writeMapUbo(QRhiResourceUpdateBatch* rub) {
        // Map pixels replace screen pixels: same shader, its own transform and spot width in map pixels.
        const QMatrix4x4 m = mmToClip(m_rhi, m_mapSize, m_mapZoom, -double(m_data->minX) * m_mapZoom, -double(m_data->minY) * m_mapZoom);
        writeUbo(rub, 2, m, QSizeF(m_mapSize), std::max(0.05, m_spotMm * m_mapZoom), 1.0f);
    }

    /** Adds the next slice of [built, target). Consumes rub in the pass. Returns the slices still to do. */
    int buildMap(QRhiCommandBuffer* cb, QRhiResourceUpdateBatch*& rub, BurnMap& map, int target) {
        if (!map.tex) return 0;
        if (target < map.built) map.reset();       // played backwards: start over, the real segments fill in meanwhile
        const int perFrame = softwareAdapter(m_rhi) ? 200'000 : 1'500'000;
        const int step = std::min(target - map.built, perFrame);
        if (step <= 0 && !map.needClear) return 0;
        auto* rt = map.needClear ? map.rtClear.get() : map.rtKeep.get();
        cb->beginPass(rt, QColor(0, 0, 0, 0), {1.0f, 0}, rub);
        rub = nullptr;
        if (step > 0) {
            cb->setViewport({0, 0, float(m_mapSize.width()), float(m_mapSize.height())});
            cb->setGraphicsPipeline(m_pipeMap.get());
            const QRhiCommandBuffer::DynamicOffset off(0, quint32(2 * m_uboStride));
            cb->setShaderResources(m_srb.get(), 1, &off);
            const QRhiCommandBuffer::VertexInput inputs[] = {{m_corners.get(), 0}, {m_instances.get(), 0}};
            cb->setVertexInput(0, 2, inputs, m_indices.get(), 0, QRhiCommandBuffer::IndexUInt16);
            cb->drawIndexed(6, quint32(step), 0, 0, quint32(map.built));
        }
        auto* mips = m_rhi->nextResourceUpdateBatch();
        mips->generateMips(map.tex.get());
        cb->endPass(mips);
        map.needClear = false;
        map.built += step;
        return map.built < target ? 1 : 0;
    }

    void writeShowUbo(QRhiResourceUpdateBatch* rub, BurnMap& map, QSize px, float opacity) {
        if (!map.tex) return;
        ShowUbo u{};
        const QMatrix4x4 m = mmToClip(m_rhi, px, m_view.zoom, m_view.panX, m_view.panY);
        memcpy(u.mmToClip, m.constData(), sizeof u.mmToClip);
        // The texture is a little larger than the job, rounded up to whole pixels.
        u.rect[0] = m_data->minX; u.rect[1] = m_data->minY;
        u.rect[2] = float(m_data->minX + m_mapSize.width() / m_mapZoom); u.rect[3] = float(m_data->minY + m_mapSize.height() / m_mapZoom);
        u.opacity = opacity;
        u.lod = float(std::max(0.0, std::log2(m_mapZoom / m_view.zoom) - 1.0));
        rub->updateDynamicBuffer(map.showUbo.get(), 0, sizeof u, &u);
    }

    void showMap(QRhiCommandBuffer* cb, BurnMap& map, QSize px) {
        cb->setGraphicsPipeline(m_pipeShow.get());
        cb->setViewport({0, 0, float(px.width()), float(px.height())});
        cb->setShaderResources(map.showSrb.get());
        cb->draw(4);
    }

    QRhi* m_rhi = nullptr;
    SegmentsItem* m_item = nullptr;
    GpuViewItem::Snapshot m_view;
    BedPass m_bed;
    std::unique_ptr<QRhiBuffer> m_corners, m_indices, m_ubo, m_instances;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipeline, m_pipeMap, m_pipeShow;
    std::unique_ptr<QRhiSampler> m_sampler;
    BurnMap m_done, m_all;
    QVector<quint32> m_rpFormat;
    QRhiResourceUpdateBatch* m_initBatch = nullptr;
    std::shared_ptr<const SegmentsItem::Data> m_data, m_holdData;
    const SegmentsItem::Data* m_uploadedData = nullptr;
    QByteArray m_look;
    qsizetype m_capacity = 0;
    quint32 m_uboStride = 256;
    QSize m_mapSize;
    double m_mapZoom = 0;
    int m_uploaded = 0, m_visibleWanted = -1;
    bool m_showTravel = true, m_useBurnMap = true;
    const SegmentsItem::Data* m_reportedData = nullptr;
    qreal m_lineWidth = 1.25, m_spotMm = 0.1, m_pendingOpacity = 0;
    QColor m_cut, m_low, m_travel;
};

SegmentsItem::SegmentsItem(QQuickItem* parent) : GpuViewItem(parent) {
    connect(&m_watcher, &QFutureWatcher<std::shared_ptr<const Data>>::finished, this, [this] {
        m_workerBusy = false;
        if (m_nextWork) {               // a newer job arrived meanwhile: this result is already stale
            auto next = std::move(m_nextWork);
            m_nextWork = nullptr;
            startWorker(std::move(next));
            return;
        }
        m_data = m_watcher.result();
        ++m_dataVersion;
        m_visible = -1;
        if (m_data->segs.empty()) m_loading = false;   // otherwise until the renderer has uploaded everything
        emit visibleCountChanged();
        emit segmentsChanged();
        emit loadingChanged();
        update();
    });
}
SegmentsItem::~SegmentsItem() { m_watcher.waitForFinished(); }
QQuickRhiItemRenderer* SegmentsItem::createRenderer() { return new SegmentsRenderer; }

void SegmentsItem::startWorker(std::function<std::vector<GpuSegment>()> make) {
    if (m_workerBusy) { m_nextWork = std::move(make); return; }
    m_workerBusy = true;
    if (!m_loading) { m_loading = true; emit loadingChanged(); }
    m_watcher.setFuture(QtConcurrent::run([make = std::move(make)] { return prepare(make()); }));
}
void SegmentsItem::uploadFinished(const Data* d) {
    if (m_data.get() == d && !m_workerBusy && m_loading) { m_loading = false; emit loadingChanged(); }
}
void SegmentsItem::setSegments(std::vector<GpuSegment> segs) {
    auto held = std::make_shared<std::vector<GpuSegment>>(std::move(segs));
    startWorker([held] { return std::move(*held); });
}
int SegmentsItem::segmentCount() const { return m_data ? int(m_data->segs.size()) : 0; }
int SegmentsItem::sourceCount() const { return m_data ? m_data->sourceCount : 0; }
bool SegmentsItem::decimated() const { return m_data && m_data->decimated; }
bool SegmentsItem::rasterLook() const { return m_data && m_data->raster; }
void SegmentsItem::setVisibleCount(int n) { if (n != m_visible) { m_visible = n; emit visibleCountChanged(); update(); } }
void SegmentsItem::setShowTravel(bool v) { if (v != m_showTravel) { m_showTravel = v; emit viewChanged(); } }

void SegmentsItem::loadBenchmark(int count) {
    const float bedW = float(property("bedWidth").toReal()), bedH = float(property("bedHeight").toReal());
    startWorker([count, bedW, bedH] {
        std::vector<GpuSegment> s;
        s.reserve(size_t(count));
        const int rows = std::max(1, int(std::sqrt(double(count) / 4)));
        const int perRow = std::max(1, (count + rows - 1) / rows);
        const float w = bedW - 40, h = bedH - 80;
        for (int r = 0; r < rows && int(s.size()) < count; ++r) {
            const float y = 60 + h * float(r) / float(rows);
            const float dx = w / float(perRow);
            for (int i = 0; i < perRow && int(s.size()) < count; ++i) {
                const float x = 20 + dx * float(i);
                const float d = std::hypot(x - bedW / 2, y - bedH / 2) / 180.0f;
                const float p = std::clamp(0.5f + 0.5f * std::sin(d * 18.0f), 0.0f, 1.0f);
                s.push_back({x, y, x + dx, y, p < 0.05f ? 0.0f : p});
            }
        }
        return s;
    });
}
