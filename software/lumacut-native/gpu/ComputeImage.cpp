#include "ComputeImage.h"
#include <QElapsedTimer>
#include <QJsonDocument>
#include <QMetaObject>
#include <QQuickWindow>
#include <QtConcurrent/QtConcurrentFilter>
#include <QtConcurrent/QtConcurrentMap>
#include <QtConcurrent/QtConcurrentRun>
#include <QThreadPool>
#include <rhi/qrhi_platform.h>
#include <algorithm>
#include <cmath>
#include <random>
#include "RhiCommon.h"

using namespace rhiutil;

namespace {
struct ParamsUbo { float factor, shift, threshold; qint32 invert; qint32 mode; qint32 pad[3]; };
struct QuadUbo { float m[16]; float opacity; float pad[3]; };

ParamsUbo toUbo(const ComputeParams& p) {
    ParamsUbo u{};
    u.factor = float(100 + std::clamp(p.contrast, -100, 100)) / 100.0f;
    u.shift = float(std::clamp(p.brightness, -100, 100)) * 2.55f;
    u.threshold = float(p.threshold);
    u.invert = p.invert ? 1 : 0;
    u.mode = p.mode;
    return u;
}
const int kBayer[64] = {0, 48, 12, 60, 3, 51, 15, 63, 32, 16, 44, 28, 35, 19, 47, 31, 8, 56, 4, 52, 11, 59, 7, 55, 40, 24, 36, 20, 43, 27, 39, 23,
                        2, 50, 14, 62, 1, 49, 13, 61, 34, 18, 46, 30, 33, 17, 45, 29, 10, 58, 6, 54, 9, 57, 5, 53, 42, 26, 38, 22, 41, 25, 37, 21};

/** One compute pipeline with its bindings; used on the window's device and on a device of its own. */
class Kernel {
public:
    bool create(QRhi* rhi) {
        m_rhi = rhi;
        m_ubo.reset(rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(ParamsUbo)));
        return m_ubo->create();
    }
    bool bind(QRhiTexture* src, QRhiTexture* dst) {
        m_srb.reset(m_rhi->newShaderResourceBindings());
        m_srb->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::ComputeStage, m_ubo.get()),
                            QRhiShaderResourceBinding::imageLoad(1, QRhiShaderResourceBinding::ComputeStage, src, 0),
                            QRhiShaderResourceBinding::imageStore(2, QRhiShaderResourceBinding::ComputeStage, dst, 0)});
        if (!m_srb->create()) return false;
        m_pipe.reset(m_rhi->newComputePipeline());
        m_pipe->setShaderStage({QRhiShaderStage::Compute, shader("image.comp")});
        m_pipe->setShaderResourceBindings(m_srb.get());
        return m_pipe->create();
    }
    /** Recorded outside any render pass. after is applied at the end of the pass, e.g. readback or mipmaps. */
    void dispatch(QRhiCommandBuffer* cb, QRhiResourceUpdateBatch* before, QRhiResourceUpdateBatch* after, const ComputeParams& p, QSize size) {
        const ParamsUbo u = toUbo(p);
        before->updateDynamicBuffer(m_ubo.get(), 0, sizeof u, &u);
        cb->beginComputePass(before);
        cb->setComputePipeline(m_pipe.get());
        cb->setShaderResources();
        cb->dispatch((size.width() + 31) / 32, (size.height() + 31) / 32, 1);
        cb->endComputePass(after);
    }
private:
    QRhi* m_rhi = nullptr;
    std::unique_ptr<QRhiBuffer> m_ubo;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb;
    std::unique_ptr<QRhiComputePipeline> m_pipe;
};
}

