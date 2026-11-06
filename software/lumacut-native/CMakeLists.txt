cmake_minimum_required(VERSION 3.24)
project(LumaCutStudio VERSION 0.2.0 LANGUAGES CXX)
# CI sets the build number; the MSI upgrades by version.
if(LUMACUT_VERSION)
  set(PROJECT_VERSION ${LUMACUT_VERSION})
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC OFF)
set(CMAKE_AUTORCC ON)
if(MSVC)
  add_compile_options(/W3 /utf-8 /permissive- /Zc:__cplusplus /MP)
  # No exceptions off, no RTTI off: Qt and Clipper2 need neither removed, std::variant etc. stay simple.
endif()

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui GuiPrivate Network Concurrent Qml Quick QuickControls2 ShaderTools Svg Test)
qt_standard_project_setup(REQUIRES 6.8)

enable_testing()
add_subdirectory(third_party)
add_subdirectory(core)    # lumacut_core: geometry, G-code, toolpath, images. Qt Core only, no GUI.
add_subdirectory(gpu)     # lumacut_gpu: QRhi items and compute shaders.
add_subdirectory(app)     # the program: QML shell, Pi client, features.
add_subdirectory(tests)

include(packaging/packaging.cmake)
