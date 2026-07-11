# Restore automated Stooq price downloads after the anti-bot + login change

## Status: PARKED (2026-07-11)

Investigation complete; **implementation deliberately not done** — user
decided to likely abandon Stooq for now. This file captures everything
reverse-engineered so the work can be resumed cold, or used to justify
switching providers. No production code has been approved/committed.

## Goal

`stocks/update-stocks-stooq.py` stopped working: the GitHub CI run fails
because Stooq now serves a JavaScript anti-bot challenge instead of CSV,
and the legacy `?apikey=` no longer authenticates. Restore unattended
daily price downloads **without changing the provider's output parsing or
the generated ledger files** (only the auth/fetch layer may change).

Success criterion: the script (in CI and/or run manually) downloads the
same CSV it used to and writes the same `.ledger` / `-monthly.ledger`
files, staying within Stooq's per-account daily limit.

## Background — what broke

- `stocks/update-stocks-stooq.py` builds `https://stooq.com/q/d/l/?s=<ticker><suffix>&f=...&t=...&i=d&o=...`
  and appended `&apikey=$STOOQ_API_KEY`. CI (`.github/workflows/automation.yml`)
  runs it from `stocks/US` and `stocks/LSE` with `STOOQ_API_KEY` secret.
- Reproduced the failure exactly as CI runs it: the endpoint now returns a
  **200 with a JS proof-of-work anti-bot page**, not CSV. The old script
  then either 404s or fails parsing. The `apikey` param is dead — it also
  just returns the challenge.

## What was reverse-engineered (all confirmed working)

### 1. Anti-bot proof-of-work (solvable in Python)
Every request to stooq.com can return an HTML page containing:
`This site requires JavaScript` plus inline JS with `c="<challenge>"` and
`d=<difficulty>` (observed `d=4`). Algorithm:
- find integer `n` (from 0 up) such that
  `sha256(c + str(n))` hex digest starts with `d` zero chars (~65k tries),
- `POST https://stooq.com/__verify` form `{c, n}` → responds `ok` and sets
  a short-lived `auth` cookie. Detection marker for the challenge page:
  the literal string `This site requires JavaScript` together with `c="`.

### 2. Login (this was the crux)
The login form is JS-rendered (not in static HTML). Its fields (provided
by the user from the live DOM) — form `method=post action=logred.htm`:
- hidden `in=1`  ← **essential discriminator; without it the POST is ignored**
- hidden `url=/`
- `login` (text, the username)
- `haslo` (password — Polish "hasło")
- `save` (remember-me checkbox → `save=on`)

`POST https://stooq.com/logred.htm` with those fields → **302 redirect to
`//stooq.com/` and sets `cookie_user=...`** = authenticated. Confirmed
repeatedly from two IPs. Username: **Fuco**. Password is NOT stored here —
keep it in git-ignored `.env` / a GitHub secret.

### 3. Download cookie requirements (bisected)
The CSV endpoint `/q/d/l/` needs, at minimum:
`auth` + `cookie_uu` + a premium `PHPSESSID`. Notes:
- `cookie_uu` = today's date as `YYMMDD` + `"000"` (e.g. `260711000`).
  The server sets this itself, or it can be synthesized. Required — without
  it the download is denied even with a good session.
- `cookie_user` and `uid` are NOT individually required for the download
  (a bisected `auth + cookie_uu + PHPSESSID` succeeded without them),
  because premium entitlement lives in the server-side session keyed by
  `PHPSESSID`.
- `auth` is NOT bound to a specific `PHPSESSID` (a freshly-solved `auth`
  from a clean session worked against a different session's `PHPSESSID`).
- A **fabricated** `PHPSESSID` is rejected — it must be server-issued.

### 4. The one proven success
Early in the session, the user's browser cookie set (`auth` + browser
`PHPSESSID=jedroblel...` + `cookie_uu`) returned **full real CSV (~980 KB
for AAPL)**. This is the ground-truth "working request". Later the same
session returned `Exceeded the daily hits limit`, then `Access denied`.

## The blocker that stopped validation

Every **scripted** download attempt returned `Access denied`, from both
the workstation and worker-1's fresh IP. Diagnosis:

