#pragma once
// LumaCut GRBL 1.1/ grblHAL status ownership. This header is Arduino-free
// so the LightBurn stream policy can be regression-tested with native g++.
#include <stdint.h>
namespace LumaBridge {
class StatusGate {
    uint8_t hostPending_=0;
public:
    uint32_t hostStatusRequests=0;
    uint32_t hostStatusForwarded=0;
    uint32_t telemetrySuppressed=0;
    // Host-initiated '?' is the ONLY reason to echo a GRBL <...> report.
    // The HMI's own polling stays private to the dashboard.
    void hostByte(uint8_t value){
        if(value=='?'){
            hostStatusRequests++;
            if(hostPending_<32)hostPending_++;
        } else if(value==0x18)hostPending_=0;
    }
    bool forwardLine(const char* line, bool hostConnected){
        if(!hostConnected)return false;
        if(line[0]!='<')return true; // ok, error, ALARM, startup, $$ etc.
        if(hostPending_){
            --hostPending_;
            hostStatusForwarded++;
            return true;
        }
        telemetrySuppressed++;
        return false;
    }
    void disconnect(){hostPending_=0;}
    bool waitingHostStatus() const {return hostPending_!=0;}
};
}
