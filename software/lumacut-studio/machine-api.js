// LumaCut Studio – simple machine API client for the Pi 400 Marlin web service.
// Warum: Erlaubt dem eigenen Windows-Studio, Status, Homing und Jobs direkt
// über die bestehende Pi-API zu steuern, ohne auf LightBurn angewiesen zu sein.
// Die API erwartet den Zugangsschlüssel aus /etc/lumacut/lumacut.env (X-LumaCut-Key).

class LumaCutMachine {
  constructor(baseUrl = "http://lumacut.local:8080", key = "") {
    this.base = baseUrl.replace(/\/$/, "");
    this.key = key;
  }

  async _req(path, options = {}) {
    const headers = { "X-LumaCut-Key": this.key, ...(options.headers || {}) };
    const res = await fetch(this.base + path, { ...options, headers });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json();
  }

  status() { return this._req("/api/status"); }
  home() { return this._req("/api/action", { method: "POST", body: new URLSearchParams({ op: "home" }) }); }
  jog(axis, distance) {
    return this._req("/api/action", {
      method: "POST",
      body: new URLSearchParams({ op: "jog", axis, distance: String(distance) })
    });
  }
  uploadJob(filename, gcode) {
    const form = new FormData();
    form.append("file", new Blob([gcode], { type: "text/plain" }), filename);
    return this._req("/api/upload", { method: "POST", body: form });
  }
  startJob(name) {
    return this._req("/api/action", {
      method: "POST",
      body: new URLSearchParams({ op: "start", name })
    });
  }
}

if (typeof module !== "undefined") module.exports = { LumaCutMachine };
