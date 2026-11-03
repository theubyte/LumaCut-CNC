file(GLOB FONT_SRCS "${CMAKE_CURRENT_SOURCE_DIR}/fonts/*.c")
idf_component_register(
    SRCS "main.c" "board.c" "lvgl_port.c" "link.c" "ui.c" ${FONT_SRCS}
    INCLUDE_DIRS "."
    REQUIRES esp_lcd driver esp_timer esp_jpeg nvs_flash)

idf_component_get_property(lvgl_lib lvgl__lvgl COMPONENT_LIB)
target_compile_options(${lvgl_lib} PRIVATE -Wno-format)
