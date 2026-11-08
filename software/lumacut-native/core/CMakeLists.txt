add_library(lumacut_core STATIC
  version.cpp
  model.h model.cpp model_json.cpp
  parallel.h parallel.cpp fastnum.h
  gcode.h gcode.cpp
  toolpath.h toolpath.cpp
  image.h image.cpp
  geometry.h geometry.cpp
  darkness.h darkness.cpp
  material.h material.cpp
  frame.h frame.cpp
  contour.h contour.cpp
  parts.h parts.cpp
  extras.h extras.cpp
  tools.h tools.cpp
  create.h create.cpp
  curves.h curves.cpp
  vectorize.h vectorize.cpp
  boolean.h boolean.cpp
  werkstatt/qr.h werkstatt/qr.cpp werkstatt/generators.h werkstatt/generators.cpp
  papier/papier.h papier/papier_net.h papier/papier_core.cpp papier/papier_vorlagen.cpp
  camera/scan.h camera/scan.cpp
)
target_include_directories(lumacut_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(lumacut_core PUBLIC Qt6::Core Qt6::Concurrent Clipper2)
# Only version.cpp sees the number, so a new version recompiles one file, not the whole program.
set_source_files_properties(version.cpp PROPERTIES COMPILE_DEFINITIONS LUMACUT_VERSION_STR="${PROJECT_VERSION}")
if(MSVC)
  # Fließkomma streng und ohne FMA-Zusammenziehen: die Golden-Dateien hängen am letzten Bit.
  target_compile_options(lumacut_core PRIVATE /fp:precise)
endif()

# Import und Export: eigene Bibliothek, weil Bilder QImage (QtGui) brauchen. lumacut_core bleibt bei Qt Core.
add_library(lumacut_import STATIC
  export.h export.cpp
  import/import.h import/vector.h import/xml.h import/zip.h
  import/import.cpp import/xml.cpp import/zip.cpp import/svg.cpp import/dxf.cpp import/formats.cpp
  import/xtool.cpp import/layout.cpp import/import_image.cpp
)
target_link_libraries(lumacut_import PUBLIC lumacut_core Qt6::Gui)

# Text als Umrisse über Systemschriften: braucht QtGui, darum eine eigene kleine Bibliothek.
add_library(lumacut_text STATIC text.h text.cpp)
target_link_libraries(lumacut_text PUBLIC lumacut_core Qt6::Gui)

# Platine: Gerber, Excellon, isolation and resist geometry (core/pcb). Example board as a resource.
add_library(lumacut_pcb STATIC
  pcb/geom.h pcb/geom.cpp pcb/gerber.h pcb/gerber.cpp pcb/excellon.h pcb/excellon.cpp
  pcb/layers.h pcb/layers.cpp pcb/board.h pcb/board.cpp pcb/job.h pcb/job.cpp
  pcb/perfboard.h pcb/perfboard.cpp
)
target_link_libraries(lumacut_pcb PUBLIC lumacut_core lumacut_import lumacut_text)
qt_add_resources(lumacut_pcb pcb_example PREFIX /pcb BASE pcb/beispiel FILES
  pcb/beispiel/beispiel.GTL pcb/beispiel/beispiel.GBL pcb/beispiel/beispiel.GTS pcb/beispiel/beispiel.GBS
  pcb/beispiel/beispiel.GTO pcb/beispiel/beispiel.GKO pcb/beispiel/beispiel.DRL)
qt_add_resources(lumacut_pcb perfboard_parts PREFIX /pcb BASE pcb FILES pcb/perfboard_parts.json
  pcb/vorlagen/laser-interface-v2.lumaraster)
