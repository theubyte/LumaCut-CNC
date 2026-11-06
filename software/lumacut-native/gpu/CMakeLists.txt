qt_add_library(lumacut_gpu STATIC
  GpuViewItem.h GpuViewItem.cpp
  RhiCommon.h BedPass.cpp
  FrameStats.h FrameStats.cpp
  SegmentsItem.h SegmentsItem.cpp
  StageItem.h StageItem.cpp
  ComputeImage.h ComputeImage.cpp
)
target_include_directories(lumacut_gpu PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(lumacut_gpu PUBLIC Qt6::Gui Qt6::GuiPrivate Qt6::Quick Qt6::Concurrent lumacut_core)
qt_add_shaders(lumacut_gpu "lumacut_gpu_shaders"
  PREFIX "/gpu"
  PRECOMPILE
  NOGLSL
  NOMSL
  FILES
    shaders/bed.vert
    shaders/bed.frag
    shaders/line.frag
    shaders/segments.vert
    shaders/mapshow.vert
    shaders/mapshow.frag
    shaders/stage_line.vert
    shaders/stage_fan.vert
    shaders/stage_cover.vert
    shaders/stage_cover.frag
    shaders/stage_overlay.vert
    shaders/quad.vert
    shaders/quad.frag
    shaders/image.comp
)
