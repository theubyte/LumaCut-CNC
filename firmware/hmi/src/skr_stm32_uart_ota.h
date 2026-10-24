#pragma once
// LumaCut SKR Mini MZ v1.0 STM32F103RC updater (ROM USART1, AN3155).
//
// Wiring is described in docs/SKR_AUTOMATIC_UPDATE.md. PCA9685 at 0x40
// controls BOOT0 and NRST through a transistor; never connect reset to a
// push-pull output. UART wiring is the existing 3.3 V HMI<->SKR pair.
//
// Hard boundary: erase begins at 0x08007000 (28 KiB SKR SD bootloader).
// No mass erase, no writes to option bytes, and no reset to ROM without the
// PCA9685 being detected. The uploaded image is SHA-256 verified and then
// every programmed block is read back before the board is rebooted.
#include <Arduino.h>
#include <HardwareSerial.h>
#include <Wire.h>
#include <FS.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>

namespace SkrUpdate {
static constexpr uint32_t FLASH_BASE=0x08000000UL;
static constexpr uint32_t APP_BASE=0x08007000UL; // exact SKR BL28K linker offset
static constexpr uint32_t FLASH_END=0x08040000UL; // STM32F103RC 256 KiB
static constexpr uint16_t PAGE_BYTES=2048;
static constexpr uint16_t FIRST_PAGE=14;
static constexpr size_t MAX_IMAGE=FLASH_END-APP_BASE;
static constexpr uint8_t PCA_ADDR=0x40; // no CH422G or GT911 address collision
static constexpr uint8_t ACK=0x79;
static constexpr uint8_t GET_ID=0x02;
static constexpr uint8_t READ_MEMORY=0x11;
static constexpr uint8_t WRITE_MEMORY=0x31;
static constexpr uint8_t ERASE=0x43;
static constexpr uint8_t EXTENDED_ERASE=0x44;
static constexpr uint16_t STM32F103_HIGH_DENSITY_ID=0x0414;
static constexpr const char* SKR_URL="https://luma.millione.de/api/updates/file/skr";
static constexpr const char* STAGING="/updates/skr-staged.bin";
static constexpr const char* PARTIAL="/updates/skr-staged.part";
using Progress=void (*)(const char* stage,uint32_t done,uint32_t total);
inline void progress(Progress cb,const char* stage,uint32_t done=0,uint32_t total=0) {
    if(cb)cb(stage,done,total);
    delay(0);
}
inline bool sha256Start(mbedtls_sha256_context& ctx) {
#if MBEDTLS_VERSION_MAJOR >= 3
    return mbedtls_sha256_starts(&ctx,0)==0;
#else
    return mbedtls_sha256_starts_ret(&ctx,0)==0;
#endif
}
inline bool sha256Update(mbedtls_sha256_context& ctx,const uint8_t* data,size_t n) {
#if MBEDTLS_VERSION_MAJOR >= 3
    return mbedtls_sha256_update(&ctx,data,n)==0;
#else
    return mbedtls_sha256_update_ret(&ctx,data,n)==0;
#endif
}
inline bool sha256Finish(mbedtls_sha256_context& ctx,unsigned char result[32]) {
#if MBEDTLS_VERSION_MAJOR >= 3
    return mbedtls_sha256_finish(&ctx,result)==0;
#else
    return mbedtls_sha256_finish_ret(&ctx,result)==0;
#endif
}
inline bool hex64(const String& s) {
    if(s.length()!=64)return false;
    for(int i=0;i<64;i++){
        char c=s[i];
        if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
    }
    return true;
}
inline String hexDigest(const unsigned char data[32]){
    char out[65]{};
    for(int i=0;i<32;i++)snprintf(out+2*i,3,"%02x",data[i]);
    return String(out);
}
inline bool validVector(const uint8_t head[8],size_t size){
    uint32_t sp=uint32_t(head[0])|(uint32_t(head[1])<<8)|
                (uint32_t(head[2])<<16)|(uint32_t(head[3])<<24);
    uint32_t reset=uint32_t(head[4])|(uint32_t(head[5])<<8)|
                   (uint32_t(head[6])<<16)|(uint32_t(head[7])<<24);
    // Cortex-M Thumb reset handler and SRAM stack, no arbitrary flash payload.
    return (sp>=0x20000000UL && sp<=0x20010000UL && (sp&3)==0 &&
            (reset&1) && ((reset&~1UL)>=APP_BASE) &&
            ((reset&~1UL)<APP_BASE+size));
}
inline bool fetchVerified(fs::FS& fs,const String& key,const String& expected,
                          size_t bytes,const char* ca,String& err,Progress cb=nullptr){
    if(!hex64(expected)||!hex64(key)||bytes<1024||bytes>MAX_IMAGE){
        err="Manifest/Schluessel/Dateilaenge ungueltig";return false;
    }
    if(!fs.exists("/updates")&&!fs.mkdir("/updates")){
        err="Kein Update-Verzeichnis auf Speicher";return false;
    }
    fs.remove(PARTIAL);
    File out=fs.open(PARTIAL,FILE_WRITE);
    if(!out){err="Update-Speicher voll oder schreibgeschuetzt";return false;}
    WiFiClientSecure tls;
    tls.setCACert(ca);
    tls.setTimeout(15);
    HTTPClient http;
    http.setConnectTimeout(5000);
    http.setTimeout(15000);
    http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    if(!http.begin(tls,SKR_URL)){
        out.close();fs.remove(PARTIAL);err="HTTPS-Start gescheitert";return false;
    }
    http.addHeader("X-LumaCut-Device-Key",key);
    const int status=http.GET();
    if(status!=200 || http.getSize()!=(int)bytes){
        err="SKR-Firmware HTTP "+String(status)+" / Laenge ungueltig";
        http.end();out.close();fs.remove(PARTIAL);return false;
    }
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    if(!sha256Start(ctx)){
        mbedtls_sha256_free(&ctx);http.end();out.close();fs.remove(PARTIAL);
        err="SHA256 Start fehlgeschlagen";return false;
    }
    WiFiClient* stream=http.getStreamPtr();
    uint8_t buf[1024],head[8]{};
    size_t done=0;
    uint32_t last=millis();
    bool ok=true;
    progress(cb,"SKR-Download",0,bytes);
    while(done<bytes){
        int avail=stream->available();
        if(avail<=0){
            if(!http.connected()||(uint32_t)(millis()-last)>15000u){
                err="Download unterbrochen";ok=false;break;
            }
            delay(1);continue;
        }
        size_t want=min((size_t)avail,min(sizeof(buf),bytes-done));
        size_t got=stream->readBytes(buf,want);
        if(!got){err="Lesefehler am HTTPS-Stream";ok=false;break;}
        for(size_t i=0;i<got && done+i<8;i++)head[done+i]=buf[i];
        if(!sha256Update(ctx,buf,got)||out.write(buf,got)!=got){
            err="Schreibfehler oder SHA256 Fehler";ok=false;break;
        }
        done+=got;last=millis();
        progress(cb,"SKR-Download",done,bytes);
    }
    unsigned char digest[32]{};
    if(ok&&!sha256Finish(ctx,digest)){err="SHA256-Abschluss fehlgeschlagen";ok=false;}
    mbedtls_sha256_free(&ctx);
    http.end();
    out.flush();out.close();
    if(ok && (done!=bytes||hexDigest(digest)!=expected)){
        err="SKR-Firmware SHA256 stimmt nicht";ok=false;
    }
    if(ok && !validVector(head,bytes)){
        err="SKR-Firmware hat keine gueltigen Cortex-M Vektoren";ok=false;
    }
    if(!ok){fs.remove(PARTIAL);return false;}
    fs.remove(STAGING);
    if(!fs.rename(PARTIAL,STAGING)){
        fs.remove(PARTIAL);err="Staging-Umbenennung fehlgeschlagen";return false;
    }
    progress(cb,"SKR-Datei geprueft",bytes,bytes);
    return true;
}

// PCA9685 reset outputs default low; BOOT0 also has a physical 10k pulldown.
// Output 1 drives an NPN base; transistor shorts NRST to GND only when HIGH.
// The module MUST be powered from HMI 3.3 V, not servo V+ 5 V.
class ResetControl {
public:
    bool writeReg(uint8_t reg,uint8_t value){
        Wire.beginTransmission(PCA_ADDR);
        Wire.write(reg);Wire.write(value);
        return Wire.endTransmission()==0;
    }
    bool output(uint8_t channel,bool high){
        // MODE1 AutoIncrement must be active for sequential writes.
        const uint8_t reg=0x06+4*channel;
        Wire.beginTransmission(PCA_ADDR);
        Wire.write(reg);
        Wire.write((uint8_t)0);
        Wire.write((uint8_t)(high?0x10:0)); // full ON bit
        Wire.write((uint8_t)0);
        Wire.write((uint8_t)(high?0:0x10)); // full OFF bit
        return Wire.endTransmission()==0;
    }
    bool begin(){
        Wire.beginTransmission(PCA_ADDR);
        if(Wire.endTransmission()!=0)return false;
        // Avoid output glitches: force BOTH channels low before changing mode.
        if(!writeReg(0x00,0x21))return false; // MODE1 AI + ALLCALL
        if(!writeReg(0x01,0x04))return false; // MODE2 totem-pole
        return output(0,false)&&output(1,false);
    }
    bool enter(){
        if(!output(0,true))return false; // BOOT0 HIGH
        delay(25);
        if(!output(1,true))return false; // RESET active through NPN
        delay(110);
        if(!output(1,false))return false;
        delay(300);
        return true;
    }
    void runApplication(){
        // Release BOOT0 before reset; no I2C expander state is left asserted.
        output(0,false);
        delay(20);
        if(output(1,true)){
            delay(100);
            output(1,false);
        }
        delay(250);
    }
};

// AN3155 framing, entirely independent from the normal 8N1 GRBL session.
class Rom {
    HardwareSerial& serial;
public:
    explicit Rom(HardwareSerial& s):serial(s){}
    bool byte(uint8_t& value,uint32_t timeoutMs=1600){
        uint32_t started=millis();
        while((uint32_t)(millis()-started)<timeoutMs){
            if(serial.available()>0){value=(uint8_t)serial.read();return true;}
            delay(1);
        }
        return false;
    }
    bool ack(uint32_t timeoutMs=1800){
        uint8_t b=0;
        return byte(b,timeoutMs)&&b==ACK;
    }
    bool begin(){
        while(serial.available())serial.read();
        serial.write((uint8_t)0x7f); serial.flush();
        return ack(2000);
    }
    bool command(uint8_t cmd){
        uint8_t data[]={cmd,(uint8_t)~cmd};
        serial.write(data,sizeof(data));serial.flush();
        return ack();
    }
    bool address(uint32_t at){
        uint8_t b[5]={
            (uint8_t)(at>>24),(uint8_t)(at>>16),
            (uint8_t)(at>>8),(uint8_t)at,0
        };
        b[4]=b[0]^b[1]^b[2]^b[3];
        serial.write(b,sizeof(b));serial.flush();
        return ack();
    }
    bool chip(uint16_t& id){
        if(!command(GET_ID))return false;
        uint8_t n=0,hi=0,lo=0;
        if(!byte(n)||n!=1||!byte(hi)||!byte(lo)||!ack())return false;
        id=(uint16_t(hi)<<8)|lo;return true;
    }
    bool commands(bool& legacy,bool& extended){
        if(!command(0x00))return false;
        uint8_t n=0;
        if(!byte(n)||n<4||n>40)return false;
        uint8_t b=0;
        bool read=false,write=false;
        legacy=extended=false;
        for(unsigned i=0;i<=n;i++){
            if(!byte(b))return false;
            if(b==READ_MEMORY)read=true;
            if(b==WRITE_MEMORY)write=true;
            if(b==ERASE)legacy=true;
            if(b==EXTENDED_ERASE)extended=true;
        }
        return ack()&&read&&write&&(legacy||extended);
    }
    bool erasePages(uint16_t first,uint16_t count,bool extended){
        if(!count||first<FIRST_PAGE||first+count>128)return false;
        if(!command(extended?EXTENDED_ERASE:ERASE))return false;
        if(extended){
            uint8_t buf[260]{};
            size_t pos=0;
            const uint16_t n=count-1;
            buf[pos++]=(uint8_t)(n>>8);buf[pos++]=(uint8_t)n;
            uint8_t xorByte=buf[0]^buf[1];
            for(uint16_t i=0;i<count;i++){
                uint16_t page=first+i;
                buf[pos++]=(uint8_t)(page>>8);
                buf[pos++]=(uint8_t)page;
                xorByte^=(uint8_t)(page>>8)^(uint8_t)page;
            }
            buf[pos++]=xorByte;
            serial.write(buf,pos);serial.flush();
        }else{
            uint8_t buf[130]{};
            buf[0]=(uint8_t)(count-1);
            uint8_t x=buf[0];
            for(uint16_t i=0;i<count;i++){
                buf[i+1]=(uint8_t)(first+i);
                x^=buf[i+1];
            }
            buf[count+1]=x;
            serial.write(buf,count+2);serial.flush();
        }
        return ack(20000);
    }
    bool write(uint32_t at,const uint8_t* data,size_t n){
        if(n<4||n>256||n%4||at<APP_BASE||at+n>FLASH_END||at%4)return false;
        if(!command(WRITE_MEMORY)||!address(at))return false;
        uint8_t frame[258]{};
        frame[0]=(uint8_t)(n-1);
        uint8_t x=frame[0];
        for(size_t i=0;i<n;i++){frame[i+1]=data[i];x^=data[i];}
        frame[n+1]=x;
        serial.write(frame,n+2);serial.flush();
        return ack(3000);
    }
    bool read(uint32_t at,uint8_t* data,size_t n){
        if(!n||n>256||at<APP_BASE||at+n>FLASH_END)return false;
        if(!command(READ_MEMORY)||!address(at))return false;
        uint8_t length[]={ (uint8_t)(n-1),(uint8_t)~(n-1) };
        serial.write(length,sizeof(length));serial.flush();
        if(!ack())return false;
        for(size_t i=0;i<n;i++)if(!byte(data[i]))return false;
        return true;
    }
};
inline bool flashVerified(fs::FS& fs,HardwareSerial& uart,const String& expectedSha,
                          String& err,Progress cb=nullptr){
    File image=fs.open(STAGING,FILE_READ);
    if(!image){err="Verifizierte SKR-Datei fehlt";return false;}
    const size_t size=image.size();
    if(size<1024||size>MAX_IMAGE){
        image.close();err="SKR-Image ungueltige Groesse";return false;
    }
    uint8_t head[8]{};
    if(image.read(head,8)!=8||!validVector(head,size)){
        image.close();err="SKR-Image falsche Startvektoren";return false;
    }
    // Check staged bytes a second time before touching STM32 flash.
    // Power loss or card corruption between download and installation cannot
    // silently turn a previously authenticated image into arbitrary code.
    if(!hex64(expectedSha)){
        image.close();err="SHA256-Metadaten fehlen";return false;
    }
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    if(!sha256Start(ctx)){
        mbedtls_sha256_free(&ctx);image.close();
        err="Staging SHA256 Start fehlgeschlagen";return false;
    }
    uint8_t hashBuffer[1024];
    bool checksumOk=true;
    while(image.available()){
        size_t n=image.read(hashBuffer,sizeof(hashBuffer));
        if(!n||!sha256Update(ctx,hashBuffer,n)){checksumOk=false;break;}
        delay(0);
    }
    unsigned char staged[32]{};
    checksumOk=checksumOk&&sha256Finish(ctx,staged)&&
               hexDigest(staged)==expectedSha;
    mbedtls_sha256_free(&ctx);
    if(!checksumOk){
        image.close();err="Staging-Karte/Datei SHA256 fehlerhaft";return false;
    }
    image.seek(0);
    ResetControl reset;
    if(!reset.begin()){
        image.close();err="I2C Boot/Reset-Modul PCA9685 (0x40) nicht gefunden";return false;
    }
    // On exit, restore ordinary SKR boot pins even if sync/erase/write fails.
    progress(cb,"SKR-ROM vorbereiten");
    uart.end();
    uart.begin(115200,SERIAL_8E1,44,43);
    if(!reset.enter()){
        err="SKR BOOT0/RESET Schaltung antwortet nicht";
        reset.runApplication();uart.end();uart.begin(115200,SERIAL_8N1,44,43);
        image.close();return false;
    }
    Rom rom(uart);
    bool ok=false;
    do{
        if(!rom.begin()){err="STM32 ROM USART1 antwortet nicht (BOOT0/NRST/UART)";break;}
        uint16_t chip=0;
        if(!rom.chip(chip)||chip!=STM32F103_HIGH_DENSITY_ID){
            err="Falsches/unerkanntes STM32-Silizium (ID muss 0x0414 sein)";break;
        }
        bool legacy=false,extended=false;
        if(!rom.commands(legacy,extended)){
            err="STM32-ROM hat keine benoetigten Lese/Schreib/Erase Befehle";break;
        }
        const size_t totalPadded=(size+3)&~size_t(3);
        const uint16_t pages=(uint16_t)((totalPadded+PAGE_BYTES-1)/PAGE_BYTES);
        if(FIRST_PAGE+pages>128){
            err="Anwendungsimage wuerde ueber Flashgrenze reichen";break;
        }
        progress(cb,"SKR-App-Seiten loeschen",0,pages);
        // Keep the initial 14 bootloader pages (0..13) entirely unchanged.
        // Bounded pages; no mass erase, even if ROM supports that operation.
        if(!rom.erasePages(FIRST_PAGE,pages,extended)){
            err="STM32 konnte die Anwendungsseiten nicht loeschen";break;
        }
        progress(cb,"SKR schreiben+Ruecklesen",0,size);
        uint8_t written[256],returned[256];
        size_t offset=0;
        bool blockOk=true;
        while(offset<size){
            size_t actual=min(sizeof(written),size-offset);
            memset(written,0xff,sizeof(written));
            if(image.read(written,actual)!=actual){err="Staging-Lesefehler";blockOk=false;break;}
            size_t padded=(actual+3)&~size_t(3);
            uint32_t address=APP_BASE+offset;
            if(!rom.write(address,written,padded)||
               !rom.read(address,returned,padded)||
               memcmp(written,returned,padded)!=0){
                err="STM32 Schreib-/Ruecklese-Pruefung fehlgeschlagen bei "+
                    String(address,HEX);
                blockOk=false;break;
            }
            offset+=actual;
            progress(cb,"SKR schreiben+Ruecklesen",offset,size);
        }
        if(!blockOk)break;
        ok=true;
        progress(cb,"SKR-Image vollstaendig verifiziert",size,size);
    }while(false);
    // BOOT0 low; hardware reset into the existing 28-KiB SD bootloader,
    // which will then start the app at 0x08007000.
    reset.runApplication();
    uart.end();
    uart.begin(115200,SERIAL_8N1,44,43);
    image.close();
    return ok;
}
} // namespace SkrUpdate
