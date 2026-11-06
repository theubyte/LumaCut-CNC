#define _USE_MATH_DEFINES
#include "StageItem.h"
#include <QHash>
#include <QMetaObject>
#include <QQuickWindow>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <climits>
#include <cmath>
#include <map>
#include "RhiCommon.h"

using namespace rhiutil;

namespace {
struct Inst { float x0, y0, x1, y1; quint32 slot; };
constexpr quint32 kHole = 0x7fffffffu, kNoFan = 0x80000000u;
constexpr int kSlotsPerRow = 512, kTexWidth = kSlotsPerRow * 2;   // 2 RGBA32F texels per element
constexpr qsizetype kUploadBytesPerFrame = 32 * 1024 * 1024;
constexpr int kMaxOverlay = 64;

struct Range { quint32 off, cnt; };
struct Packed { quint64 id; int layer; std::vector<Inst> inst; QPointF centre; QTransform t; bool visible; };

/** Geometry relative to the element's centre, so the fill's fan stays small and floats stay exact. */
Packed pack(const StageElement& e) {
    Packed p{e.id, e.layer, {}, {}, e.transform, e.visible};
    double x0 = 1e30, y0 = 1e30, x1 = -1e30, y1 = -1e30;
    size_t edges = 0;
    for (const auto& path : e.paths) {
        if (path.size() >= 2) edges += path.size() - 1;
        for (const QPointF& q : path) { x0 = std::min(x0, q.x()); x1 = std::max(x1, q.x()); y0 = std::min(y0, q.y()); y1 = std::max(y1, q.y()); }
    }
    if (edges == 0) return p;
    const double cx = (x0 + x1) * 0.5, cy = (y0 + y1) * 0.5;
    p.centre = {cx, cy};
    p.inst.reserve(edges);
    for (const auto& path : e.paths) {
        if (path.size() < 2) continue;
        const bool closed = path.size() > 2 && std::hypot(path.front().x() - path.back().x(), path.front().y() - path.back().y()) < 1e-6;
        const quint32 flag = closed ? 0 : kNoFan;
        for (size_t i = 0; i + 1 < path.size(); ++i)
            p.inst.push_back({float(path[i].x() - cx), float(path[i].y() - cy), float(path[i + 1].x() - cx), float(path[i + 1].y() - cy), flag});
    }
    return p;
}
struct StageUbo {
    float mmToClip[16];
    float viewportPx[2];
    float halfWidthPx, selectedHalfPx;
    float color[4];
    float selected[4];
};
struct QuadUbo { float m[16]; float opacity; float pad[3]; };
struct OverlayInst { float x0, y0, x1, y1; quint8 rgba[4]; float halfPx; };
const float kFanWeights[] = {0, 0, 1, 0, 0, 1};
}

struct StageItem::Scene {
    struct Store {
        StageLayer desc;
        bool declared = false;
        std::vector<Inst> inst;
        std::vector<Range> free, dirty;
    };
    struct Elem { quint64 id = 0; int layer = 0; quint32 off = 0, cnt = 0; QPointF centre; QTransform t; bool visible = true, selected = false, used = false; };
    struct Image { StageImage img; quint64 version = 0; };

    std::map<int, Store> stores;
    std::vector<int> order;
    std::vector<Elem> elems;
    std::vector<quint32> freeSlots, selected;
    QHash<quint64, quint32> slotOf;
    std::vector<float> tex;                 // kTexWidth x rows x RGBA32F, whole rows
    int dirtyLo = INT_MAX, dirtyHi = -1;    // texture rows
    quint64 generation = 1;
    std::vector<Image> images;
    quint64 imageVersion = 0;
    QPolygonF frame;
    QRectF marquee;
    int liveElements = 0;
    qint64 liveInstances = 0;

