qt_add_library(lumacut_gpu STATIC
  SegmentsItem.h SegmentsItem.cpp
)
target_include_directories(lumacut_gpu PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(lumacut_gpu PUBLIC Qt6::Gui Qt6::GuiPrivate Qt6::Quick lumacut_core)
qt_add_shaders(lumacut_gpu "lumacut_gpu_shaders"
  PREFIX "/gpu"
  BATCHABLE
  PRECOMPILE
  FILES
    shaders/segments.vert
    shaders/segments.frag
)
