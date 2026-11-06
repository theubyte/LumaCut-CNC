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
