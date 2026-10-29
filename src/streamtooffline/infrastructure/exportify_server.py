from __future__ import annotations

import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit


@dataclass(frozen=True, slots=True)
class ExportifyImport:
    filename: str
    csv_text: str


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, callback: Callable[[ExportifyImport], None], event: threading.Event, *args, **kwargs) -> None:
        self.callback = callback
        self.event = event
        super().__init__(*args, **kwargs)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:3000")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        if urlsplit(self.path).path != "/import":
            self.send_response(404)
        else:
            self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/import":
            self.send_response(404)
            self._cors_headers()
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        query_filename = parse_qs(parsed.query).get("filename", [None])[0]
        filename = unquote(query_filename or self.headers.get("X-Playlist-Filename", "playlist.csv"))
        try:
            self.callback(ExportifyImport(filename, body))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as exc:
            self.send_response(500)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8", errors="replace"))
        finally:
            self.event.set()

    def log_message(self, format: str, *args) -> None:
        pass


class ExportifyImportServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 3001) -> None:
        self.host = host
        self.port = port
        self._received: ExportifyImport | None = None
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._event = threading.Event()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/import"

    def start(self) -> None:
        self._received = None
        self._event.clear()

        def handler(*args, **kwargs):
            return _Handler(self._on_receive, self._event, *args, **kwargs)

        self._server = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None

    def _on_receive(self, payload: ExportifyImport) -> None:
        self._received = payload

    def wait(self, timeout: float | None = None) -> ExportifyImport | None:
        self._event.wait(timeout=timeout)
        return self._received
