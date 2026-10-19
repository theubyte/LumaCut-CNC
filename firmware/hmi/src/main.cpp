/*
  LumaCut 7-inch HMI v0.1 – real RGB/GT911 LVGL dashboard.
  INTERLOCK: NO motion or laser commands are transmitted by this build.
  Future UART builds require signed-off board electrical + grblHAL protocol.
  This firmware provides a functional touch panel, editable calibration
  preview, no laser-control outputs, and startup-safe status indication.
*/
#include <Arduino.h>
#include <Wire.h>
#include <lvgl.h>
#include "esp_lcd_panel_rgb.h"
#include "esp_lcd_panel_ops.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

static constexpr int W=800, H=480;
static constexpr uint8_t GT=0x5D, CH_MODE=0x24, CH_OUT=0x38;
static constexpr int PIN_SDA=8, PIN_SCL=9;
static constexpr uint16_t TOUCH_STATUS=0x814E, TOUCH_POINTS=0x814F;

static esp_lcd_panel_handle_t panel=nullptr;
static lv_disp_draw_buf_t drawbuf;
static lv_disp_drv_t display_driver;
static lv_indev_drv_t input_driver;
static lv_color_t* pixels=nullptr;
static lv_obj_t* status_label=nullptr;
static lv_obj_t* x_label=nullptr;
static lv_obj_t* y_label=nullptr;
static lv_obj_t* z_label=nullptr;
static lv_obj_t* profile_label=nullptr;
static lv_obj_t* message_label=nullptr;
static lv_obj_t* step_label=nullptr;
static lv_obj_t* tool_label=nullptr;
static int selected_step=1;
static const float steps[]={0.1f,1.0f,10.0f};
static bool touch_ready=false;

static bool write_expander(uint8_t addr,uint8_t data) {
    Wire.beginTransmission(addr);
    Wire.write(data);
    return Wire.endTransmission()==0;
}
static bool read_touch_reg(uint16_t reg,uint8_t* out,uint8_t count) {
    Wire.beginTransmission(GT);
    Wire.write(static_cast<uint8_t>(reg >> 8));
    Wire.write(static_cast<uint8_t>(reg));
    if(Wire.endTransmission(false)!=0) return false;
    if(Wire.requestFrom(GT,count)!=(int)count) return false;
    for(uint8_t i=0;i<count;++i) out[i]=Wire.read();
    return true;
}
static bool clear_touch() {
    Wire.beginTransmission(GT);
    Wire.write(0x81); Wire.write(0x4E); Wire.write(0x00);
    return Wire.endTransmission()==0;
}
static void init_i2c() {
    Wire.begin(PIN_SDA,PIN_SCL,400000);
    write_expander(CH_MODE,0);
    write_expander(CH_OUT,0);
    delay(30);
    // CH422G outputs: LCD RESET bit0, GT911 RESET bit1, BL bit2.
    write_expander(CH_OUT,0x07);
    delay(120);
    uint8_t product[4]{};
    touch_ready=read_touch_reg(0x8140,product,4);
    Serial.printf("GT911 detected: %d\n",touch_ready);
}
static void flush_cb(lv_disp_drv_t* d,const lv_area_t* a,lv_color_t* px) {
    if(panel) {
        esp_lcd_panel_draw_bitmap(panel,a->x1,a->y1,a->x2+1,a->y2+1,px);
    }
    lv_disp_flush_ready(d);
}
static void touch_cb(lv_indev_drv_t* d,lv_indev_data_t* data) {
    (void)d;
    static int16_t last_x=0,last_y=0;
    data->state=LV_INDEV_STATE_REL;
    data->point.x=last_x; data->point.y=last_y;
    if(!touch_ready) return;
    uint8_t status=0;
    if(!read_touch_reg(TOUCH_STATUS,&status,1)) return;
    if(!(status&0x80)) return;
    if((status&0x0F)!=0) {
        uint8_t pt[7]{};
        if(read_touch_reg(TOUCH_POINTS,pt,7)) {
            // GT911 first contact: TrackID, X_L, X_H, Y_L, Y_H.
            last_x=(int16_t)(pt[1]|(pt[2]<<8));
            last_y=(int16_t)(pt[3]|(pt[4]<<8));
            if(last_x>=0&&last_x<W&&last_y>=0&&last_y<H) {
                data->state=LV_INDEV_STATE_PR;
                data->point.x=last_x; data->point.y=last_y;
            }
        }
    }
    clear_touch();
}
static void tick_cb(void*){lv_tick_inc(5);}

