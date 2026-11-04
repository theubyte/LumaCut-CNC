// Display, touch and IO expander of the Waveshare ESP32-S3-Touch-LCD-7.
// Pins and timings from the Waveshare ESP-IDF demo (08_lvgl_Porting).

#include "board.h"

#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "lvgl_port.h"

static const char *TAG = "board";

#define I2C_PORT        0
#define I2C_SDA         8
#define I2C_SCL         9
#define TOUCH_INT       4      // held low during the touch reset: GT911 address 0x5D
#define CH422G_MODE     0x24
#define CH422G_OUT      0x38
// CH422G outputs: EXIO1 touch reset, EXIO2 backlight, EXIO3 LCD reset,
// EXIO4 SD card CS, EXIO5 USB_SEL (0 = USB-C "USB" goes to the ESP32, 1 = CAN).
#define EXIO_TP_RST     (1 << 1)
#define EXIO_BL         (1 << 2)
#define EXIO_LCD_RST    (1 << 3)
#define EXIO_SD_CS      (1 << 4)

static uint8_t exio = EXIO_TP_RST | EXIO_BL | EXIO_LCD_RST | EXIO_SD_CS;

static void ch422g_write(uint8_t value)
{
    uint8_t mode = 0x01;   // push-pull outputs
    i2c_master_write_to_device(I2C_PORT, CH422G_MODE, &mode, 1, pdMS_TO_TICKS(100));
    i2c_master_write_to_device(I2C_PORT, CH422G_OUT, &value, 1, pdMS_TO_TICKS(100));
}

void board_backlight(bool on)
{
    exio = on ? (exio | EXIO_BL) : (exio & ~EXIO_BL);
    ch422g_write(exio);
}

IRAM_ATTR static bool on_frame(esp_lcd_panel_handle_t panel, const esp_lcd_rgb_panel_event_data_t *e, void *ctx)
{
    return lvgl_port_notify_rgb_vsync();
}

static esp_lcd_touch_handle_t touch_init(void)
{
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_SDA,
        .scl_io_num = I2C_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_PORT, &conf));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_PORT, conf.mode, 0, 0, 0));

    gpio_config_t io = {.pin_bit_mask = 1ULL << TOUCH_INT, .mode = GPIO_MODE_OUTPUT};
    gpio_config(&io);
    // Touch reset with INT low; USB_SEL stays 0 throughout so the Pi link never drops.
    ch422g_write(EXIO_BL | EXIO_LCD_RST);
    esp_rom_delay_us(100 * 1000);
    gpio_set_level(TOUCH_INT, 0);
    esp_rom_delay_us(100 * 1000);
    ch422g_write(EXIO_TP_RST | EXIO_BL | EXIO_LCD_RST);
    esp_rom_delay_us(200 * 1000);
    ch422g_write(exio);

    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_i2c_config_t io_conf = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    io_conf.scl_speed_hz = 0;   // legacy i2c driver: the bus speed is set above, must be 0 here
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c((esp_lcd_i2c_bus_handle_t)I2C_PORT, &io_conf, &io_handle));
    esp_lcd_touch_config_t tp_conf = {
        .x_max = LVGL_PORT_H_RES,
        .y_max = LVGL_PORT_V_RES,
        .rst_gpio_num = -1,
        .int_gpio_num = -1,
    };
    esp_lcd_touch_handle_t tp = NULL;
    ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_gt911(io_handle, &tp_conf, &tp));
    return tp;
}

esp_err_t board_init(void)
{
    esp_lcd_rgb_panel_config_t conf = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = 16 * 1000 * 1000,
            .h_res = LVGL_PORT_H_RES,
            .v_res = LVGL_PORT_V_RES,
            .hsync_pulse_width = 4, .hsync_back_porch = 8, .hsync_front_porch = 8,
            .vsync_pulse_width = 4, .vsync_back_porch = 8, .vsync_front_porch = 8,
            .flags = {.pclk_active_neg = 1},
        },
        .data_width = 16,
        .bits_per_pixel = 16,
        .num_fbs = LVGL_PORT_LCD_RGB_BUFFER_NUMS,
        .bounce_buffer_size_px = LVGL_PORT_H_RES * CONFIG_EXAMPLE_LCD_RGB_BOUNCE_BUFFER_HEIGHT,
        .sram_trans_align = 4,
        .psram_trans_align = 64,
        .hsync_gpio_num = 46,
        .vsync_gpio_num = 3,
        .de_gpio_num = 5,
        .pclk_gpio_num = 7,
        .disp_gpio_num = -1,
        .data_gpio_nums = {14, 38, 18, 17, 10, 39, 0, 45, 48, 47, 21, 1, 2, 42, 41, 40},
        .flags = {.fb_in_psram = 1},
    };
    esp_lcd_panel_handle_t panel = NULL;
    ESP_ERROR_CHECK(esp_lcd_new_rgb_panel(&conf, &panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));

    esp_lcd_touch_handle_t tp = touch_init();
    ESP_ERROR_CHECK(lvgl_port_init(panel, tp));
    esp_lcd_rgb_panel_event_callbacks_t cbs = {.on_bounce_frame_finish = on_frame};
    ESP_ERROR_CHECK(esp_lcd_rgb_panel_register_event_callbacks(panel, &cbs, NULL));
    ESP_LOGI(TAG, "display ready");
    return ESP_OK;
}
