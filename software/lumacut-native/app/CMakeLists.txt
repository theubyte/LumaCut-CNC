# New QML and C++ files are picked up automatically: put them under qml/ or src/. Basenames must be unique.
file(GLOB_RECURSE APP_SOURCES CONFIGURE_DEPENDS RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} src/*.cpp src/*.h)
file(GLOB_RECURSE APP_QML CONFIGURE_DEPENDS RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} qml/*.qml)
qt_add_executable(lumacut_studio WIN32 main.cpp ${APP_SOURCES})
set_target_properties(lumacut_studio PROPERTIES OUTPUT_NAME "LumaCutStudio")

set_source_files_properties(qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
qt_add_qml_module(lumacut_studio
  URI LumaCut
  VERSION 1.0
  QML_FILES ${APP_QML}
  DEPENDENCIES QtQuick QtQuick.Controls
)
target_link_libraries(lumacut_studio PRIVATE
  Qt6::Quick Qt6::QuickControls2 Qt6::Network Qt6::Svg lumacut_gpu lumacut_core)
target_include_directories(lumacut_studio PRIVATE src)
target_compile_definitions(lumacut_studio PRIVATE QT_MESSAGELOGCONTEXT)

install(TARGETS lumacut_studio RUNTIME DESTINATION bin BUNDLE DESTINATION bin)
qt_generate_deploy_qml_app_script(
  TARGET lumacut_studio
  OUTPUT_SCRIPT deploy_script
  NO_UNSUPPORTED_PLATFORM_ERROR
  DEPLOY_USER_QML_MODULES_ON_UNSUPPORTED_PLATFORM
  NO_TRANSLATIONS
  NO_COMPILER_RUNTIME
)
install(SCRIPT ${deploy_script})
