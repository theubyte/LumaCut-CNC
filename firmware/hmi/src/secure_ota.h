#pragma once
// LumaCut HMI update transport (ESP32-S3 only).
// Download is pinned to the operator's HTTPS server; neither a JSON URL nor
// a redirect may change the origin. A complete SHA-256 match precedes boot
// partition selection. The attached laser must be physically powered off.
#include <Arduino.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>

namespace LumaOta {
static constexpr const char* IMAGE_URL="https://luma.millione.de/api/updates/file/hmi";

inline bool isHex(const String& s, size_t count) {
    if(s.length()!=count)return false;
    for(size_t i=0;i<count;++i) {
        const char c=s[i];
        if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
    }
    return true;
}
inline bool available() {
    const esp_partition_t* running=esp_ota_get_running_partition();
    const esp_partition_t* target=esp_ota_get_next_update_partition(nullptr);
    return running && target && target!=running;
}
inline bool install(const String& expectedSha,const size_t bytes,
                    const String& deviceKey,const char* ca,String& error) {
    if(!available()) {error="Keine zweite OTA-Partition";return false;}
    const esp_partition_t* target=esp_ota_get_next_update_partition(nullptr);
    if(!isHex(expectedSha,64)||!isHex(deviceKey,64)||
       bytes<65536||bytes>target->size) {
        error="OTA-Manifest/Geraeteschluessel ungueltig";return false;
    }
    WiFiClientSecure client;
    client.setCACert(ca);
    client.setTimeout(15);
    HTTPClient http;
    http.setConnectTimeout(5000);
    http.setTimeout(15000);
    http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    if(!http.begin(client,IMAGE_URL)){error="HTTPS-Start gescheitert";return false;}
    http.addHeader("X-LumaCut-Device-Key",deviceKey);
    const int status=http.GET();
    if(status!=200){error="OTA-Download HTTP "+String(status);http.end();return false;}
    if(http.getSize()!=(int)bytes){
        error="Firmware-Dateilaenge stimmt nicht";http.end();return false;
    }
    if(!Update.begin(bytes,U_FLASH)) {
        error="OTA-Partition konnte nicht geoeffnet werden";http.end();return false;
    }
    mbedtls_sha256_context digest;
    mbedtls_sha256_init(&digest);
#if MBEDTLS_VERSION_MAJOR >= 3
    int hashError=mbedtls_sha256_starts(&digest,0);
#else
    int hashError=mbedtls_sha256_starts_ret(&digest,0);
#endif
    if(hashError!=0) {
        mbedtls_sha256_free(&digest);Update.abort();http.end();
        error="SHA-256-Initialisierung fehlgeschlagen";return false;
    }
    WiFiClient* stream=http.getStreamPtr();
    uint8_t buffer[2048];
    size_t done=0;
    uint32_t lastData=millis();
    bool ok=true;
    while(done<bytes){
        const int avail=stream->available();
        if(avail<=0){
            if(!http.connected()||(uint32_t)(millis()-lastData)>15000u){
                error="Firmware-Download abgebrochen";ok=false;break;
            }
            delay(1);continue;
        }
        const size_t wanted=min((size_t)avail,min(sizeof(buffer),bytes-done));
        const size_t got=stream->readBytes(buffer,wanted);
        if(got==0){error="Fehler beim Empfang";ok=false;break;}
#if MBEDTLS_VERSION_MAJOR >= 3
        hashError=mbedtls_sha256_update(&digest,buffer,got);
#else
        hashError=mbedtls_sha256_update_ret(&digest,buffer,got);
#endif
        if(hashError!=0||Update.write(buffer,got)!=got){
            error="SHA-256/Flash-Schreibfehler";ok=false;break;
        }
        done+=got;lastData=millis();
        delay(0);
    }
    unsigned char sha[32]{};
    if(ok){
#if MBEDTLS_VERSION_MAJOR >= 3
        hashError=mbedtls_sha256_finish(&digest,sha);
#else
        hashError=mbedtls_sha256_finish_ret(&digest,sha);
#endif
        if(hashError!=0){error="SHA-256-Abschluss fehlgeschlagen";ok=false;}
    }
    mbedtls_sha256_free(&digest);
    http.end();
    if(ok) {
        char textSha[65]{};
        for(size_t i=0;i<32;i++)sprintf(textSha+i*2,"%02x",sha[i]);
        if(expectedSha!=String(textSha)){error="SHA-256-Pruefsumme falsch";ok=false;}
    }
    if(!ok){Update.abort();return false;}
    if(!Update.end(false)){
        error="ESP32-OTA-Abschluss fehlgeschlagen";Update.abort();return false;
    }
    return true;
}
inline bool restorePrior(const String& label) {
    if(label.length()==0 || label.length()>15)return false;
    const esp_partition_t* previous=esp_partition_find_first(
        ESP_PARTITION_TYPE_APP,ESP_PARTITION_SUBTYPE_ANY,label.c_str());
    return previous && esp_ota_set_boot_partition(previous)==ESP_OK;
}
}
