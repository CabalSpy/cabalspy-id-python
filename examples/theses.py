"""Token theses through the Data API.

    CABALSPY_API_KEY=... CSID_USER=<sub> python examples/theses.py <mint>

Writing needs a user who signed in to your app with the scope "thesis".
"""

from __future__ import annotations

import os
import sys

from cabalspy_id import CabalSpyID, PermissionError

mint = sys.argv[1] if len(sys.argv) > 1 else "So11111111111111111111111111111111111111112"

with CabalSpyID() as csid:
    # Reading: any key, any token
    s = csid.thesis_summary(blockchain="solana", mint=mint)
    print(f"{s['token']['symbol']}: {s['theses']} theses ({s['bull']} bull / {s['bear']} bear)")
    for t in csid.iter_theses(blockchain="solana", mint=mint, sort="top"):
        now = (t.get("position") or {}).get("now")
        pos = f" [{now['status']}, PnL ${now['pnl_usd']}]" if now else ""
        print(f"@{t['author']['username']} {t.get('stance') or ''}: {t['body']}{pos}")

    # Writing in the name of one of your users (csid_id = the `sub` of their ID token)
    user = os.environ.get("CSID_USER")
    if user:
        ok = csid.thesis_eligibility(blockchain="solana", mint=mint, csid_id=user)
        if ok["can_post"]:
            try:
                t = csid.post_thesis(
                    blockchain="solana", mint=mint, body="Posted from my platform.", stance="bull", csid_id=user
                )
                print("posted", t["id"])
            except PermissionError as err:
                print("not allowed:", err.code)
        else:
            print("cannot post:", ok.get("reason") or ("paused" if ok.get("paused") else "not a holder"))
