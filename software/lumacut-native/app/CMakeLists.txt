qt_add_executable(lumacut_studio WIN32
  main.cpp
  Automation.h Automation.cpp
)
set_target_properties(lumacut_studio PROPERTIES OUTPUT_NAME "LumaCutStudio")

set_source_files_properties(qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
qt_add_qml_module(lumacut_studio
  URI LumaCut
  VERSION 1.0
  QML_FILES
    qml/Main.qml
    qml/Theme.qml
    qml/TopBar.qml
    qml/Rail.qml
    qml/Placeholder.qml
    qml/GpuProbe.qml
  DEPENDENCIES QtQuick QtQuick.Controls
)
# Types from the GPU library, registered in the same QML module.
target_sources(lumacut_studio PRIVATE app_gpu_types.h)

target_link_libraries(lumacut_studio PRIVATE
  Qt6::Quick Qt6::QuickControls2 Qt6::Network Qt6::Svg lumacut_gpu lumacut_core)
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
