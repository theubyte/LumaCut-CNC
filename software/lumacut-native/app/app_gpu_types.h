#pragma once
// Makes the GPU items visible to QML under "import LumaCut".
#include <QtQml/qqmlregistration.h>
#include "gpu/SegmentsItem.h"

struct SegmentsItemForeign {
    Q_GADGET
    QML_FOREIGN(SegmentsItem)
    QML_NAMED_ELEMENT(Segments)
};
