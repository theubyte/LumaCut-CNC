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
)
target_include_directories(lumacut_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(lumacut_core PUBLIC Qt6::Core Qt6::Concurrent Clipper2)
target_compile_definitions(lumacut_core PUBLIC LUMACUT_VERSION_STR="${PROJECT_VERSION}")
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
