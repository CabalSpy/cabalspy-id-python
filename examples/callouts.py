"""Callouts tour: your users call tokens, every call is stamped and tracked.

    pip install "cabalspy-id[stream]"            # the stream part only
    CABALSPY_API_KEY=... python examples/callouts.py

Callouts are an extra that CabalSpy switches on per instance on request; without
it every call raises PermissionError (feature_not_enabled). The user and the token
below are placeholders: replace them with one of your platform users and a token
they hold.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cabalspy_id import (
    FEATURE_CALLOUTS,
    AsyncCabalSpyID,
    CabalSpyID,
    Chain,
    ConflictError,
    PermissionError,
    RateLimitError,
)

USER = "user_1"  # your platform's user id (external_id)
CHAIN: Chain = "solana"
MINT = "So11111111111111111111111111111111111111112"


def tour() -> None:
    with CabalSpyID() as csid:  # reads CABALSPY_ID_API_KEY or CABALSPY_API_KEY
        if FEATURE_CALLOUTS not in csid.me()["features"]:
            print("Callouts are not switched on for this instance yet: ask CabalSpy to enable them.")
            return

        # Rules of the instance: who may call, holders only, cooldown between two callouts
        settings = csid.update_callout_settings(who="all", require_holding=True, cooldown_minutes=360)
        print("settings:", settings)

        # 1. A user calls a token: price and market cap are stamped now and tracked from here
        try:
            c = csid.create_callout(USER, chain=CHAIN, mint=MINT, note="Strong chart, team ships")
            print(f"called {c['token']['symbol']} at ${c['at_call']['market_cap_usd']:,.0f} market cap")
        except ConflictError as err:  # already_called: one call per token and 24 hours
            print("already called:", err.message)
        except RateLimitError as err:  # callout_cooldown: never retried by the SDK
            print(f"cooldown: next callout in {err.retry_after or 0:.0f} s")
        except PermissionError as err:  # not_a_holder, kol_only, posting_paused, ...
            print("not allowed:", err.code)

        # 2. Callouts on the token, e.g. as chart markers (newest first)
        for c in csid.iter_callouts(chain=CHAIN, mint=MINT):
            t = c["tracking"]
            print(
                f"  {c['called_at']} {c['author'].get('name')} now {c['now']['x']}x peak {c['score_x']}x ({t['phase']})"
            )
            if t["below_10k_since"]:
                print("    below a $10k market cap since", t["below_10k_since"])
            if "first_day" in c:
                print("    first day:", c["first_day"]["kind"], c["first_day"]["peak_x"])

        # 3. One user's numbers per period (6h, 1d, 7d, 30d)
        stats = csid.callout_stats(USER, hit_x=2)
        for period, s in stats["periods"].items():
            print(f"  {period}: {s['callouts']} callouts, avg peak {s['avg_peak_x']}x, hit rate {s['hit_rate']}%")

        # 4. The callers leaderboard
        board = csid.callout_leaderboard(period="7d", sort="avg_peak_x", min_callouts=1)
        for e in board["leaderboard"][:10]:
            name = (e["author"] or {}).get("name") or e["csid_id"]
            print(f"  #{e['rank']} {name}: avg {e['avg_peak_x']}x, best {e['best_call']['symbol']} {e['best_peak_x']}x")

        # 5. A callout competition between your users (counts every chain)
        comp = csid.create_competition(
            name="Caller of the week",
            kind="callouts",
            chain="all",
            metric="avg_peak_x",
            duration_hours=168,
            min_callouts=3,
            hit_x=2,
            enrollment="all_users",
        )
        print("competition:", comp["id"], comp["status"])


async def live() -> None:
    """Every callout event of the instance for 60 seconds."""
    async with AsyncCabalSpyID() as csid:
        cs = csid.callouts_stream(chain=CHAIN)

        @cs.on("callout.created")
        def on_created(c: dict[str, Any]) -> None:
            print("new callout:", c["token"]["symbol"], "by", c["author"].get("name"))

        @cs.on("callout.milestone")
        def on_milestone(c: dict[str, Any]) -> None:
            print(f"{c['token']['symbol']} hit {c['milestone_x']}x")

        @cs.on("callout.final")
        def on_final(c: dict[str, Any]) -> None:
            print("tracking stopped:", c["id"], c["tracking"]["stop_reason"], "score", c["score_x"])

        @cs.on("error")
        def on_error(e: Exception) -> None:
            print("error:", e)

        await cs.connect()
        try:
            await asyncio.wait_for(cs.run_forever(), timeout=60)
        except asyncio.TimeoutError:
            pass
        finally:
            await cs.close()


if __name__ == "__main__":
    tour()
    asyncio.run(live())
