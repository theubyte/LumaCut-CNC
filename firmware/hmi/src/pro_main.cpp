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
#include <SPIFFS.h>
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
constexpr uint32_t WIFI_TCP_PORT=23, STATUS_INTERVAL=950, ARM_DURATION=30000;
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
lv_obj_t* pages[5]{};
lv_obj_t* navButtons[5]{};
lv_obj_t *statusLabel=nullptr,*positionLabel=nullptr,*messageLabel=nullptr,
*sourceLabel=nullptr,*jobLabel=nullptr,*ipLabel=nullptr,*ssidEntry=nullptr,
*passwordEntry=nullptr,*keyboard=nullptr,*macroLabel=nullptr,*macroEntry=nullptr;
int activePage=0,parkSlot=0;
constexpr uint32_t INK=0x1C2738,SUBTLE=0x748195,BG=0xF5F7FA,WHITE=0xFFFFFF;
constexpr uint32_t BLUE=0x007AFF,PALE_BLUE=0xE6F2FF,GRAY=0xF0F3F8,RED=0xCE3550;

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
                x=nx;y=ny;result->point.x=x;result->point.y=y;
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
    const int pins[]={14,38,18,17,10,39,0,45,48,47,21,1,2,42,41,40};
    for(int i=0;i<16;i++)cfg.data_gpio_nums[i]=pins[i];
    if(esp_lcd_new_rgb_panel(&cfg,&lcd)!=ESP_OK)return false;
    if(esp_lcd_panel_reset(lcd)!=ESP_OK||esp_lcd_panel_init(lcd)!=ESP_OK)return false;
    lv_init();
    drawPixels=(lv_color_t*)heap_caps_malloc(W*16*sizeof(lv_color_t),MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
    if(!drawPixels)return false;
    lv_disp_draw_buf_init(&draw,drawPixels,nullptr,W*16);
    lv_disp_drv_init(&disp);disp.hor_res=W;disp.ver_res=H;disp.draw_buf=&draw;
    disp.flush_cb=displayFlush;lv_disp_drv_register(&disp);
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
bool canCommand(){return owner==Owner::None&&idle()&&machineHomed&&armed();}
void setNotice(const String& s){notice=s;if(messageLabel)lv_label_set_text(messageLabel,notice.c_str());}
void updateUi(){
    if(statusLabel)lv_label_set_text_fmt(statusLabel,"%s  %s",fresh()?stateText():"Verbindung fehlt",armed()?"· Freigegeben":"");
    if(positionLabel) {
        if(fresh()&&haveMpos)lv_label_set_text_fmt(positionLabel,"X %.2f   Y %.2f   Z %.2f",mx,my,mz);
        else lv_label_set_text(positionLabel,"X --.--   Y --.--   Z --.--");
    }
    if(sourceLabel)lv_label_set_text(sourceLabel,ownerText());
    if(jobLabel){
        String t=selectedJob.length()?"Datei: "+selectedJob:"Noch keine Datei ausgewählt";
        if(bounds.valid)t+="  ·  "+String(bounds.x1-bounds.x0,1)+" × "+String(bounds.y1-bounds.y0,1)+" mm";
        lv_label_set_text(jobLabel,t.c_str());
    }
    if(macroLabel)lv_label_set_text(macroLabel,parks[parkSlot].stored?parks[parkSlot].name.c_str():"Freier Makroplatz");
    if(ipLabel){
        String s="WLAN: "+(WiFi.status()==WL_CONNECTED?WiFi.localIP().toString():String("nicht verbunden"))+
        "\nHotspot: "+apName+"  /  "+apPass+
        "\nApp: http://"+WiFi.softAPIP().toString()+
        "\nZugangscode: "+apiKey;
        lv_label_set_text(ipLabel,s.c_str());
    }
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
            else{machineHomed=false;setNotice("Referenzfahrt fehlgeschlagen: "+line);}
            homingInProgress=false;
        }
        if((owner==Owner::Script)&&commandPending){
            commandPending=false;
            if(ok)nextScript();
            else{scriptActive=false;scriptCount=0;owner=Owner::None;setNotice("Makro gestoppt: "+line);}
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
    if(owner!=Owner::Internal||!jobRunning||jobPaused||commandPending)return;
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
    jobFile=SPIFFS.open("/jobs/"+selectedJob,FILE_READ);
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
    if(!canCommand()||!haveMpos){setNotice("Speichern nur mit Referenzfahrt und lokaler Freigabe.");return;}
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
    File f=SPIFFS.open("/jobs/"+selectedJob,FILE_READ);
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
    if(!storageOk||!SPIFFS.exists("/jobs/"+name))return false;
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
            File root=SPIFFS.open("/jobs");
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
            uploadAllowed=auth()&&storageOk&&owner==Owner::None;
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
            if(uploadAllowed&&SPIFFS.exists(uploadDestination))uploadAllowed=false;
            if(uploadAllowed){
                SPIFFS.remove(uploadTemporary);
                uploadFile=SPIFFS.open(uploadTemporary,FILE_WRITE);
                if(!uploadFile)uploadAllowed=false;
            }
        } else if(up.status==UPLOAD_FILE_WRITE && uploadAllowed){
            uploadBytes+=up.currentSize;
            if(uploadBytes>MAX_JOB_BYTES||uploadFile.write(up.buf,up.currentSize)!=up.currentSize){
                uploadAllowed=false;uploadFile.close();
                if(uploadTemporary.length())SPIFFS.remove(uploadTemporary);
            }
        } else if(up.status==UPLOAD_FILE_END){
            if(uploadFile)uploadFile.close();
            if(uploadAllowed&&uploadBytes>0&&uploadTemporary.length()&&uploadDestination.length()&&
               !SPIFFS.exists(uploadDestination)){
                uploadFinished=SPIFFS.rename(uploadTemporary,uploadDestination);
            }
            if(!uploadFinished&&uploadTemporary.length())SPIFFS.remove(uploadTemporary);
            uploadAllowed=uploadFinished;
        } else if(up.status==UPLOAD_FILE_ABORTED){
            if(uploadFile)uploadFile.close();
            if(uploadTemporary.length())SPIFFS.remove(uploadTemporary);
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
    lv_obj_t* p=lv_label_create(parent);lv_label_set_text(p,text.c_str());
    lv_obj_set_pos(p,x,y);lv_obj_set_style_text_color(p,lv_color_hex(color),0);
    if(px>=28)lv_obj_set_style_text_font(p,&lv_font_montserrat_28,0);
    else if(px>=20)lv_obj_set_style_text_font(p,&lv_font_montserrat_20,0);
    else lv_obj_set_style_text_font(p,&lv_font_montserrat_14,0);
    return p;
}
lv_obj_t* card(lv_obj_t* parent,int x,int y,int w,int h){
    lv_obj_t* p=lv_obj_create(parent);lv_obj_set_pos(p,x,y);lv_obj_set_size(p,w,h);
    lv_obj_set_style_radius(p,21,0);lv_obj_set_style_bg_color(p,lv_color_hex(WHITE),0);
    lv_obj_set_style_border_width(p,1,0);lv_obj_set_style_border_color(p,lv_color_hex(0xE7ECF1),0);
    lv_obj_set_style_pad_all(p,0,0);lv_obj_clear_flag(p,LV_OBJ_FLAG_SCROLLABLE);
    return p;
}
void action(const char* id);
void actionCb(lv_event_t* e){action((const char*)lv_event_get_user_data(e));}
lv_obj_t* btn(lv_obj_t* parent,const char* text,int x,int y,int w,int h,const char* op,uint32_t bg=GRAY,uint32_t fg=INK){
    lv_obj_t* p=lv_btn_create(parent);lv_obj_set_pos(p,x,y);lv_obj_set_size(p,w,h);
    lv_obj_set_style_radius(p,14,0);lv_obj_set_style_bg_color(p,lv_color_hex(bg),0);
    lv_obj_set_style_shadow_width(p,0,0);
    if(op)lv_obj_add_event_cb(p,actionCb,LV_EVENT_CLICKED,(void*)op);
    lv_obj_t* t=lv_label_create(p);lv_label_set_text(t,text);lv_obj_center(t);
    lv_obj_set_style_text_color(t,lv_color_hex(fg),0);lv_obj_set_style_text_font(t,&lv_font_montserrat_14,0);
    return p;
}
void switchTab(int idx){
    activePage=idx;
    for(int i=0;i<5;i++){
        if(i==idx)lv_obj_clear_flag(pages[i],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(pages[i],LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(navButtons[i],lv_color_hex(i==idx?PALE_BLUE:WHITE),0);
    }
    updateUi();
}
void navCb(lv_event_t* e){switchTab((int)(uintptr_t)lv_event_get_user_data(e));}
void makeUi(){
    lv_obj_t* root=lv_scr_act();
    lv_obj_clear_flag(root,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(root,lv_color_hex(BG),0);
    lbl(root,"LumaCut",22,11,28);lbl(root,"CONTROL OS",173,22,14,BLUE);
    statusLabel=lbl(root,"Initialisiere…",450,17,14,BLUE);
    positionLabel=lbl(root,"X --  Y --  Z --",24,62,20);
    sourceLabel=lbl(root,"Verbindung frei",540,68,14,SUBTLE);
    for(int i=0;i<5;i++){
        pages[i]=lv_obj_create(root);lv_obj_set_pos(pages[i],14,104);
        lv_obj_set_size(pages[i],772,286);lv_obj_set_style_bg_opa(pages[i],LV_OPA_TRANSP,0);
        lv_obj_set_style_border_width(pages[i],0,0);lv_obj_set_style_pad_all(pages[i],0,0);
        lv_obj_clear_flag(pages[i],LV_OBJ_FLAG_SCROLLABLE);
    }
    lv_obj_t* c=card(pages[0],0,0,458,266);
    lbl(c,"Maschinenübersicht",21,20,20);
    lbl(c,"Intelligente Lasersteuerung",21,51,14,SUBTLE);
    btn(c,"Referenzfahrt",20,95,192,48,"home");
    btn(c,"Lokale Freigabe",226,95,209,48,"arm",PALE_BLUE,BLUE);
    btn(c,"Start",20,159,131,51,"start",BLUE,WHITE);
    btn(c,"Pause",163,159,130,51,"pause");
    btn(c,"Abbruch",305,159,130,51,"abort",0xFFEDF0,RED);
    lbl(c,"Verbindung & Bewegungen nur mit Statusfreigabe",21,238,14,SUBTLE);
    lv_obj_t* quick=card(pages[0],474,0,297,266);
    lbl(quick,"Schnellzugriff",19,20,20);
    btn(quick,"Rahmen trocken",19,68,258,49,"frame");
    btn(quick,"Parkposition",19,127,258,49,"park");
    btn(quick,"LightBurn WLAN erlauben",19,186,258,49,"host");
    c=card(pages[1],0,0,772,266);
    lbl(c,"Jobs & Dateien",22,19,20);
    jobLabel=lbl(c,"Noch keine Datei ausgewählt",22,54,14,SUBTLE);
    btn(c,"Nächste Datei",21,106,180,52,"next");
    btn(c,"Rahmen trocken",217,106,180,52,"frame");
    btn(c,"Job starten",413,106,176,52,"start",BLUE,WHITE);
    btn(c,"Pause / Weiter",605,106,145,52,"toggle");
    lbl(c,"Upload: Handy im WLAN mit dem HMI-Webportal verbinden.",22,210,14,SUBTLE);
    c=card(pages[2],0,0,772,266);
    lbl(c,"Manuelle Steuerung",21,17,20);
    lbl(c,"Nur referenziert und lokal freigegeben",21,50,14,SUBTLE);
    btn(c,"Y+",315,62,126,52,"y+");
    btn(c,"X-",176,126,126,52,"x-");
    btn(c,"X+",454,126,126,52,"x+");
    btn(c,"Y-",315,190,126,52,"y-");
    btn(c,"Z+",604,62,125,52,"z+");
    btn(c,"Z-",604,126,125,52,"z-");
    btn(c,"0,1 / 1 / 10 mm",18,190,250,52,"step");
    c=card(pages[3],0,0,772,266);
    lbl(c,"Meine Parkpositionen",21,15,20);
    lbl(c,"Eigene Makros per Position speichern",21,48,14,SUBTLE);
    btn(c,"Position 1",21,92,231,45,"p0");
    btn(c,"Position 2",270,92,231,45,"p1");
    btn(c,"Position 3",519,92,230,45,"p2");
    macroLabel=lbl(c,"Position 1",21,153,20);
    macroEntry=lv_textarea_create(c);lv_obj_set_pos(macroEntry,209,143);
    lv_obj_set_size(macroEntry,278,43);
    lv_textarea_set_one_line(macroEntry,true);lv_textarea_set_max_length(macroEntry,24);
    lv_textarea_set_text(macroEntry,parks[parkSlot].name.c_str());
    btn(c,"Namen speichern",499,143,250,43,"rename",PALE_BLUE,BLUE);
    btn(c,"Aktuelle XY sichern",21,197,334,47,"capture",PALE_BLUE,BLUE);
    btn(c,"Anfahren",372,197,377,47,"park");
    c=card(pages[4],0,0,772,266);
    lbl(c,"Netzwerk & Geräte",21,14,20);
    ipLabel=lbl(c,"Netzwerk startet...",21,53,14,SUBTLE);
    lbl(c,"WLAN-Name",415,32,14,SUBTLE);
    ssidEntry=lv_textarea_create(c);lv_obj_set_pos(ssidEntry,415,54);lv_obj_set_size(ssidEntry,328,41);
    lv_textarea_set_one_line(ssidEntry,true);lv_textarea_set_text(ssidEntry,wifiSsid.c_str());
    lbl(c,"WLAN-Passwort",415,100,14,SUBTLE);
    passwordEntry=lv_textarea_create(c);lv_obj_set_pos(passwordEntry,415,124);lv_obj_set_size(passwordEntry,328,41);
    lv_textarea_set_one_line(passwordEntry,true);lv_textarea_set_password_mode(passwordEntry,true);
    btn(c,"WLAN verbinden",415,185,328,51,"wifi",PALE_BLUE,BLUE);
    const char* tabs[]={"Home","Jobs","Steuerung","Makros","System"};
    lv_obj_t* dock=card(root,14,400,772,64);lv_obj_set_style_radius(dock,25,0);
    for(int i=0;i<5;i++){
        navButtons[i]=btn(dock,tabs[i],8+i*153,8,144,48,nullptr,WHITE,INK);
        lv_obj_add_event_cb(navButtons[i],navCb,LV_EVENT_CLICKED,(void*)(uintptr_t)i);
    }
    messageLabel=lbl(root,"Laser muss hardwareseitig abgesichert sein.",19,378,14,SUBTLE);
    keyboard=lv_keyboard_create(root);
    lv_obj_set_size(keyboard,772,246);lv_obj_set_pos(keyboard,14,134);
    lv_obj_add_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
    auto kb=(lv_event_cb_t)+[](lv_event_t* e){
        lv_event_code_t code=lv_event_get_code(e);
        if(code==LV_EVENT_READY||code==LV_EVENT_CANCEL){
            lv_obj_add_flag(keyboard,LV_OBJ_FLAG_HIDDEN);
        }
    };
    lv_obj_add_event_cb(keyboard,kb,LV_EVENT_READY,nullptr);
    lv_obj_add_event_cb(keyboard,kb,LV_EVENT_CANCEL,nullptr);
    auto showKeyboard=(lv_event_cb_t)+[](lv_event_t* e){
        lv_keyboard_set_textarea(keyboard,lv_event_get_target(e));
        lv_obj_clear_flag(keyboard,LV_OBJ_FLAG_HIDDEN);lv_obj_move_foreground(keyboard);
    };
    lv_obj_add_event_cb(ssidEntry,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    lv_obj_add_event_cb(passwordEntry,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    lv_obj_add_event_cb(macroEntry,showKeyboard,LV_EVENT_FOCUSED,nullptr);
    switchTab(0);
}
int jogStep=1;
void action(const char* id){
    String op=id;
    if(op=="arm"){
        if(!idle()||owner!=Owner::None||!machineHomed){setNotice("Nur nach Referenzfahrt im Leerlauf freigeben.");return;}
        localArmUntil=millis()+ARM_DURATION;
        setNotice("30 Sekunden lokal freigegeben. Vor jeder Bewegung Fahrweg prüfen.");return;
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
        if(owner!=Owner::None||!fresh()||(machineState!=MachineState::Idle&&machineState!=MachineState::Alarm)){
            setNotice("Referenzfahrt nur ohne aktiven Host bei Idle/Alarm.");return;
        }
        if(claim(Owner::Script)){
            String cmds[]={"$H"};script[0]=cmds[0];scriptCount=1;scriptIndex=0;scriptActive=true;
            homingInProgress=true;nextScript();setNotice("Referenzfahrt ausgelöst.");
        }return;
    }
    if(op=="start"){if(!jobStart())setNotice("Start gesperrt: Idle, Home, Freigabe und gewählter Job erforderlich.");return;}
    if(op=="frame"){if(!dryFrame())setNotice("Trockenrahmen gesperrt oder Dateigrenzen unbekannt.");return;}
    if(op=="park"){if(!runPark())setNotice("Parken erst nach Home, lokaler Freigabe und gespeichertem Makro.");return;}
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
        File dir=SPIFFS.open("/jobs");File f=dir.openNextFile();
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
        if(!startScript(cmds,1))setNotice("Jog gesperrt: Maschine muss Idle, referenziert und lokal freigegeben sein.");
        return;
    }
}
void internalInit(){
    prefs.begin("lumacut",false);
    storageOk=SPIFFS.begin(true);
    if(storageOk&&!SPIFFS.exists("/jobs"))SPIFFS.mkdir("/jobs");
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
    static uint32_t lastUi=0;
    if(millis()-lastUi>600){lastUi=millis();updateUi();}
    delay(2);
}
#endif
