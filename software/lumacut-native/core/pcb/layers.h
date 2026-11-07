#pragma once
/** Recognises what a fabrication file is: X2 attribute first, then file name, then content. */
#include <QString>
#include <string_view>

namespace lumacut::pcb {

enum class LayerKind {
    CopperTop, CopperBottom, CopperInner, MaskTop, MaskBottom, SilkTop, SilkBottom, PasteTop, PasteBottom, Outline, Drill, Other
};
inline constexpr int kLayerKindCount = 12;

/** German label for the UI, e.g. "Kupfer oben". */
QString layerLabel(LayerKind k);
/** Stable key, e.g. "copper-top" (as in the Tauri version). */
QString layerKey(LayerKind k);
LayerKind layerFromKey(const QString& key);

/** X2 attribute value, for example "Copper,L1,Top". Returns Other if it says nothing usable. */
LayerKind kindFromFileFunction(const QString& f);
bool looksLikeDrill(std::string_view text);
/** text may be empty: then only the name counts. */
LayerKind classifyLayer(const QString& fileName, std::string_view text = {});

}  // namespace lumacut::pcb
