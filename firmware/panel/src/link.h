// Link to the Pi over the native USB of the ESP32-S3 (JSON lines, see pi400/marlin/panel.py).
#pragma once

void link_start(void);
// {"t":"act","id":n,"op":op,<key>:<value>...}; key/value strings, NULL-terminated. Returns n.
int link_act(const char *op, ...);
// {"t":kind}: "jobs", "mats", "events" or "sys"; the answer arrives at ui_on_*.
void link_request(const char *kind);
