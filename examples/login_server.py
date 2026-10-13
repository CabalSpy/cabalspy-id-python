"""Server-side "Login with CabalSpy ID" with nothing but the standard library.

    CSID_CLIENT_ID=csid_... CSID_CLIENT_SECRET=csid_sk_... python examples/login_server.py

Register http://localhost:3000/callback as a redirect URI of your instance
(https://apidashboard.cabalspy.xyz, tab "CabalSpy ID").
"""

from __future__ import annotations

import html
import json
import os
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlsplit

from cabalspy_id import CabalSpyIDAuth, CabalSpyIDError, is_limited

auth = CabalSpyIDAuth(
    os.environ["CSID_CLIENT_ID"],
    client_secret=os.environ.get("CSID_CLIENT_SECRET"),
    redirect_uri="http://localhost:3000/callback",
)

# Demo storage. Use your session store (or a signed, http-only cookie) in production.
pending: dict[str, dict[str, str]] = {}  # login id -> state, nonce, code_verifier, redirect_uri
sessions: dict[str, dict[str, Any]] = {}  # session id -> claims


class Handler(BaseHTTPRequestHandler):
    def cookie(self, name: str) -> str | None:
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        return jar[name].value if name in jar else None

    def redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def page(self, body: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/login":
                req = auth.create_authorization_url(scope=["openid", "profile", "wallets"])
                login_id = secrets.token_hex(16)
                pending[login_id] = req.to_dict()
                self.redirect(req.url, f"csid_login={login_id}; HttpOnly; SameSite=Lax; Path=/; Max-Age=600")
            elif path == "/callback":
                stored = pending.pop(self.cookie("csid_login") or "", None)
                if not stored:
                    return self.page('Login expired, <a href="/login">try again</a>.', 400)
                result = auth.handle_callback(self.path, **stored)
                # userinfo has the verified wallets (the ID token carries only the profile)
                user = result.claims if is_limited(result.claims) else auth.userinfo(result.tokens["access_token"])
                sid = secrets.token_hex(16)
                sessions[sid] = user
                self.redirect("/", f"sid={sid}; HttpOnly; SameSite=Lax; Path=/")
            elif path == "/logout":
                sessions.pop(self.cookie("sid") or "", None)
                self.redirect("/", "sid=; Max-Age=0; Path=/")
            else:
                self.home()
        except CabalSpyIDError as err:
            self.page(f"{type(err).__name__}: {html.escape(str(err))}", 400)

    def home(self) -> None:
        user = sessions.get(self.cookie("sid") or "")
        signed_in = f'data-user="{html.escape(user["sub"])}" data-logout-href="/logout"' if user else ""
        button = f"""
          <div data-csid-login data-client-id="{auth.client_id}" data-href="/login" {signed_in}></div>
          <script src="https://id.cabalspy.xyz/widget.js" async></script>"""
        if not user:
            return self.page(f"<h1>Demo</h1>{button}")
        if is_limited(user):
            return self.page(f"<h1>Signed in</h1><p>This platform is over its plan's user limit.</p>{button}")
        wallets = html.escape(json.dumps(user.get("wallets", []), indent=2))
        self.page(f"<h1>Hi @{html.escape(user['preferred_username'])}</h1>{button}<pre>{wallets}</pre>")


if __name__ == "__main__":
    print("http://localhost:3000")
    HTTPServer(("127.0.0.1", 3000), Handler).serve_forever()
