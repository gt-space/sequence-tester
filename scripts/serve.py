import http.server
import mimetypes
import sys

# Ensure correct MIME types on all platforms (especially Windows)
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/json", ".json")

class DevHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Disable caching during local development to avoid stale 304s
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

def run(port=8000):
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), DevHandler)
    print(f"Serving HTTP on port {port} (http://localhost:{port}/) ...", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run(port)
