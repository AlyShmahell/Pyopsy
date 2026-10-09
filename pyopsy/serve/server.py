"""Serve the live page and a snapshot stream."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
}


class PageServer:
    """Serve the dashboard on the local host."""

    def __init__(self, host, port, latest):
        self.host = host
        self.port = port
        self.latest = latest
        self._httpd = None
        self._worker = None

    def start(self):
        """Start the HTTP server.

        The method returns the bound port.
        """
        handler = _make_handler(self.latest)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = self._httpd.server_address[1]
        self._worker = threading.Thread(
            target=self._httpd.serve_forever,
            name="pyopsy-http",
            daemon=True,
        )
        self._worker.start()
        return self.port

    def stop(self):
        """Stop the HTTP server."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None


def _make_handler(latest):
    """Build a request handler that reads the last snapshot."""

    class Handler(BaseHTTPRequestHandler):
        """Serve the page, the assets, and the snapshot stream."""

        def log_message(self, _format, *_args):
            """Keep the session log quiet."""
            return

        def do_GET(self):
            """Serve one GET request."""
            path = urlparse(self.path).path
            if path == "/events":
                self._events()
                return
            if path == "/snapshot":
                self._snapshot()
                return
            self._asset(path)

        def _events(self):
            """Send snapshots as server-sent events."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(latest(), separators=(",", ":"))
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    threading.Event().wait(0.5)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _snapshot(self):
            """Send one snapshot as JSON."""
            body = json.dumps(latest()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _asset(self, path):
            """Serve one file from the asset directory."""
            name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            full = os.path.normpath(os.path.join(ASSET_DIR, name))
            if not full.startswith(ASSET_DIR) or not os.path.isfile(full):
                self.send_error(404)
                return
            ext = os.path.splitext(full)[1]
            with open(full, "rb") as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
