/*
  LumaCut Control OS – professional Waveshare ESP32-S3 gateway and UI.
  Laboratory implementation: compilation is NOT hardware/laser safety approval.
  USB-CDC and Wi-Fi TCP are alternative LightBurn GRBL host ports.
  SKR grblHAL must run the UART-primary bridge firmware, NOT keypad firmware.
  Bluetooth Classic SPP is impossible on ESP32-S3; BLE is separate.
*/
#if defined(HMI_PRO_ENABLED) && HMI_PRO_ENABLED
#include <Arduino.h>
#include <HardwareSerial.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include "update_ca.h"
#ifndef LUMACUT_SOURCE_SHA
#define LUMACUT_SOURCE_SHA "unknown"
#endif
#include <WebServer.h>
#include <ESPmDNS.h>
#include <BLEDevice.h>
#include <Preferences.h>
#include <LittleFS.h>
#include <lvgl.h>
#include <esp_lcd_panel_rgb.h>
#include <esp_lcd_panel_ops.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include "mobile_portal.h"

namespace {
constexpr int W=800,H=480;
constexpr int SDA_PIN=8,SCL_PIN=9;
constexpr uint8_t IO_MODE=0x24,IO_OUT=0x38;
constexpr uint8_t LCD_RESET=(1<<3),TP_RESET=(1<<1),BACKLIGHT=(1<<2);
constexpr uint32_t WIFI_TCP_PORT=23, STATUS_INTERVAL=250;
constexpr size_t MAX_JOB_BYTES=3*1024*1024, MAX_LINE=220;
HardwareSerial machine(1);
WiFiServer tcpServer(WIFI_TCP_PORT);
WiFiClient tcp;
WebServer http(80);
Preferences prefs;
BLECharacteristic* bleStatus=nullptr;
uint32_t lastBleMs=0;
File uploadFile,jobFile;
lv_disp_draw_buf_t draw;
lv_disp_drv_t disp;
lv_indev_drv_t input;
esp_lcd_panel_handle_t lcd=nullptr;
lv_color_t* drawPixels=nullptr;
bool uiReady=false;
uint8_t gtAddr=0x5d;
bool touchOk=false,storageOk=false,machineHomed=false;
bool uploadAllowed=false,uploadFinished=false;
size_t uploadBytes=0;
String uploadTemporary,uploadDestination;
String selectedJob,apName,apPass,apiKey,notice;
String wifiSsid,wifiPass,linkLine,hostLine;
String script[12];int scriptCount=0,scriptIndex=0;
bool commandPending=false,jobRunning=false,jobPaused=false,scriptActive=false;
bool homePending=false,homingInProgress=false,hostBlocked=false;
uint32_t lastStatusMs=0,lastQueryMs=0,localArmUntil=0,lastInputMs=0,wifiHostUntil=0;
enum class Owner { None, Usb, Tcp, Internal, Script };
Owner owner=Owner::None;
enum class MachineState { Unknown, Idle, Run, Hold, Alarm, Home };
MachineState machineState=MachineState::Unknown;
float mx=0,my=0,mz=0;
bool haveMpos=false;
struct Bounds {float x0=0,y0=0,x1=0,y1=0;bool valid=false;};
Bounds bounds;
struct Park {String name;float x=0,y=0;bool stored=false;};
Park parks[3];
lv_obj_t* pages[10]{};
lv_obj_t* navButtons[7]{};
lv_obj_t *areaField=nullptr,*areaDot=nullptr,*areaCaption=nullptr,*configCaption=nullptr;
lv_obj_t *updateLabel=nullptr;
String offeredUpdateSha,updateCheckStatus="Noch nicht geprueft";
uint32_t lastUpdateCheckMs=0;
bool updateCheckRequested=false,updateAvailable=false;
lv_obj_t *sizeXField=nullptr,*sizeYField=nullptr,*sizeZField=nullptr;
lv_obj_t *paramKeyField=nullptr,*paramValueField=nullptr;
lv_obj_t *releaseButton=nullptr,*focusLiftField=nullptr,*focusGapField=nullptr,*tipOffsetField=nullptr,
    *probeTravelField=nullptr,*probeFeedField=nullptr,*probeInfo=nullptr,
    *motorInfo=nullptr,*catalogTitle=nullptr;
lv_obj_t* catalogRows[6]{};
float savedSetting[400]{};
bool knownSetting[400]{};
float focusLiftMm=7.f,focusGapMm=7.f,tipOffsetMm=0.f,
      probeTravelMm=15.f,probeFeedMm=60.f;
bool autoLiftAfterHome=true,postHomePending=false,motorsReleased=false;
bool motorHoldConfigured=false;
bool contactSwitchAtHead=false,postContactLift=false;
bool homeFromHmi=false;
int catalogCategory=0;
lv_disp_t* uiDisplay=nullptr;
bool rotate180=false,settingsRequested=false;
float workX=0,workY=0,workZ=0;
int directionMask=-1,homingDirectionMask=-1;
bool softLimitsEnabled=false,hardLimitsEnabled=false,homingEnabled=false;
bool machineZeroAtMax=true;
bool travelInputsDirty=false;
enum class ConfigWrite {None,Travel,Parameter,MotorHold,Limits};
ConfigWrite configWrite=ConfigWrite::None;
float travelRequested[3]{};
int requestedSettingId=-1;
float requestedSettingValue=0.f;
String lastControllerError, zLiftReason;
uint32_t postHomeStartedMs=0,scriptCommandStartedMs=0;
bool zLiftDirectionVerified=false;
lv_obj_t *statusLabel=nullptr,*positionLabel=nullptr,*messageLabel=nullptr,
*sourceLabel=nullptr,*jobLabel=nullptr,*ipLabel=nullptr,*ssidEntry=nullptr,
*passwordEntry=nullptr,*keyboard=nullptr,*macroLabel=nullptr,*macroEntry=nullptr;
lv_obj_t *editOverlay=nullptr,*editInput=nullptr,*editTarget=nullptr;
int activePage=0,parkSlot=0;
constexpr uint32_t INK=0xF2F7FF,SUBTLE=0xA4B4C7,BG=0x091321,WHITE=0x172638;
constexpr uint32_t BLUE=0x39C7F6,PALE_BLUE=0x153B54,GRAY=0x26384D,RED=0xFF6B75;

bool expander(uint8_t b){Wire.beginTransmission(IO_OUT);Wire.write(b);return Wire.endTransmission()==0;}
bool readReg(uint16_t reg,uint8_t* buf,uint8_t len){
    Wire.beginTransmission(gtAddr);Wire.write(uint8_t(reg>>8));Wire.write(uint8_t(reg));
    if(Wire.endTransmission(false))return false;
    if(Wire.requestFrom(gtAddr,len)!=(int)len)return false;
    for(uint8_t i=0;i<len;i++)buf[i]=Wire.read();
    return true;
}
void touchInit(){
    Wire.begin(SDA_PIN,SCL_PIN,400000);
    Wire.beginTransmission(IO_MODE);Wire.write(0x01);Wire.endTransmission();
    expander(0); // EXIO5=0 selects native USB, not CAN.
    pinMode(4,OUTPUT);digitalWrite(4,LOW);delay(10);
    expander(LCD_RESET);delay(100);expander(LCD_RESET|TP_RESET);delay(180);
    pinMode(4,INPUT);
    uint8_t product[4]{};
    touchOk=readReg(0x8140,product,4);
    if(!touchOk){gtAddr=0x14;touchOk=readReg(0x8140,product,4);}
    // Diagnostic failsafe: assert the Waveshare EXIO2 backlight immediately
    // after I2C/CH422G initialization, BEFORE RGB, LVGL, filesystem and Wi-Fi.
    // Even a later panel or UI initialization failure can no longer leave a
    // completely dark backlight due solely to late startup ordering.
    if(!expander(LCD_RESET|TP_RESET|BACKLIGHT))
        Serial.println("LUMACUT WARNING: CH422G EXIO2 backlight I2C write failed");
}
void touchRead(lv_indev_drv_t*,lv_indev_data_t* result){
    static int16_t x=0,y=0;
    result->state=LV_INDEV_STATE_REL;result->point.x=x;result->point.y=y;
    if(!touchOk)return;
    uint8_t available=0;
    if(!readReg(0x814e,&available,1)||!(available&0x80))return;
    if(available&0x0f){
        uint8_t p[7]{};
        if(readReg(0x814f,p,7)){
            int nx=p[1]|(p[2]<<8),ny=p[3]|(p[4]<<8);
            if(nx>=0&&nx<W&&ny>=0&&ny<H){
                x=rotate180?W-1-nx:nx;
                y=rotate180?H-1-ny:ny;
                result->point.x=x;result->point.y=y;
                result->state=LV_INDEV_STATE_PR;
            }
        }
    }
    Wire.beginTransmission(gtAddr);Wire.write(0x81);Wire.write(0x4e);Wire.write(0);
    Wire.endTransmission();
}
void displayFlush(lv_disp_drv_t* d,const lv_area_t* a,lv_color_t* px){
    esp_lcd_panel_draw_bitmap(lcd,a->x1,a->y1,a->x2+1,a->y2+1,px);
    lv_disp_flush_ready(d);
}
void tick(void*){lv_tick_inc(5);}
bool displayInit(){
    esp_lcd_rgb_panel_config_t cfg={};
    cfg.clk_src=LCD_CLK_SRC_PLL160M;
    cfg.timings.pclk_hz=16000000;cfg.timings.h_res=W;cfg.timings.v_res=H;
    cfg.timings.hsync_pulse_width=4;cfg.timings.hsync_back_porch=8;cfg.timings.hsync_front_porch=8;
    cfg.timings.vsync_pulse_width=4;cfg.timings.vsync_back_porch=8;cfg.timings.vsync_front_porch=8;
    cfg.timings.flags.pclk_active_neg=1;
    cfg.data_width=16;cfg.sram_trans_align=4;cfg.psram_trans_align=64;
    cfg.hsync_gpio_num=46;cfg.vsync_gpio_num=3;cfg.de_gpio_num=5;cfg.pclk_gpio_num=7;
    cfg.disp_gpio_num=GPIO_NUM_NC;cfg.flags.fb_in_psram=true;
    // LCD EDMA competes with Wi-Fi and PSRAM for bandwidth: DRAM bounce
    // buffers reduce scanline starvation (visual line drift). Not a substitute
    // for proper 5V supply or vsync-validated full-frame swapping.
    cfg.bounce_buffer_size_px=W*10;
    const int pins[]={14,38,18,17,10,39,0,45,48,47,21,1,2,42,41,40};
    for(int i=0;i<16;i++)cfg.data_gpio_nums[i]=pins[i];
    if(!psramFound()){
        Serial.println("LUMACUT DISPLAY ERROR: external PSRAM not detected");
        return false;
    }
    esp_err_t lcdError=esp_lcd_new_rgb_panel(&cfg,&lcd);
    if(lcdError!=ESP_OK){
        Serial.printf("LUMACUT DISPLAY ERROR: RGB panel 0x%X\n",(unsigned)lcdError);
        return false;
    }
    lcdError=esp_lcd_panel_reset(lcd);
    if(lcdError==ESP_OK)lcdError=esp_lcd_panel_init(lcd);
    if(lcdError!=ESP_OK){
        Serial.printf("LUMACUT DISPLAY ERROR: RGB init 0x%X\n",(unsigned)lcdError);
        return false;
    }
    lv_init();
    drawPixels=(lv_color_t*)heap_caps_malloc(W*16*sizeof(lv_color_t),MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
    if(!drawPixels){
        Serial.printf("LUMACUT DISPLAY ERROR: DMA draw buffer (%u bytes) allocation failed\n",
                      (unsigned)(W*16*sizeof(lv_color_t)));
        return false;
    }
    lv_disp_draw_buf_init(&draw,drawPixels,nullptr,W*16);
    lv_disp_drv_init(&disp);disp.hor_res=W;disp.ver_res=H;disp.draw_buf=&draw;
    disp.sw_rotate=1;
    disp.flush_cb=displayFlush;uiDisplay=lv_disp_drv_register(&disp);
    rotate180=prefs.getBool("rotate180",false);
    lv_disp_set_rotation(uiDisplay,rotate180?LV_DISP_ROT_180:LV_DISP_ROT_NONE);
    lv_indev_drv_init(&input);input.type=LV_INDEV_TYPE_POINTER;
    input.read_cb=touchRead;lv_indev_drv_register(&input);
    esp_timer_handle_t tm=nullptr;
    esp_timer_create_args_t args={.callback=tick,.arg=nullptr,.dispatch_method=ESP_TIMER_TASK,.name="lc-tick"};
    if(esp_timer_create(&args,&tm)!=ESP_OK)return false;
    return esp_timer_start_periodic(tm,5000)==ESP_OK;
}
const char* stateText(){
    switch(machineState){case MachineState::Idle:return "Bereit";case MachineState::Run:return "Arbeitet";
    case MachineState::Hold:return "Pausiert";case MachineState::Alarm:return "Alarm";
    case MachineState::Home:return "Referenzfahrt";default:return "Keine Statusdaten";}
}
const char* ownerText(){
    switch(owner){case Owner::Usb:return "LightBurn USB";case Owner::Tcp:return "LightBurn Wi-Fi";
    case Owner::Internal:return "Lokaler Auftrag";case Owner::Script:return "Touch/Makro";
    default:return "Steuerung frei";}
}
bool fresh(){return lastStatusMs && (uint32_t)(millis()-lastStatusMs)<3500u;}
bool idle(){return fresh()&&machineState==MachineState::Idle;}
bool armed(){return localArmUntil && int32_t(localArmUntil-millis())>0;}
bool wifiHostAuthorized(){return wifiHostUntil && int32_t(wifiHostUntil-millis())>0;}
bool canCommand(){return owner==Owner::None&&idle();}
bool canConfigure(){return owner==Owner::None&&fresh()&&
    (machineState==MachineState::Idle||machineState==MachineState::Alarm);}
bool canMotion(){return canCommand()&&machineHomed&&haveMpos&&
    !motorsReleased&&softLimitsEnabled&&workX>0&&workY>0&&workZ>0;}
// A Z clearance move has its own locally checked travel envelope.
 // $20 is recommended but its OFF state must not lock out a bounded
 // retreat from a successfully homed endstop.
bool canZMotion(){return canCommand()&&fresh()&&machineHomed&&haveMpos&&
    !motorsReleased&&workZ>0;}
String uiText(String s){
    s.replace("ä","ae");s.replace("ö","oe");s.replace("ü","ue");
    s.replace("Ä","Ae");s.replace("Ö","Oe");s.replace("Ü","Ue");
    s.replace("ß","ss");s.replace("–","-");s.replace("—","-");
    s.replace("…","...");s.replace("·","/");s.replace("×","x");
    return s;
}
// Operator-facing coordinates: grblHAL's default machine volume is
// [-axis travel, 0]. A raw position of -1 mm is already 1 mm away from
// the homing switch. LightBurn, status telemetry and GRBL keep the
// unmodified native MPos values; only the LumaCut operator view changes.
float operatorPos(float machinePos){
    float pos=machineZeroAtMax?-machinePos:machinePos;
    return fabsf(pos)<0.0005f?0.f:pos; // avoid negative zero
}
float machinePosFromOperator(float operatorPosition){
    return machineZeroAtMax?-operatorPosition:operatorPosition;
}
void setNotice(const String& s){notice=s;if(messageLabel)lv_label_set_text(messageLabel,uiText(notice).c_str());}
void labelChanged(lv_obj_t* o,const String& value){
    if(!o)return;
    String display=uiText(value);
    if(strcmp(lv_label_get_text(o),display.c_str())!=0)
        lv_label_set_text(o,display.c_str());
}
void refreshSizeFields(){
    // The numeric editor copies text into a field and then hides the modal.
    // It is no longer focused, so the old refresh used to overwrite pending
    // user edits on the next $ response (even before 'Save' was clicked).
    if(travelInputsDirty)return;
    if(sizeXField&&workX>0&&!lv_obj_has_state(sizeXField,LV_STATE_FOCUSED))
        lv_textarea_set_text(sizeXField,String(workX,1).c_str());
    if(sizeYField&&workY>0&&!lv_obj_has_state(sizeYField,LV_STATE_FOCUSED))
        lv_textarea_set_text(sizeYField,String(workY,1).c_str());
    if(sizeZField&&workZ>0&&!lv_obj_has_state(sizeZField,LV_STATE_FOCUSED))
        lv_textarea_set_text(sizeZField,String(workZ,1).c_str());
}
void updateArea(){
    if(!areaField||!areaDot)return;
    bool valid=fresh()&&machineHomed&&haveMpos&&workX>0.f&&workY>0.f;
    if(!valid){
        lv_obj_add_flag(areaDot,LV_OBJ_FLAG_HIDDEN);
        labelChanged(areaCaption,"Arbeitsfeld unbekannt: GRBL-Werte $130 / $131 lesen");
        return;
    }
    labelChanged(areaCaption,String(workX,1)+" x "+String(workY,1)+
        " mm / Position X "+String(operatorPos(mx),2)+"  Y "+String(operatorPos(my),2));
    // Standard GRBL machine coordinates occupy [-travel, 0] after homing.
    // Origin-at-zero mode is selectable for alternative controller settings.
    float rx=machineZeroAtMax?(mx+workX)/workX:mx/workX;
    float ry=machineZeroAtMax?(my+workY)/workY:my/workY;
    // Do not falsely display clamped outside coordinates as inside the bed.
    if(rx < -0.001f||rx > 1.001f||ry < -0.001f||ry > 1.001f){
        lv_obj_add_flag(areaDot,LV_OBJ_FLAG_HIDDEN);
        labelChanged(areaCaption,"Position ausserhalb des eingestellten Arbeitsfeldes");
        return;
    }
    rx=constrain(rx,0.f,1.f);ry=constrain(ry,0.f,1.f);
    int usable=188;
    int px=6+int(rx*usable);
    int py=6+int((1.f-ry)*usable);
    if(lv_obj_get_x(areaDot)!=px||lv_obj_get_y(areaDot)!=py)
        lv_obj_set_pos(areaDot,px,py);
    lv_obj_clear_flag(areaDot,LV_OBJ_FLAG_HIDDEN);
}
// LVGL updates need the parameter catalog declared before its definition.
void refreshCatalog();
// Version DISCOVERY only. Firmware installation is intentionally disabled
// until HMI OTA rollback and SKR BOOT0/NRST flashing have been hardware tested.
// HTTPS is validated against a public CA in update_ca.h: never setInsecure().
String extractReleaseSha(const String& json){
    int key=json.indexOf("\"source_sha\"");
    if(key<0||json.length()>4096)return "";
    int colon=json.indexOf(':',key+12);
    if(colon<0)return "";
    int first=json.indexOf('"',colon+1);
    if(first<0)return "";
    int last=json.indexOf('"',first+1);
    if(last<0)return "";
    String sha=json.substring(first+1,last);
    if(sha.length()!=40)return "";
    for(unsigned i=0;i<sha.length();i++){
        char c=sha[i];
        if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return "";
    }
    return sha;
}
void checkLumaCutUpdates(){
    if(WiFi.status()!=WL_CONNECTED){
        updateCheckStatus="Updatecheck: WLAN nicht verbunden";return;
    }
    // TLS certificate validity cannot be assessed until SNTP synchronizes.
    if(time(nullptr)<1700000000){
        updateCheckStatus="Updatecheck: Uhr noch nicht synchron";return;
    }
    WiFiClientSecure tls;
    tls.setCACert(LUMACUT_UPDATE_CA);
    tls.setTimeout(4);
    HTTPClient request;
    request.setConnectTimeout(4000);
    request.setTimeout(5000);
    if(!request.begin(tls,"https://luma.millione.de/api/updates/latest")){
        updateCheckStatus="Updatecheck: HTTPS-Verbindung fehlgeschlagen";return;
    }
    int code=request.GET();
    if(code==200){
        String body=request.getString();
        if(body.indexOf("\"available\":true")>=0){
            String sha=extractReleaseSha(body);
            if(sha.length()==40){
                offeredUpdateSha=sha;
                updateAvailable=(sha!=String(LUMACUT_SOURCE_SHA));
                updateCheckStatus=updateAvailable?
                    ("NEUES UPDATE: "+sha.substring(0,12)):
                    ("HMI-Stand aktuell: "+sha.substring(0,12));
                if(updateAvailable)
                    setNotice("LumaCut Update verfuegbar. Unter WLAN/System anzeigen.");
            }else updateCheckStatus="Updatecheck: Manifest ungueltig";
        }else if(body.indexOf("\"available\":false")>=0){
            updateAvailable=false;
            updateCheckStatus="Noch keine freigegebene Stable-Version";
        }else updateCheckStatus="Updatecheck: Unerwartetes Manifest";
    }else{
        // A TLS mismatch is a failure, not permission to use plaintext HTTP.
        updateCheckStatus="Updatecheck: Server/TLS Fehler "+String(code);
    }
    request.end();
}
void updateCheckService(){
    const uint32_t now=millis();
    bool periodic=(now>180000u)&&(lastUpdateCheckMs==0||
              (uint32_t)(now-lastUpdateCheckMs)>21600000u);
    if(!updateCheckRequested&&!periodic)return;
    // No networking that can stall the machine command dispatcher mid-job.
    if(owner!=Owner::None||jobRunning||scriptActive||homingInProgress||
       (fresh()&&machineState!=MachineState::Idle))return;
    lastUpdateCheckMs=now;
    updateCheckRequested=false;
    checkLumaCutUpdates();
}

void updateUi(){
    labelChanged(statusLabel,fresh()?stateText():"Keine Verbindung");
    labelChanged(positionLabel,(fresh()&&haveMpos)?
        "X "+String(operatorPos(mx),2)+"    Y "+String(operatorPos(my),2)+
        "    Z "+String(operatorPos(mz),2):
        "X --.--     Y --.--     Z --.--");
    labelChanged(sourceLabel,activePage==5?
        ("Motor $3="+(directionMask<0?String("?"):String(directionMask))+
         "  Homing $23="+(homingDirectionMask<0?String("?"):String(homingDirectionMask)))
        :String(ownerText()));
    String job=selectedJob.length()?"Datei: "+selectedJob:"Noch keine Datei ausgewaehlt";
    if(bounds.valid)job+="  /  "+String(bounds.x1-bounds.x0,1)+
                                " x "+String(bounds.y1-bounds.y0,1)+" mm";
    labelChanged(jobLabel,job);
    labelChanged(macroLabel,parks[parkSlot].stored?parks[parkSlot].name:String("Freier Makroplatz"));
    if(ipLabel){
        String net="WLAN: "+(WiFi.status()==WL_CONNECTED?WiFi.localIP().toString():String("nicht verbunden"))+
        "\nHotspot: "+apName+" / "+apPass+
        "\nApp: http://"+WiFi.softAPIP().toString()+
        "\nZugangscode: "+apiKey+
        "\nGRBL $1:"+(knownSetting[1]?String(savedSetting[1],0):"?")+
        " $20:"+(knownSetting[20]?String(savedSetting[20],0):"?")+
        " $132:"+(knownSetting[132]?String(savedSetting[132],1):"?");
        labelChanged(ipLabel,net);
    }
    if(releaseButton)labelChanged(lv_obj_get_child(releaseButton,0),
        motorsReleased?"Aufwecken":"Handbewegung");
    if(updateLabel)labelChanged(updateLabel,updateCheckStatus);
    if(motorInfo){
        labelChanged(motorInfo,motorsReleased?
            "Schlafmodus: Achsen duerfen bewegt werden.":
            (!motorHoldConfigured?"Haltemoment aus: $1=255 aktivieren.":
             (machineHomed?"Haltemoment EIN, Referenz gespeichert.":"Homing erforderlich")));
    }
    if(probeInfo){
        labelChanged(probeInfo,"Z-Endschalter PC2 / separate Probe nicht angeschlossen");
    }
    refreshCatalog();
    if(configCaption){
        labelChanged(configCaption,"Motor $3: "+(directionMask<0?String("?"):String(directionMask))+
            "  /  Homing $23: "+(homingDirectionMask<0?String("?"):String(homingDirectionMask))+
            "  /  X "+String(workX,0)+" Y "+String(workY,0)+" Z "+String(workZ,0));
    }
    updateArea();
}

bool claim(Owner value){
    if(owner==value)return true;
    if(owner!=Owner::None)return false;
    owner=value;lastInputMs=millis();return true;
}
void releaseLocal(){
    if((owner==Owner::Script||owner==Owner::Internal)&&!jobRunning&&!scriptActive&&!commandPending&&idle())owner=Owner::None;
}
void writeCmd(const String& text){machine.print(text);machine.write('\n');}
void feedHold(){machine.write('!');}
void abortHost(){
    postHomePending=false;homeFromHmi=false;
    if(owner!=Owner::Tcp&&owner!=Owner::Usb)return;
    machine.write((uint8_t)0x18);
    machineHomed=false;haveMpos=false;hostBlocked=true;
    setNotice("Externer Job abgebrochen. LightBurn stoppen; Quellenwechsel erst bei Idle.");
}
void abortJob(){
    postHomePending=false;postContactLift=false;homeFromHmi=false;
    // Soft reset also clears host parser state; machine must be re-homed.
    machine.write((uint8_t)0x18);
    if(jobFile)jobFile.close();
    jobRunning=false;jobPaused=false;scriptActive=false;commandPending=false;
    configWrite=ConfigWrite::None;
    scriptCount=scriptIndex=0;owner=Owner::None;machineHomed=false;haveMpos=false;
    setNotice("Abbruch gesendet. Referenzfahrt erneut erforderlich.");
}
void nextScript(){
    if(scriptIndex>=scriptCount){
        scriptActive=false;commandPending=false;releaseLocal();return;
    }
    String cmd=script[scriptIndex++];
    if(cmd=="$H"||cmd=="$HZ"){
        homingInProgress=true;homeFromHmi=true;machineHomed=false;
        postContactLift=(cmd=="$HZ");
        haveMpos=false;postHomePending=false;
    }
    writeCmd(cmd);commandPending=true;scriptCommandStartedMs=millis();
}
bool startScript(const String* commands,int count,bool motion=false,bool zOnly=false){
    if(!canConfigure()||(motion&&!(zOnly?canZMotion():canMotion()))||
       count<1||count>12)return false;
    if(!claim(Owner::Script))return false;
    for(int i=0;i<count;i++)script[i]=commands[i];
    scriptCount=count;scriptIndex=0;scriptActive=true;
    nextScript();return true;
}
void finishConfigWrite(bool success,const String& error){
    ConfigWrite kind=configWrite;
    configWrite=ConfigWrite::None;
    if(kind==ConfigWrite::None)return;
    if(!success){
        lastControllerError=error;
        setNotice("SKR hat Einstellung ABGELEHNT: "+error);
        return;
    }
    if(kind==ConfigWrite::Travel){
        bool verified=true;
        for(int i=0;i<3;i++){
            int key=130+i;
            if(!knownSetting[key]||
               fabsf(savedSetting[key]-travelRequested[i])>0.01f)
                verified=false;
        }
        if(verified){
            travelInputsDirty=false;
            refreshSizeFields();
            setNotice("SKR bestaetigt alle drei Verfahrwege $130/$131/$132.");
        }else setNotice("SKR Verfahrwege nicht bestaetigt. $ lesen und Werte vergleichen.");
    }else if(kind==ConfigWrite::MotorHold){
        motorHoldConfigured=knownSetting[1]&&fabsf(savedSetting[1]-255.f)<0.01f;
        setNotice(motorHoldConfigured?
            "SKR bestaetigt $1=255. Falls Treiber aus waren: neu homen.":
            "Motor-Haltewert nicht bestaetigt. $ und TMC2209 pruefen.");
    }else if(kind==ConfigWrite::Limits){
        setNotice(softLimitsEnabled&&hardLimitsEnabled&&homingEnabled?
            "SKR bestaetigt Homing/Soft/Hard Limits.":
            "SKR Limits nicht alle bestaetigt. $20/$21/$22 pruefen.");
    }else if(kind==ConfigWrite::Parameter){
        bool matching=requestedSettingId>=0&&requestedSettingId<400&&
            knownSetting[requestedSettingId]&&
            fabsf(savedSetting[requestedSettingId]-requestedSettingValue)<0.01f;
        setNotice(matching?
            ("SKR bestaetigt $"+String(requestedSettingId)+"="+
             String(savedSetting[requestedSettingId],3)):
            ("SKR Parameter $"+String(requestedSettingId)+
             " nicht bestaetigt. $ lesen."));
    }
}

void parseMachineLine(const String& line){
    if(line.length()>2 && line[0]==char(36) && isDigit(line[1])){
        int equal=line.indexOf('=');
        if(equal>1){
            String key=line.substring(1,equal);
            bool digits=true;
            for(unsigned i=0;i<key.length();i++)if(!isDigit(key[i]))digits=false;
            if(digits){
                int id=key.toInt();
                float number=line.substring(equal+1).toFloat();
                if(id>=0&&id<400&&isfinite(number)){
                    savedSetting[id]=number;knownSetting[id]=true;
                }
                if(id==1)motorHoldConfigured=(number>=255);
                if(id==3&&number>=0&&number<=7)directionMask=int(number);
                if(id==23&&number>=0&&number<=7)homingDirectionMask=int(number);
                if(id==20)softLimitsEnabled=(number>=1);
                if(id==21)hardLimitsEnabled=(number>=1);
                if(id==22)homingEnabled=(number>=1);
                bool changed=false;
                if(id==130&&number>0){workX=number;changed=true;}
                if(id==131&&number>0){workY=number;changed=true;}
                if(id==132&&number>0){workZ=number;changed=true;}
                if(changed)refreshSizeFields();
            }
        }
    }
    if(line.startsWith("<")){
        int end=line.indexOf('|');if(end<0)end=line.indexOf('>');
        String state=line.substring(1,end);
        if(state=="Idle")machineState=MachineState::Idle;
        else if(state=="Run"||state=="Jog")machineState=MachineState::Run;
        else if(state=="Hold")machineState=MachineState::Hold;
        else if(state=="Home")machineState=MachineState::Home;
        else if(state=="Alarm"||state=="Door")machineState=MachineState::Alarm;
        else machineState=MachineState::Unknown;
        int m=line.indexOf("MPos:");
        if(m>=0){
            float x,y,z;
            if(sscanf(line.c_str()+m,"MPos:%f,%f,%f",&x,&y,&z)==3){
                mx=x;my=y;mz=z;haveMpos=true;
            }
        }
        lastStatusMs=millis();
    } else if(line=="ok" || line.startsWith("error:")){
        bool ok=line=="ok";
        if(homingInProgress){
            if(ok){
                machineHomed=true;
                postHomePending=(homeFromHmi&&autoLiftAfterHome);
                postHomeStartedMs=millis();
                settingsRequested=false; // force fresh $ after completed homing
                setNotice(postHomePending?
                    "Homing OK; pruefe Z-Lift und Controllergrenzen.":
                    "Homing OK; automatischer Z-Rueckzug ausgeschaltet.");
            }
            else{machineHomed=false;setNotice(line=="error:5"?"Homing im SKR deaktiviert. Unter System $22=1 aktivieren.":"Referenzfahrt fehlgeschlagen: "+line);}
            homingInProgress=false;homeFromHmi=false;
        }
        if((owner==Owner::Script)&&commandPending){
            commandPending=false;
            if(ok){
                nextScript();
                if(!scriptActive)finishConfigWrite(true,"");
            }else{
                scriptActive=false;scriptCount=0;owner=Owner::None;
                ConfigWrite failedWrite=configWrite;
                finishConfigWrite(false,line);
                if(failedWrite==ConfigWrite::None)
                    setNotice("SKR Befehl fehlgeschlagen: "+line);
            }
        } else if(owner==Owner::Internal&&commandPending){
            commandPending=false;
            if(!ok){jobRunning=false;if(jobFile)jobFile.close();feedHold();setNotice("G-Code-Fehler: "+line+". Maschine angehalten.");}
        }
    } else if(line.startsWith("[LIM:")||line.startsWith("[HOMING:")){
        setNotice("Schalterzustand: "+line);
    } else if(line.startsWith("ALARM:")){
        machineState=MachineState::Alarm;machineHomed=false;
        postHomePending=false;homeFromHmi=false;
        lastControllerError=line;
        setNotice(line);
    }
}
void machineService(){
    unsigned count=0;
    while(machine.available()&&count++<768){
        char c=char(machine.read());
        if(owner==Owner::Usb)Serial.write((uint8_t)c);
        else if(owner==Owner::Tcp&&tcp&&tcp.connected())tcp.write((uint8_t)c);
        if(c=='\n'||c=='\r'){
            if(linkLine.length())parseMachineLine(linkLine);
            linkLine="";
        } else if(linkLine.length()<240){linkLine+=c;}
        else linkLine="";
    }
    if((uint32_t)(millis()-lastQueryMs)>=STATUS_INTERVAL){
        lastQueryMs=millis();machine.write('?');
    }
}
void externalForward(Owner value,Stream& src){
    // One controller owner at a time. No interleaved competing G-code.
    unsigned n=0;
    while(src.available()&&n++<512){
        int c=src.read();if(c<0)break;
        if(!claim(value)){
            // Never silently discard host commands when another owner is active.
            if(c=='\n'||c=='\r'){
                if(value==Owner::Usb)Serial.print("error:9\r\n");
                else if(value==Owner::Tcp&&tcp&&tcp.connected())tcp.print("error:9\r\n");
            }
            continue;
        }
        lastInputMs=millis();
        if(hostBlocked){
            if(c=='?')machine.write('?'); // only read-only status after abort
            continue;
        }
        if(c=='\n'||c=='\r'){
            if(hostLine=="$H"||hostLine=="$HZ"){
                homingInProgress=true;homeFromHmi=false;
            }
            if(hostLine.startsWith("$")&&hostLine.indexOf('=')>1){
                // LightBurn may modify $20 or travels without going through
                // our machine setup. Re-query the real controller settings
                // before enabling any later local motion.
                softLimitsEnabled=false;
                settingsRequested=false;
                if(hostLine.startsWith("$3=")||hostLine.startsWith("$23=")||
                   hostLine.startsWith("$130=")||hostLine.startsWith("$131=")||
                   hostLine.startsWith("$132=")||hostLine.startsWith("$22=")||
                   hostLine.startsWith("$1="))
                    machineHomed=false;
            }
            hostLine="";
        }else if(c>=32&&hostLine.length()<96)hostLine+=char(c);
        machine.write((uint8_t)c);
        if(c==0x18)machineHomed=false;
    }
}
void bridgeService(){
    // Losing live GRBL telemetry must suspend local G-code streaming.
    // This is a software request only; the external laser interlock is mandatory.
    static bool lostStatusReported=false;
    if(lastStatusMs && (uint32_t)(millis()-lastStatusMs)>3500u){
        if(!lostStatusReported && (owner==Owner::Internal||owner==Owner::Script||
                                  owner==Owner::Tcp||owner==Owner::Usb)){
            feedHold();
            if(jobFile)jobFile.close();
            jobRunning=false;jobPaused=true;
            scriptActive=false;commandPending=false;scriptCount=scriptIndex=0;
            machineHomed=false;haveMpos=false;
            if(owner==Owner::Usb||owner==Owner::Tcp)hostBlocked=true;
            setNotice("SKR-Status verloren. Feed Hold gesendet; Laser hardwareseitig sichern.");
            lostStatusReported=true;
        }
    } else if(fresh())lostStatusReported=false;
    if(tcpServer.hasClient()){
        WiFiClient incoming=tcpServer.available();
        if((tcp&&tcp.connected())||!wifiHostAuthorized()||owner!=Owner::None){
            incoming.print("error: WLAN-Host nicht lokal freigegeben oder Maschine belegt\r\n");
            incoming.stop();
        } else tcp=incoming;
    }
    if(owner==Owner::Tcp&&(!tcp||!tcp.connected())){
        if(machineState==MachineState::Run)feedHold();
        owner=Owner::None;hostBlocked=false;
        setNotice("TCP-Verbindung verloren; Hold bei RUN angefordert.");
    }
    if(tcp&&tcp.connected())externalForward(Owner::Tcp,tcp);
    if(Serial.available())externalForward(Owner::Usb,Serial);
    if(owner==Owner::Usb&&idle()&&(uint32_t)(millis()-lastInputMs)>120000u){
        owner=Owner::None;hostLine="";hostBlocked=false;
    }
    machineService();
    releaseLocal();
}
bool nextJobLine(String& line){
    line="";
    while(jobFile.available()){
        char c=char(jobFile.read());
        if(c=='\r')continue;
        if(c=='\n')break;
        if(line.length()>=MAX_LINE)return false;
        line+=c;
    }
    line.trim();return true;
}
void internalJobService(){
    if(owner!=Owner::Internal||!jobRunning||jobPaused||commandPending||!fresh())return;
    if(!jobFile.available()){
        jobFile.close();jobRunning=false;
        setNotice("Alle G-Code-Zeilen quittiert. Maschine fährt bis Stillstand weiter.");
        return;
    }
    String line;
    if(!nextJobLine(line)){abortJob();setNotice("Jobzeile zu lang, kontrollierter Reset.");return;}
    if(line.length()==0||line.startsWith(";"))return;
    writeCmd(line);commandPending=true;
}
bool jobStart(){
    if(!canMotion()||!selectedJob.length()||!storageOk)return false;
    jobFile=LittleFS.open("/jobs/"+selectedJob,FILE_READ);
    if(!jobFile)return false;
    owner=Owner::Internal;jobRunning=true;jobPaused=false;commandPending=false;
    setNotice("Job aktiv – keine zweite Steuerquelle erlaubt.");return true;
}
void loadParks(){
    for(int i=0;i<3;i++){
        String prefix="p"+String(i);
        parks[i].stored=prefs.getBool((prefix+"v").c_str(),false);
        parks[i].name=prefs.getString((prefix+"n").c_str(),("Position "+String(i+1)).c_str());
        parks[i].x=prefs.getFloat((prefix+"x").c_str(),0);
        parks[i].y=prefs.getFloat((prefix+"y").c_str(),0);
    }
}
void savePark(){
    if(!canMotion()){setNotice("Erst Referenzfahrt und Soft Limits einrichten.");return;}
    int i=parkSlot;String prefix="p"+String(i);
    parks[i].x=mx;parks[i].y=my;parks[i].stored=true;
    prefs.putBool((prefix+"v").c_str(),true);
    prefs.putFloat((prefix+"x").c_str(),mx);
    prefs.putFloat((prefix+"y").c_str(),my);
    prefs.putString((prefix+"n").c_str(),parks[i].name);
    setNotice("Makro gespeichert: "+parks[i].name+" (Maschinenkoordinaten X/Y).");
}
bool runPark(){
    if(!parks[parkSlot].stored)return false;
    // Intentionally no automatic Z move: safe clearance cannot be inferred.
    String cmds[]={"M5","G21 G90",
        "G53 G0 X"+String(parks[parkSlot].x,3)+" Y"+String(parks[parkSlot].y,3)};
    return startScript(cmds,3,true);
}
bool parseBounds(){
    // Deliberately conservative: unsafe/ambiguous G-code has NO framing preview.
    // We do not try to guess absolute coordinates or resolve arc extrema.
    bounds=Bounds{};
    if(!storageOk||!selectedJob.length())return false;
    File f=LittleFS.open("/jobs/"+selectedJob,FILE_READ);
    if(!f)return false;
    bool modeAbsolute=false,modeMetric=false,firstPoint=false,good=true;
    int motion=-1;
    float x=0.f,y=0.f;
    while(f.available()&&good){
        String ln=f.readStringUntil('\n');ln.trim();ln.toUpperCase();
        if(ln.length()>MAX_LINE){good=false;break;}
        int semicolon=ln.indexOf(';');
        if(semicolon>=0)ln.remove(semicolon);
        // Strip ordinary balanced parenthesized comments, refuse unmatched ones.
        while(true){
            int a=ln.indexOf('(');if(a<0)break;
            int b=ln.indexOf(')',a+1);
            if(b<0){good=false;break;}
            ln.remove(a,b-a+1);
        }
        if(!good||ln.indexOf(')')>=0){good=false;break;}
        bool hasX=false,hasY=false;
        float nextX=x,nextY=y;
        const char* text=ln.c_str();
        size_t i=0,n=ln.length();
        while(i<n&&good){
            if(text[i]==' '||text[i]=='\t'){i++;continue;}
            char letter=text[i++];
            if(letter<'A'||letter>'Z'){good=false;break;}
            char* end=nullptr;
            float value=strtof(text+i,&end);
            if(end==text+i||!isfinite(value)){good=false;break;}
            i=size_t(end-text);
            if(letter=='G'){
                int code=int(value);
                if(float(code)!=value){good=false;break;}
                if(code==90)modeAbsolute=true;
                else if(code==21)modeMetric=true;
                else if(code==0||code==1)motion=code;
                else if(code!=17&&code!=40&&code!=49&&code!=54&&
                        code!=80&&code!=94){good=false;break;}
            } else if(letter=='X'){nextX=value;hasX=true;}
            else if(letter=='Y'){nextY=value;hasY=true;}
            else if(letter=='M'){
                int code=int(value);
                if(float(code)!=value||
                   (code!=2&&code!=3&&code!=4&&code!=5&&
                    code!=7&&code!=8&&code!=9&&code!=30)){good=false;break;}
            } else if(letter!='N'&&letter!='F'&&letter!='S'&&letter!='Z'){
                good=false;break;
            }
        }
        if(!good)break;
        if(hasX||hasY){
            if(!modeAbsolute||!modeMetric||motion<0){good=false;break;}
            // First position must be completely specified, not inferred from origin.
            if(!firstPoint&&!(hasX&&hasY)){good=false;break;}
            x=nextX;y=nextY;
            if(!firstPoint){
                bounds.x0=bounds.x1=x;bounds.y0=bounds.y1=y;firstPoint=true;
            } else {
                bounds.x0=min(bounds.x0,x);bounds.x1=max(bounds.x1,x);
                bounds.y0=min(bounds.y0,y);bounds.y1=max(bounds.y1,y);
            }
        }
    }
    f.close();
    bounds.valid=good&&firstPoint;
    return bounds.valid;
}

bool dryFrame(){
    if(!bounds.valid)return false;
    String cmds[]={"M5","G21 G90",
        "G0 X"+String(bounds.x0,3)+" Y"+String(bounds.y0,3),
        "G0 X"+String(bounds.x1,3)+" Y"+String(bounds.y0,3),
        "G0 X"+String(bounds.x1,3)+" Y"+String(bounds.y1,3),
        "G0 X"+String(bounds.x0,3)+" Y"+String(bounds.y1,3),
        "G0 X"+String(bounds.x0,3)+" Y"+String(bounds.y0,3),
        "M5"};
    return startScript(cmds,8,true);
}
bool selectJob(String name){
    if(owner==Owner::Internal||owner==Owner::Script)return false;
    if(name.indexOf('/')>=0||name.indexOf('\\')>=0||name.indexOf("..")>=0)return false;
    if(!storageOk||!LittleFS.exists("/jobs/"+name))return false;
    selectedJob=name;parseBounds();updateUi();return true;
}
bool auth(){return apiKey.length()&&http.hasHeader("X-LumaCut-Key")&&
        http.header("X-LumaCut-Key")==apiKey;}
void fail(int code,String text){http.send(code,"text/plain; charset=utf-8",text);}
String jsonMachine(){
    String out="{\"machine\":\"LumaCut CNC\",";
    out+="\"axes\":3,\"units\":\"mm\",\"homed\":";
    out+=(machineHomed?"true":"false");
    out+=",\"soft_limits_enabled\":";
    out+=(softLimitsEnabled?"true":"false");
    out+=",\"hard_limits_enabled\":";
    out+=(hardLimitsEnabled?"true":"false");
    out+=",\"homing_enabled\":";
    out+=(homingEnabled?"true":"false");
    out+=",\"direction_mask\":"+String(directionMask);
    out+=",\"homing_direction_mask\":"+String(homingDirectionMask);
    out+=",\"work_area\":{";
    out+="\"x_mm\":"+String(workX,3)+",\"y_mm\":"+String(workY,3)+
         ",\"z_mm\":"+String(workZ,3)+"}";
    out+=",\"coordinates\":{\"zero_at_max\":";
    out+=(machineZeroAtMax?"true":"false");
    out+=",\"x_mm\":"+String(mx,3)+",\"y_mm\":"+String(my,3)+
         ",\"z_mm\":"+String(mz,3)+
         ",\"display_x_mm\":"+String(operatorPos(mx),3)+
         ",\"display_y_mm\":"+String(operatorPos(my),3)+
         ",\"display_z_mm\":"+String(operatorPos(mz),3)+
         ",\"display_system\":\"positive_distance_from_reference\",\"valid\":";
    out+=((fresh()&&machineHomed&&haveMpos)?"true":"false");
    out+="},\"focus\":{\"target_gap_mm\":"+String(focusGapMm,3)+
         ",\"homing_retract_mm\":"+String(focusLiftMm,3)+
         ",\"switch_trigger_clearance_mm\":"+String(tipOffsetMm,3)+
         ",\"auto_retract\":"+String(autoLiftAfterHome?"true":"false")+
         ",\"head_contact_mode\":"+String(contactSwitchAtHead?"true":"false")+
         ",\"g38_supported\":false,\"z_single_axis_home_supported\":true},\"steppers\":{\"holding\":"+
         String(!motorsReleased?"true":"false")+"}}";
    return out;
}
String jsonStatus(){
    String out="{\"state\":\""+String(fresh()?stateText():"Offline")+
      "\",\"owner\":\""+String(ownerText())+
      "\",\"position\":\""+(haveMpos?("X "+String(operatorPos(mx),2)+
      " / Y "+String(operatorPos(my),2)+" / Z "+String(operatorPos(mz),2)):"Unbekannt")+
      "\",\"job\":\""+selectedJob+
      "\",\"message\":\""+String(machineHomed?"Referenziert":"Referenzfahrt erforderlich")+
      "\",\"bounds\":"+String(bounds.valid?
        ("{\"x0\":"+String(bounds.x0,3)+",\"y0\":"+String(bounds.y0,3)+
         ",\"x1\":"+String(bounds.x1,3)+",\"y1\":"+String(bounds.y1,3)+"}"):"null")+
      ",\"machine\":"+jsonMachine()+"}";
    return out;
}
void installRoutes(){
    const char* headers[]={"X-LumaCut-Key"};
    http.collectHeaders(headers,1);
    http.on("/",HTTP_GET,[]{http.send_P(200,"text/html; charset=utf-8",MOBILE_PORTAL);});
    http.on("/api/status",HTTP_GET,[]{if(!auth()){fail(401,"Code erforderlich");return;}http.send(200,"application/json",jsonStatus());});
    http.on("/api/update/status",HTTP_GET,[]{
        if(!auth()){fail(401,"Code erforderlich");return;}
        String payload="{\"local_sha\":\""+String(LUMACUT_SOURCE_SHA)+
            "\",\"offered_sha\":\""+offeredUpdateSha+
            "\",\"available\":"+(updateAvailable?String("true"):String("false"))+
            ",\"hmi_ota_ready\":false,\"skr_ota_ready\":false}";
        http.send(200,"application/json",payload);
    });
    http.on("/api/machine",HTTP_GET,[]{
        if(!auth()){fail(401,"Code erforderlich");return;}
        http.send(200,"application/json",jsonMachine());
    });
    http.on("/api/jobs",HTTP_GET,[]{
        if(!auth()){fail(401,"Code erforderlich");return;}
        String out="{\"files\":[";bool first=true;
        if(storageOk){
            File root=LittleFS.open("/jobs");
            File f=root.openNextFile();
            while(f){if(!f.isDirectory()){
                String name=String(f.name());int pos=name.lastIndexOf('/');
                if(pos>=0)name=name.substring(pos+1);
                if(!name.endsWith(".part")){
                    if(!first)out+=',';first=false;
                    out+="{\"name\":\""+name+"\",\"bytes\":"+String(f.size())+"}";
                }
            }f=root.openNextFile();}
        }out+="]}";http.send(200,"application/json",out);
    });
    http.on("/api/select",HTTP_POST,[]{
        if(!auth()){fail(401,"Code erforderlich");return;}
        if(!selectJob(http.arg("name"))){fail(400,"Datei nicht vorhanden oder Maschine beschäftigt");return;}
        http.send(200,"application/json","{\"ok\":true}");
    });
    http.on("/api/action",HTTP_POST,[]{
        if(!auth()){fail(401,"Code erforderlich");return;}
        String op=http.arg("op");bool ok=false;
        if(op=="pause"&&owner==Owner::Internal&&jobRunning){feedHold();jobPaused=true;ok=true;}
        else if(op=="resume"&&owner==Owner::Internal&&jobPaused){machine.write('~');jobPaused=false;ok=true;}
        else if(op=="abort"&&owner==Owner::Internal){abortJob();ok=true;}
        else if(op=="abort"&&(owner==Owner::Tcp||owner==Owner::Usb)){abortHost();ok=true;}
        else if(op=="frame")ok=dryFrame();
        else if(op=="start")ok=jobStart();
        else if(op=="park")ok=runPark();
        if(!ok){fail(409,"Maschine nicht bereit / HMI-Freigabe erforderlich / Aktion gesperrt");return;}
        http.send(200,"application/json","{\"ok\":true}");
    });
    http.on("/api/upload",HTTP_POST,[]{
        if(!auth()||!uploadFinished){fail(403,"Upload fehlgeschlagen oder Datei existiert bereits");return;}
        uploadFinished=false;uploadAllowed=false;
        http.send(200,"application/json","{\"ok\":true}");
    },[]{
        HTTPUpload &up=http.upload();
        if(up.status==UPLOAD_FILE_START){
            uploadAllowed=auth()&&storageOk&&owner==Owner::None&&
                (!fresh()||machineState==MachineState::Idle);
            uploadFinished=false;uploadBytes=0;
            uploadTemporary="";uploadDestination="";
            String name=up.filename;name.replace(" ","_");
            for(size_t k=0;k<name.length();k++){
                char ch=name.charAt(k);
                if(!((ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z')||
                     (ch>='0'&&ch<='9')||ch=='_'||ch=='-'||ch=='.'))uploadAllowed=false;
            }
            if(name.length()>72||name.indexOf("..")>=0||name.indexOf('/')>=0||name.indexOf('\\')>=0 ||
               !(name.endsWith(".gcode")||name.endsWith(".nc")||name.endsWith(".tap")||name.endsWith(".txt")))
                uploadAllowed=false;
            uploadDestination="/jobs/"+name;
            uploadTemporary="/jobs/."+name+".part";
            if(uploadAllowed&&LittleFS.exists(uploadDestination))uploadAllowed=false;
            if(uploadAllowed){
                LittleFS.remove(uploadTemporary);
                uploadFile=LittleFS.open(uploadTemporary,FILE_WRITE);
                if(!uploadFile)uploadAllowed=false;
            }
        } else if(up.status==UPLOAD_FILE_WRITE && uploadAllowed){
            uploadBytes+=up.currentSize;
            if(uploadBytes>MAX_JOB_BYTES||uploadFile.write(up.buf,up.currentSize)!=up.currentSize){
                uploadAllowed=false;uploadFile.close();
                if(uploadTemporary.length())LittleFS.remove(uploadTemporary);
            }
        } else if(up.status==UPLOAD_FILE_END){
            if(uploadFile)uploadFile.close();
            if(uploadAllowed&&uploadBytes>0&&uploadTemporary.length()&&uploadDestination.length()&&
               !LittleFS.exists(uploadDestination)){
                uploadFinished=LittleFS.rename(uploadTemporary,uploadDestination);
            }
            if(!uploadFinished&&uploadTemporary.length())LittleFS.remove(uploadTemporary);
            uploadAllowed=uploadFinished;
        } else if(up.status==UPLOAD_FILE_ABORTED){
            if(uploadFile)uploadFile.close();
            if(uploadTemporary.length())LittleFS.remove(uploadTemporary);
            uploadAllowed=false;uploadFinished=false;
        }
    });
    http.begin();
}
String randomToken(uint32_t value){
    char b[16];snprintf(b,sizeof(b),"%08lx",(unsigned long)value);
    return String(b);
}
void bleInit(){
    BLEDevice::init("LumaCut Control");
    BLEServer* s=BLEDevice::createServer();
    BLEService* service=s->createService("a50d8324-5e0d-42db-92f8-c3f3b5b93051");
    bleStatus=service->createCharacteristic("a50d8324-5e0d-42db-92f8-c3f3b5b93052",BLECharacteristic::PROPERTY_READ);
    bleStatus->setValue("BOOT");
    service->start();
    BLEAdvertising* advertising=BLEDevice::getAdvertising();
    advertising->addServiceUUID("a50d8324-5e0d-42db-92f8-c3f3b5b93051");
    advertising->start();
}
void bleUpdate(){
    if(!bleStatus||(uint32_t)(millis()-lastBleMs)<1300u)return;
    lastBleMs=millis();
    String state=String(stateText())+" X"+String(mx,2)+" Y"+String(my,2)+" Z"+String(mz,2);
    bleStatus->setValue((uint8_t*)state.c_str(),state.length());
}
void networkInit(){
    configTime(0,0,"pool.ntp.org","time.cloudflare.com");
    wifiSsid=prefs.getString("ssid","");
    wifiPass=prefs.getString("wpw","");
    apName="LumaCut-"+String((uint32_t)(ESP.getEfuseMac()&0xffff),HEX);
    apPass=prefs.getString("ap","");
    apiKey=prefs.getString("key","");
    if(apPass.length()<8){apPass="LC"+randomToken(esp_random());prefs.putString("ap",apPass);}
    if(apiKey.length()<8){apiKey=randomToken(esp_random())+randomToken(esp_random());prefs.putString("key",apiKey);}
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP(apName.c_str(),apPass.c_str(),6,false,2);
    if(wifiSsid.length())WiFi.begin(wifiSsid.c_str(),wifiPass.c_str());
    tcpServer.begin();
    MDNS.begin("lumacut");
    installRoutes();
    bleInit();
}
lv_obj_t* lbl(lv_obj_t* parent,const String& text,int x,int y,int px,uint32_t color=INK){
    lv_obj_t* p=lv_label_create(parent);lv_label_set_text(p,uiText(text).c_str());
    lv_obj_set_pos(p,x,y);lv_obj_set_style_text_color(p,lv_color_hex(color),0);
    if(px>=28)lv_obj_set_style_text_font(p,&lv_font_montserrat_28,0);
    else if(px>=20)lv_obj_set_style_text_font(p,&lv_font_montserrat_20,0);
    else lv_obj_set_style_text_font(p,&lv_font_montserrat_14,0);
    return p;
}
lv_obj_t* card(lv_obj_t* parent,int x,int y,int w,int h){
    lv_obj_t* p=lv_obj_create(parent);lv_obj_set_pos(p,x,y);lv_obj_set_size(p,w,h);
    lv_obj_set_style_radius(p,20,0);lv_obj_set_style_bg_color(p,lv_color_hex(WHITE),0);
    lv_obj_set_style_border_width(p,1,0);lv_obj_set_style_border_color(p,lv_color_hex(0x284059),0);
    lv_obj_set_style_pad_all(p,0,0);lv_obj_clear_flag(p,LV_OBJ_FLAG_SCROLLABLE);
    return p;
}
void action(const char* id);
void openKeyboard(lv_event_t* e){
    // CLICKED is deliberate: focus is not consistently delivered by the
    // GT911/LVGL pointer driver. A modal also keeps the typed text visible.
    editTarget=lv_event_get_target(e);
    if(!editTarget||!editOverlay||!keyboard||!editInput)return;
    lv_textarea_set_text(editInput,lv_textarea_get_text(editTarget));
    lv_textarea_set_password_mode(editInput,editTarget==passwordEntry);
    const bool numeric=editTarget==sizeXField||editTarget==sizeYField||
        editTarget==sizeZField||editTarget==paramKeyField||
        editTarget==paramValueField||editTarget==focusLiftField||
        editTarget==focusGapField||editTarget==tipOffsetField;
    lv_keyboard_set_mode(keyboard,numeric?LV_KEYBOARD_MODE_NUMBER:LV_KEYBOARD_MODE_TEXT_LOWER);
    lv_keyboard_set_textarea(keyboard,editInput);
    lv_obj_clear_flag(editOverlay,LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(editOverlay);
}
void keyboardEvent(lv_event_t* e){
    lv_event_code_t code=lv_event_get_code(e);
    if(code==LV_EVENT_READY)action("editorcommit");
    else if(code==LV_EVENT_CANCEL)action("editorcancel");
}
void actionCb(lv_event_t* e){action((const char*)lv_event_get_user_data(e));}
lv_obj_t* btn(lv_obj_t* parent,const char* text,int x,int y,int w,int h,const char* op,uint32_t bg=GRAY,uint32_t fg=INK){
    lv_obj_t* p=lv_btn_create(parent);lv_obj_set_pos(p,x,y);lv_obj_set_size(p,w,h);
    lv_obj_set_style_radius(p,13,0);lv_obj_set_style_bg_color(p,lv_color_hex(bg),0);
    lv_obj_set_style_border_color(p,lv_color_hex(bg==GRAY?0x35506B:bg),0);
    lv_obj_set_style_border_width(p,1,0);
    lv_obj_set_style_shadow_width(p,0,0);
    lv_obj_set_style_bg_color(p,lv_color_hex(PALE_BLUE),LV_STATE_PRESSED);
    if(op)lv_obj_add_event_cb(p,actionCb,LV_EVENT_CLICKED,(void*)op);
    lv_obj_t* t=lv_label_create(p);lv_label_set_text(t,uiText(String(text)).c_str());lv_obj_center(t);
    lv_obj_set_style_text_color(t,lv_color_hex(fg),0);lv_obj_set_style_text_font(t,&lv_font_montserrat_14,0);
    return p;
}
lv_obj_t* configEntry(lv_obj_t* parent,int x,int y,int w,int h,const String& text){
    lv_obj_t* item=lv_textarea_create(parent);
    lv_obj_set_pos(item,x,y);lv_obj_set_size(item,w,h);
    lv_textarea_set_one_line(item,true);lv_textarea_set_max_length(item,13);
    lv_textarea_set_text(item,text.c_str());
    lv_obj_set_style_bg_color(item,lv_color_hex(GRAY),0);
    lv_obj_set_style_text_color(item,lv_color_hex(INK),0);
    lv_obj_set_style_border_width(item,0,0);
    return item;
}
void switchTab(int idx){
    activePage=idx;
    const int navMap[7]={0,5,1,2,3,6,4};
    for(int j=0;j<10;j++)lv_obj_add_flag(pages[j],LV_OBJ_FLAG_HIDDEN);
    if(idx>=0&&idx<7)lv_obj_clear_flag(pages[navMap[idx]],LV_OBJ_FLAG_HIDDEN);
    else if(idx>=7&&idx<10)lv_obj_clear_flag(pages[idx],LV_OBJ_FLAG_HIDDEN);
    for(int i=0;i<7;i++){
        lv_obj_set_style_bg_color(navButtons[i],lv_color_hex(i==idx?PALE_BLUE:WHITE),0);
        lv_obj_t* t=lv_obj_get_child(navButtons[i],0);
        if(t)lv_obj_set_style_text_color(t,lv_color_hex(i==idx?BLUE:SUBTLE),0);
    }
    updateUi();
}
void navCb(lv_event_t* e){switchTab((int)(uintptr_t)lv_event_get_user_data(e));}
// Machine parameter catalog: metadata only. Available values must be read
// back from SKR via GRBL $; unknown firmware extensions are marked "?".
struct ParameterEntry {int id; const char* label;};
const ParameterEntry parameterPages[7][6]={
    {{0,"Schrittpuls us"},{1,"Motor Haltestrom"},{2,"Schritt invert."},{3,"Motor Richtung"},
     {4,"Enable invert."},{5,"Endstop Polaritaet"}},
    {{100,"X Schritte/mm"},{101,"Y Schritte/mm"},{102,"Z Schritte/mm"},
     {110,"X max mm/min"},{111,"Y max mm/min"},{112,"Z max mm/min"}},
    {{120,"X Beschleunig."},{121,"Y Beschleunig."},{122,"Z Beschleunig."},
     {130,"X Fahrweg mm"},{131,"Y Fahrweg mm"},{132,"Z Fahrweg mm"}},
    {{20,"Soft Limits"},{21,"Hard Limits"},{22,"XYZ Homing"},{23,"Homing-Richtung"},
     {24,"Homing Fein"},{25,"Homing Schnell"}},
    {{26,"Homing Entprell."},{27,"Homing Freifahrt"},{30,"Laser Leistung max"},
     {31,"Laser Leistung min"},{32,"Laser-Modus"},{33,"Laser PWM Hz"}},
    {{6,"Probe Polaritaet"},{10,"Statusmaske"},{11,"Kurvenabweichung"},
     {12,"Kreisbogen-Tol."},{13,"Zoll-Ausgabe"},{34,"PWM/Spindel Extra"}},
    {{140,"X Motorstrom"},{141,"Y Motorstrom"},{142,"Z Motorstrom"},
     {150,"X Microsteps"},{151,"Y Microsteps"},{152,"Z Microsteps"}}
};
const char* catalogNames[7]={"Antrieb & Endschalter","Schrittaufl./Tempo",
    "Beschleunigung & Wege","Homing & Limits","Laser & PWM",
    "GRBL Spezial","TMC2209 Erweiterungen"};
void refreshCatalog(){
    if(!catalogTitle)return;
    labelChanged(catalogTitle,String("GRBL / ")+catalogNames[catalogCategory]);
    for(int i=0;i<6;i++){
        int id=parameterPages[catalogCategory][i].id;
        String value=knownSetting[id]?String(savedSetting[id],3):String("nicht gemeldet");
        lv_obj_t* child=lv_obj_get_child(catalogRows[i],0);
        labelChanged(child,String("$")+String(id)+" "+parameterPages[catalogCategory][i].label+
                      " / "+value);
    }
}

void areaTap(lv_event_t* e){
    if(lv_event_get_code(e)!=LV_EVENT_CLICKED)return;
    if(!machineHomed||!canMotion()||postHomePending){
        setNotice("Erst Homing, Motor-Haltebetrieb und Verfahrgrenzen pruefen.");
        return;
    }
    lv_indev_t* dev=lv_indev_get_act();
    if(!dev||!areaField||workX<=0||workY<=0)return;
    lv_point_t touch;
    lv_indev_get_point(dev,&touch);
    lv_area_t area;
    lv_obj_get_coords(areaField,&area);
    // Only the actual 188x188 inner travel projection is actionable.
    float u=(float(touch.x-area.x1)-6.f)/188.f;
    float v=(float(touch.y-area.y1)-6.f)/188.f;
    if(u<0.f||u>1.f||v<0.f||v>1.f)return;
    float x=machineZeroAtMax?(u-1.f)*workX:u*workX;
    float y=machineZeroAtMax?(-v)*workY:(1.f-v)*workY;
    // Clamp away from nominal limit values, respecting homing pull-off.
    const float margin=1.0f;
    float xmin=machineZeroAtMax?-workX+margin:margin;
    float xmax=machineZeroAtMax?-margin:workX-margin;
    float ymin=machineZeroAtMax?-workY+margin:margin;
    float ymax=machineZeroAtMax?-margin:workY-margin;
    if(xmin>=xmax||ymin>=ymax)return;
    x=constrain(x,xmin,xmax);y=constrain(y,ymin,ymax);
    // Never turn laser on for touch travel. Coordinates are MPos (G53).
    String cmds[]={"M5","G53 G0 X"+String(x,3)+" Y"+String(y,3)};
    if(startScript(cmds,2,true))
        setNotice("Fahre mit Laser AUS nach X "+String(operatorPos(x),1)+
                  " / Y "+String(operatorPos(y),1)+". Fahrweg beobachten.");
    else setNotice("Maschine belegt, keine Touch-Bewegung moeglich.");
}

void makeUi(){
    lv_obj_t* root=lv_scr_act();
    lv_obj_clear_flag(root,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(root,lv_color_hex(BG),0);
    lv_obj_set_style_pad_all(root,0,0);

    // Premium command-center header: product identity, live state and DRO.
    lbl(root,"LumaCut",22,9,28);
    lbl(root,"STUDIO  /  CNC",181,22,14,BLUE);
    lbl(root,"LASER CONTROL SYSTEM",23,48,14,SUBTLE);
    lv_obj_t* live=card(root,585,13,196,43);
    statusLabel=lbl(live,"VERBINDUNG...",15,12,14,BLUE);
    positionLabel=lbl(root,"X --.--     Y --.--     Z --.--",23,78,20,INK);
    sourceLabel=lbl(root,"Steuerung frei",583,84,14,SUBTLE);

    // Every page fits 800x480 without accidental scrolling.
    for(int i=0;i<10;i++){
        pages[i]=lv_obj_create(root);lv_obj_set_pos(pages[i],14,117);
        lv_obj_set_size(pages[i],772,272);
        lv_obj_set_style_bg_opa(pages[i],LV_OPA_TRANSP,0);
        lv_obj_set_style_border_width(pages[i],0,0);
        lv_obj_set_style_pad_all(pages[i],0,0);
        lv_obj_clear_flag(pages[i],LV_OBJ_FLAG_SCROLLABLE);
    }

    // HOME: reference controls are prominent; no timed unlock.
    lv_obj_t* c=card(pages[0],0,0,470,268);
    lbl(c,"Maschinensteuerung",20,15,20);
    lbl(c,"XYZ  /  Echtzeit  /  GRBL",20,47,14,SUBTLE);
    btn(c,"Referenzfahrt",20,88,209,54,"home",BLUE,BG);
    btn(c,"Homing aktivieren",244,88,206,54,"enablehome",PALE_BLUE,BLUE);
    btn(c,"Job starten",20,157,132,53,"start",GRAY,INK);
    btn(c,"Pause / Weiter",166,157,133,53,"toggle",GRAY,INK);
    btn(c,"Abbrechen",313,157,137,53,"abort",0x55303A,0xFF8992);
    lbl(c,"Status und Fehlermeldungen unten im Display",20,236,14,SUBTLE);

    lv_obj_t* quick=card(pages[0],482,0,290,268);
    lbl(quick,"Schnellzugriff",19,15,20);
    lbl(quick,"Dein direkter Workflow",19,46,14,SUBTLE);
    btn(quick,"Kontur abfahren",18,89,254,49,"frame",GRAY,INK);
    btn(quick,"Parkposition",18,149,254,49,"park",GRAY,INK);
    btn(quick,"LightBurn per WLAN",18,209,254,43,"host",PALE_BLUE,BLUE);

    // JOBS: large clear actions and filename/status.
    c=card(pages[1],0,0,772,268);
    lbl(c,"Job Studio",22,15,20);
    lbl(c,"Datei vom Handy oder aus LightBurn",22,47,14,SUBTLE);
    jobLabel=lbl(c,"Keine Datei ausgewaehlt",22,80,20,INK);
    lv_obj_set_width(jobLabel,722);
    lv_label_set_long_mode(jobLabel,LV_LABEL_LONG_DOT);
    btn(c,"Datei wechseln",21,137,177,55,"next",GRAY,INK);
    btn(c,"Kontur testen",211,137,170,55,"frame",GRAY,INK);
    btn(c,"Job starten",393,137,170,55,"start",BLUE,BG);
    btn(c,"Pause / Weiter",575,137,174,55,"toggle",GRAY,INK);
    lbl(c,"Dateien lokal im HMI speichern: WLAN-Portal in der Systemansicht",22,226,14,SUBTLE);

    // JOG: spatial arrow arrangement with separate Z column.
    c=card(pages[2],0,0,772,268);
    lbl(c,"Manuelle Achsen",20,15,20);
    lbl(c,"Jogging mit GRBL / Schrittweite waehlen",20,47,14,SUBTLE);
    btn(c,"Y +",300,75,116,50,"y+",GRAY,INK);
    btn(c,"X -",169,137,116,50,"x-",GRAY,INK);
    btn(c,"X +",431,137,116,50,"x+",GRAY,INK);
    btn(c,"Y -",300,201,116,49,"y-",GRAY,INK);
    lbl(c,"Z-ACHSE",604,51,14,SUBTLE);
    btn(c,"Z +",593,87,153,54,"z+",PALE_BLUE,BLUE);
    btn(c,"Z -",593,151,153,54,"z-",PALE_BLUE,BLUE);
    lbl(c,"SCHRITTWEITE",20,172,14,SUBTLE);
    btn(c,"0.1 / 1 / 10 mm",20,201,234,48,"step",PALE_BLUE,BLUE);

    // MACROS: three dedicated programmable machine XY positions.
    c=card(pages[3],0,0,772,268);
    lbl(c,"Parkpositionen",21,15,20);
    lbl(c,"Drei eigene XY-Positionen mit Namen",21,46,14,SUBTLE);
    btn(c,"Position 1",21,88,231,48,"p0",GRAY,INK);
    btn(c,"Position 2",270,88,231,48,"p1",GRAY,INK);
    btn(c,"Position 3",519,88,230,48,"p2",GRAY,INK);
    macroLabel=lbl(c,"Position 1",21,153,20,INK);
    lv_obj_set_width(macroLabel,180);
    lv_label_set_long_mode(macroLabel,LV_LABEL_LONG_DOT);
    macroEntry=lv_textarea_create(c);lv_obj_set_pos(macroEntry,208,149);
    lv_obj_set_size(macroEntry,287,44);
    lv_textarea_set_one_line(macroEntry,true);lv_textarea_set_max_length(macroEntry,24);
    lv_textarea_set_text(macroEntry,parks[parkSlot].name.c_str());
    lv_obj_set_style_bg_color(macroEntry,lv_color_hex(GRAY),0);
    lv_obj_set_style_text_color(macroEntry,lv_color_hex(INK),0);
    lv_obj_set_style_border_width(macroEntry,0,0);
    btn(c,"Name sichern",509,149,240,44,"rename",PALE_BLUE,BLUE);
    btn(c,"Aktuelle Position speichern",21,209,355,43,"capture",GRAY,INK);
    btn(c,"Position anfahren",393,209,356,43,"park",BLUE,BG);

    // SYSTEM: Wi-Fi and local network configuration.
    c=card(pages[4],0,0,772,268);
    lbl(c,"System & Verbindung",21,15,20);
    ipLabel=lbl(c,"Netzwerk wird gestartet...",22,63,14,SUBTLE);
    lv_obj_set_width(ipLabel,372);
    lbl(c,"WLAN-NAME (SSID)",418,36,14,SUBTLE);
    ssidEntry=lv_textarea_create(c);lv_obj_set_pos(ssidEntry,415,58);
    lv_obj_set_size(ssidEntry,333,41);lv_textarea_set_one_line(ssidEntry,true);
    lv_textarea_set_text(ssidEntry,wifiSsid.c_str());
    lbl(c,"WLAN-PASSWORT",418,104,14,SUBTLE);
    passwordEntry=lv_textarea_create(c);lv_obj_set_pos(passwordEntry,415,126);
    lv_obj_set_size(passwordEntry,333,41);
    lv_textarea_set_one_line(passwordEntry,true);
    lv_textarea_set_password_mode(passwordEntry,true);
    for(lv_obj_t* field : {ssidEntry,passwordEntry}){
        lv_obj_set_style_bg_color(field,lv_color_hex(GRAY),0);
        lv_obj_set_style_text_color(field,lv_color_hex(INK),0);
        lv_obj_set_style_border_width(field,0,0);
    }
    btn(c,"Mit WLAN verbinden",415,189,333,54,"wifi",BLUE,BG);
    btn(c,"Updates pruefen",20,206,356,41,"updatecheck",PALE_BLUE,BLUE);
    updateLabel=lbl(c,"Noch nicht geprueft",20,247,14,SUBTLE);
    lv_obj_set_width(updateLabel,390);

    // ARBEITSFLAECHE: true XY machine position in an explicitly defined square.
    c=card(pages[5],0,0,304,268);
    lbl(c,"LIVE-ARBEITSFELD",18,10,14,BLUE);
    areaField=lv_obj_create(c);
    lv_obj_set_pos(areaField,47,31);lv_obj_set_size(areaField,210,210);
    lv_obj_set_style_bg_color(areaField,lv_color_hex(0x101D2E),0);
    lv_obj_set_style_border_color(areaField,lv_color_hex(0x46718F),0);
    lv_obj_set_style_border_width(areaField,2,0);
    lv_obj_set_style_radius(areaField,5,0);
    lv_obj_set_style_pad_all(areaField,0,0);
    lv_obj_clear_flag(areaField,LV_OBJ_FLAG_SCROLLABLE);
    for(int i=1;i<4;i++){
        lv_obj_t* v=lv_obj_create(areaField);
        lv_obj_set_pos(v,i*52,0);lv_obj_set_size(v,1,206);
        lv_obj_set_style_bg_color(v,lv_color_hex(0x263A4D),0);
        lv_obj_set_style_border_width(v,0,0);lv_obj_set_style_radius(v,0,0);
        lv_obj_t* h=lv_obj_create(areaField);
        lv_obj_set_pos(h,0,i*52);lv_obj_set_size(h,206,1);
        lv_obj_set_style_bg_color(h,lv_color_hex(0x263A4D),0);
        lv_obj_set_style_border_width(h,0,0);lv_obj_set_style_radius(h,0,0);
    }
    areaDot=lv_obj_create(areaField);lv_obj_set_size(areaDot,14,14);
    lv_obj_set_style_radius(areaDot,LV_RADIUS_CIRCLE,0);
    lv_obj_set_style_bg_color(areaDot,lv_color_hex(0xFF304D),0);
    lv_obj_set_style_border_color(areaDot,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_border_width(areaDot,2,0);
    lv_obj_set_style_pad_all(areaDot,0,0);
    lv_obj_add_flag(areaDot,LV_OBJ_FLAG_HIDDEN);
    // Invisible touch layer above grid and position dot.
    lv_obj_t* areaTouch=lv_obj_create(areaField);
    lv_obj_set_pos(areaTouch,0,0);lv_obj_set_size(areaTouch,207,207);
    lv_obj_set_style_bg_opa(areaTouch,LV_OPA_TRANSP,0);
    lv_obj_set_style_border_width(areaTouch,0,0);
    lv_obj_set_style_pad_all(areaTouch,0,0);
    lv_obj_set_style_shadow_width(areaTouch,0,0);
    lv_obj_clear_flag(areaTouch,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(areaTouch,areaTap,LV_EVENT_CLICKED,nullptr);
    c=card(pages[5],316,0,456,268);
    lbl(c,"Position & Verfahrweg",20,17,20,INK);
    areaCaption=lbl(c,"GRBL-Arbeitsfeld wird geladen...",20,55,14,SUBTLE);
    lv_obj_set_width(areaCaption,414);
    lv_label_set_long_mode(areaCaption,LV_LABEL_LONG_DOT);
    lbl(c,"Roter Punkt = aktuelle Maschinenposition (MPos)",20,88,14,SUBTLE);
    btn(c,"Referenzfahrt",20,129,200,49,"home",BLUE,BG);
    btn(c,"Koordinatennullpunkt",233,129,202,49,"origin",GRAY,INK);
    btn(c,"Fokus / Taster",20,197,200,48,"focusgo",PALE_BLUE,BLUE);
    btn(c,"Parameter",233,197,202,48,"cataloggo",GRAY,INK);

    // MASCHINEN-SETUP: live GRBL $-parameters, motor polarity and bed dimensions.
    c=card(pages[6],0,0,380,268);
    lbl(c,"Arbeitsbereich & Richtung",18,12,20);
    lbl(c,"Arbeitsweg X / Y / Z [mm]",18,45,14,SUBTLE);
    sizeXField=configEntry(c,18,74,105,43,"");
    sizeYField=configEntry(c,137,74,105,43,"");
    sizeZField=configEntry(c,256,74,105,43,"");
    btn(c,"Verfahrwege speichern",18,131,343,45,"savearea",BLUE,BG);
    lbl(c,"Motor-Richtung invertieren ($3)",18,184,14,SUBTLE);
    btn(c,"XYZ",18,209,87,42,"flipall",PALE_BLUE,BLUE);
    btn(c,"X",111,209,78,42,"flipx",GRAY,INK);
    btn(c,"Y",195,209,78,42,"flipy",GRAY,INK);
    btn(c,"Z",279,209,82,42,"flipz",GRAY,INK);

    c=card(pages[6],392,0,380,268);
    lbl(c,"GRBL Maschinen-Setup",18,12,20);
    lbl(c,"Homing-Richtung umschalten ($23)",18,45,14,SUBTLE);
    btn(c,"X",18,69,105,44,"homex",GRAY,INK);
    btn(c,"Y",137,69,105,44,"homey",GRAY,INK);
    btn(c,"Z",256,69,105,44,"homez",GRAY,INK);
    lbl(c,"Parameter-ID / Wert",18,119,14,SUBTLE);
    paramKeyField=configEntry(c,18,143,99,43,"");
    paramValueField=configEntry(c,130,143,113,43,"");
    btn(c,"Setzen",256,143,105,43,"setparam",PALE_BLUE,BLUE);
    btn(c,"$ Lesen",18,208,102,44,"readcfg",GRAY,INK);
    btn(c,"Limits EIN",128,208,112,44,"softon",PALE_BLUE,BLUE);
    btn(c,"Parameter",247,208,114,44,"cataloggo",GRAY,INK);

    // Z focus and workpiece switch page. All numbers are stored in HMI
    // preferences, and motor lock/release is written into SKR GRBL ($1).
    c=card(pages[7],0,0,380,268);
    lbl(c,"Z-Fokus & Werkstueck",18,12,20);
    lbl(c,"Z-Rueckzug nach Homing [mm]",18,45,14,SUBTLE);
    focusLiftField=configEntry(c,18,66,148,43,String(focusLiftMm,2));
    btn(c,"Speichern",181,66,180,43,"focusSave",BLUE,BG);
    lbl(c,"Optischer Fokusabstand [mm]",18,116,14,SUBTLE);
    focusGapField=configEntry(c,18,136,149,41,String(focusGapMm,2));
    btn(c,"Z + Rueckzug",181,136,180,41,"zlift",GRAY,INK);
    lbl(c,"Schalter-Offset [mm]",18,190,14,SUBTLE);
    tipOffsetField=configEntry(c,18,212,149,42,String(tipOffsetMm,2));
    btn(c,"Auto-Z: EIN/AUS",181,212,180,42,"toggleAutoLift",PALE_BLUE,BLUE);

    c=card(pages[7],392,0,380,268);
    lbl(c,"Motoren / Taster",18,12,20);
    motorInfo=lbl(c,"Schrittmotoren halten",18,45,14,SUBTLE);
    lv_obj_set_width(motorInfo,340);
    btn(c,"Motoren halten",18,74,160,45,"motorHold",PALE_BLUE,BLUE);
    releaseButton=btn(c,"Handbewegung",194,74,168,45,"motorRelease",GRAY,INK);
    lbl(c,"Werkstueck-Abtastung",18,134,14,SUBTLE);
    probeInfo=lbl(c,"Probe: Z-Endschalter wird geteilt",18,156,14,SUBTLE);
    lv_obj_set_width(probeInfo,343);
    btn(c,"Probe konfigurieren",18,186,344,39,"probeSetup",GRAY,INK);
    btn(c,"Z-Test 0,5 mm",18,230,166,34,"ztest",GRAY,INK);
    btn(c,"Z-Richtung OK",196,230,166,34,"zverify",PALE_BLUE,BLUE);

    // Parameter catalog: grouped by actual GRBL $ IDs; tapping a row
    // populates the editable raw setting on Setup, not an HMI-only dummy.
    c=card(pages[8],0,0,772,268);
    catalogTitle=lbl(c,"GRBL-Parameter",19,14,20);
    btn(c,"Kategorie",551,12,200,39,"catalogNext",PALE_BLUE,BLUE);
    for(int i=0;i<6;i++){
        // Persistent C-string IDs for event handlers.
        static const char* ids[]={"cat0","cat1","cat2","cat3","cat4","cat5"};
        catalogRows[i]=btn(c,"Parameter",19+(i%2)*375,64+(i/2)*65,360,56,ids[i],GRAY,INK);
    }
    btn(c,"Setup",404,12,136,39,"setupgo",GRAY,INK);

    // A single-axis Z homing cycle can use the existing PC2 switch
    // as a MATERIAL SURFACE reference, if the head-mounted switch physically
    // touches the workpiece. It is NOT G38 probing and changes Z machine home.
    c=card(pages[9],0,0,380,268);
    lbl(c,"Werkstueck-Z / PC2",18,12,20);
    lbl(c,"Z-Schalter am Kopf auf Werkstueckkontakt?",18,49,14,SUBTLE);
    btn(c,"Kopf-Taster Modus",18,76,343,48,"contactMode",PALE_BLUE,BLUE);
    btn(c,"Schalterstatus lesen",18,138,343,47,"switchcheck",GRAY,INK);
    lbl(c,"Z-only Homing: $HZ, benoetigt $22 Bit 1",18,198,14,SUBTLE);
    lbl(c,"Nur bei korrekter Z-Suchrichtung ($23)!",18,225,14,RED);

    c=card(pages[9],392,0,380,268);
    lbl(c,"Werkstueck neu referenzieren",18,12,20);
    lbl(c,"Die Z-Maschinenreferenz wird neu gesetzt.",18,50,14,SUBTLE);
    lbl(c,"Homing-Tempo: $24 langsam, $25 schnell.",18,76,14,SUBTLE);
    btn(c,"Z-Oberflaeche antasten",18,113,343,56,"zsurface",BLUE,BG);
    btn(c,"Z auf Abstand",18,180,166,46,"zlift",PALE_BLUE,BLUE);
    btn(c,"Zurueck",196,180,165,46,"focusgo",GRAY,INK);
    lbl(c,"Kein G38-Probing / kein Hoehenraster",18,238,14,SUBTLE);

    // Bottom dock is always visible, and labels remain within touch targets.
    const char* tabs[]={"Home","Flaeche","Jobs","Jog","Makros","Setup","WLAN"};
    lv_obj_t* dock=card(root,14,406,772,59);
    lv_obj_set_style_radius(dock,19,0);
    for(int i=0;i<7;i++){
        navButtons[i]=btn(dock,tabs[i],7+i*109,7,102,45,nullptr,WHITE,SUBTLE);
        lv_obj_add_event_cb(navButtons[i],navCb,LV_EVENT_CLICKED,(void*)(uintptr_t)i);
    }
    messageLabel=lbl(root,"Maschinenstatus wird geladen.",21,387,14,SUBTLE);
    lv_obj_set_width(messageLabel,754);
    lv_label_set_long_mode(messageLabel,LV_LABEL_LONG_DOT);

    // True full-screen editor: input ABOVE keyboard, so nothing is covered.
    // Closing the modal explicitly commits back to the original field.
    editOverlay=lv_obj_create(root);
    lv_obj_set_pos(editOverlay,0,0);lv_obj_set_size(editOverlay,W,H);
    lv_obj_set_style_radius(editOverlay,0,0);
    lv_obj_set_style_pad_all(editOverlay,0,0);
    lv_obj_set_style_bg_color(editOverlay,lv_color_hex(BG),0);
    lv_obj_set_style_border_width(editOverlay,0,0);
    lv_obj_clear_flag(editOverlay,LV_OBJ_FLAG_SCROLLABLE);
    lbl(editOverlay,"EINGABE",24,11,20,BLUE);
    editInput=lv_textarea_create(editOverlay);
    lv_obj_set_pos(editInput,20,51);lv_obj_set_size(editInput,760,48);
    lv_textarea_set_one_line(editInput,true);lv_textarea_set_max_length(editInput,96);
    lv_obj_set_style_bg_color(editInput,lv_color_hex(GRAY),0);
    lv_obj_set_style_text_color(editInput,lv_color_hex(INK),0);
    keyboard=lv_keyboard_create(editOverlay);
    lv_obj_set_pos(keyboard,12,108);lv_obj_set_size(keyboard,776,269);
    lv_obj_set_style_bg_color(keyboard,lv_color_hex(WHITE),0);
    lv_obj_add_event_cb(keyboard,keyboardEvent,LV_EVENT_READY,nullptr);
    lv_obj_add_event_cb(keyboard,keyboardEvent,LV_EVENT_CANCEL,nullptr);
    btn(editOverlay,"Speichern",404,394,376,67,"editorcommit",BLUE,BG);
    btn(editOverlay,"Zurueck",20,394,367,67,"editorcancel",GRAY,INK);
    lv_obj_add_flag(editOverlay,LV_OBJ_FLAG_HIDDEN);
    for(lv_obj_t* field : {ssidEntry,passwordEntry,macroEntry,
         sizeXField,sizeYField,sizeZField,paramKeyField,paramValueField,
         focusLiftField,focusGapField,tipOffsetField})
        lv_obj_add_event_cb(field,openKeyboard,LV_EVENT_CLICKED,nullptr);
    refreshSizeFields();
    switchTab(0);
}
bool zDeltaAllowed(float delta){
    zLiftReason="";
    if(!fresh()){zLiftReason="SKR ist nicht erreichbar.";return false;}
    if(!machineHomed){zLiftReason="Maschine nicht referenziert.";return false;}
    if(!haveMpos){zLiftReason="Keine Maschinenposition MPos. GRBL Statusmaske $10 pruefen.";return false;}
    if(workZ<=0){zLiftReason="Z-Verfahrweg $132 fehlt. Gemessenen Wert speichern.";return false;}
    if(!isfinite(delta)||fabsf(delta)<0.001f){zLiftReason="Z-Rueckzug muss ungleich 0 mm sein.";return false;}
    if(!canZMotion()){zLiftReason="SKR ist beschaeftigt oder Motoren sind freigegeben.";return false;}
    float minZ=machineZeroAtMax?-workZ:0.f;
    float maxZ=machineZeroAtMax?0.f:workZ;
    float target=mz+delta;
    if(target<=minZ+0.05f||target>=maxZ-0.05f){
        zLiftReason="Z-Ziel "+String(target,2)+" ausserhalb "+
            String(minZ,1)+".."+String(maxZ,1)+
            " mm. Z-Lift-Vorzeichen und Referenzrichtung pruefen.";
        return false;
    }
    return true;
}
bool zJogRawDelta(float delta){
    if(!zDeltaAllowed(delta))return false;
    String cmds[]={"M5","$J=G91 G21 Z"+String(delta,3)+
                        " F"+String(constrain(probeFeedMm,30.f,600.f),1)};
    return startScript(cmds,2,true,true);
}
// A target such as 7.00 mm is the displayed positive position AFTER homing,
// not an additional +7 mm added to the homing switch pull-off.
// Example MPos Z=-1 => logical Z=+1, target +7 => raw delta=-6.
bool zLift(float targetOperatorMm){
    if(!isfinite(targetOperatorMm)||targetOperatorMm<0.05f){
        zLiftReason="Z-Zielabstand muss mindestens 0,05 mm betragen.";
        return false;
    }
    const float machineTarget=machinePosFromOperator(targetOperatorMm);
    const float rawDelta=machineTarget-mz;
    if(fabsf(rawDelta)<0.005f){
        zLiftReason="Z steht bereits bei "+String(targetOperatorMm,2)+" mm.";
        return false;
    }
    return zJogRawDelta(rawDelta);
}
bool settingAllowed(int id,float val){
    // Keep hard/soft limits and homing active when modified through the HMI.
    if((id==20||id==21||id==22)&&val<1)return false;
    if(id==3||id==23)return(val>=0&&val<=7&&int(val)==val);
    if(id==130||id==131||id==132)return val>0&&val<=3000;
    return id>=0&&id<=999&&isfinite(val);
}
int jogStep=1;
void action(const char* id){
    String op=id;
    if(op=="focusSave"){
        if(!focusLiftField||!focusGapField||!tipOffsetField)return;
        String lift=lv_textarea_get_text(focusLiftField);
        String gap=lv_textarea_get_text(focusGapField);
        String offset=lv_textarea_get_text(tipOffsetField);
        float a=lift.toFloat(),b=gap.toFloat(),c=offset.toFloat();
        if(!isfinite(a)||!isfinite(b)||!isfinite(c)||
           a<0.05f||a>50.f||b<0.5f||b>100.f||fabsf(c)>100.f){
            setNotice("Z-Ziel 0.05-50 mm; Fokus 0.5-100 mm; Offset +/-100 mm.");return;
        }
        if(fabsf(a-focusLiftMm)>0.001f){
            zLiftDirectionVerified=false;
            prefs.putBool("zsignOK",false);
        }
        focusLiftMm=a;focusGapMm=b;tipOffsetMm=c;
        prefs.putFloat("zlift",a);prefs.putFloat("focgap",b);prefs.putFloat("tipoffs",c);
        setNotice("Z-Rueckzug, Fokusabstand und Tasteroffset gespeichert.");
        return;
    }
    if(op=="toggleAutoLift"){
        autoLiftAfterHome=!autoLiftAfterHome;
        prefs.putBool("autoZlift",autoLiftAfterHome);
        setNotice(autoLiftAfterHome?
            "Auto-Z EIN. Vor Auto-Fahrt Z-Test 0,5 mm und Richtung OK erforderlich.":
            "Auto-Z nach Homing AUS");
        return;
    }
    if(op=="ztest"){
        // +0.5 operator-space is a small retreat from the homed reference.
        float delta=machinePosFromOperator(0.5f);
        if(zJogRawDelta(delta))
            setNotice("Z-Test +0,5 mm im positiven Anzeigeraum gestartet.");
        else setNotice("Z-Test abgelehnt: "+zLiftReason);
        return;
    }
    if(op=="zverify"){
        if(!machineHomed||!fresh()||!haveMpos||workZ<=0||!softLimitsEnabled){
            setNotice("Z-Richtung erst nach Homing, MPos und $20/$132 pruefen.");return;
        }
        zLiftDirectionVerified=true;
        prefs.putBool("zsignOK",true);
        setNotice("Z-Vorzeichen vom Bediener bestaetigt. Auto-Z nutzt diesen Wert.");
        return;
    }
    if(op=="zlift"){
        if(zLift(focusLiftMm))
            setNotice("Z-Ziel "+String(focusLiftMm,2)+" mm bei Laser AUS angefahren.");
        else setNotice("Z-Lift nicht moeglich: "+zLiftReason);
        return;
    }
    if(op=="motorHold"){
        String cmds[]={"$1=255",String(char(36))+char(36)};
        if(startScript(cmds,2)){
            motorsReleased=false;configWrite=ConfigWrite::MotorHold;
            setNotice("Sende $1=255. Wenn Motoren aus waren, danach XYZ homen.");
        } else setNotice("Motor-Einstellung nur im Leerlauf/Alarm.");
        return;
    }
    if(op=="motorRelease"){
        if(motorsReleased){
            machine.write((uint8_t)0x18); // controller reset wakes from $SLP
            machineHomed=false;haveMpos=false;motorsReleased=false;
            homingInProgress=false;postHomePending=false;
            owner=Owner::None;scriptActive=false;commandPending=false;
            settingsRequested=false;lastStatusMs=0;
            setNotice("Motoren aktiv. Vor weiteren Fahrten XYZ neu referenzieren.");
            return;
        }
        if(owner!=Owner::None||!idle()){
            setNotice("Motorfreigabe nur im Leerlauf moeglich.");return;
        }
        // grblHAL $SLP disables drivers reliably; $1=0 alone may not
        // force an immediate enable-pin transition when already idle.
        machine.print("M5\n$SLP\n");
        machineHomed=false;haveMpos=false;
        motorsReleased=true;postHomePending=false;
        setNotice("Schlafmodus: Motoren frei. Erneut tippen zum Aufwecken.");
        return;
    }
    if(op=="probeSetup"){switchTab(9);return;}
    if(op=="contactMode"){
        contactSwitchAtHead=!contactSwitchAtHead;
        prefs.putBool("headsw",contactSwitchAtHead);
        setNotice(contactSwitchAtHead?
          "Kopf-Taster: Kontakt auf Werkstueckoberflaeche bestaetigt.":
          "Werkstueck-Z-Modus ausgeschaltet.");
        return;
    }
    if(op=="switchcheck"){
        String cmds[]={"$LIM"};
        if(startScript(cmds,1))setNotice("Lese mechanische X/Y/Z-Schalter.");
        else setNotice("Schaltertest nur bei freier Steuerung.");
        return;
    }
    if(op=="zsurface"){
        if(!contactSwitchAtHead){
            setNotice("Z-Taster muss am Kopf die Werkstueckoberflaeche beruehren.");return;
        }
        if(!canMotion()||!homingEnabled||!haveMpos){
            setNotice("Vor dem Z-Werkstueckkontakt zuerst XYZ homen und Soft Limits setzen.");return;
        }
        // $22=3 enables single-axis homing on grblHAL; $HZ finds only Z's
        // existing limit contact. This resets machine Z, NOT a G38 probe.
        String cmds[]={"M5","$22=3","$1=255","$HZ"};
        if(startScript(cmds,4))
            setNotice("Werkstueckkontakt: Z-Referenzfahrt ($HZ) vorbereitet.");
        else setNotice("Z-Werkstueckkontakt nur im Leerlauf.");
        return;
    }
    if(op=="editorcancel"){
        lv_obj_add_flag(editOverlay,LV_OBJ_FLAG_HIDDEN);
        editTarget=nullptr;return;
    }
    if(op=="editorcommit"){
        if(editTarget){
            if(editTarget==sizeXField||editTarget==sizeYField||editTarget==sizeZField)
                travelInputsDirty=true;
            lv_textarea_set_text(editTarget,lv_textarea_get_text(editInput));
            lv_obj_add_flag(editOverlay,LV_OBJ_FLAG_HIDDEN);
            editTarget=nullptr;
            setNotice("Eingabe uebernommen.");updateUi();
        }
        return;
    }
    if(op=="updatecheck"){
        updateCheckRequested=true;
        setNotice("LumaCut Stable-Updates werden per HTTPS geprueft.");
        return;
    }
    if(op=="setupgo"){switchTab(5);return;}
    if(op=="focusgo"){switchTab(7);return;}
    if(op=="cataloggo"){switchTab(8);return;}
    if(op=="catalogNext"){catalogCategory=(catalogCategory+1)%7;refreshCatalog();return;}
    if(op.startsWith("cat")&&op.length()==4&&op[3]>='0'&&op[3]<='5'){
        int slot=op[3]-'0',id=parameterPages[catalogCategory][slot].id;
        lv_textarea_set_text(paramKeyField,String(id).c_str());
        lv_textarea_set_text(paramValueField,
            knownSetting[id]?String(savedSetting[id],3).c_str():"");
        switchTab(5);
        setNotice("Parameter $"+String(id)+" bearbeiten und Setzen waehlen.");
        return;
    }
    if(op=="rotate180"){
        if(!uiDisplay)return;
        rotate180=!rotate180;
        prefs.putBool("rotate180",rotate180);
        lv_disp_set_rotation(uiDisplay,rotate180?LV_DISP_ROT_180:LV_DISP_ROT_NONE);
        setNotice(rotate180?"Display um 180 Grad gedreht.":"Normale Displayausrichtung.");
        return;
    }
    if(op=="origin"){
        machineZeroAtMax=!machineZeroAtMax;
        prefs.putBool("zeroMax",machineZeroAtMax);
        updateArea();
        setNotice(machineZeroAtMax?"GRBL-Maschinenbereich: -Weg bis 0.":"GRBL-Maschinenbereich: 0 bis Weg.");
        return;
    }
    if(op=="readcfg"){
        String cmds[]={"$$"};
        if(!startScript(cmds,1))setNotice("Maschinenparameter nur im Leerlauf lesbar.");
        else setNotice("Lese $3, $23 und Verfahrwege aus GRBL.");
        return;
    }
    if(op=="flipall"||op=="flipx"||op=="flipy"||op=="flipz"){
        if(directionMask<0||homingDirectionMask<0){
            setNotice("Erst Motor- und Homing-Masken mit $$ Lesen laden.");return;
        }
        int axis=op=="flipall"?7:op=="flipx"?1:op=="flipy"?2:4;
        int newMask=directionMask^axis;
        int newHomeMask=homingDirectionMask^axis;
        // When stepper polarity flips, invert homing search too to preserve
        // physical direction toward the existing mechanical endstop.
        String cmds[]={"$3="+String(newMask),"$23="+String(newHomeMask),"$$"};
        if(startScript(cmds,3))
            setNotice("Motor $3="+String(newMask)+", Homing $23="+
                      String(newHomeMask)+". Fahrtrichtung erst pruefen.");
        else setNotice("Motor-Richtung nur im Leerlauf aenderbar.");
        return;
    }
    if(op=="homex"||op=="homey"||op=="homez"){
        if(homingDirectionMask<0){setNotice("Erst GRBL-Einstellungen mit $ Lesen laden.");return;}
        int bit=op=="homex"?1:op=="homey"?2:4;
        int newMask=homingDirectionMask^bit;
        String cmds[]={"$23="+String(newMask),"$$"};
        if(startScript(cmds,2))
            setNotice("Homing-Richtungsmaske wird auf "+String(newMask)+" gesetzt.");
        else setNotice("Homing-Richtung nur im Leerlauf aenderbar.");
        return;
    }
    if(op=="savearea"){
        const char* sx=lv_textarea_get_text(sizeXField);
        const char* sy=lv_textarea_get_text(sizeYField);
        const char* sz=lv_textarea_get_text(sizeZField);
        float x=atof(sx),y=atof(sy),z=atof(sz);
        if(!isfinite(x)||!isfinite(y)||!isfinite(z)||
            x<1||y<1||z<1||x>3000||y>3000||z>3000){
            setNotice("Fahrwege: X, Y, Z in mm zwischen 1 und 3000 eingeben.");return;
        }
        // The controller alone validates travel; these must be measured,
        // not estimated by repeatedly driving against endstops.
        String cmds[]={"$130="+String(x,3),"$131="+String(y,3),
                       "$132="+String(z,3),"$$"};
        if(startScript(cmds,4)){
            travelRequested[0]=x;travelRequested[1]=y;travelRequested[2]=z;
            configWrite=ConfigWrite::Travel;
            setNotice("Sende Verfahrwege; warte auf SKR-Bestaetigung.");
        }
        else setNotice("Fahrwege nur im Leerlauf aenderbar.");
        return;
    }
    if(op=="softon"){
        if(workX<=0||workY<=0||workZ<=0){
            setNotice("Zuerst alle drei gemessenen Verfahrwege in GRBL speichern.");return;
        }
        // Both limits are active: software checks the measured travel, while
        // physical switches trigger SKR hard-limit alarms on endstop contact.
        String cmds[]={"$22=1","$20=1","$21=1",String(char(36))+char(36)};
        if(startScript(cmds,4)){
            configWrite=ConfigWrite::Limits;
            setNotice("Limits werden gesetzt; warte auf SKR-Bestaetigung.");
        }
        else setNotice("Limits nur bei freier Maschine aktivierbar.");
        return;
    }
    if(op=="setparam"){
        String idText=lv_textarea_get_text(paramKeyField);
        String vText=lv_textarea_get_text(paramValueField);
        idText.trim();idText.replace("$","");
        if(!idText.length()||!vText.length()){setNotice("Parameter-ID und Wert eingeben.");return;}
        for(unsigned i=0;i<idText.length();i++)if(!isDigit(idText[i])){
            setNotice("Parameter-ID muss numerisch sein.");return;
        }
        char* end=nullptr;
        float value=strtof(vText.c_str(),&end);
        if(end==vText.c_str()||*end!='\0'||!settingAllowed(idText.toInt(),value)){
            setNotice("Parameterwert ungueltig oder Sicherheitseinstellung blockiert.");return;
        }
        String cmds[]={"$"+idText+"="+vText,"$$"};
        if(startScript(cmds,2)){
            requestedSettingId=idText.toInt();requestedSettingValue=value;
            configWrite=ConfigWrite::Parameter;
            setNotice("Warte auf SKR-Bestaetigung fuer $"+idText+".");
        }
        else setNotice("Parameter nur im Leerlauf aenderbar.");
        return;
    }
    if(op=="host"){
        if(owner!=Owner::None||!fresh()||
           (machineState!=MachineState::Idle&&machineState!=MachineState::Alarm)){
            setNotice("WLAN LightBurn nur bei freier Maschine aktivieren.");return;
        }
        wifiHostUntil=millis()+300000u;
        setNotice("LightBurn TCP-Port 23 für 5 Minuten zur Verbindung geöffnet.");
        return;
    }
    if(op=="release"){
        if(owner!=Owner::Internal&&owner!=Owner::Script&&idle()){
            owner=Owner::None;hostBlocked=false;setNotice("Hostverbindung freigegeben.");
        } else setNotice("Quellenwechsel bei aktivem Job untersagt.");
        return;
    }
    if(op=="pause"||op=="toggle"){
        if(owner==Owner::Internal&&jobRunning){
            if(jobPaused){machine.write('~');jobPaused=false;}else{feedHold();jobPaused=true;}
        }else setNotice("Keine lokale Jobausführung.");return;
    }
    if(op=="abort"){
        if(owner==Owner::Internal||owner==Owner::Script)abortJob();
        else if(owner==Owner::Usb||owner==Owner::Tcp){abortHost();}
        return;
    }
    if(op=="home"){
        // Real machine: one installed endstop for each of X, Y and Z.
        if(owner!=Owner::None||!fresh()||
           (machineState!=MachineState::Idle&&machineState!=MachineState::Alarm)){
            setNotice("Referenzfahrt nur bei freier Maschine moeglich.");return;
        }
        if(claim(Owner::Script)){
            // Program idle holding BEFORE motors are woken by the homing
            // cycle. Changing $1 after homing may leave an already-disabled
            // enable pin OFF until another motor movement.
            script[0]="$1=255";script[1]="$H";
            scriptCount=2;scriptIndex=0;scriptActive=true;
            homingInProgress=false;homeFromHmi=false;machineHomed=false;
            haveMpos=false;postHomePending=false;
            nextScript();setNotice("Referenzfahrt gestartet.");
        }
        return;
    }
    if(op=="enablehome"){
        if(owner!=Owner::None||!idle()){
            setNotice("Homing nur im Leerlauf konfigurierbar.");return;
        }
        if(claim(Owner::Script)){
            script[0]="$22=1";scriptCount=1;scriptIndex=0;scriptActive=true;
            nextScript();setNotice("Homing aktivieren: $22=1 gesendet.");
        }
        return;
    }
    if(op=="start"){if(!jobStart())setNotice("Zum Start Datei waehlen und Leerlauf abwarten.");return;}
    if(op=="frame"){if(!dryFrame())setNotice("Trockenrahmen gesperrt oder Dateigrenzen unbekannt.");return;}
    if(op=="park"){if(!runPark())setNotice("Parkposition fehlt oder Maschine ist beschaeftigt.");return;}
    if(op=="capture"){savePark();return;}
    if(op=="rename"){
        String name=lv_textarea_get_text(macroEntry);name.trim();
        if(name.length()<1||name.length()>24){setNotice("Makroname: 1 bis 24 Zeichen.");return;}
        parks[parkSlot].name=name;
        String prefKey="p"+String(parkSlot)+"n";
        prefs.putString(prefKey.c_str(),name);
        if(editOverlay)lv_obj_add_flag(editOverlay,LV_OBJ_FLAG_HIDDEN);
        updateUi();setNotice("Makro umbenannt: "+name);return;
    }
    if(op=="p0"||op=="p1"||op=="p2"){
        parkSlot=op[1]-'0';lv_textarea_set_text(macroEntry,parks[parkSlot].name.c_str());
        updateUi();return;
    }
    if(op=="next"){
        if(!storageOk)return;
        File dir=LittleFS.open("/jobs");File f=dir.openNextFile();
        bool useNext=selectedJob.length()==0,chosen=false;
        String first;
        while(f){
            if(!f.isDirectory()){
                String n=String(f.name());int slash=n.lastIndexOf('/');n=n.substring(slash+1);
                if(!first.length())first=n;
                if(useNext){chosen=selectJob(n);if(chosen)break;}
                if(n==selectedJob)useNext=true;
            }f=dir.openNextFile();
        }
        if(!chosen&&first.length())selectJob(first);
        if(!first.length())setNotice("Noch keine Jobs. Über Handy hochladen.");
        return;
    }
    if(op=="step"){jogStep=(jogStep+1)%3;setNotice("Schrittweite: "+String(jogStep==0?0.1f:jogStep==1?1.f:10.f)+" mm");return;}
    if(op=="wifi"){
        wifiSsid=lv_textarea_get_text(ssidEntry);wifiPass=lv_textarea_get_text(passwordEntry);
        prefs.putString("ssid",wifiSsid);prefs.putString("wpw",wifiPass);
        WiFi.begin(wifiSsid.c_str(),wifiPass.c_str());
        if(editOverlay)lv_obj_add_flag(editOverlay,LV_OBJ_FLAG_HIDDEN);
        setNotice("WLAN-Verbindung gestartet. Hotspot bleibt erreichbar.");return;
    }
    if(op=="x+"||op=="x-"||op=="y+"||op=="y-"||op=="z+"||op=="z-"){
        const float dist=(jogStep==0?0.1f:jogStep==1?1.f:10.f)*(op[1]=='-'?-1:1);
        const char axis=(op[0]=='x'?'X':op[0]=='y'?'Y':'Z');
        if(!canMotion()){
            setNotice("Erst XYZ referenzieren und Soft Limits aktivieren.");return;
        }
        float current=axis=='X'?mx:axis=='Y'?my:mz;
        float travel=axis=='X'?workX:axis=='Y'?workY:workZ;
        float target=current+dist;
        float minPos=machineZeroAtMax?-travel:0;
        float maxPos=machineZeroAtMax?0:travel;
        if(target<minPos+0.001f||target>maxPos-0.001f){
            setNotice("Fahrbefehl endet ausserhalb des Arbeitsbereichs.");return;
        }
        String cmds[]={"$J=G91 G21 "+String(axis)+String(dist,2)+" F600"};
        if(!startScript(cmds,1,true))setNotice("Jog nur bei freier Maschine moeglich.");
        return;
    }
}
void internalInit(){
    prefs.begin("lumacut",false);
    machineZeroAtMax=prefs.getBool("zeroMax",true);
    focusLiftMm=fabsf(prefs.getFloat("zlift",7.f));
    zLiftDirectionVerified=prefs.getBool("zsignOK",false);
    focusGapMm=prefs.getFloat("focgap",7.f);
    tipOffsetMm=prefs.getFloat("tipoffs",0.f);
    probeTravelMm=prefs.getFloat("ptravel",15.f);
    probeFeedMm=prefs.getFloat("pfeed",60.f);
    autoLiftAfterHome=prefs.getBool("autoZlift",true);
    contactSwitchAtHead=prefs.getBool("headsw",false);
    // Format only on first provisioning. Never silently erase saved jobs
    // because of a later filesystem or power-loss mounting failure.
    storageOk=LittleFS.begin(false);
    if(!storageOk&&!prefs.getBool("fsinit",false))storageOk=LittleFS.begin(true);
    if(storageOk){
        prefs.putBool("fsinit",true);
        if(!LittleFS.exists("/jobs"))LittleFS.mkdir("/jobs");
    }
    loadParks();
    machine.begin(115200,SERIAL_8N1,44,43); // Physical UART2 switch; SKR PA9/PA10 crossed.
    Serial.begin(115200); // Native USB CDC for LightBurn; never print diagnostic messages here.
    touchInit();
    if(!displayInit()){
        // Do not enter LVGL/network/GRBL service with an uninitialized LCD.
        // Serial USB diagnostic is emitted only on startup failure.
        uiReady=false;
        return;
    }
    // Important: CH422G EXIO2 previously stayed OFF until all 10 UI pages
    // and the network had initialized. Memory exhaustion therefore looked
    // exactly like a permanently black screen. Show a minimal boot message
    // and enable backlight *before* constructing the heavyweight interface.
    lv_obj_t* boot=lv_label_create(lv_scr_act());
    lv_label_set_text(boot,"LumaCut Studio\nDisplay gestartet - lade Oberflaeche...");
    lv_obj_set_style_text_font(boot,&lv_font_montserrat_20,0);
    lv_obj_set_style_text_color(boot,lv_color_hex(0x40D8C3),0);
    lv_obj_center(boot);
    lv_timer_handler();
    if(!expander(LCD_RESET|TP_RESET|BACKLIGHT))
        Serial.println("LUMACUT DISPLAY WARNING: CH422G EXIO2 backlight enable failed");
    delay(100);
    makeUi();
    lv_obj_del(boot);
    lv_timer_handler();
    uiReady=true;
    networkInit();
    setNotice("LumaCut Control OS. Nur Laborbetrieb bis Hardware und Interlocks geprueft.");
}
}
void setup(){internalInit();}
void loop(){
    if(!uiReady){
        // A failed LCD/PSRAM init must not repeatedly dereference null LVGL
        // objects. The USB bootloader can still be used to reflash the HMI.
        delay(250);
        return;
    }
    http.handleClient();
    bridgeService();
    // A missing or rejected settings response must not monopolize the UART
    // and prevent all later parameter edits indefinitely.
    if(scriptActive&&commandPending&&owner==Owner::Script&&!homingInProgress&&
       (uint32_t)(millis()-scriptCommandStartedMs)>12000u){
        scriptActive=false;commandPending=false;scriptCount=scriptIndex=0;
        owner=Owner::None;
        ConfigWrite timedOut=configWrite;configWrite=ConfigWrite::None;
        lastControllerError="Antwort-Timeout bei GRBL Einstellbefehl";
        setNotice(timedOut==ConfigWrite::None?
            "SKR antwortet nicht; UART/Wiring/GRBL pruefen.":
            "SKR hat Einstellbefehl nicht bestaetigt; UART pruefen.");
        machineHomed=false;haveMpos=false;
        postHomePending=false;
    }
    if(postHomePending&&machineHomed){
        if(owner==Owner::None&&idle()&&
           (haveMpos||(uint32_t)(millis()-postHomeStartedMs)>3500u)){
            postHomePending=false; // Never show an endless waiting notice
            const float requested=postContactLift?
                (focusGapMm-tipOffsetMm):focusLiftMm;
            postContactLift=false;
            // Normal $H uses the verified convention expressed by user:
            // raw MPos is negative and retreat grows the positive HMI
            // distance. The stored target is absolute distance from zero.
            // Workpiece contact $HZ remains separately calibrated.
            if(!zLift(requested)){
                setNotice("Auto-Z nicht gefahren: "+zLiftReason);
            }else{
                zLiftReason="";
                setNotice("Auto-Z auf "+String(requested,2)+" mm bei Laser AUS gestartet.");
            }
        }
    }
    internalJobService();
    bleUpdate();
    updateCheckService();
    lv_timer_handler();
    // Collect actual GRBL persistent limits and axis polarity once controller is
    // available; do not fabricate travel distances from the nominal frame size.
    if(!settingsRequested&&millis()>4500&&canConfigure()){
        settingsRequested=true;
        String cmds[]={"$$"};startScript(cmds,1);
    }
    static uint32_t lastUi=0;
    if(millis()-lastUi>160){lastUi=millis();updateUi();}
    delay(2);
}
#endif
