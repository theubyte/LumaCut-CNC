#pragma once
// LumaCut tool-centre versus switch-tip coordinates.
// All coordinates are in the HMI's POSITIVE operator frame, not raw GRBL MPos.
// probeX = laserX + offsetX; probeY = laserY + offsetY.
// The actual carriage position must remain inside the measured XYZ envelope.
#include <math.h>
#include <stdint.h>
namespace LumaProbe {
struct Region { float x, y, width, height, pitch, offsetX, offsetY; };
struct Plan { float x0, y0, x1, y1; uint32_t nx, ny; bool clipped; };
inline bool finite(float x) { return isfinite(x); }
inline bool clip(const Region& r,float travelX,float travelY,
                 float margin,Plan& out) {
    out={};
    if(!finite(r.x)||!finite(r.y)||!finite(r.width)||!finite(r.height)||
       !finite(r.pitch)||!finite(r.offsetX)||!finite(r.offsetY)||
       !finite(travelX)||!finite(travelY)||
       r.width<=0.f||r.height<=0.f||r.pitch<=0.f||
       travelX<=2.f*margin||travelY<=2.f*margin) return false;
    // Only the intersection of requested material and physically reachable
    // switch-tip positions is rasterized. No out-of-bounds points are emitted.
    out.x0=fmaxf(r.x,fmaxf(0.f,margin+r.offsetX));
    out.x1=fminf(r.x+r.width,fminf(travelX,travelX-margin+r.offsetX));
    out.y0=fmaxf(r.y,fmaxf(0.f,margin+r.offsetY));
    out.y1=fminf(r.y+r.height,fminf(travelY,travelY-margin+r.offsetY));
    if(!finite(out.x0)||!finite(out.x1)||!finite(out.y0)||!finite(out.y1)||
       out.x1<=out.x0||out.y1<=out.y0)return false;
    // Check count BEFORE float-to-integer conversion (very small pitch).
    const double cx=double(out.x1-out.x0)/double(r.pitch);
    const double cy=double(out.y1-out.y0)/double(r.pitch);
    if(!isfinite(cx)||!isfinite(cy)||cx>99998.0||cy>99998.0)return false;
    out.nx=(uint32_t)ceil(cx)+1;
    out.ny=(uint32_t)ceil(cy)+1;
    if(out.nx<2||out.ny<2||out.nx>100000||out.ny>100000)return false;
    out.clipped=(out.x0>r.x+0.0001f||out.x1<r.x+r.width-0.0001f||
                 out.y0>r.y+0.0001f||out.y1<r.y+r.height-0.0001f);
    return true;
}
inline bool point(const Region& r,const Plan& p,uint32_t n,
                  float& switchX,float& switchY,
                  float& laserX,float& laserY) {
    if((uint64_t)n>=(uint64_t)p.nx*p.ny)return false;
    const uint32_t row=n/p.nx;
    const uint32_t column=n%p.nx;
    const uint32_t idx=row&1?(p.nx-1-column):column; // serpentine
    switchX=idx==p.nx-1?p.x1:fminf(p.x1,p.x0+idx*r.pitch);
    switchY=row==p.ny-1?p.y1:fminf(p.y1,p.y0+row*r.pitch);
    laserX=switchX-r.offsetX;
    laserY=switchY-r.offsetY;
    return laserX>=0.f&&laserY>=0.f;
}
}
