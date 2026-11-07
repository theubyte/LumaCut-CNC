# Tests that need no window. UI tests against the real window live in tests/ui (Python driver).
set(LUMACUT_GOLDEN_DIR ${CMAKE_CURRENT_SOURCE_DIR}/golden)

function(lumacut_core_test name)
  qt_add_executable(${name} ${name}.cpp)
  target_link_libraries(${name} PRIVATE lumacut_core Qt6::Test)
  target_compile_definitions(${name} PRIVATE LUMACUT_GOLDEN_DIR="${LUMACUT_GOLDEN_DIR}")
  set_target_properties(${name} PROPERTIES WIN32_EXECUTABLE OFF MACOSX_BUNDLE OFF)
  add_test(NAME ${name} COMMAND ${name})
  # Qt liegt beim Testlauf auf dem Suchpfad, ohne Installation.
  set_tests_properties(${name} PROPERTIES ENVIRONMENT_MODIFICATION
    "PATH=path_list_prepend:$<TARGET_FILE_DIR:Qt6::Core>")
endfunction()

lumacut_core_test(test_golden)   # bis aufs Zeichen gegen den Kotlin-Code
lumacut_core_test(test_core)     # Projekt-JSON, Grenzfälle, Clipper, Vektorisieren, Kurven
lumacut_core_test(test_speed)    # Messung: Foto 2000 × 2000 bis G-Code und Werkzeugweg
set_tests_properties(test_speed PROPERTIES LABELS speed)

lumacut_core_test(test_import)         # alle Fälle aus Android und TypeScript, Rückimport des Exports
lumacut_core_test(test_import_robust)  # kaputte Dateien: abgeschnitten, zufällig verändert, Bomben
lumacut_core_test(test_import_big)     # Messung: 100.000 Pfade, Zeit und Speicher
target_link_libraries(test_import PRIVATE lumacut_import)
target_link_libraries(test_import_robust PRIVATE lumacut_import)
target_link_libraries(test_import_big PRIVATE lumacut_import)
set_tests_properties(test_import_big PROPERTIES LABELS speed)

lumacut_core_test(test_werkstatt)  # Werkstatt-Generatoren: QR, Box, Zahnrad, Materialtest, Seriennummern

lumacut_core_test(test_pcb)            # Platine: Gerber, Excellon, Lagen, Isolation, Spiegeln, Ins Projekt
target_link_libraries(test_pcb PRIVATE lumacut_pcb)
target_compile_definitions(test_pcb PRIVATE LUMACUT_PCB_DIR="${CMAKE_CURRENT_SOURCE_DIR}/pcb")

lumacut_core_test(test_perfboard)      # Lochraster: Raster, Bauteile, Drehung, Pad-Aussparung, Spiegeln, Prüfungen, Datei
target_link_libraries(test_perfboard PRIVATE lumacut_pcb Qt6::Gui)
