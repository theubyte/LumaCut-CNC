// Command layer: answers lines, enforces the safety rules, runs from the main loop.
#pragma once
#include <stdbool.h>
#include <stdint.h>

void cmd_init(void);
void cmd_poll(void); // one main-loop pass

// USB interrupt: the host link went away (DTR, bus reset, suspend).
void cmd_rt_link_lost(void);

void cmd_reply_ok(void);
