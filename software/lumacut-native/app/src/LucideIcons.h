#pragma once
#include <QHash>
#include <QString>
// SVG body of a Lucide icon (24x24, stroke only), or nullptr. Add icons with tools/gen_lucide.mjs.
const char* lucideIconBody(const QString& name);
