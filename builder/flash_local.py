"""Serve the downloaded HMI flash package on loopback for Web Serial.

http://127.0.0.1 is a browser secure context. No network or serial device
on the Unraid builder is needed; the user explicitly picks the USB port.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

ROOT = Path(__file__).resolve().parent
ROUTES = {
    "/": ("flash_ui.html", "text/html; charset=utf-8"),
    "/manifest.json": ("manifest.json", "application/json"),
    "/firmware.bin": ("firmware.bin", "application/octet-stream"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route not in ROUTES:
            self.send_error(404)
            return
        filename, mime = ROUTES[route]
        path = ROOT / filename
        if not path.is_file():
            self.send_error(404, "Datei fehlt: " + filename)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print("LumaCut Waveshare HMI Flasher:", url)
        print("Nur Chrome/Edge mit USB-Verbindung zum Waveshare verwenden.")
        print("USB TO UART; UART1 zum Flashen. Nach Abschluss RESET druecken.")
        print("Dieses Fenster waehrend des Flashens geoeffnet lassen.")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
