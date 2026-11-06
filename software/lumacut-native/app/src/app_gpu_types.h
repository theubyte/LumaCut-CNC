#pragma once
// Makes the GPU items visible to QML under "import LumaCut".
#include <QtQml/qqmlregistration.h>
#include "gpu/ComputeImage.h"
#include "gpu/GpuViewItem.h"
#include "gpu/SegmentsItem.h"
#include "gpu/StageItem.h"

struct GpuViewItemForeign {
    Q_GADGET
    QML_FOREIGN(GpuViewItem)
    QML_ANONYMOUS
};
struct SegmentsItemForeign {
    Q_GADGET
    QML_FOREIGN(SegmentsItem)
    QML_NAMED_ELEMENT(Segments)
};
struct StageItemForeign {
    Q_GADGET
    QML_FOREIGN(StageItem)
    QML_NAMED_ELEMENT(Stage)
};
struct ComputeImageForeign {
    Q_GADGET
    QML_FOREIGN(ComputeImage)
    QML_NAMED_ELEMENT(ComputeImage)
};