    void writeTex(quint32 slot) {
        const Elem& e = elems[slot];
        const size_t rows = (size_t(slot) / kSlotsPerRow + 1);
        if (tex.size() < rows * kTexWidth * 4) tex.resize(std::max(rows, tex.size() / (kTexWidth * 4) * 3 / 2 + 1) * kTexWidth * 4, 0.0f);
        float* o = tex.data() + size_t(slot) * 8;
        const QTransform& t = e.t;
        const double cx = e.centre.x(), cy = e.centre.y();
        o[0] = float(t.m11()); o[1] = float(t.m21()); o[2] = float(t.m11() * cx + t.m21() * cy + t.dx());
        o[3] = !e.used || !e.visible ? 0.0f : e.selected ? 2.0f : 1.0f;
        o[4] = float(t.m12()); o[5] = float(t.m22()); o[6] = float(t.m12() * cx + t.m22() * cy + t.dy());
        o[7] = 0.0f;
        const int row = int(slot) / kSlotsPerRow;
        dirtyLo = std::min(dirtyLo, row); dirtyHi = std::max(dirtyHi, row);
    }
    static void markDirty(Store& s, quint32 off, quint32 cnt) {
        if (cnt == 0) return;
        if (!s.dirty.empty() && s.dirty.back().off + s.dirty.back().cnt == off) s.dirty.back().cnt += cnt;
        else s.dirty.push_back({off, cnt});
    }
    quint32 allocInst(Store& s, quint32 cnt) {
        // Only the newest gaps are looked at: finding room must stay cheap, a little waste does not matter.
        const size_t first = s.free.size() > 64 ? s.free.size() - 64 : 0;
        for (size_t i = s.free.size(); i-- > first;) {
            if (s.free[i].cnt >= cnt) {
                const quint32 off = s.free[i].off;
                s.free[i].off += cnt; s.free[i].cnt -= cnt;
                if (s.free[i].cnt == 0) s.free.erase(s.free.begin() + qsizetype(i));
                return off;
            }
        }
        const quint32 off = quint32(s.inst.size());
        s.inst.resize(s.inst.size() + cnt);
        return off;
    }
    void freeInst(const Elem& e) {
        if (e.cnt == 0) return;
        Store& s = stores[e.layer];
        for (quint32 i = 0; i < e.cnt; ++i) s.inst[e.off + i] = {0, 0, 0, 0, kHole};
        markDirty(s, e.off, e.cnt);
        s.free.push_back({e.off, e.cnt});
    }
    void upsert(Packed&& p) {
        quint32 slot;
        const auto found = slotOf.constFind(p.id);
        if (found != slotOf.constEnd()) {
            slot = *found;
        } else {
            if (!freeSlots.empty()) { slot = freeSlots.back(); freeSlots.pop_back(); }
            else { slot = quint32(elems.size()); elems.emplace_back(); }
            slotOf.insert(p.id, slot);
            elems[slot] = Elem{};
            ++liveElements;
        }
        Elem& e = elems[slot];
        const quint32 cnt = quint32(p.inst.size());
        Store& s = stores[p.layer];
        if (e.used && e.layer == p.layer && cnt <= e.cnt) {
            // Fits where it was: the rest becomes holes.
            for (quint32 i = cnt; i < e.cnt; ++i) s.inst[e.off + i] = {0, 0, 0, 0, kHole};
            markDirty(s, e.off, e.cnt);
            if (e.cnt > cnt) s.free.push_back({e.off + cnt, e.cnt - cnt});
        } else {
            if (e.used) freeInst(e);
            e.off = allocInst(s, cnt);
            markDirty(s, e.off, cnt);
        }
        liveInstances += qint64(cnt) - qint64(e.used ? e.cnt : 0);
        for (quint32 i = 0; i < cnt; ++i) { Inst q = p.inst[i]; q.slot |= slot; s.inst[e.off + i] = q; }
        e.id = p.id; e.layer = p.layer; e.cnt = cnt; e.centre = p.centre; e.t = p.t; e.visible = p.visible; e.used = true;
        writeTex(slot);
    }
    void remove(quint64 id) {
        const auto found = slotOf.constFind(id);
        if (found == slotOf.constEnd()) return;
        const quint32 slot = *found;
        Elem& e = elems[slot];
        freeInst(e);
        liveInstances -= e.cnt;
        --liveElements;
        e = Elem{};
        writeTex(slot);
        freeSlots.push_back(slot);
        slotOf.erase(found);
    }
    void select(const std::vector<quint64>& ids) {
        for (quint32 slot : selected) if (slot < elems.size() && elems[slot].selected) { elems[slot].selected = false; writeTex(slot); }
        selected.clear();
        for (quint64 id : ids) {
            const auto found = slotOf.constFind(id);
            if (found == slotOf.constEnd()) continue;
            elems[*found].selected = true;
            writeTex(*found);
            selected.push_back(*found);
        }
    }
    /** Takes the geometry of a scene built on the worker; layers, images and overlays stay. */
    void adoptGeometry(Scene& o) {
        std::map<int, Store> next;
        for (auto& [id, s] : stores) { Store n; n.desc = s.desc; n.declared = s.declared; next.emplace(id, std::move(n)); }
        for (auto& [id, s] : o.stores) {
            Store& n = next[id];
            n.inst = std::move(s.inst);
            n.dirty.clear(); n.free.clear();
        }
        stores = std::move(next);
        elems = std::move(o.elems);
        freeSlots.clear(); selected.clear();
        slotOf = std::move(o.slotOf);
        tex = std::move(o.tex);
        dirtyLo = INT_MAX; dirtyHi = -1;
        liveElements = o.liveElements; liveInstances = o.liveInstances;
        ++generation;
    }
};

