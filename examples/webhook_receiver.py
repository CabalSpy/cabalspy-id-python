"""Webhook receiver.  CSID_WEBHOOK_SECRET=whsec_... python examples/webhook_receiver.py"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from cabalspy_id import WebhookVerificationError, verify_webhook

SECRET = os.environ["CSID_WEBHOOK_SECRET"]
seen: set[str] = set()  # dedupe on event id (retries reuse it); use your database in production


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        payload = self.rfile.read(int(self.headers.get("Content-Length", 0)))  # the raw body
        try:
            event = verify_webhook(payload, self.headers, SECRET)
        except WebhookVerificationError as err:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(err.code.encode())
            return

        if event["id"] not in seen:
            seen.add(event["id"])
            if event["type"] == "consent.revoked":
                print("user", event["data"]["sub"], "removed access: delete their data")
            else:
                print(event["type"], event["data"])

        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    print("POST http://localhost:3001")
    HTTPServer(("127.0.0.1", 3001), Handler).serve_forever()