static bool lcd_begin() {
    esp_lcd_rgb_panel_config_t cfg={};
    cfg.clk_src=LCD_CLK_SRC_PLL160M;
    cfg.timings.pclk_hz=16*1000*1000;
    cfg.timings.h_res=W;
    cfg.timings.v_res=H;
    cfg.timings.hsync_pulse_width=4;
    cfg.timings.hsync_back_porch=43;
    cfg.timings.hsync_front_porch=210;
    cfg.timings.vsync_pulse_width=4;
    cfg.timings.vsync_back_porch=12;
    cfg.timings.vsync_front_porch=22;
    cfg.timings.flags.pclk_active_neg=1;
    cfg.data_width=16;
    cfg.sram_trans_align=4;
    cfg.psram_trans_align=64;
    cfg.hsync_gpio_num=46;
    cfg.vsync_gpio_num=3;
    cfg.de_gpio_num=5;
    cfg.pclk_gpio_num=7;
    cfg.disp_gpio_num=GPIO_NUM_NC;
    cfg.flags.fb_in_psram=true;
    const int pins[16]={14,38,18,17,10,39,0,45,48,47,21,1,2,42,41,40};
    for(int i=0;i<16;i++) cfg.data_gpio_nums[i]=pins[i];
    esp_err_t err=esp_lcd_new_rgb_panel(&cfg,&panel);
    if(err!=ESP_OK) {Serial.printf("rgb error 0x%x\n",err);return false;}
    if(esp_lcd_panel_reset(panel)!=ESP_OK||esp_lcd_panel_init(panel)!=ESP_OK) return false;
    return true;
}
static bool lvgl_begin() {
    lv_init();
    pixels=(lv_color_t*)heap_caps_malloc(W*16*sizeof(lv_color_t),MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
    if(!pixels)return false;
    lv_disp_draw_buf_init(&drawbuf,pixels,nullptr,W*16);
    lv_disp_drv_init(&display_driver);
    display_driver.hor_res=W; display_driver.ver_res=H;
    display_driver.flush_cb=flush_cb; display_driver.draw_buf=&drawbuf;
    lv_disp_drv_register(&display_driver);
    lv_indev_drv_init(&input_driver);
    input_driver.type=LV_INDEV_TYPE_POINTER;
    input_driver.read_cb=touch_cb;
    lv_indev_drv_register(&input_driver);
    esp_timer_handle_t timer=nullptr;
    const esp_timer_create_args_t arg={.callback=tick_cb,.arg=nullptr,.dispatch_method=ESP_TIMER_TASK,.name="lvgl_tick"};
    if(esp_timer_create(&arg,&timer)!=ESP_OK)return false;
    return esp_timer_start_periodic(timer,5000)==ESP_OK;
}
static lv_obj_t* label(lv_obj_t* parent,const char* text,int x,int y,int size) {
    lv_obj_t* item=lv_label_create(parent);
    lv_label_set_text(item,text);
    lv_obj_set_pos(item,x,y);
    lv_obj_set_style_text_color(item,lv_color_hex(0xDCE9F3),0);
    if(size>=20) lv_obj_set_style_text_font(item,&lv_font_montserrat_20,0);
    else lv_obj_set_style_text_font(item,&lv_font_montserrat_16,0);
    return item;
}
static lv_obj_t* button(lv_obj_t* parent,const char* text,int x,int y,int w,int h,
                         lv_event_cb_t on_click) {
    lv_obj_t* obj=lv_btn_create(parent);
    lv_obj_set_size(obj,w,h); lv_obj_set_pos(obj,x,y);
    lv_obj_set_style_radius(obj,12,0);
    lv_obj_set_style_bg_color(obj,lv_color_hex(0x344C66),0);
    lv_obj_set_style_border_color(obj,lv_color_hex(0x517896),0);
    lv_obj_set_style_border_width(obj,1,0);
    if(on_click) lv_obj_add_event_cb(obj,on_click,LV_EVENT_CLICKED,nullptr);
    lv_obj_t* child=lv_label_create(obj);
    lv_label_set_text(child,text); lv_obj_center(child);
    return obj;
}
static void notify_disabled(lv_event_t*) {
    lv_label_set_text(message_label,"Sicherheit: Bedienbefehle noch gesperrt. SKR-Verbindung nicht freigegeben.");
}
static void cycle_step(lv_event_t*) {
    selected_step=(selected_step+1)%3;
    char buf[48];snprintf(buf,sizeof(buf),"Schritt: %.1f mm",steps[selected_step]);
    lv_label_set_text(step_label,buf);
}
static void show_profile(lv_event_t*) {
    lv_label_set_text(message_label,"Taster-Profil: XY/Z-Offsets werden erst nach Kalibrierung aktiviert.");
}
static void init_ui() {
    lv_obj_t* root=lv_scr_act();
    lv_obj_set_style_bg_color(root,lv_color_hex(0x0E1622),0);
    lv_obj_clear_flag(root,LV_OBJ_FLAG_SCROLLABLE);
    label(root,"LumaCut CNC",22,15,20);
    status_label=label(root,"OFFLINE / NO MOTION PERMITTED",540,20,16);
    lv_obj_set_style_text_color(status_label,lv_color_hex(0xFFBD74),0);
    label(root,"Maschine",24,79,20);
    x_label=label(root,"X: ---.--- mm",25,125,20);
    y_label=label(root,"Y: ---.--- mm",25,174,20);
    z_label=label(root,"Z: ---.--- mm",25,223,20);
    label(root,"Live-Position wird nach sicherer UART-Integration aktiviert.",25,279,16);
    label(root,"Touch-Steuerung",476,80,20);
    button(root,"X-",470,128,95,58,notify_disabled);
    button(root,"X+",576,128,95,58,notify_disabled);
    button(root,"Y-",470,195,95,58,notify_disabled);
    button(root,"Y+",576,195,95,58,notify_disabled);
    button(root,"Z-",470,262,95,58,notify_disabled);
    button(root,"Z+",576,262,95,58,notify_disabled);
    step_label=label(root,"Schritt: 1.0 mm",477,338,16);
    button(root,"Schritt",655,325,120,47,cycle_step);
    button(root,"Homing",25,326,140,50,notify_disabled);
    button(root,"Autofokus",175,326,140,50,notify_disabled);
    button(root,"Tasterprofil",325,326,140,50,show_profile);
    message_label=label(root,"Laser-Ausgang gesperrt | keine Verbindung zum SKR",25,413,16);
    lv_obj_set_style_text_color(message_label,lv_color_hex(0x76E0C5),0);
    (void)x_label; (void)y_label; (void)z_label; (void)profile_label; (void)tool_label;
}
void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("LumaCut HMI experimental v0.1 - laser and movement disabled");
    init_i2c();
    if(!lcd_begin()||!lvgl_begin()) {
        Serial.println("FATAL: RGB panel / LVGL init failed");
        while(true)delay(1000);
    }
    init_ui();
    write_expander(CH_OUT,0x07);
    // Some revisions gate the backlight through CH422G open-drain bank.
    write_expander(0x23,0xFF);
}
void loop(){
    lv_timer_handler();
    delay(5);
}
