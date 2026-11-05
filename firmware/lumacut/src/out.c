#include "out.h"
#include "hal.h"
#include <string.h>

void out_str(const char *s) { hal_usb_write(s, strlen(s)); }

void out_u32(uint32_t v)
{
    char buf[11];
    int i = sizeof buf;
    do {
        buf[--i] = (char)('0' + v % 10u);
        v /= 10u;
    } while (v);
    hal_usb_write(&buf[i], sizeof buf - (size_t)i);
}

void out_i32(int32_t v)
{
    if (v < 0) {
        hal_usb_write("-", 1);
        out_u32(0u - (uint32_t)v);
    } else {
        out_u32((uint32_t)v);
    }
}

void out_hex(uint32_t v)
{
    static const char digits[] = "0123456789ABCDEF";
    char buf[10] = {'0', 'x'};
    for (int i = 0; i < 8; i++) buf[2 + i] = digits[(v >> (28 - 4 * i)) & 15u];
    hal_usb_write(buf, sizeof buf);
}

void out_fix3(int32_t fix)
{
    int64_t thousandths = fix;
    bool neg = thousandths < 0;
    if (neg) thousandths = -thousandths;
    thousandths = (thousandths + 50) / 100;
    if (neg && thousandths) hal_usb_write("-", 1);
    out_u32((uint32_t)(thousandths / 1000));
    uint32_t frac = (uint32_t)(thousandths % 1000);
    char buf[4] = {'.', (char)('0' + frac / 100u), (char)('0' + frac / 10u % 10u),
                   (char)('0' + frac % 10u)};
    hal_usb_write(buf, sizeof buf);
}

void out_nl(void) { hal_usb_write("\n", 1); }
