add_library(lumacut_core STATIC
  version.cpp
)
target_include_directories(lumacut_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/..)
target_link_libraries(lumacut_core PUBLIC Qt6::Core Qt6::Concurrent Clipper2)
target_compile_definitions(lumacut_core PUBLIC LUMACUT_VERSION_STR="${PROJECT_VERSION}")