class StageRenderer : public QQuickRhiItemRenderer {
public:
    void initialize(QRhiCommandBuffer*) override {
        m_rhi = rhi();
        const auto fmt = renderTarget()->renderPassDescriptor()->serializedFormat();
        if (!m_pipeLine || m_rpFormat != fmt) { build(); m_rpFormat = fmt; }
    }
    void synchronize(QQuickRhiItem* item) override {
        auto* it = static_cast<StageItem*>(item);
        m_item = it;
        m_scene = it->m_scene;
        for (auto& op : it->m_ops) op(*m_scene);
        it->m_ops.clear();
        m_view = it->snapshot();
        m_selectionColor = it->m_selectionColor;
        m_lineWidth = it->m_lineWidth; m_selectedWidth = it->m_selectedWidth;
    }
    void render(QRhiCommandBuffer* cb) override {
        const QSize px = renderTarget()->pixelSize();
        StageItem::Scene& sc = *m_scene;
        auto* rub = m_rhi->nextResourceUpdateBatch();
        if (m_initBatch) { rub->merge(m_initBatch); m_initBatch->release(); m_initBatch = nullptr; }
        const bool texChanged = uploadElementTexture(rub, sc);
        if (texChanged || !m_srb) rebuildSrb();
        const qint64 pending = uploadGeometry(rub, sc);
        uploadImages(rub, sc, px);

        const QMatrix4x4 clip = mmToClip(m_rhi, px, m_view.zoom, m_view.panX, m_view.panY);
        ensureUbo(1 + int(sc.order.size()) * 2);
        writeSlot(rub, 0, clip, px, QColor(255, 255, 255));
        int slot = 1;
        for (int id : sc.order) {
            const auto& d = sc.stores[id].desc;
            QColor line = d.color; line.setAlphaF(d.opacity);
            QColor fill = d.color; fill.setAlphaF(d.opacity * d.fillOpacity);
            writeSlot(rub, slot++, clip, px, line);
            writeSlot(rub, slot++, clip, px, fill);
        }
        const int overlays = writeOverlay(rub, sc);
        m_bed.prepare(rub, m_view, px);

        cb->beginPass(renderTarget(), premul(m_view.canvas), {1.0f, 0}, rub);
        const QRhiViewport vp(0, 0, float(px.width()), float(px.height()));
        cb->setViewport(vp);
        m_bed.draw(cb, px);
        drawImages(cb, sc, vp);

        // Fills first: every fill layer as a whole, even-odd through the stencil's invert. Cover resets the stencil.
        slot = 1;
        for (int id : sc.order) {
            auto& st = sc.stores[id];
            const LayerGpu* g = gpuOf(id);
            if (st.desc.fill && st.desc.visible && g && g->valid > 0) {
                const QRhiCommandBuffer::DynamicOffset off(0, quint32((slot + 1) * m_stride));
                cb->setGraphicsPipeline(m_pipeFan.get());
                cb->setViewport(vp);
                cb->setStencilRef(0);
                cb->setShaderResources(m_srb.get(), 1, &off);
                const QRhiCommandBuffer::VertexInput in[] = {{m_fanWeights.get(), 0}, {g->buf.get(), 0}};
                cb->setVertexInput(0, 2, in);
                cb->draw(3, quint32(g->valid));
                cb->setGraphicsPipeline(m_pipeCover.get());
                cb->setStencilRef(0);
                cb->setShaderResources(m_srb.get(), 1, &off);
                cb->draw(4);
            }
            slot += 2;
        }
        // Then the lines, one instanced draw per layer.
        slot = 1;
        cb->setGraphicsPipeline(m_pipeLine.get());
        for (int id : sc.order) {
            auto& st = sc.stores[id];
            const LayerGpu* g = gpuOf(id);
            if (st.desc.visible && g && g->valid > 0) {
                const QRhiCommandBuffer::DynamicOffset off(0, quint32(slot * m_stride));
                cb->setShaderResources(m_srb.get(), 1, &off);
                const QRhiCommandBuffer::VertexInput in[] = {{m_corners.get(), 0}, {g->buf.get(), 0}};
                cb->setVertexInput(0, 2, in, m_indices.get(), 0, QRhiCommandBuffer::IndexUInt16);
                cb->drawIndexed(6, quint32(g->valid));
            }
            slot += 2;
        }
        if (overlays > 0) {
            const QRhiCommandBuffer::DynamicOffset off(0, 0);
            cb->setGraphicsPipeline(m_pipeOverlay.get());
            cb->setShaderResources(m_srb.get(), 1, &off);
            const QRhiCommandBuffer::VertexInput in[] = {{m_corners.get(), 0}, {m_overlay.get(), 0}};
            cb->setVertexInput(0, 2, in, m_indices.get(), 0, QRhiCommandBuffer::IndexUInt16);
            cb->drawIndexed(6, quint32(overlays));
        }
        cb->endPass();

        m_item->m_elementCount.storeRelaxed(sc.liveElements);
        m_item->m_instanceCount.storeRelaxed(int(sc.liveInstances));
        m_item->m_pendingUpload.storeRelaxed(int(pending));
        if (pending == 0 && m_item->m_loading) QMetaObject::invokeMethod(m_item, [it = m_item] { it->workerDone(); }, Qt::QueuedConnection);
        if (pending > 0 || m_view.continuous) update();
    }

private:
    struct LayerGpu { std::unique_ptr<QRhiBuffer> buf; qsizetype capacity = 0; int valid = 0; size_t fullPos = 0; bool full = false; quint64 generation = 0; };
    struct ImageGpu { std::unique_ptr<QRhiTexture> tex; std::unique_ptr<QRhiBuffer> ubo; std::unique_ptr<QRhiShaderResourceBindings> srb; quint64 version = 0; bool visible = true; };

    const LayerGpu* gpuOf(int id) const { const auto f = m_layers.find(id); return f == m_layers.end() ? nullptr : &f->second; }

