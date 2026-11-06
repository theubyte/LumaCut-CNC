#include "RhiCommon.h"

namespace {
struct BedUbo {
    float clip[16];
    float bed[2], pan[2];
    float zoom, dpr, parkW, parkH;
    float showGrid, pad[3];
    float sheet[4], grid[4], gridMajor[4], edge[4], park[4];
};
}

void BedPass::create(QRhi* rhi, QRhiRenderPassDescriptor* rp, int samples) {
    m_rhi = rhi;
    m_ubo.reset(rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(BedUbo)));
    m_ubo->create();
    m_srb.reset(rhi->newShaderResourceBindings());
    m_srb->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, m_ubo.get())});
    m_srb->create();
    m_pipeline.reset(rhi->newGraphicsPipeline());
    m_pipeline->setTargetBlends({rhiutil::premulOver()});
    m_pipeline->setTopology(QRhiGraphicsPipeline::TriangleStrip);
    m_pipeline->setShaderStages({{QRhiShaderStage::Vertex, rhiutil::shader("bed.vert")}, {QRhiShaderStage::Fragment, rhiutil::shader("bed.frag")}});
    m_pipeline->setVertexInputLayout({});
    m_pipeline->setSampleCount(samples);
    m_pipeline->setShaderResourceBindings(m_srb.get());
    m_pipeline->setRenderPassDescriptor(rp);
    m_pipeline->create();
}

void BedPass::prepare(QRhiResourceUpdateBatch* rub, const GpuViewItem::Snapshot& s, QSize px) {
    m_visible = s.showSheet;
    if (!m_visible) return;
    BedUbo u{};
    const QMatrix4x4 m = rhiutil::mmToClip(m_rhi, px, 1.0, 0, 0);   // bed.vert works in device pixels
    memcpy(u.clip, m.constData(), sizeof u.clip);
    u.bed[0] = float(s.bedW); u.bed[1] = float(s.bedH);
    u.pan[0] = float(s.panX); u.pan[1] = float(s.panY);
    u.zoom = float(s.zoom); u.dpr = float(s.dpr);
    u.parkW = float(s.parkW); u.parkH = float(s.parkH);
    u.showGrid = s.showGrid ? 1 : 0;
    rhiutil::color(u.sheet, s.sheet); rhiutil::color(u.grid, s.grid); rhiutil::color(u.gridMajor, s.gridMajor);
    rhiutil::color(u.edge, s.edge); rhiutil::color(u.park, s.park);
    rub->updateDynamicBuffer(m_ubo.get(), 0, sizeof u, &u);
}

void BedPass::draw(QRhiCommandBuffer* cb, QSize px) {
    if (!m_visible) return;
    cb->setGraphicsPipeline(m_pipeline.get());
    cb->setViewport({0, 0, float(px.width()), float(px.height())});
    cb->setShaderResources();
    cb->draw(4);
}