class ComputeRenderer : public QQuickRhiItemRenderer {
public:
    void initialize(QRhiCommandBuffer*) override {
        m_rhi = rhi();
        const auto fmt = renderTarget()->renderPassDescriptor()->serializedFormat();
        if (m_pipe && m_rpFormat == fmt) return;
        m_rpFormat = fmt;
        if (!m_ubo) {
            m_ubo.reset(m_rhi->newBuffer(QRhiBuffer::Dynamic, QRhiBuffer::UniformBuffer, sizeof(QuadUbo)));
            m_ubo->create();
            m_sampler.reset(m_rhi->newSampler(QRhiSampler::Linear, QRhiSampler::Linear, QRhiSampler::Linear, QRhiSampler::ClampToEdge, QRhiSampler::ClampToEdge));
            m_sampler->create();
            m_gpu = m_rhi->isFeatureSupported(QRhi::Compute) && !qEnvironmentVariableIsSet("LUMACUT_NO_COMPUTE");
            if (m_gpu) m_gpu = m_kernel.create(m_rhi);
        }
        ensureTextures(QSize(1, 1));
        buildPipeline();
    }
    void synchronize(QQuickRhiItem* item) override {
        auto* it = static_cast<ComputeImage*>(item);
        m_item = it;
        m_continuous = it->m_continuous;
        m_params = it->m_p;
        m_itemSize = QSizeF(it->width(), it->height()) * (it->window() ? it->window()->effectiveDevicePixelRatio() : 1.0);
        if (m_imageVersion != it->m_imageVersion) { m_imageVersion = it->m_imageVersion; m_pendingImage = it->m_image; m_newImage = true; }
        if (m_paramsVersion != it->m_paramsVersion) { m_paramsVersion = it->m_paramsVersion; m_dirty = true; }
        if (!m_gpu) {
            it->m_backend.storeRelaxed(2);
            if (m_cpuVersion != it->m_cpuVersion) { m_cpuVersion = it->m_cpuVersion; m_pendingCpu = it->m_cpuResult; m_newCpu = true; }
            if (m_dirty || m_newImage) { m_dirty = false; QMetaObject::invokeMethod(it, [it] { it->runCpuFallback(); }, Qt::QueuedConnection); }
        } else {
            it->m_backend.storeRelaxed(1);
        }
    }
    void render(QRhiCommandBuffer* cb) override {
        auto* rub = m_rhi->nextResourceUpdateBatch();
        if (m_gpu) {
            if (m_newImage && !m_pendingImage.isNull()) {
                ensureTextures(m_pendingImage.size());
                rub->uploadTexture(m_src.get(), m_pendingImage);
                m_pendingImage = {};
                m_dirty = true;
                m_kernelBound = false;
            }
            m_newImage = false;
            if (!m_kernelBound && m_src) {
                m_kernelBound = m_kernel.bind(m_src.get(), m_dst.get());
                if (!m_kernelBound) {       // driver refused the pipeline: say so, the CPU takes over
                    m_gpu = false;
                    m_dst.reset();
                    QMetaObject::invokeMethod(m_item, [it = m_item] { it->update(); it->paramsTouched(); }, Qt::QueuedConnection);
                }
            }
            if (m_dirty && m_kernelBound && m_size.width() > 1) {
                auto* mips = m_rhi->nextResourceUpdateBatch();
                mips->generateMips(m_dst.get());
                m_kernel.dispatch(cb, rub, mips, m_params, m_size);
                rub = m_rhi->nextResourceUpdateBatch();
                m_dirty = false;
                m_hasOutput = true;
            }
        } else if (m_newCpu && !m_pendingCpu.isNull()) {
            ensureTextures(m_pendingCpu.size());
            rub->uploadTexture(m_dst.get(), m_pendingCpu);
            rub->generateMips(m_dst.get());
            m_pendingCpu = {};
            m_newCpu = false;
            m_hasOutput = true;
        }
        const QSize px = renderTarget()->pixelSize();
        QuadUbo u{};
        // Fit the picture into the item, keeping its proportions.
        const double k = std::min(m_itemSize.width() / std::max(1, m_size.width()), m_itemSize.height() / std::max(1, m_size.height()));
        const double w = m_size.width() * k, h = m_size.height() * k;
        const QMatrix4x4 clip = mmToClip(m_rhi, px, 1.0, (m_itemSize.width() - w) * 0.5, (m_itemSize.height() - h) * 0.5);
        QMatrix4x4 m = clip;
        m.scale(float(w), float(h));
        memcpy(u.m, m.constData(), sizeof u.m);
        u.opacity = 1;
        rub->updateDynamicBuffer(m_ubo.get(), 0, sizeof u, &u);
        cb->beginPass(renderTarget(), QColor(0, 0, 0, 0), {1.0f, 0}, rub);
        if (m_hasOutput) {
            cb->setGraphicsPipeline(m_pipe.get());
            cb->setViewport({0, 0, float(px.width()), float(px.height())});
            cb->setShaderResources(m_srb.get());
            cb->draw(4);
        }
        cb->endPass();
        if (m_continuous) { m_dirty = true; update(); }
    }

private:
    void ensureTextures(QSize size) {
        if (m_dst && size == m_size) return;
        m_size = size;
        if (m_gpu) {
            m_src.reset(m_rhi->newTexture(QRhiTexture::RGBA8, size, 1, QRhiTexture::UsedWithLoadStore));
            m_src->create();
        }
        QRhiTexture::Flags flags = QRhiTexture::MipMapped | QRhiTexture::UsedWithGenerateMips;
        if (m_gpu) flags |= QRhiTexture::UsedWithLoadStore;
        m_dst.reset(m_rhi->newTexture(QRhiTexture::RGBA8, size, 1, flags));
        m_dst->create();
        m_kernelBound = false;
        m_hasOutput = false;
        if (!m_srb) m_srb.reset(m_rhi->newShaderResourceBindings());
        m_srb->setBindings({QRhiShaderResourceBinding::uniformBuffer(0, QRhiShaderResourceBinding::VertexStage | QRhiShaderResourceBinding::FragmentStage, m_ubo.get()),
                            QRhiShaderResourceBinding::sampledTexture(1, QRhiShaderResourceBinding::FragmentStage, m_dst.get(), m_sampler.get())});
        m_srb->create();
    }
    void buildPipeline() {
        m_pipe.reset(m_rhi->newGraphicsPipeline());
        m_pipe->setTopology(QRhiGraphicsPipeline::TriangleStrip);
        m_pipe->setTargetBlends({premulOver()});
        m_pipe->setShaderStages({{QRhiShaderStage::Vertex, shader("quad.vert")}, {QRhiShaderStage::Fragment, shader("quad.frag")}});
        m_pipe->setVertexInputLayout({});
        m_pipe->setSampleCount(renderTarget()->sampleCount());
        m_pipe->setShaderResourceBindings(m_srb.get());
        m_pipe->setRenderPassDescriptor(renderTarget()->renderPassDescriptor());
        m_pipe->create();
    }