    void build() {
        if (!m_corners) {
            m_corners.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::VertexBuffer, sizeof kLineCorners));
            m_corners->create();
            m_indices.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::IndexBuffer, sizeof kLineIndices));
            m_indices->create();
            m_fanWeights.reset(m_rhi->newBuffer(QRhiBuffer::Immutable, QRhiBuffer::VertexBuffer, sizeof kFanWeights));
            m_fanWeights->create();
            m_overlay.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::VertexBuffer, kMaxOverlay * sizeof(OverlayInst)));
            m_overlay->create();
            m_elemSampler.reset(m_rhi->newSampler(QRhiSampler::Nearest, QRhiSampler::Nearest, QRhiSampler::None, QRhiSampler::ClampToEdge, QRhiSampler::ClampToEdge));
            m_elemSampler->create();
            m_imgSampler.reset(m_rhi->newSampler(QRhiSampler::Linear, QRhiSampler::Linear, QRhiSampler::Linear, QRhiSampler::ClampToEdge, QRhiSampler::ClampToEdge));
            m_imgSampler->create();
            auto* rub = m_rhi->nextResourceUpdateBatch();
            rub->uploadStaticBuffer(m_corners.get(), kLineCorners);
            rub->uploadStaticBuffer(m_indices.get(), kLineIndices);
            rub->uploadStaticBuffer(m_fanWeights.get(), kFanWeights);
            m_initBatch = rub;
            m_stride = m_rhi->ubufAligned(sizeof(StageUbo));
            ensureUbo(1 + 2 * 16);
            ensureElementTexture(1);
            rebuildSrb();
            // Only so that pipelines can be built before the first image arrives.
            m_quadUboLayout.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(QuadUbo)));
            m_quadUboLayout->create();
            m_quadTexLayout.reset(m_rhi->newTexture(QRhiTexture::RGBA8, QSize(1, 1)));
            m_quadTexLayout->create();
            m_quadSrbLayout.reset(m_rhi->newShaderResourceBindings());
            m_quadSrbLayout->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, m_quadUboLayout.get()),
                                          QRhiShaderResourceBinding::sampledTexture(1, QRhiShaderResourceBinding::FragmentStage, m_quadTexLayout.get(), m_imgSampler.get())});
            m_quadSrbLayout->create();
        }
        auto* rp = renderTarget()->renderPassDescriptor();
        const int samples = renderTarget()->sampleCount();
        const auto common = [&](QRhiGraphicsPipeline* p) {
            p->setSampleCount(samples);
            p->setRenderPassDescriptor(rp);
        };
        const auto lineLayout = [](int firstLoc2Format) {
            QRhiVertexInputLayout l;
            l.setBindings({{2 * sizeof(float)}, {sizeof(Inst), QRhiVertexInputBinding::PerInstance}});
            l.setAttributes({{0, 0, QRhiVertexInputAttribute::Float2, 0}, {1, 1, QRhiVertexInputAttribute::Float4, 0},
                             {1, 2, QRhiVertexInputAttribute::Format(firstLoc2Format), 4 * sizeof(float)}});
            return l;
        };
        m_pipeLine.reset(m_rhi->newGraphicsPipeline());
        common(m_pipeLine.get());
        m_pipeLine->setTargetBlends({premulOver()});
        m_pipeLine->setShaderStages({{QRhiShaderStage::Vertex, shader("stage_line.vert")}, {QRhiShaderStage::Fragment, shader("line.frag")}});
        m_pipeLine->setVertexInputLayout(lineLayout(QRhiVertexInputAttribute::UInt));
        m_pipeLine->setShaderResourceBindings(m_srb.get());
        m_pipeLine->create();

        QRhiGraphicsPipeline::TargetBlend noColor;
        noColor.colorWrite = {};
        m_pipeFan.reset(m_rhi->newGraphicsPipeline());
        common(m_pipeFan.get());
        m_pipeFan->setTargetBlends({noColor});
        m_pipeFan->setShaderStages({{QRhiShaderStage::Vertex, shader("stage_fan.vert")}, {QRhiShaderStage::Fragment, shader("stage_cover.frag")}});
        m_pipeFan->setVertexInputLayout(lineLayout(QRhiVertexInputAttribute::UInt));
        m_pipeFan->setStencilTest(true);
        QRhiGraphicsPipeline::StencilOpState invert{QRhiGraphicsPipeline::Keep, QRhiGraphicsPipeline::Keep, QRhiGraphicsPipeline::Invert, QRhiGraphicsPipeline::Always};
        m_pipeFan->setStencilFront(invert);
        m_pipeFan->setStencilBack(invert);
        m_pipeFan->setShaderResourceBindings(m_srb.get());
        m_pipeFan->create();

        m_pipeCover.reset(m_rhi->newGraphicsPipeline());
        common(m_pipeCover.get());
        m_pipeCover->setFlags(QRhiGraphicsPipeline::UsesStencilRef);
        m_pipeCover->setTopology(QRhiGraphicsPipeline::TriangleStrip);
        m_pipeCover->setTargetBlends({premulOverNonPremulSource()});
        m_pipeCover->setShaderStages({{QRhiShaderStage::Vertex, shader("stage_cover.vert")}, {QRhiShaderStage::Fragment, shader("stage_cover.frag")}});
        m_pipeCover->setVertexInputLayout({});
        m_pipeCover->setStencilTest(true);
        QRhiGraphicsPipeline::StencilOpState cover{QRhiGraphicsPipeline::StencilZero, QRhiGraphicsPipeline::Keep, QRhiGraphicsPipeline::StencilZero, QRhiGraphicsPipeline::NotEqual};
        m_pipeCover->setStencilFront(cover);
        m_pipeCover->setStencilBack(cover);
        m_pipeCover->setShaderResourceBindings(m_srb.get());
        m_pipeCover->create();

        m_pipeOverlay.reset(m_rhi->newGraphicsPipeline());
        common(m_pipeOverlay.get());
        m_pipeOverlay->setTargetBlends({premulOver()});
        m_pipeOverlay->setShaderStages({{QRhiShaderStage::Vertex, shader("stage_overlay.vert")}, {QRhiShaderStage::Fragment, shader("line.frag")}});
        QRhiVertexInputLayout ol;
        ol.setBindings({{2 * sizeof(float)}, {sizeof(OverlayInst), QRhiVertexInputBinding::PerInstance}});
        ol.setAttributes({{0, 0, QRhiVertexInputAttribute::Float2, 0}, {1, 1, QRhiVertexInputAttribute::Float4, 0},
                          {1, 2, QRhiVertexInputAttribute::UNormByte4, 4 * sizeof(float)}, {1, 3, QRhiVertexInputAttribute::Float, 4 * sizeof(float) + 4}});
        m_pipeOverlay->setVertexInputLayout(ol);
        m_pipeOverlay->setShaderResourceBindings(m_srb.get());
        m_pipeOverlay->create();

        m_pipeImage.reset(m_rhi->newGraphicsPipeline());
        common(m_pipeImage.get());
        m_pipeImage->setTopology(QRhiGraphicsPipeline::TriangleStrip);
        m_pipeImage->setTargetBlends({premulOver()});
        m_pipeImage->setShaderStages({{QRhiShaderStage::Vertex, shader("quad.vert")}, {QRhiShaderStage::Fragment, shader("quad.frag")}});
        m_pipeImage->setVertexInputLayout({});
        m_pipeImage->setShaderResourceBindings(m_quadSrbLayout.get());
        m_pipeImage->create();

        m_bed.create(m_rhi, rp, samples);
    }
    static QRhiGraphicsPipeline::TargetBlend premulOverNonPremulSource() {
        // Cover colour comes straight from the uniform, not premultiplied.
        QRhiGraphicsPipeline::TargetBlend b;
        b.enable = true;
        b.srcColor = QRhiGraphicsPipeline::SrcAlpha; b.dstColor = QRhiGraphicsPipeline::OneMinusSrcAlpha;
        b.srcAlpha = QRhiGraphicsPipeline::One; b.dstAlpha = QRhiGraphicsPipeline::OneMinusSrcAlpha;
        return b;
    }
    void ensureUbo(int wanted) {
        if (m_ubo && m_uboSlots >= wanted) return;
        m_uboSlots = std::max(wanted, 1 + 2 * 16);
        m_ubo.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, m_uboSlots * m_stride));
        m_ubo->create();
        if (m_srb) rebuildSrb();
    }
    void rebuildSrb() {
        if (!m_srb) m_srb.reset(m_rhi->newShaderResourceBindings());
        m_srb->setBindings({QRhiShaderResourceBinding::uniformBufferWithDynamicOffset(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, m_ubo.get(), sizeof(StageUbo)),
                            QRhiShaderResourceBinding::sampledTexture(1, QRhiShaderResourceBinding::VertexStage, m_elemTex.get(), m_elemSampler.get())});
        m_srb->create();
    }
    bool ensureElementTexture(int rows) {
        if (m_elemTex && m_texRows >= rows) return false;
        m_texRows = std::max(rows, 8);
        m_elemTex.reset(m_rhi->newTexture(QRhiTexture::RGBA32F, QSize(kTexWidth, m_texRows)));
        m_elemTex->create();
        m_texGeneration = 0;     // everything again
        return true;
    }
    bool uploadElementTexture(QRhiResourceUpdateBatch* rub, StageItem::Scene& sc) {
        const int rows = int(sc.tex.size() / (kTexWidth * 4));
        const bool changed = ensureElementTexture(std::max(rows, 1));
        int lo = sc.dirtyLo, hi = std::min(sc.dirtyHi, rows - 1);
        if (m_texGeneration != sc.generation) { lo = 0; hi = rows - 1; m_texGeneration = sc.generation; }
        sc.dirtyLo = INT_MAX; sc.dirtyHi = -1;
        if (rows <= 0 || hi < lo) return changed;
        QRhiTextureSubresourceUploadDescription d(sc.tex.data() + size_t(lo) * kTexWidth * 4, quint32((hi - lo + 1) * kTexWidth * 16));
        d.setSourceSize(QSize(kTexWidth, hi - lo + 1));
        d.setDestinationTopLeft(QPoint(0, lo));
        rub->uploadTexture(m_elemTex.get(), QRhiTextureUploadDescription({QRhiTextureUploadEntry(0, 0, d)}));
        return changed;
    }
    /** At most a budget per frame. A grown buffer starts over and draws what has arrived. Returns instances still to go. */
    qint64 uploadGeometry(QRhiResourceUpdateBatch* rub, StageItem::Scene& sc) {
        qsizetype budget = softwareAdapter(m_rhi) ? kUploadBytesPerFrame / 4 : kUploadBytesPerFrame;
        qint64 pending = 0;
        for (auto& [id, st] : sc.stores) {
            LayerGpu& g = m_layers[id];
            const qsizetype need = qsizetype(st.inst.size()) * qsizetype(sizeof(Inst));
            if (!g.buf || g.capacity < need) {
                g.capacity = std::max<qsizetype>(need + need / 2, 64 * 1024);
                g.buf.reset(m_rhi->newBuffer(QRhiBuffer::Static, QRhiBuffer::VertexBuffer, g.capacity));
                if (!g.buf->create()) { g.buf.reset(); g.capacity = 0; continue; }
                g.full = true;
            }
            if (g.generation != sc.generation) { g.generation = sc.generation; g.full = true; }
            if (g.full && g.fullPos == 0) { st.dirty.clear(); g.valid = 0; }
            if (g.full) {
                const size_t todo = st.inst.size() - g.fullPos;
                const size_t n = std::min<size_t>(todo, size_t(budget) / sizeof(Inst));
                if (n) rub->uploadStaticBuffer(g.buf.get(), qsizetype(g.fullPos * sizeof(Inst)), qsizetype(n * sizeof(Inst)), st.inst.data() + g.fullPos);
                g.fullPos += n;
                g.valid = int(g.fullPos);
                budget -= qsizetype(n * sizeof(Inst));
                if (g.fullPos >= st.inst.size()) { g.full = false; g.fullPos = 0; }
                else pending += qint64(st.inst.size() - g.fullPos);
            }
            if (!g.full) {
                size_t i = 0;
                for (; i < st.dirty.size() && budget > 0; ++i) {
                    Range& r = st.dirty[i];
                    const quint32 n = quint32(std::min<qsizetype>(r.cnt, budget / qsizetype(sizeof(Inst))));
                    if (n == 0) break;
                    rub->uploadStaticBuffer(g.buf.get(), qsizetype(r.off) * qsizetype(sizeof(Inst)), qsizetype(n) * qsizetype(sizeof(Inst)), st.inst.data() + r.off);
                    g.valid = std::max(g.valid, int(r.off + n));
                    budget -= qsizetype(n) * qsizetype(sizeof(Inst));
                    r.off += n; r.cnt -= n;
                    if (r.cnt > 0) break;
                }
                st.dirty.erase(st.dirty.begin(), st.dirty.begin() + qsizetype(i));
                for (const Range& r : st.dirty) pending += r.cnt;
            }
        }
        return pending;
    }
    void uploadImages(QRhiResourceUpdateBatch* rub, StageItem::Scene& sc, QSize px) {
        const QMatrix4x4 clip = mmToClip(m_rhi, px, m_view.zoom, m_view.panX, m_view.panY);
        for (auto it = m_images.begin(); it != m_images.end();) {
            const bool alive = std::any_of(sc.images.begin(), sc.images.end(), [&](const auto& im) { return im.img.id == it->first; });
            if (alive) ++it; else it = m_images.erase(it);
        }
        for (const auto& im : sc.images) {
            ImageGpu& g = m_images[im.img.id];
            g.visible = im.img.visible;
            if (g.version != im.version || !g.tex) {
                const QImage& src = im.img.image;
                const int limit = m_rhi->resourceLimit(QRhi::TextureSizeMax);
                const QImage up = std::max(src.width(), src.height()) > limit ? src.scaled(limit, limit, Qt::KeepAspectRatio, Qt::SmoothTransformation) : src;
                g.tex.reset(m_rhi->newTexture(QRhiTexture::RGBA8, up.size(), 1, QRhiTexture::MipMapped | QRhiTexture::UsedWithGenerateMips));
                if (!g.tex->create()) { g.tex.reset(); continue; }
                rub->uploadTexture(g.tex.get(), up);
                rub->generateMips(g.tex.get());
                if (!g.ubo) { g.ubo.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(QuadUbo))); g.ubo->create(); }
                g.srb.reset(m_rhi->newShaderResourceBindings());
                g.srb->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, g.ubo.get()),
                                    QRhiShaderResourceBinding::sampledTexture(1, QRhiShaderResourceBinding::FragmentStage, g.tex.get(), m_imgSampler.get())});
                g.srb->create();
                g.version = im.version;
            }
            QuadUbo u{};
            const QMatrix4x4 m = clip * QMatrix4x4(im.img.transform);
            memcpy(u.m, m.constData(), sizeof u.m);
            u.opacity = im.img.opacity;
            rub->updateDynamicBuffer(g.ubo.get(), 0, sizeof u, &u);
        }
    }
    void drawImages(QRhiCommandBuffer* cb, StageItem::Scene& sc, const QRhiViewport& vp) {
        for (const auto& im : sc.images) {
            const auto f = m_images.find(im.img.id);
            if (f == m_images.end() || !f->second.tex || !f->second.visible) continue;
            cb->setGraphicsPipeline(m_pipeImage.get());
            cb->setViewport(vp);
            cb->setShaderResources(f->second.srb.get());
            cb->draw(4);
        }
    }
    void writeSlot(QRhiResourceUpdateBatch* rub, int slot, const QMatrix4x4& clip, QSize px, const QColor& c) {
        StageUbo u{};
        memcpy(u.mmToClip, clip.constData(), sizeof u.mmToClip);
        u.viewportPx[0] = float(px.width()); u.viewportPx[1] = float(px.height());
        u.halfWidthPx = float(0.5 * m_lineWidth * m_view.dpr);
        u.selectedHalfPx = float(0.5 * m_selectedWidth * m_view.dpr);
        // Lines are premultiplied by the shader's output; the cover pipeline blends straight. See premulOverNonPremulSource.
        color(u.color, c);
        if (slot % 2 == 1) { u.color[0] *= u.color[3]; u.color[1] *= u.color[3]; u.color[2] *= u.color[3]; }
        const QColor s = premul(m_selectionColor);
        color(u.selected, s);
        rub->updateDynamicBuffer(m_ubo.get(), slot * m_stride, sizeof u, &u);
    }
    int writeOverlay(QRhiResourceUpdateBatch* rub, const StageItem::Scene& sc) {
        OverlayInst o[kMaxOverlay];
        int n = 0;
        const auto add = [&](QPointF a, QPointF b, const QColor& c, double halfPx) {
            if (n >= kMaxOverlay) return;
            o[n++] = {float(a.x()), float(a.y()), float(b.x()), float(b.y()), {quint8(c.red()), quint8(c.green()), quint8(c.blue()), quint8(c.alpha())}, float(halfPx)};
        };
        const double dpr = m_view.dpr;
        const QColor accent = m_selectionColor;
        if (sc.frame.size() == 4) {
            for (int i = 0; i < 4; ++i) add(sc.frame[i], sc.frame[(i + 1) % 4], accent, 0.625 * dpr);
            const double hOuter = 4.0 * dpr, hInner = 2.75 * dpr, mm = hOuter / m_view.zoom, mmIn = hInner / m_view.zoom;
            QPolygonF handles;
            for (int i = 0; i < 4; ++i) { handles << sc.frame[i]; handles << (sc.frame[i] + sc.frame[(i + 1) % 4]) * 0.5; }
            for (const QPointF& h : handles) {
                add(h - QPointF(mm, 0), h + QPointF(mm, 0), accent, hOuter);
                add(h - QPointF(mmIn, 0), h + QPointF(mmIn, 0), m_view.sheet, hInner);
            }
        }
        if (!sc.marquee.isNull()) {
            const QRectF r = sc.marquee;
            add(r.topLeft(), r.topRight(), accent, 0.5 * dpr); add(r.topRight(), r.bottomRight(), accent, 0.5 * dpr);
            add(r.bottomRight(), r.bottomLeft(), accent, 0.5 * dpr); add(r.bottomLeft(), r.topLeft(), accent, 0.5 * dpr);
        }
        if (n) rub->updateDynamicBuffer(m_overlay.get(), 0, n * sizeof(OverlayInst), o);
        return n;
    }

    QRhi* m_rhi = nullptr;
    StageItem* m_item = nullptr;
    std::shared_ptr<StageItem::Scene> m_scene;
    GpuViewItem::Snapshot m_view;
    BedPass m_bed;
    std::unique_ptr<QRhiBuffer> m_corners, m_indices, m_fanWeights, m_overlay, m_ubo, m_quadUboLayout;
    std::unique_ptr<QRhiTexture> m_elemTex, m_quadTexLayout;
    std::unique_ptr<QRhiSampler> m_elemSampler, m_imgSampler;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb, m_quadSrbLayout;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipeLine, m_pipeFan, m_pipeCover, m_pipeOverlay, m_pipeImage;
    std::map<int, LayerGpu> m_layers;
    std::map<quint64, ImageGpu> m_images;
    QVector<quint32> m_rpFormat;
    QRhiResourceUpdateBatch* m_initBatch = nullptr;
    quint32 m_stride = 256;
    int m_uboSlots = 0, m_texRows = 0;
    quint64 m_texGeneration = 0;
    QColor m_selectionColor;
    qreal m_lineWidth = 1.25, m_selectedWidth = 1.75;
};

