#ifndef LV_CONF_H
#define LV_CONF_H
#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 0
#define LV_USE_LOG 0
/* The 10-page PRO UI + modal keyboard exceed a small static 64 KB LVGL
 * pool. Allocate widget/style/text memory in external 8 MB PSRAM instead.
 * The RGB scanout framebuffer is already in PSRAM; the short LVGL DMA
 * transfer buffer remains explicitly allocated from internal DMA RAM.
 */
#define LV_MEM_CUSTOM 1
#define LV_MEM_CUSTOM_INCLUDE <esp_heap_caps.h>
#define LV_MEM_CUSTOM_ALLOC(size) heap_caps_malloc((size), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)
#define LV_MEM_CUSTOM_FREE(ptr) heap_caps_free((ptr))
#define LV_MEM_CUSTOM_REALLOC(ptr, size) heap_caps_realloc((ptr), (size), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)
#define LV_MEM_SIZE (64U * 1024U) /* inactive fallback when LV_MEM_CUSTOM=1 */
#define LV_TICK_CUSTOM 0
#define LV_USE_ASSERT_NULL 1
#define LV_USE_ASSERT_MALLOC 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_DEFAULT &lv_font_montserrat_16
#endif