    QRhi* m_rhi = nullptr;
    ComputeImage* m_item = nullptr;
    Kernel m_kernel;
    std::unique_ptr<QRhiTexture> m_src, m_dst;
    std::unique_ptr<QRhiBuffer> m_ubo;
    std::unique_ptr<QRhiSampler> m_sampler;
    std::unique_ptr<QRhiShaderResourceBindings> m_srb;
    std::unique_ptr<QRhiGraphicsPipeline> m_pipe;
    QVector<quint32> m_rpFormat;
    QImage m_pendingImage, m_pendingCpu;
    QSize m_size;
    QSizeF m_itemSize;
    ComputeParams m_params;
    quint64 m_imageVersion = 0, m_paramsVersion = 0, m_cpuVersion = 0;
    bool m_gpu = false, m_kernelBound = false, m_dirty = false, m_newImage = false, m_newCpu = false, m_hasOutput = false, m_continuous = false;
};

ComputeImage::ComputeImage(QQuickItem* parent) : QQuickRhiItem(parent) {
    setAlphaBlending(true);
    connect(&m_cpuWatcher, &QFutureWatcher<QImage>::finished, this, [this] {
        m_cpuBusy = false;
        m_cpuResult = m_cpuWatcher.result();
        ++m_cpuVersion;
        update();
        if (m_cpuAgain) { m_cpuAgain = false; runCpuFallback(); }
    });
    connect(&m_loadWatcher, &QFutureWatcher<QImage>::finished, this, [this] { setImage(m_loadWatcher.result()); });
    connect(&m_benchWatcher, &QFutureWatcher<QString>::finished, this, [this] { m_benchResult = m_benchWatcher.result(); emit benchFinished(); });
    connect(this, &ComputeImage::continuousChanged, this, [this] { update(); });
}
ComputeImage::~ComputeImage() { m_cpuWatcher.waitForFinished(); m_loadWatcher.waitForFinished(); m_benchWatcher.waitForFinished(); }
QQuickRhiItemRenderer* ComputeImage::createRenderer() { return new ComputeRenderer; }

