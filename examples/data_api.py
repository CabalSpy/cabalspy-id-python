"""Data API tour.  CABALSPY_API_KEY=... python examples/data_api.py

The key is your CabalSpy API key with "CabalSpy ID" enabled on the API keys page.
"""

from __future__ import annotations

from cabalspy_id import CabalSpyID, NotFoundError, PlanUserLimitError

with CabalSpyID() as csid:  # reads CABALSPY_ID_API_KEY or CABALSPY_API_KEY
    print(csid.health())
    me = csid.me()
    print(f"{me['instance']}: {me['plan']} plan, {me['rate_limit_rps']} req/s, {me['users_with_data']} users with data")

    # Every user of your instance (follows the cursor for you)
    for user in csid.iter_users(limit=100):
        badge = "KOL" if user["kol"]["badge"] else ""
        print(f"@{user['username']}", badge, [w["address"] for w in user["wallets"]])

        wallet = next((w for w in user["wallets"] if "solana" in w["chains"]), None)
        if wallet:
            t = csid.tracker(blockchain="solana", address=wallet["address"], period="7d")
            stats, wr = t["period_stats"], t["period_win_rate_distribution"]
            print(f"  7d PnL {stats['realized_pnl_usd']:.2f} USD, win rate {wr['win_rate_percentage']}%")

    # Leaderboard of your users
    board = csid.leaderboard(blockchain="solana", period="7d", sort="pnl_usd", limit=10)
    for entry in board["leaderboard"]:
        print(entry["rank"], entry["profile"]["username"], entry["period_stats"]["realized_pnl_usd"])

    # Latest trades of your users on every chain
    for trade in csid.latest_transactions(limit=5):
        print(trade["trader"] and trade["trader"]["username"], trade["transaction_type"], trade["token_symbol"])

    # Look someone up by the `sub` of their ID token
    try:
        csid.profile(csid_id="anon_example")
    except PlanUserLimitError as err:
        print("over the plan user limit:", err.docs)
    except NotFoundError:
        print("not one of your users")

    print("rate limit after the last call:", csid.last_rate_limit)