StageItem::StageItem(QQuickItem* parent) : GpuViewItem(parent), m_scene(std::make_shared<Scene>()) {
    connect(&m_watcher, &QFutureWatcher<std::shared_ptr<Scene>>::finished, this, [this] {
        m_workerBusy = false;
        if (m_nextWork) { auto next = std::move(m_nextWork); m_nextWork = nullptr; startWorker(std::move(next)); return; }
        auto built = m_watcher.result();
        m_ops.push_back([built](Scene& s) { s.adoptGeometry(*built); });
        for (auto& op : m_held) m_ops.push_back(std::move(op));
        m_held.clear();
        update();
    });
}
StageItem::~StageItem() { m_watcher.waitForFinished(); }
QQuickRhiItemRenderer* StageItem::createRenderer() { return new StageRenderer; }

void StageItem::push(Op op) {
    (m_workerBusy ? m_held : m_ops).push_back(std::move(op));
    update();
}
void StageItem::workerDone() {
    if (!m_workerBusy && m_ops.empty() && m_loading) { m_loading = false; emit loadingChanged(); }
}
void StageItem::startWorker(std::function<std::shared_ptr<Scene>()> make) {
    if (m_workerBusy) { m_nextWork = std::move(make); return; }
    m_workerBusy = true;
    if (!m_loading) { m_loading = true; emit loadingChanged(); }
    m_watcher.setFuture(QtConcurrent::run([make = std::move(make)] { return make(); }));
}