void ComputeImage::setImage(const QImage& image) {
    m_image = image.convertToFormat(QImage::Format_RGBA8888);
    ++m_imageVersion;
    update();
}
void ComputeImage::loadTestImage(int megapixels) { m_loadWatcher.setFuture(QtConcurrent::run([megapixels] { return makeTestImage(megapixels); })); }
void ComputeImage::paramsTouched() { ++m_paramsVersion; emit paramsChanged(); update(); }
void ComputeImage::runCpuFallback() {
    if (m_image.isNull()) return;
    if (m_cpuBusy) { m_cpuAgain = true; return; }
    m_cpuBusy = true;
    m_cpuWatcher.setFuture(QtConcurrent::run([img = m_image, p = m_p] { return processCpu(img, p); }));
}

QImage ComputeImage::processCpu(const QImage& input, const ComputeParams& p, int threads) {
    const QImage src = input.convertToFormat(QImage::Format_RGBA8888);
    QImage dst(src.size(), QImage::Format_RGBA8888);
    const int w = src.width(), h = src.height();
    if (w == 0 || h == 0) return dst;
    const ParamsUbo u = toUbo(p);
    quint8 lut[256];
    for (int g = 0; g < 256; ++g) {
        const float x = std::clamp((float(g) - 128.0f) * u.factor + 128.0f + u.shift, 0.0f, 255.0f);
        lut[g] = quint8(std::floor((p.invert ? 255.0f - x : x) + 0.5f));
    }
    const auto grey = [&](const quint8* s) {
        const float a = float(s[3]) / 255.0f;
        const float l = 0.2126f * s[0] + 0.7152f * s[1] + 0.0722f * s[2];
        return lut[std::clamp(int(std::floor(l * a + 255.0f * (1.0f - a) + 0.5f)), 0, 255)];
    };
    const auto rows = [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            const quint8* row = src.constScanLine(y);
            quint8* out = dst.scanLine(y);
            const quint8* up = src.constScanLine(std::max(0, y - 1));
            const quint8* dn = src.constScanLine(std::min(h - 1, y + 1));
            for (int x = 0; x < w; ++x) {
                int v;
                if (p.mode == ComputeParams::Edges) {
                    const int xl = std::max(0, x - 1) * 4, xr = std::min(w - 1, x + 1) * 4, xc = x * 4;
                    const float tl = grey(up + xl), t = grey(up + xc), tr = grey(up + xr), l = grey(row + xl), r = grey(row + xr), bl = grey(dn + xl), b = grey(dn + xc), br = grey(dn + xr);
                    const float gx = (tr + 2 * r + br) - (tl + 2 * l + bl), gy = (bl + 2 * b + br) - (tl + 2 * t + tr);
                    v = 255 - int(std::floor(std::min(255.0f, std::sqrt(gx * gx + gy * gy) * 0.25f) + 0.5f));
                } else {
                    v = grey(row + x * 4);
                    if (p.mode == ComputeParams::Threshold) v = v < p.threshold ? 0 : 255;
                    else if (p.mode == ComputeParams::Ordered) v = float(v) < (float(kBayer[(y & 7) * 8 + (x & 7)]) + 0.5f) * 255.0f / 64.0f ? 0 : 255;
                }
                out[x * 4] = out[x * 4 + 1] = out[x * 4 + 2] = quint8(v);
                out[x * 4 + 3] = 255;
            }
        }
    };
    if (threads == 1) { rows(0, h); return dst; }
    std::vector<int> starts;
    const int step = std::max(16, h / (QThreadPool::globalInstance()->maxThreadCount() * 4));
    for (int y = 0; y < h; y += step) starts.push_back(y);
    QtConcurrent::blockingMap(starts, [&](int y) { rows(y, std::min(h, y + step)); });
    return dst;
}

