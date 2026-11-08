#pragma once
#include <QQuickImageProvider>
#include "Workshop.h"

/** image://papier/<id>: the gallery pictures of the paper templates, painted once on the CPU by Workshop. */
class PaperThumbs : public QQuickImageProvider {
public:
    PaperThumbs() : QQuickImageProvider(QQuickImageProvider::Image) {}
    QImage requestImage(const QString& id, QSize* size, const QSize& requested) override {
        QImage img = Workshop::instance()->thumbImage(id);
        if (img.isNull()) { img = QImage(4, 4, QImage::Format_ARGB32_Premultiplied); img.fill(Qt::transparent); }
        if (requested.isValid() && !requested.isEmpty()) img = img.scaled(requested, Qt::KeepAspectRatio, Qt::SmoothTransformation);
        if (size) *size = img.size();
        return img;
    }
};