- **worker-1's very first download of the day was already denied** → the
  block predates that IP → it is **account-level on Fuco**, caused by ~30
  test downloads earlier tripping the daily hits limit and escalating
  `Exceeded the daily hits limit` → hard `Access denied` for the rest of
  the day. **Not IP blocking, not a login failure.**
- Separately, the workstation IP got anti-bot-flagged ("can't access the
  page at all") — an independent, temporary **IP-level** block. worker-1
  loads pages fine.

Two independent temporary blocks: IP anti-bot (workstation) and account
daily-limit (Fuco).

## Open question (must resolve before trusting the flow)

A scripted login authenticates (`cookie_user` set) but no scripted session
ever produced CSV — because by the time the login flow existed, Fuco was
already daily-limit-blocked. So one of:

- **(P1) Quota only** — the flow is correct; it just needs the daily limit
  to reset. Strongly supported (worker-1's first-ever attempt was blocked
  → block is account-wide and pre-existing).
- **(P2) Missing premium-activation step** — a scripted login yields a
  logged-in but not premium-entitled session. The browser's working
  `cookie_user` had an extra `?<token>|<ticker>` tail (e.g.
  `...5135312?0001dllg000011540d1300e3|aapl.us`) that scripted logins never
  produced. Could be cosmetic (last-viewed ticker) or the entitlement.

Things already ruled out as the fix: visiting logged-in sections
(`/`, `/q/d/`, `/db/`), logging in while holding a pre-established
`PHPSESSID` (session did not rotate but download still denied), the
persistent `uid` remember-me cookie alone, adding consent/analytics
cookies (`FCCDCF`/`_ga`/...), and appending `&apikey=` (anon or logged-in).

## Step-by-step plan (if resumed)

### Step 1 — Validate the flow from a fresh IP after the daily limit resets
- Wait for the per-account daily limit to reset (Stooq is Polish → likely
  midnight CET/CEST; confirm empirically).
- From **worker-1** (fresh IP), as the **first** request of the day, run:
  session → GET a chart page (solve challenge) → `POST logred.htm`
  (`in=1,url=/,login,haslo,save=on`) → ensure `cookie_uu=YYMMDD000` →
  GET `/q/d/l/?s=aapl.us&i=d&o=0100000` (solve challenge if re-shown).
- **Verification**: response body starts with `Date,Open,High,Low,Close,Volume`.
  - Data → **P1 confirmed**, flow is complete → proceed to Step 3.
  - `Access denied` → **P2** → go to Step 2.

### Step 2 — (only if Step 1 fails) diff a real browser session
- Ask the user, from an un-blocked browser, to log in and then "Copy as
  cURL" both (a) the `logred.htm` login POST and (b) a **successful**
  `/q/d/l/` download request, with full cookies.
- Diff the browser's post-login cookies/headers against the scripted
  session to find what grants premium entitlement (focus on the
  `cookie_user` `?<token>` tail and any cookie the script lacks).
- Replicate that step in the client.

### Step 3 — Implement the auth/fetch layer (no change to parsing/output)
Add a `StooqClient` to `stocks/update-stocks-stooq.py`:
- `requests.Session` with a Chrome `User-Agent` + browser `Accept`/`Accept-Language`.
- `solve_challenge(html)`: regex `c="([A-Za-z0-9_\-]+)"` and `\bd=(\d+)`,
  brute-force `n`, `POST /__verify {c,n}`.
- `login()`: GET `https://stooq.com/q/d/?s=<first ticker>` (solve challenge if
  shown) → `POST https://stooq.com/logred.htm` with
  `{in:1, url:/, login:$STOOQ_USER, haslo:$STOOQ_PASS, save:on}` (Referer
  `https://stooq.com/`) → require `cookie_user` in the jar else raise
  "login failed / bad credentials"; ensure `cookie_uu = YYMMDD000`.
- `get_csv(url, referer)`: GET; if challenge shown, solve + retry once;
  classify and raise on `Access denied` / `Exceeded the daily hits limit` /
  still-challenged / body not starting with `Date`.
- `fetch_stock_data()` calls the shared client; **URL, params, CSV parsing
  and ledger writing stay byte-for-byte unchanged.**
- Credentials from env `STOOQ_USER` / `STOOQ_PASS` (or `--user`/`--password`).
- Keep a manual fallback: `--cookie` / `STOOQ_COOKIE` accepting a raw
  browser Cookie header (script still auto-solves PoW + synthesizes
  `cookie_uu`); the minimum a user must paste is their premium `PHPSESSID`.
- **Verification**: run `--ticker AAPL` in a scratch dir; ledger files
  written; spot-check values.

### Step 4 — Measure the daily hits limit
- On a good day, from one session, download tickers one-by-one counting
  successes until `Exceeded the daily hits limit`. Record N.
- **Verification**: N is stable across a couple of days.

### Step 5 — Ticker rotation to stay under the limit
- The full sweep is ~33 US tickers (30 current + dual SPY/QQQ/BRK-B) plus
  LSE. If that exceeds N/day, partition tickers deterministically by day
  (e.g. `index % ceil(total / batch) == day_of_year % ceil(...)`), update
  only that day's batch, commit. Committed prices persist between runs, so
  each ticker refreshes every few days.
- Prefer a small config knob (batch size / groups) over hardcoding.
- **Verification**: over `ceil(total/batch)` days every ticker's file gets
  a fresh timestamp; no day trips the limit.

### Step 6 — Wire CI
- In `.github/workflows/automation.yml`, replace `STOOQ_API_KEY` env with
  `STOOQ_USER` / `STOOQ_PASS` GitHub secrets for the US and LSE steps.
- GitHub runners get a fresh IP each run (good vs the IP/anti-bot gate);
  the per-account daily limit is handled by Step 5's rotation.
- **Verification**: a manual `workflow_dispatch` run downloads its batch
  and auto-commits.

## Risks & open questions

- **P2 unresolved** — scripted-login premium entitlement is unproven; Step 1
  is the gate. If P2 holds and the entitlement can't be replicated headless,
  auto-login may be infeasible and the manual `--cookie` path (Step 3
  fallback) or a provider switch becomes the answer.
- **Abuse/ToS + lockout** — heavy scripted access already triggered both an
  IP anti-bot flag and an account daily-limit block in one afternoon. CI
  must be gentle (rotation, one attempt/ticker, back off on limit messages).
- **Anti-bot escalation** — the PoW difficulty could rise or a CAPTCHA/token
  could be added, breaking headless login. (No CAPTCHA/2FA seen as of
  2026-07-11.)
- **Provider alternative** — given the fragility, evaluate whether the US/LSE
  tickers can come from another source that fits the existing CSV→ledger
  pipeline (the CZK currency + PSE paths are unaffected and still work).
- **Working-tree state** — `stocks/update-stocks-stooq.py` currently holds
  **uncommitted, unapproved** prototype edits (a cookie-based `StooqClient`
  + `--cookie`/`STOOQ_COOKIE`, credential check removed). Decide whether to
  revert to HEAD (design is fully preserved here) or keep as the Step 3
  starting point. The credential-based `login()` is NOT yet implemented in
  that prototype.

## Reference — request recipes (copy-pasteable)

Working browser download (ground truth, needs a premium browser session):
```
GET https://stooq.com/q/d/l/?s=aapl.us&i=d&o=0100000
Cookie: auth=<solved>; PHPSESSID=<premium session>; cookie_uu=YYMMDD000
Referer: https://stooq.com/q/d/?s=aapl.us
User-Agent: Mozilla/5.0 (... Chrome/143 ...)
```

Scripted login + download sequence (validated up to "Access denied" only,
pending Step 1):
```
S = requests.Session(UA=Chrome)
GET  https://stooq.com/q/d/?s=aapl.us        # if challenge: solve -> POST /__verify {c,n}
POST https://stooq.com/logred.htm  data={in:1,url:/,login:Fuco,haslo:***,save:on}
     -> expect 302 + Set-Cookie cookie_user=...
set  cookie_uu = strftime(%y%m%d)+"000"  (if 'p' or missing)
GET  https://stooq.com/q/d/l/?s=aapl.us&i=d&o=0100000   Referer=chart page
     # if challenge: solve + retry
```

Response classification: body starts `Date,` = success; `Access denied` =
not entitled / blocked; `Exceeded the daily hits limit` = recognized but
over quota; contains `This site requires JavaScript` = still challenged.

See also memory `stooq-auth-mechanism` and `plan-before-coding`.
