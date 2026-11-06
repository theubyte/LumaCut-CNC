#pragma once
// Small helpers shared by the GPU items. Internal to gpu/.
#include <QColor>
#include <QFile>
#include <QMatrix4x4>
#include <rhi/qrhi.h>
#include <rhi/qshader.h>
#include <memory>
#include "GpuViewItem.h"

namespace rhiutil {
inline QShader shader(const QString& name) {
    QFile f(QStringLiteral(":/gpu/shaders/") + name + QStringLiteral(".qsb"));
    return f.open(QIODevice::ReadOnly) ? QShader::fromSerialized(f.readAll()) : QShader();
}
inline void color(float* o, const QColor& c) { o[0] = c.redF(); o[1] = c.greenF(); o[2] = c.blueF(); o[3] = c.alphaF(); }
/** mm (y down) to clip space for a target of `px` device pixels. */
inline QMatrix4x4 mmToClip(QRhi* rhi, QSize px, double zoom, double panX, double panY) {
    const float yFlip = rhi->isYUpInNDC() ? -1.0f : 1.0f;
    QMatrix4x4 m;
    m.translate(-1, -yFlip);
    m.scale(2.0f / px.width(), yFlip * 2.0f / px.height());
    m.translate(float(panX), float(panY));
    m.scale(float(zoom), float(zoom));
    return m;
}
inline QRhiGraphicsPipeline::TargetBlend premulOver() {
    QRhiGraphicsPipeline::TargetBlend b;
    b.enable = true;
    b.srcColor = QRhiGraphicsPipeline::One; b.dstColor = QRhiGraphicsPipeline::OneMinusSrcAlpha;
    b.srcAlpha = QRhiGraphicsPipeline::One; b.dstAlpha = QRhiGraphicsPipeline::OneMinusSrcAlpha;
    return b;
}
inline bool softwareAdapter(QRhi* rhi) { return rhi->driverInfo().deviceType == QRhiDriverInfo::CpuDevice; }
inline QColor premul(const QColor& c) {
    QColor o; o.setRgbF(c.redF() * c.alphaF(), c.greenF() * c.alphaF(), c.blueF() * c.alphaF(), c.alphaF());
    return o;
}
// One unit quad in the instance technique: x 0..1 along the segment, y -1..1 across.
inline constexpr float kLineCorners[] = {0, -1, 1, -1, 1, 1, 0, 1};
inline constexpr quint16 kLineIndices[] = {0, 1, 2, 0, 2, 3};
}

/** The sheet: drop shadow, crisp grid without moire, park corner. One draw, procedural in the fragment shader. */
class BedPass {
public:
    void create(QRhi* rhi, QRhiRenderPassDescriptor* rp, int samples);
    void prepare(QRhiResourceUpdateBatch* rub, const GpuViewItem::Snapshot& s, QSize px);
    void draw(QRhiCommandBuffer* cb, QSize px);
private:
    QRhi* m_rhi = nullptr;
    std::unique_ptr<QRhiBuffer> m_ubo;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipeline;
    bool m_visible = true;
};