void StageItem::setLayers(std::vector<StageLayer> layers) {
    auto held = std::make_shared<std::vector<StageLayer>>(std::move(layers));
    push([held](Scene& s) {
        s.order.clear();
        for (auto& [id, st] : s.stores) st.declared = false;
        for (const StageLayer& l : *held) { auto& st = s.stores[l.id]; st.desc = l; st.declared = true; s.order.push_back(l.id); }
    });
}
void StageItem::setElements(std::vector<StageElement> elements) {
    auto held = std::make_shared<std::vector<StageElement>>(std::move(elements));
    startWorker([held] {
        auto sc = std::make_shared<Scene>();
        for (const StageElement& e : *held) sc->upsert(pack(e));
        for (auto& [id, st] : sc->stores) st.dirty.clear();
        return sc;
    });
}
void StageItem::upsertElement(StageElement element) {
    auto p = std::make_shared<Packed>(pack(element));
    push([p](Scene& s) { s.upsert(std::move(*p)); });
}
void StageItem::upsertElements(std::vector<StageElement> elements) {
    auto p = std::make_shared<std::vector<Packed>>();
    p->reserve(elements.size());
    for (const StageElement& e : elements) p->push_back(pack(e));
    push([p](Scene& s) { for (Packed& e : *p) s.upsert(std::move(e)); });
}
void StageItem::removeElements(std::vector<quint64> ids) {
    push([ids = std::move(ids)](Scene& s) { for (quint64 id : ids) s.remove(id); });
}
void StageItem::setTransforms(std::vector<std::pair<quint64, QTransform>> transforms) {
    push([t = std::move(transforms)](Scene& s) {
        for (const auto& [id, m] : t) {
            const auto f = s.slotOf.constFind(id);
            if (f == s.slotOf.constEnd()) continue;
            s.elems[*f].t = m;
            s.writeTex(*f);
        }
    });
}
void StageItem::setElementVisible(quint64 id, bool visible) {
    push([id, visible](Scene& s) {
        const auto f = s.slotOf.constFind(id);
        if (f == s.slotOf.constEnd()) return;
        s.elems[*f].visible = visible;
        s.writeTex(*f);
    });
}
void StageItem::setSelection(std::vector<quint64> ids) { push([ids = std::move(ids)](Scene& s) { s.select(ids); }); }
void StageItem::setSelectionFrame(QPolygonF corners) { push([corners = std::move(corners)](Scene& s) { s.frame = corners; }); }
void StageItem::setMarquee(QRectF rect) { push([rect](Scene& s) { s.marquee = rect; }); }
void StageItem::setImage(StageImage image) {
    // Converting a big picture must not hold up the window.
    QtConcurrent::run([src = image.image] { return src.convertToFormat(QImage::Format_RGBA8888_Premultiplied); })
        .then(this, [this, image](QImage converted) mutable {
            image.image = std::move(converted);
            auto held = std::make_shared<StageImage>(std::move(image));
            push([held](Scene& s) {
                const quint64 v = ++s.imageVersion;
                for (auto& im : s.images) if (im.img.id == held->id) {
                    const bool same = im.img.image.cacheKey() == held->image.cacheKey();
                    im.img = *held;
                    if (!same) im.version = v;
                    return;
                }
                s.images.push_back({*held, v});
            });
        });
}
void StageItem::removeImage(quint64 id) {
    push([id](Scene& s) { s.images.erase(std::remove_if(s.images.begin(), s.images.end(), [&](const auto& im) { return im.img.id == id; }), s.images.end()); });
}

