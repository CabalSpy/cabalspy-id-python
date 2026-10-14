# CabalSpy ID — SocialFi API & SDK for Python

[![PyPI](https://img.shields.io/pypi/v/cabalspy-id.svg)](https://pypi.org/project/cabalspy-id/) [![ci](https://github.com/CabalSpy/cabalspy-id-python/actions/workflows/ci.yml/badge.svg)](https://github.com/CabalSpy/cabalspy-id-python/actions/workflows/ci.yml) [![Python](https://img.shields.io/pypi/pyversions/cabalspy-id.svg)](https://pypi.org/project/cabalspy-id/) [![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Official Python SDK (sync and async) for [CabalSpy ID](https://id.cabalspy.xyz). **CabalSpy ID is the SocialFi API for crypto apps**: one SocialFi integration gives your platform login with X, wallets verified by a tiny on-chain payment (no wallet connect, no signatures), reviewed KOL badges, live trades and PnL of your users and a drop-in SocialFi widget for token theses — on **Solana, BNB Chain, Base, Ethereum and Robinhood Chain**.

Your platform adds "Login with CabalSpy ID" and receives the user's X profile, verified wallets, KOL badge and full trading stats — PnL, win rate, trades, holdings — for copy trading, leaderboards and social features.

[Website](https://www.cabalspy.xyz/cabalspy-id/) · [Docs](https://docs.cabalspy.xyz/cabalspy-id) · [Sign in](https://id.cabalspy.xyz) · [API dashboard](https://apidashboard.cabalspy.xyz)

```bash
pip install cabalspy-id
```

The live stream needs one extra dependency:

```bash
pip install "cabalspy-id[stream]"
```

| | |
|---|---|
| `CabalSpyIDAuth` / `AsyncCabalSpyIDAuth` | OpenID Connect for your server: PKCE, code exchange, refresh, revoke, userinfo, ID token verification (ES256 / JWKS) |
| `CabalSpyID` / `AsyncCabalSpyID` | Data API client for `https://api-id.cabalspy.xyz/v1`, typed responses, pagination, live trade stream |
| `ThesisClient` / `AsyncThesisClient` | public token thesis API with a user's access token, plus `live()` updates |
| `verify_webhook` | Standard Webhooks signature verification |

Sync and async, fully typed (`py.typed`, `TypedDict` responses). Python 3.10+.

Everything for developers — instance (client_id), client secrets, redirect URIs, button builder, webhooks, API keys — lives in the [API dashboard](https://apidashboard.cabalspy.xyz), tab **CabalSpy ID**. For React and the browser, see the [TypeScript SDK](https://www.npmjs.com/package/cabalspy-id).

## What can you build

- **Social trading feed** — every trade of your users live, with their X profile and PnL
- **Leaderboards** — rank your users by PnL, volume, win rate or trades
- **Copy trading** — follow verified wallets of real, identified traders
- **Token theses** — holders-only opinions on a token with the author's real position, as a SocialFi widget or your own UI
- **Trader profiles** — X profile, verified wallets, holdings, PnL calendar
- **KOL badges** — reviewed badges for influential traders, shown wherever they sign in

## Login button

Put the official button on your page and point it at your login route:

```html
<div data-csid-login data-client-id="csid_..." data-href="/login"></div>
<script src="https://id.cabalspy.xyz/widget.js" async></script>
```

Signed in, mark the person so the button shows their avatar menu: `data-user="<sub>" data-logout-href="/logout"`. Design overrides: `data-theme`, `data-color`, `data-text-color`, `data-shape`, `data-size`, `data-label`, `data-full-width`, `data-show-logo`.

## Server-side login (OpenID Connect)

Authorization code flow with PKCE S256 (required for every client), state and nonce.

```python
from cabalspy_id import CabalSpyIDAuth, is_limited

auth = CabalSpyIDAuth(
    "csid_...",                                      # your instance's client_id
    client_secret=os.environ["CSID_CLIENT_SECRET"],  # csid_sk_... (omit for public clients)
    redirect_uri="https://your.app/callback",        # registered in the dashboard
)

# GET /login
req = auth.create_authorization_url(scope=["openid", "profile", "wallets", "offline_access"])
session["csid"] = req.to_dict()   # state, nonce, code_verifier, redirect_uri
return redirect(req.url)

# GET /callback
result = auth.handle_callback(request.url, **session.pop("csid"))
# checks error, state and iss, exchanges the code, verifies the ID token and its nonce

if is_limited(result.claims):
    ...  # over your plan's user limit: anonymous sub "anon_...", no profile or wallet data
else:
    user = auth.userinfo(result.tokens["access_token"])  # x profile, wallets, onchain
```

| Method | |
|---|---|
| `discover()` | the discovery document (cached) |
| `create_authorization_url(scope=, prompt=, redirect_uri=, state=, nonce=)` | returns `AuthorizationRequest(url, state, nonce, code_verifier, redirect_uri)` |
| `handle_callback(url, state=, nonce=, code_verifier=)` | full callback handling, returns `LoginResult(tokens, claims)` |
| `exchange_code(code=, code_verifier=, redirect_uri=)` | `POST /oauth/token`, authorization_code |
| `refresh(refresh_token)` | `POST /oauth/token`, refresh_token. Tokens rotate: store the new one; reusing an old one revokes the chain |
| `revoke(token)` | `POST /oauth/revoke` |
| `userinfo(access_token)` | `GET /oauth/userinfo` |
| `verify_id_token(id_token, nonce=, max_age=)` | ES256 signature via JWKS, iss, aud, azp, exp, iat, nonce |
| `verify_access_token(access_token)` | for access tokens your frontend sends to your API (`typ: at+jwt`) |

`AsyncCabalSpyIDAuth` has the same methods as coroutines. Scopes: `openid` `profile` `wallets` `onchain` `thesis` `offline_access` (`thesis`: post theses and replies, react and report in the user's name). Client authentication: `client_secret_basic` (default with a secret), `client_secret_post`, `none`. Access and ID tokens live 15 minutes; refresh tokens 30 days of inactivity, 90 days absolute.

**Browser apps** (public clients) let the widget run PKCE itself; it hands your page an `idToken`. Send it to your backend and verify it there:

```python
auth = CabalSpyIDAuth("csid_...")
claims = auth.verify_id_token(id_token_from_the_browser)
```

**Users over the plan's limit can always sign in.** Their token carries an anonymous `sub` (`anon_...`), `limited: true` and `reason: "plan_user_limit"`, and no profile or wallet data, until the platform upgrades. `is_limited(claims)` checks both.

A runnable server is in [examples/login_server.py](examples/login_server.py).

## Data API

```python
from cabalspy_id import CabalSpyID

csid = CabalSpyID()  # reads CABALSPY_ID_API_KEY, then CABALSPY_API_KEY

me = csid.me()  # instance, plan, rate limit, users with data

# The person who just signed in: look them up by the `sub` of their ID token
profile = csid.profile(csid_id=claims["sub"])
wallet = next(w for w in profile["wallets"] if "solana" in w["chains"])

# Full trading profile for a period, same numbers as the CabalSpy API
t = csid.tracker(blockchain="solana", address=wallet["address"], period="7d")
print(t["period_stats"]["realized_pnl_usd"], t["period_win_rate_distribution"]["win_rate_percentage"])

# Your users ranked by PnL
board = csid.leaderboard(blockchain="solana", period="7d", sort="pnl_usd", limit=25)
```

Async:

```python
from cabalspy_id import AsyncCabalSpyID

async with AsyncCabalSpyID() as csid:
    users = await csid.users(kol=True)
```

The API key is the **same key as the CabalSpy API**, with the per-key toggle "CabalSpy ID" enabled on the API keys page. A key sees **its instance only**: users that signed in to its apps, within the plan's user limit. `scope="global"` (every CabalSpy ID user) is Enterprise only.

| Method | Endpoint |
|---|---|
| `health()` | `GET /v1/health` (no key needed) |
| `me()` | `GET /v1/me` |
| `users(limit=, kol=, cursor=, scope=)` | `GET /v1/users` |
| `profile(username= \| csid_id= \| address=)` | `GET /v1/profile` |
| `wallet_lookup(address)` | `GET /v1/wallets/lookup` |
| `tracker(blockchain=, address=, period=)` | `GET /v1/wallets/tracker` |
| `history(blockchain=, address=, limit=, cursor=)` | `GET /v1/wallets/history` |
| `holdings(blockchain=, address=)` | `GET /v1/wallets/holdings` |
| `pnl_calendar(blockchain=, address=)` | `GET /v1/wallets/pnl_calendar` |
| `leaderboard(blockchain=, period=, sort=, limit=, cursor=, scope=)` | `GET /v1/wallets/leaderboard` |
| `latest_transactions(blockchain=, limit=)` | `GET /v1/transactions/latest` |

Chains: `solana`, `bnb`, `base`, `eth`, `rh`. Periods: `6h`, `1d`, `7d`, `30d`. Leaderboard sorts: `volume`, `pnl`, `pnl_usd`, `win_rate`, `trades`. Responses are plain dicts typed with `TypedDict`s (`Profile`, `TrackerResponse`, `LeaderboardResponse`, …).

If your account has several CabalSpy ID instances, pass `instance="csid_..."` (the client_id).

### Pagination

Iterators follow `next_cursor` for you (async generators on `AsyncCabalSpyID`):

```python
for user in csid.iter_users(kol=True):
    print(user["username"])
for trade in csid.iter_history(blockchain="solana", address=address):
    print(trade["tx_signature"])
for entry in csid.iter_leaderboard(blockchain="base", period="30d"):
    print(entry["rank"])
```

For whole pages with metadata: `csid.pages("/users", {"limit": 100})` yields `Envelope`s, and `csid.get_raw(path, params)` returns one.

### Errors

Every failure is a subclass of `CabalSpyIDError` carrying `.code`, `.status`, `.request_id`, `.docs` (a link to the error's documentation), and for validation errors `.parameter` and `.allowed`.

```python
from cabalspy_id import NotFoundError, PlanUserLimitError, RateLimitError

try:
    csid.profile(csid_id=claims["sub"])
except PlanUserLimitError:
    show_upgrade_notice()          # anon_ sub: no data until you upgrade
except NotFoundError:
    pass                           # not one of your users
except RateLimitError as err:
    print(err.retry_after)
```

| Class | Status | Codes |
|---|---|---|
| `BadRequestError` | 400 | `missing_parameter`, `invalid_parameter`, `instance_required` |
| `AuthenticationError` | 401 | `missing_api_key` |
| `PermissionError` | 403 | `invalid_api_key`, `product_not_enabled`, `no_instance`, `scope_not_allowed` |
| `PlanUserLimitError` | 403 | `plan_user_limit` |
| `NotFoundError` | 404 | `profile_not_found`, `wallet_not_found`, `instance_not_found` |
| `RateLimitError` | 429 | `rate_limit_exceeded` |
| `ServerError` | 5xx | `internal_error`, `service_unavailable` |
| `APIConnectionError` | – | network failure, timeout |
| `OAuthError` | 4xx | OAuth errors from the login endpoints (`invalid_grant`, `invalid_client`, …) |
| `TokenVerificationError` | – | ID / access token failed verification |
| `WebhookVerificationError` | – | webhook signature or timestamp invalid |

`429`, `5xx` and network errors are retried with exponential backoff (default 2 retries); `Retry-After` wins. The rate limit of the last call is in `csid.last_rate_limit` (`X-RateLimit-Limit/Remaining/Reset`).

## Token theses

A thesis is a short opinion on a token (up to 1000 characters), optionally tagged bull or bear. **Only holders post theses**: one of the author's verified wallets bought the token and still holds it. Every thesis shows the author's real position — what they bought when posting and their live PnL now (or "sold"); authors who keep their trading private show only that they hold. Anyone signed in can reply and react (`like` plus 🔥 🚀 💎 👀 😂 🤝 💀 🐂 🐻). The same theses appear in the widget, through the Data API and on every platform.

Writing needs the scope **`thesis`** in your login (`scope=["openid", "profile", "thesis"]`).

**Scope of reads.** Theses are shared across platforms. Every read (`list_theses`, `thesis_summary`, `latest_theses`, `ThesisClient`, the widget, the live sockets) takes `scope`: `global` (default, every platform) or `instance` (only theses written on your instance). In the Data API your key decides the instance; the public API and widget need your `client_id`.

### Widget

```html
<div data-csid-thesis data-chain="solana" data-mint="..." data-client-id="csid_..." data-theme="dark"></div>
<script src="https://id.cabalspy.xyz/widget.js" async></script>
<script>CSID.thesis.setAccessToken(accessToken)  // optional: the signed-in person writes right away</script>
```

### Data API (server to server)

Reading works with any key, for every token and user. Writing happens **in the name of one of your users**: pass their `csid_id` (the `sub` of their ID token); they must have signed in to your app with the scope `thesis` and be within your plan's user limit.

```python
theses = csid.list_theses(blockchain="solana", mint=mint, sort="new")
counts = csid.thesis_summary(blockchain="solana", mint=mint)  # theses, bull, bear, authors, token

ok = csid.thesis_eligibility(blockchain="solana", mint=mint, csid_id=claims["sub"])
if ok["can_post"]:
    t = csid.post_thesis(blockchain="solana", mint=mint, body="Accumulating here.", stance="bull", csid_id=claims["sub"])
```

| Method | Endpoint |
|---|---|
| `list_theses(blockchain=, mint=, sort=, stance=, limit=, cursor=, csid_id=)` / `iter_theses()` | `GET /v1/theses` |
| `thesis_summary(blockchain=, mint=)` | `GET /v1/theses/summary` |
| `thesis(id, csid_id=)` | `GET /v1/theses/item` |
| `thesis_replies(id, limit=, cursor=)` / `iter_thesis_replies()` | `GET /v1/theses/replies` |
| `latest_theses(blockchain=, users="all" \| "instance", limit=, cursor=)` | `GET /v1/theses/latest` |
| `user_theses(csid_id= \| username=)` | `GET /v1/theses/user` |
| `thesis_eligibility(blockchain=, mint=, csid_id=)` | `GET /v1/theses/eligibility` |
| `post_thesis(blockchain=, mint=, body=, stance=, csid_id=)` | `POST /v1/theses` |
| `reply_to_thesis(thesis_id=, body=, csid_id=)` | `POST /v1/theses/replies` |
| `react_to_thesis(thesis_id=, emoji=, on=, csid_id=)` | `POST /v1/theses/reactions` |
| `report_thesis(thesis_id=, reason=, note=, csid_id=)` | `POST /v1/theses/report` |
| `delete_thesis(thesis_id=, csid_id=)` | `POST /v1/theses/delete` |

| `thesis_notifications(csid_id)` | `GET /v1/theses/notifications` |
| `appeal_thesis_decision(csid_id, notification_id, message)` | `POST /v1/theses/appeal` |

Every thesis carries `reacted_by` (the latest reactions with who reacted) and, for theses, `latest_replies` (a preview of the newest replies).

**Moderation.** Posts hidden after reports, pauses and moderator decisions reach the author as notifications (`id`, `kind`, `text`, `data`, `created_at`, `read`, `appealable`, `appeal`); `appealable` ones can be appealed within 30 days with 10-1000 characters. Through the Data API in your user's name: `thesis_notifications(csid_id)` / `appeal_thesis_decision(...)`; with the user's token: `ThesisClient.notifications()`, `mark_notifications_read()`, `appeal(id, message)`. `ThesisClient.me()` also returns `notices` (`unread`, `latest`, `url`) for a badge.

Thesis error codes: `not_a_holder`, `consent_required`, `scope_missing`, `plan_user_limit` (`PlanUserLimitError`), `posting_paused`, `reporting_paused`, `sandbox_user` (403, `PermissionError`); `invalid_body`, `duplicate` (400); `not_found` (404); `rate_limited` (429). Writes are never retried after a server or network error, so a post can't be duplicated; only the API's own rate limit is retried.

With `data-client-id` the widget loads the design saved in the dashboard; `data-theme`, `data-scope`, `data-sort`, `data-font`, `data-radius`, `data-bg`, `data-card`, `data-text`, `data-muted`, `data-border`, `data-accent`, `data-accent-text`, `data-bull`, `data-bear`, `data-show-header`, `data-show-sentiment`, `data-compact` and `data-height` override it.

### Theses stream (every plan)

Live theses for the tokens you choose, e.g. to put markers on a chart. Up to 200 tokens per connection (or all), on every plan; subscriptions are sent again after every reconnect. Async, needs the `stream` extra.

```python
async with AsyncCabalSpyID() as csid:
    ts = csid.theses_stream(scope="global")          # or "instance"

    @ts.on("thesis")
    def on_thesis(t):
        add_marker(t["blockchain"], t["mint"], t)

    await ts.connect()                               # returns on "ready"
    await ts.subscribe([{"blockchain": "solana", "mint": MINT_A}, {"blockchain": "base", "mint": TOKEN_B}])
    await ts.unsubscribe([{"blockchain": "base", "mint": TOKEN_B}])
    # await ts.subscribe_all() / await ts.unsubscribe_all()
    await ts.run_forever()

    # or iterate {"event": ..., "data": ...}
    async with csid.theses_stream() as ts:
        await ts.subscribe_all()
        async for ev in ts:
            print(ev["event"], ev["data"])
```

Events: `ready`, `subscribed`, `thesis`, `thesis.reply`, `thesis.reaction`, `thesis.removed`, `heartbeat`, `reconnecting`, `close`, `error`. A refused connection (`invalid_api_key`, …) is fatal; a bad frame (`too_many_tokens`, an invalid address) is reported as `error` and the connection stays.

Also over the trade stream (Pro plan): `csid.stream(events=["theses"], blockchain="solana", mint=mint)` emits `thesis`, `thesis.reply`, `thesis.reaction` and `thesis.removed` (or iterate `stream.theses()`). Your users' activity also arrives as webhooks: `thesis.created` (`event["data"]["thesis"]`), `thesis.reply` (`event["data"]["reply"]`) and `thesis.reaction` (`thesis_id`, `chain`, `mint`, `emoji`, `on`, `reactions`).

### Public thesis API: `ThesisClient`

`https://id.cabalspy.xyz/thesis/v1` needs no API key: reading is open, writing uses the user's access token (scope `thesis`).

```python
from cabalspy_id import ThesisClient

# client_id credits posts to your app; add scope="instance" to show only theses written on your platform
with ThesisClient(access_token=result.tokens["access_token"], client_id="csid_...") as theses:
    page = theses.list("solana", mint, sort="top")     # items, pagination, token, summary
    if theses.me("solana", mint)["can_post"]:
        theses.post("solana", mint, body="Strong community, still early.", stance="bull")
    theses.react(page.items[0]["id"], "🚀")
```

Methods: `list`, `iterate`, `summary`, `get`, `replies`, `by_user`, `me`, `post`, `reply`, `react`, `report`, `delete`, `notifications`, `mark_notifications_read`, `appeal`, `live`, `set_access_token`. `AsyncThesisClient` has the same methods as coroutines. Live updates for one token (async):

```python
live = ThesisClient().live("solana", mint)               # also takes scope=, client_id=
live.on("thesis", lambda t: print("new", t["body"]))   # also: reply, reaction, removed
await live.connect()
await live.run_forever()
```

## Live stream

Every trade of your users the moment it is indexed, with the trader's profile (Pro plan and up). Async only, needs `pip install "cabalspy-id[stream]"`.

```python
async with AsyncCabalSpyID() as csid:
    stream = csid.stream(blockchain="solana")  # omit blockchain for every chain
    # events=["trades"] (default), ["theses"] or both; mint= theses of one token

    @stream.on("trade")
    def on_trade(t):
        print(t["trader"]["username"], t["transaction_type"], t["token_symbol"], t["value_usd"])

    await stream.connect()        # returns once the server confirmed the subscription
    await stream.run_forever()    # until stream.close() or a fatal error

    # or iterate
    async with csid.stream() as stream:
        async for trade in stream:
            print(trade)
```

The server sends a heartbeat every 30 seconds. The client reconnects with exponential backoff after a dropped connection or when heartbeats stop; configuration errors (`invalid_api_key`, `plan_required`, `scope_not_allowed`) are fatal and stop reconnecting. Events: `trade`, `thesis`, `thesis.reply`, `thesis.reaction`, `thesis.removed`, `subscribed`, `heartbeat`, `open`, `close`, `reconnecting`, `error`; handlers may be sync or async.

## Webhooks

Deliveries follow the [Standard Webhooks](https://www.standardwebhooks.com) spec (`webhook-id`, `webhook-timestamp`, `webhook-signature`, secret `whsec_...`) and are retried for about 2 days. Events: `wallet.verified`, `wallet.removed`, `profile.updated`, `kol.granted`, `consent.revoked`, `thesis.created`, `thesis.reply`, `thesis.reaction` — only for users within the plan's limit.

```python
from cabalspy_id import verify_webhook

# pass the RAW body, exactly as received
event = verify_webhook(request.body, request.headers, os.environ["CSID_WEBHOOK_SECRET"])

if event["type"] == "consent.revoked":
    delete_user_data(event["data"]["sub"])
```

Timestamps older than 5 minutes are rejected (`tolerance=`). During a secret roll several signatures are sent; any match is accepted. Dedupe on `event["id"]`, it is the same on every retry. `sign_webhook()` builds test requests for your receiver.

## Configuration

```python
CabalSpyID(
    api_key=None,          # env fallback: CABALSPY_ID_API_KEY, then CABALSPY_API_KEY
    instance=None,         # client_id, when the account has several instances
    base_url="https://api-id.cabalspy.xyz/v1",
    stream_url="wss://api-id.cabalspy.xyz/v1/stream",
    timeout=30.0,
    max_retries=2,
    headers={},
    http_client=None,      # bring your own httpx.Client / httpx.AsyncClient
)

CabalSpyIDAuth(
    "csid_...",
    client_secret=None,    # csid_sk_..., server apps only
    redirect_uri=None,
    issuer="https://id.cabalspy.xyz",
    token_endpoint_auth_method=None,  # client_secret_basic | client_secret_post | none
    clock_tolerance=60,
    timeout=15.0,
    http_client=None,
)
```

Keep the API key and the client secret on your server; read them from the environment or a secret manager.

## Pricing

Per month and registrable domain. Everyone can always sign in; above the limit the platform receives no data for the extra users until it upgrades.

| Plan | Price / month | Users with data | API rate | |
|---|---|---|---|---|
| Free | $0 | 50 | 1 req/s | |
| Starter | $49 | 200 | 5 req/s | |
| Pro | $149 | 500 | 10 req/s | + live stream |
| Business | $499 | 1,000 | 25 req/s | |
| Enterprise | custom | unlimited | custom + SLA | `scope=global` |

Yearly billing is 20% off. Card or crypto at [apidashboard.cabalspy.xyz/billing/csid](https://apidashboard.cabalspy.xyz/billing/csid).

## Docs

[docs.cabalspy.xyz/cabalspy-id](https://docs.cabalspy.xyz/cabalspy-id) · Discovery: [id.cabalspy.xyz/.well-known/openid-configuration](https://id.cabalspy.xyz/.well-known/openid-configuration)

## Related

- [CabalSpy ID](https://id.cabalspy.xyz) · [leaderboard](https://id.cabalspy.xyz/leaderboard) · [API dashboard](https://apidashboard.cabalspy.xyz)
- CabalSpy ID SDKs: [TypeScript](https://www.npmjs.com/package/cabalspy-id) · [Python](https://pypi.org/project/cabalspy-id/)
- CabalSpy API SDKs (KOL and smart money wallet tracking): [TypeScript](https://www.npmjs.com/package/cabalspy) · [Python](https://pypi.org/project/cabalspy/) · [Rust](https://crates.io/crates/cabalspy)
- [SDK overview](https://www.cabalspy.xyz/sdks/) · [MCP server](https://www.cabalspy.xyz/mcp/) · [CabalSpy Terminal](https://app.cabalspy.xyz/)

## License

MIT