ComputeImage::Result ComputeImage::process(const QImage& input, const ComputeParams& params) {
    Result r;
    const QImage src = input.convertToFormat(QImage::Format_RGBA8888);
    const auto cpu = [&](const QString& why) {
        QElapsedTimer t; t.start();
        r.image = processCpu(src, params);
        r.computeMs = double(t.nsecsElapsed()) / 1e6;
        r.gpu = false;
        r.error = why;
        return r;
    };
    if (qEnvironmentVariableIsSet("LUMACUT_NO_COMPUTE")) return cpu(QStringLiteral("abgeschaltet"));
    QRhiD3D11InitParams init;
    QRhi::Flags flags;
    if (qEnvironmentVariableIsSet("QSG_RHI_PREFER_SOFTWARE_RENDERER")) flags |= QRhi::PreferSoftwareRenderer;
    std::unique_ptr<QRhi> rhi(QRhi::create(QRhi::D3D11, &init, flags));
    if (!rhi) return cpu(QStringLiteral("kein Gerät"));
    if (!rhi->isFeatureSupported(QRhi::Compute)) return cpu(QStringLiteral("kein Compute"));
    QImage result;
    {
        std::unique_ptr<QRhiTexture> a(rhi->newTexture(QRhiTexture::RGBA8, src.size(), 1, QRhiTexture::UsedWithLoadStore));
        std::unique_ptr<QRhiTexture> b(rhi->newTexture(QRhiTexture::RGBA8, src.size(), 1, QRhiTexture::UsedWithLoadStore));
        if (!a->create() || !b->create()) return cpu(QStringLiteral("Textur zu groß"));
        Kernel kernel;
        if (!kernel.create(rhi.get()) || !kernel.bind(a.get(), b.get())) return cpu(QStringLiteral("Pipeline"));
        QRhiCommandBuffer* cb = nullptr;
        QElapsedTimer t;
        // Each step ends with a small readback, because that is what really waits for the GPU.
        const auto syncPoint = [&](QRhiTexture* tex) {
            QRhiReadbackResult* tiny = new QRhiReadbackResult;
            QRhiReadbackDescription d(tex);
            d.setRect(QRect(0, 0, 1, 1));
            auto* rb = rhi->nextResourceUpdateBatch();
            rb->readBackTexture(d, tiny);
            return std::pair{rb, tiny};
        };
        t.start();
        rhi->beginOffscreenFrame(&cb);
        auto* up = rhi->nextResourceUpdateBatch();
        up->uploadTexture(a.get(), src);
        cb->resourceUpdate(up);
        auto [rb0, tiny0] = syncPoint(a.get());
        cb->resourceUpdate(rb0);
        rhi->endOffscreenFrame();
        delete tiny0;
        r.uploadMs = double(t.nsecsElapsed()) / 1e6;

        // Several dispatches per sync point, so the cost of the wait itself does not pass for compute time.
        constexpr int kRepeat = 8;
        t.restart();
        rhi->beginOffscreenFrame(&cb);
        auto [rb1, tiny1] = syncPoint(b.get());
        for (int i = 0; i < kRepeat; ++i)
            kernel.dispatch(cb, rhi->nextResourceUpdateBatch(), i == kRepeat - 1 ? rb1 : nullptr, params, src.size());
        rhi->endOffscreenFrame();
        delete tiny1;
        r.computeMs = double(t.nsecsElapsed()) / 1e6 / kRepeat;

        t.restart();
        QRhiReadbackResult full;
        rhi->beginOffscreenFrame(&cb);
        auto* rb2 = rhi->nextResourceUpdateBatch();
        rb2->readBackTexture(QRhiReadbackDescription(b.get()), &full);
        cb->resourceUpdate(rb2);
        rhi->endOffscreenFrame();
        r.readbackMs = double(t.nsecsElapsed()) / 1e6;
        if (full.data.size() >= src.width() * src.height() * 4) {
            QImage view(reinterpret_cast<const uchar*>(full.data.constData()), full.pixelSize.width(), full.pixelSize.height(),
                        full.data.size() / full.pixelSize.height(), QImage::Format_RGBA8888);
            result = view.copy();
        }
    }
    if (result.isNull()) return cpu(QStringLiteral("Rücklesen fehlgeschlagen"));
    r.image = std::move(result);
    r.gpu = true;
    return r;
}