// --- test content --------------------------------------------------------------------------------------------------
namespace {
std::vector<QPointF> wobble(double cx, double cy, double r, int segs, int seed) {
    std::vector<QPointF> p;
    p.reserve(size_t(segs) + 1);
    for (int i = 0; i < segs; ++i) {
        const double a = 2 * M_PI * i / segs;
        const double k = r * (1.0 + 0.18 * std::sin(a * (3 + seed % 5) + seed));
        p.push_back({cx + k * std::cos(a), cy + k * std::sin(a)});
    }
    p.push_back(p.front());
    return p;
}
}

void StageItem::loadBenchmark(int paths, int segmentsPerPath) {
    const double bw = property("bedWidth").toDouble(), bh = property("bedHeight").toDouble();
    setLayers({StageLayer{1, QColor(0x4f, 0xd8, 0xb4), true}, StageLayer{2, QColor(0xe0, 0x5a, 0x7a), false}});
    m_benchIds.clear(); m_benchTransforms.clear();
    for (int i = 0; i < paths; ++i) { m_benchIds.push_back(quint64(i + 1)); m_benchTransforms.emplace_back(); }
    auto held = std::make_shared<std::vector<StageElement>>();
    startWorker([held, paths, segmentsPerPath, bw, bh] {
        const int cols = std::max(1, int(std::ceil(std::sqrt(double(paths) * bw / bh))));
        const int rows = std::max(1, int(std::ceil(double(paths) / cols)));
        const double pitchX = (bw - 20) / cols, pitchY = (bh - 60) / rows;
        auto sc = std::make_shared<Scene>();
        for (int i = 0; i < paths; ++i) {
            StageElement e;
            e.id = quint64(i + 1);
            const int c = i % cols, r = i / cols;
            const bool fill = (c + r) % 3 == 0;
            e.layer = fill ? 1 : 2;
            // Filled ones overlap their neighbours, so even-odd shows as holes where two meet.
            const double radius = std::min(pitchX, pitchY) * (fill ? 0.95 : 0.38);
            e.paths.push_back(wobble(10 + (c + 0.5) * pitchX, 50 + (r + 0.5) * pitchY, radius, std::max(3, segmentsPerPath), i));
            sc->upsert(pack(e));
        }
        for (auto& [id, st] : sc->stores) st.dirty.clear();
        return sc;
    });
}
int StageItem::benchmarkMove(int step, qreal dx, qreal dy) {
    std::vector<std::pair<quint64, QTransform>> t;
    t.reserve(m_benchIds.size() / size_t(std::max(1, step)) + 1);
    for (size_t i = 0; i < m_benchIds.size(); i += size_t(std::max(1, step))) {
        m_benchTransforms[i] = m_benchTransforms[i] * QTransform::fromTranslate(dx, dy);
        t.emplace_back(m_benchIds[i], m_benchTransforms[i]);
    }
    const int n = int(t.size());
    setTransforms(std::move(t));
    return n;
}
void StageItem::benchmarkReshape(int index) {
    StageElement e;
    e.id = quint64(index + 1);
    e.layer = 2;
    e.transform = size_t(index) < m_benchTransforms.size() ? m_benchTransforms[size_t(index)] : QTransform();
    e.paths.push_back(wobble(100 + index % 50, 100 + index % 37, 20, 64, index));
    upsertElement(std::move(e));
}
void StageItem::benchmarkImage() {
    QImage img(1024, 1024, QImage::Format_RGBA8888);
    for (int y = 0; y < img.height(); ++y) {
        auto* line = reinterpret_cast<quint8*>(img.scanLine(y));
        for (int x = 0; x < img.width(); ++x) {
            const double d = std::hypot(x - 512.0, y - 512.0) / 512.0;
            const int v = std::clamp(int(255 * (0.5 + 0.5 * std::cos(d * 14))), 0, 255);
            line[x * 4] = line[x * 4 + 1] = line[x * 4 + 2] = quint8(v); line[x * 4 + 3] = 255;
        }
    }
    StageImage s;
    s.id = 1;
    s.image = img;
    s.transform = QTransform(120, 0, 0, 120, 20, 80);
    s.opacity = 0.9f;
    setImage(std::move(s));
}
void StageItem::benchmarkEvenOdd() {
    const auto square = [](double x, double y, double s) { return std::vector<QPointF>{{x, y}, {x + s, y}, {x + s, y + s}, {x, y + s}, {x, y}}; };
    setLayers({StageLayer{7, QColor(0, 120, 255), true}});
    std::vector<StageElement> all(3);
    all[0].id = 1; all[0].layer = 7; all[0].paths = {square(100, 100, 100)};
    all[1].id = 2; all[1].layer = 7; all[1].paths = {square(150, 150, 100)};
    all[2].id = 3; all[2].layer = 7; all[2].paths = {{{300, 300}, {340, 300}, {340, 340}}};   // open: stroke only
    setElements(std::move(all));
}
void StageItem::benchmarkSelect(int n, QRectF frame) {
    std::vector<quint64> ids;
    for (int i = 0; i < n && size_t(i) < m_benchIds.size(); ++i) ids.push_back(m_benchIds[size_t(i)]);
    setSelection(std::move(ids));
    QPolygonF q;
    if (!frame.isNull()) q << frame.topLeft() << frame.topRight() << frame.bottomRight() << frame.bottomLeft();
    setSelectionFrame(q);
}
