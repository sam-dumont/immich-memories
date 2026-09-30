"""A real subprocess standing in for the pinned caption model's HTTP boundary."""

import gzip
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data": [{"id": "synthetic-captioner"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if "compressed=1" in self.path:
            self.send_header("Content-Encoding", "gzip")
            body = gzip.compress(body)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(400 if self.headers.get("Authorization") else 200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"caption"}}]}\n\ndata: [DONE]\n\n')

    def log_message(self, *_args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
