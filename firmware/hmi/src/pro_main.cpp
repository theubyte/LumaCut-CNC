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
constexpr uint32_t WIFI_TCP_PORT=23, STATUS_INTERVAL=250, ARM_DURATION=30000;
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
lv_obj_t* pages[7]{};
lv_obj_t* navButtons[7]{};
lv_obj_t *areaField=nullptr,*areaDot=nullptr,*areaCaption=nullptr,*configCaption=nullptr;
lv_obj_t *sizeXField=nullptr,*sizeYField=nullptr,*sizeZField=nullptr;
lv_obj_t *paramKeyField=nullptr,*paramValueField=nullptr;
lv_disp_t* uiDisplay=nullptr;
bool rotate180=false,settingsRequested=false;
float workX=0,workY=0,workZ=0;
int directionMask=-1,homingDirectionMask=-1;
bool machineZeroAtMax=true;
lv_obj_t *statusLabel=nullptr,*positionLabel=nullptr,*messageLabel=nullptr,
*sourceLabel=nullptr,*jobLabel=nullptr,*ipLabel=nullptr,*ssidEntry=nullptr,
*passwordEntry=nullptr,*keyboard=nullptr,*macroLabel=nullptr,*macroEntry=nullptr;
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
    if(esp_lcd_new_rgb_panel(&cfg,&lcd)!=ESP_OK)return false;
    if(esp_lcd_panel_reset(lcd)!=ESP_OK||esp_lcd_panel_init(lcd)!=ESP_OK)return false;
    lv_init();
    drawPixels=(lv_color_t*)heap_caps_malloc(W*16*sizeof(lv_color_t),MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
    if(!drawPixels)return false;
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
String uiText(String s){
    s.replace("ä","ae");s.replace("ö","oe");s.replace("ü","ue");
    s.replace("Ä","Ae");s.replace("Ö","Oe");s.replace("Ü","Ue");
    s.replace("ß","ss");s.replace("–","-");s.replace("—","-");
    s.replace("…","...");s.replace("·","/");s.replace("×","x");
    return s;
}
void setNotice(const String& s){notice=s;if(messageLabel)lv_label_set_text(messageLabel,uiText(notice).c_str());}
void labelChanged(lv_obj_t* o,const String& value){
    if(!o)return;
    String display=uiText(value);
    if(strcmp(lv_label_get_text(o),display.c_str())!=0)
        lv_label_set_text(o,display.c_str());
}
void refreshSizeFields(){
    if(sizeXField&&workX>0&&!lv_obj_has_state(sizeXField,LV_STATE_FOCUSED))
        lv_textarea_set_text(sizeXField,String(workX,1).c_str());
    if(sizeYField&&workY>0&&!lv_obj_has_state(sizeYField,LV_STATE_FOCUSED))
        lv_textarea_set_text(sizeYField,String(workY,1).c_str());
    if(sizeZField&&workZ>0&&!lv_obj_has_state(sizeZField,LV_STATE_FOCUSED))
        lv_textarea_set_text(sizeZField,String(workZ,1).c_str());
}
void updateArea(){
    if(!areaField||!areaDot)return;
    bool valid=fresh()&&haveMpos&&workX>0.f&&workY>0.f;
    if(!valid){
        lv_obj_add_flag(areaDot,LV_OBJ_FLAG_HIDDEN);
        labelChanged(areaCaption,"Arbeitsfeld unbekannt: GRBL-Werte $130 / $131 lesen");
        return;
    }
    labelChanged(areaCaption,String(workX,1)+" x "+String(workY,1)+
        " mm / MPos X "+String(mx,2)+"  Y "+String(my,2));
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
void updateUi(){
    labelChanged(statusLabel,fresh()?stateText():"Keine Verbindung");
    labelChanged(positionLabel,(fresh()&&haveMpos)?
        "X "+String(mx,2)+"    Y "+String(my,2)+"    Z "+String(mz,2):
        "X --.--     Y --.--     Z --.--");
    labelChanged(sourceLabel,ownerText());
    String job=selectedJob.length()?"Datei: "+selectedJob:"Noch keine Datei ausgewaehlt";
    if(bounds.valid)job+="  /  "+String(bounds.x1-bounds.x0,1)+
                                " x "+String(bounds.y1-bounds.y0,1)+" mm";
    labelChanged(jobLabel,job);
    labelChanged(macroLabel,parks[parkSlot].stored?parks[parkSlot].name:String("Freier Makroplatz"));
    if(ipLabel){
        String net="WLAN: "+(WiFi.status()==WL_CONNECTED?WiFi.localIP().toString():String("nicht verbunden"))+
        "\nHotspot: "+apName+" / "+apPass+
        "\nApp: http://"+WiFi.softAPIP().toString()+
        "\nZugangscode: "+apiKey;
        labelChanged(ipLabel,net);
    }
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
    if(owner!=Owner::Tcp&&owner!=Owner::Usb)return;
    machine.write((uint8_t)0x18);
    machineHomed=false;haveMpos=false;hostBlocked=true;
    setNotice("Externer Job abgebrochen. LightBurn stoppen; Quellenwechsel erst bei Idle.");
}
void abortJob(){
    // Soft reset also clears host parser state; machine must be re-homed.
    machine.write((uint8_t)0x18);
    if(jobFile)jobFile.close();
    jobRunning=false;jobPaused=false;scriptActive=false;commandPending=false;
    scriptCount=scriptIndex=0;owner=Owner::None;machineHomed=false;haveMpos=false;
    setNotice("Abbruch gesendet. Referenzfahrt erneut erforderlich.");
}
void nextScript(){
    if(scriptIndex>=scriptCount){
        scriptActive=false;commandPending=false;releaseLocal();return;
    }
    writeCmd(script[scriptIndex++]);commandPending=true;
}
bool startScript(const String* commands,int count){
    if(!canCommand()||count<1||count>12)return false;
    if(!claim(Owner::Script))return false;
    for(int i=0;i<count;i++)script[i]=commands[i];
    scriptCount=count;scriptIndex=0;scriptActive=true;
    nextScript();return true;
}
void parseMachineLine(const String& line){
    if(line.startsWith("$")){
        int equal=line.indexOf('=');
        if(equal>1){
            String key=line.substring(1,equal);
            bool digits=true;
            for(unsigned i=0;i<key.length();i++)if(!isDigit(key[i]))digits=false;
            if(digits){
                int id=key.toInt();
                float number=line.substring(equal+1).toFloat();
                if(id==3&&number>=0&&number<=7)directionMask=int(number);
                if(id==23&&number>=0&&number<=7)homingDirectionMask=int(number);
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
            if(ok){machineHomed=true;setNotice("Referenzfahrt bestätigt.");}
            else{machineHomed=false;setNotice(line=="error:5"?"Homing im SKR deaktiviert. Unter System $22=1 aktivieren.":"Referenzfahrt fehlgeschlagen: "+line);}
            homingInProgress=false;
        }
        if((owner==Owner::Script)&&commandPending){
            commandPending=false;
            if(ok)nextScript();
            else{scriptActive=false;scriptCount=0;owner=Owner::None;setNotice(line=="error:5"?"Homing im SKR ausgeschaltet ($22=0).":"Befehl fehlgeschlagen: "+line);}
        } else if(owner==Owner::Internal&&commandPending){
            commandPending=false;
            if(!ok){jobRunning=false;if(jobFile)jobFile.close();feedHold();setNotice("G-Code-Fehler: "+line+". Maschine angehalten.");}
        }
    } else if(line.startsWith("ALARM:")){
        machineState=MachineState::Alarm;machineHomed=false;
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
            if(hostLine=="$H")homingInProgress=true;
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
    if(!canCommand()||!selectedJob.length()||!storageOk)return false;
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
    if(!canCommand()||!haveMpos){setNotice("Speichern nur im Leerlauf mit Positionsdaten moeglich.");return;}
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
    return startScript(cmds,3);
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
    return startScript(cmds,8);
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
String jsonStatus(){
    String val="{\"state\":\""+String(fresh()?stateText():"Offline")+
      "\",\"owner\":\""+String(ownerText())+
      "\",\"position\":\""+(haveMpos?("X "+String(mx,2)+" / Y "+String(my,2)+" / Z "+String(mz,2)):"Unbekannt")+
      "\",\"job\":\""+selectedJob+
      "\",\"message\":\""+String(machineHomed?"Referenziert":"Referenzfahrt erforderlich")+
      "\",\"bounds\":"+String(bounds.valid?
        ("{\"x0\":"+String(bounds.x0,3)+",\"y0\":"+String(bounds.y0,3)+
         ",\"x1\":"+String(bounds.x1,3)+",\"y1\":"+String(bounds.y1,3)+"}"):"null")+"}";
    return val;
}
void installRoutes(){
    const char* headers[]={"X-LumaCut-Key"};
    http.collectHeaders(headers,1);
    http.on("/",HTTP_GET,[]{http.send_P(200,"text/html; charset=utf-8",MOBILE_PORTAL);});
    http.on("/api/status",HTTP_GET,[]{if(!auth()){fail(401,"Code erforderlich");return;}http.send(200,"application/json",jsonStatus());});
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
    for(int i=0;i<7;i++){
        if(i==idx)lv_obj_clear_flag(pages[navMap[i]],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(pages[navMap[i]],LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(navButtons[i],lv_color_hex(i==idx?PALE_BLUE:WHITE),0);
        lv_obj_t* t=lv_obj_get_child(navButtons[i],0);
        if(t)lv_obj_set_style_text_color(t,lv_color_hex(i==idx?BLUE:SUBTLE),0);
    }
    updateUi();
}
void navCb(lv_event_t* e){switchTab((int)(uintptr_t)lv_event_get_user_data(e));}
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
    for(int i=0;i<7;i++){
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
    c=card(pages[5],316,0,456,268);
    lbl(c,"Position & Verfahrweg",20,17,20,INK);
    areaCaption=lbl(c,"GRBL-Arbeitsfeld wird geladen...",20,55,14,SUBTLE);
    lv_obj_set_width(areaCaption,414);
    lv_label_set_long_mode(areaCaption,LV_LABEL_LONG_DOT);
    lbl(c,"Roter Punkt = aktuelle Maschinenposition (MPos)",20,88,14,SUBTLE);
    btn(c,"Referenzfahrt",20,129,200,49,"home",BLUE,BG);
    btn(c,"Koordinatennullpunkt",233,129,202,49,"origin",GRAY,INK);
    btn(c,"Soft Limits aktivieren",20,197,200,48,"softon",PALE_BLUE,BLUE);
    btn(c,"Setup oeffnen",233,197,202,48,"setupgo",GRAY,INK);

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
    btn(c,"180 Grad",247,208,114,44,"rotate180",GRAY,INK);

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

    keyboard=lv_keyboard_create(root);
    lv_obj_set_size(keyboard,772,246);lv_obj_set_pos(keyboard,14,140);
    lv_obj_add_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
    auto kb=(lv_event_cb_t)+[](lv_event_t* e){
        lv_event_code_t code=lv_event_get_code(e);
        if(code==LV_EVENT_READY||code==LV_EVENT_CANCEL)
            lv_obj_add_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
    };
    lv_obj_add_event_cb(keyboard,kb,LV_EVENT_READY,nullptr);
    lv_obj_add_event_cb(keyboard,kb,LV_EVENT_CANCEL,nullptr);
    auto showKeyboard=(lv_event_cb_t)+[](lv_event_t* e){
        lv_keyboard_set_textarea(keyboard,lv_event_get_target(e));
        lv_obj_clear_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(keyboard);
    };
    lv_obj_add_event_cb(ssidEntry,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    lv_obj_add_event_cb(passwordEntry,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    lv_obj_add_event_cb(macroEntry,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    for(lv_obj_t* field : {sizeXField,sizeYField,sizeZField,paramKeyField,paramValueField})
        lv_obj_add_event_cb(field,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    refreshSizeFields();
    switchTab(0);
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
    if(op=="setupgo"){switchTab(5);return;}
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
        String cmds[]={"$"};
        if(!startScript(cmds,1))setNotice("Maschinenparameter nur im Leerlauf lesbar.");
        else setNotice("Lese $3, $23 und Verfahrwege aus GRBL.");
        return;
    }
    if(op=="flipall"||op=="flipx"||op=="flipy"||op=="flipz"){
        if(directionMask<0){setNotice("Erst GRBL-Einstellungen mit $ Lesen laden.");return;}
        int axis=op=="flipall"?7:op=="flipx"?1:op=="flipy"?2:4;
        int newMask=directionMask^axis;
        String cmds[]={"$3="+String(newMask),"$"};
        if(startScript(cmds,2))
            setNotice("Motor-Richtungsmaske wird auf "+String(newMask)+" gesetzt.");
        else setNotice("Motor-Richtung nur im Leerlauf aenderbar.");
        return;
    }
    if(op=="homex"||op=="homey"||op=="homez"){
        if(homingDirectionMask<0){setNotice("Erst GRBL-Einstellungen mit $ Lesen laden.");return;}
        int bit=op=="homex"?1:op=="homey"?2:4;
        int newMask=homingDirectionMask^bit;
        String cmds[]={"$23="+String(newMask),"$"};
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
                       "$132="+String(z,3),"$"};
        if(startScript(cmds,4))
            setNotice("Verfahrwege werden im SKR gespeichert.");
        else setNotice("Fahrwege nur im Leerlauf aenderbar.");
        return;
    }
    if(op=="softon"){
        if(workX<=0||workY<=0||workZ<=0){
            setNotice("Zuerst alle drei gemessenen Verfahrwege in GRBL speichern.");return;
        }
        String cmds[]={"$22=1","$20=1","$"};
        if(startScript(cmds,3))setNotice("Homing und Soft Limits aktiviert.");
        else setNotice("Soft Limits nur bei freier Maschine aktivierbar.");
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
        String cmds[]={"$"+idText+"="+vText,"$"};
        if(startScript(cmds,2))setNotice("GRBL-Parameter gespeichert.");
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
            script[0]="$H";scriptCount=1;scriptIndex=0;scriptActive=true;
            homingInProgress=true;machineHomed=false;
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
        lv_obj_add_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
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
        lv_obj_add_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
        setNotice("WLAN-Verbindung gestartet. Hotspot bleibt erreichbar.");return;
    }
    if(op=="x+"||op=="x-"||op=="y+"||op=="y-"||op=="z+"||op=="z-"){
        const float dist=(jogStep==0?0.1f:jogStep==1?1.f:10.f)*(op[1]=='-'?-1:1);
        const char axis=(op[0]=='x'?'X':op[0]=='y'?'Y':'Z');
        String cmds[]={"$J=G91 G21 "+String(axis)+String(dist,2)+" F600"};
        if(!startScript(cmds,1))setNotice("Manuelles Verfahren nur im Leerlauf moeglich.");
        return;
    }
}
void internalInit(){
    prefs.begin("lumacut",false);
    machineZeroAtMax=prefs.getBool("zeroMax",true);
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
    if(!displayInit())return;
    wifiSsid=prefs.getString("ssid","");
    makeUi();networkInit();
    expander(LCD_RESET|TP_RESET|BACKLIGHT); // EXIO5 stays LOW for native USB CDC.
    setNotice("LumaCut Control OS. Nur Laborbetrieb bis Hardware und Interlocks geprüft.");
}
}
void setup(){internalInit();}
void loop(){
    http.handleClient();
    bridgeService();
    internalJobService();
    bleUpdate();
    lv_timer_handler();
    // Collect actual GRBL persistent limits and axis polarity once controller is
    // available; do not fabricate travel distances from the nominal frame size.
    if(!settingsRequested&&millis()>4500&&idle()&&owner==Owner::None){
        settingsRequested=true;
        String cmds[]={"$"};startScript(cmds,1);
    }
    static uint32_t lastUi=0;
    if(millis()-lastUi>160){lastUi=millis();updateUi();}
    delay(2);
}
#endif
