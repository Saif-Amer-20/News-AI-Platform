from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from newsintel_crawlers.settings import BOT_NAME


class HealthHandler(BaseHTTPRequestHandler):
    def _send(self, payload: dict[str, str], status_code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in {"/health/live", "/health/ready"}:
            self._send({"status": "ok", "service": "crawlers", "bot": BOT_NAME})
            return
        self._send({"status": "not-found"}, status_code=404)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9100), HealthHandler)
    server.serve_forever()