int ComputeImage::maxDifference(const QImage& a, const QImage& b) {
    if (a.size() != b.size() || a.format() != b.format()) return 255;
    int worst = 0;
    for (int y = 0; y < a.height(); ++y) {
        const quint8* p = a.constScanLine(y);
        const quint8* q = b.constScanLine(y);
        for (int x = 0; x < a.width() * 4; ++x) worst = std::max(worst, std::abs(int(p[x]) - int(q[x])));
    }
    return worst;
}

QImage ComputeImage::makeTestImage(int megapixels) {
    const int h = int(std::sqrt(megapixels * 1e6 * 3.0 / 4.0)), w = h * 4 / 3;
    QImage img(w, h, QImage::Format_RGBA8888);
    std::vector<int> rows(size_t(h), 0);
    for (int y = 0; y < h; ++y) rows[size_t(y)] = y;
    QtConcurrent::blockingMap(rows, [&](int y) {
        std::minstd_rand rng(quint32(y + 1));
        quint8* o = img.scanLine(y);
        for (int x = 0; x < w; ++x) {
            const double u = double(x) / w, v = double(y) / h, d = std::hypot(u - 0.5, v - 0.5);
            double base = 0.5 + 0.3 * std::cos(d * 28.0) * (1.0 - d) + 0.2 * (u - 0.5);
            // Hard shapes, so that thresholds and edges have something to show.
            if (std::hypot(u - 0.27, (v - 0.3) * 0.75) < 0.12) base = 0.12;
            if (u > 0.62 && u < 0.86 && v > 0.58 && v < 0.84) base = 0.9;
            if (std::abs(u - v) < 0.006) base = 0.05;
            const int n = int(rng() % 13) - 6;
            o[x * 4] = quint8(std::clamp(int(255 * base) + n, 0, 255));
            o[x * 4 + 1] = quint8(std::clamp(int(255 * base * (0.8 + 0.4 * v)) + n, 0, 255));
            o[x * 4 + 2] = quint8(std::clamp(int(255 * (1 - base) * (0.6 + 0.4 * u)) + n, 0, 255));
            o[x * 4 + 3] = 255;
        }
    });
    return img;
}

void ComputeImage::startBenchmark(int megapixels) {
    m_benchResult.clear();
    m_benchWatcher.setFuture(QtConcurrent::run([megapixels] {
        const QImage img = makeTestImage(megapixels);
        QJsonObject out{{"width", img.width()}, {"height", img.height()}};
        ComputeParams p;
        p.contrast = 35; p.brightness = 10;
        const auto msOf = [](auto&& fn) { QElapsedTimer t; t.start(); fn(); return double(t.nsecsElapsed()) / 1e6; };
        QImage serial, parallel;
        out["cpu1Ms"] = msOf([&] { serial = processCpu(img, p, 1); });
        out["cpuMs"] = msOf([&] { parallel = processCpu(img, p); });
        out["threads"] = QThreadPool::globalInstance()->maxThreadCount();
        // Measure after a warm-up, as the slider would see it: the first dispatch includes driver setup.
        Result g = process(img, p);
        Result g2 = process(img, p);
        out["gpu"] = g2.gpu;
        out["gpuUploadMs"] = g2.uploadMs;
        out["gpuComputeMs"] = std::min(g.computeMs, g2.computeMs);
        out["gpuReadbackMs"] = g2.readbackMs;
        out["error"] = g2.error;
        out["maxDiffGrey"] = maxDifference(g2.image, parallel);
        for (const auto& [name, mode] : {std::pair{"threshold", int(ComputeParams::Threshold)}, std::pair{"ordered", int(ComputeParams::Ordered)}, std::pair{"edges", int(ComputeParams::Edges)}}) {
            ComputeParams q = p;
            q.mode = mode;
            QImage c;
            const double cpuMs = msOf([&] { c = processCpu(img, q); });
            Result r = process(img, q);
            out[QString::fromLatin1(name) + "CpuMs"] = cpuMs;
            out[QString::fromLatin1(name) + "GpuMs"] = r.computeMs;
            out[QString::fromLatin1(name) + "MaxDiff"] = maxDifference(r.image, c);
        }
        return QString::fromUtf8(QJsonDocument(out).toJson(QJsonDocument::Compact));
    }));
}
