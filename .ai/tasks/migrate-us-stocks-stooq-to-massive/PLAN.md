# Migrate US stock prices from Stooq to Massive.com

## Goal

Replace the dead stooq.com scraper with new massive.com-based tooling:

1. `update-stocks-massive.py` — appends **raw** daily US closes to the committed
   `.ledger` files (incremental, no history rewrite).
2. A dividend/DRIP companion — caches each dividend ticker's payouts to
   `TICKER-dividend.csv` and (re)generates the total-return `TICKERd.ledger`
   benchmark by forward chaining, **without changing already-committed history**.

Success criterion: a daily run appends only missing raw dates; the `d` series is a
correct DRIP benchmark (price growth + taxed dividends reinvested on pay date) and
its recompute reproduces every committed row exactly — **crashing** if it ever
wouldn't; CI runs green under the free-plan rate limit with UK removed.

## Context / mismatch summary

`update-stocks-stooq.py` stopped working: stooq now gates the CSV endpoint behind
a JS proof-of-work anti-bot page **and** a logged-in premium account with a
per-account daily hit limit (memory `stooq-auth-mechanism`). We move US stocks to
**massive.com** (Polygon.io-compatible). Massive is US-only; UK/`CSPX` is dropped.

Verified live against the API (key redacted; **5 req/min, rolling** — the 6th call
in a minute returns HTTP 429):

| Concern | Finding |
|---|---|
| Base URL / auth | `https://api.massive.com`, `?apiKey=<key>` query param |
| Raw daily bars | `GET /v2/aggs/ticker/{TICKER}/range/1/day/{from}/{to}?adjusted=false&sort=asc&limit=50000` |
| Response fields | `results[]` with `c` (close) and `t` (ms epoch, **start of trading day in ET**) |
| Correctness | `adjusted=false` AAPL closes 306.31/315.20/310.26 exactly match committed `AAPL.ledger` |
| `BRK.B` | **User-verified** the `BRK.B` symbol works on massive |
| History depth | Free plan ≈ 2 years; irrelevant since we only *extend* existing 2015→2026 files |
| Dividends | `GET /stocks/v1/dividends?ticker=…` → `results[]` with `pay_date`, `ex_dividend_date`, `cash_amount`, `frequency`, … |
| Splits | `GET /stocks/v1/splits?ticker=…` → `results[]` with `execution_date`, `split_from`, `split_to` |

Settled decisions:
- **Use the official `massive` Python SDK** (`from massive import RESTClient`;
  PyPI `massive`, a Polygon.io-compatible fork). `get_aggs(...)` for prices;
  `list_stocks_dividends` / `list_stocks_splits` (auto-paginating iterators) for the
  later corporate-action steps. It auto-retries 429 but with too-small backoff for a
  per-minute cap, so we still pace calls ourselves (~13 s). Drops the direct
  `requests` dependency.
- **Raw price files** use `adjusted=false`: no split/dividend adjustment (splits
  handled manually in ledger by editing lots).
- **Config keeps only `current_stocks` + `historic_stocks`.** `dual_download_tickers`
  is deleted; `QQQ` moves into `current_stocks`.
- **`update-stocks-stooq.py` is left untouched** — removing the config key is safe
  for it (`config.get("dual_download_tickers", [])` defaults to `[]`).
- **UK removed** — no LSE step in CI; `CSPX` has no source now.
- **Incremental append (raw)**: fetch `last_date − buffer(20d) .. today`, append only
  `date > last_date`.
- **`d` series = DRIP total-return benchmark**: reinvest dividends **on `pay_date`**,
  **net of tax** (`net_div = cash_amount × (1 − tax_rate)`); ex-date is irrelevant.
  Forward-chained so historical values are never rewritten by a new dividend; a
  recompute that *would* change a committed row is a hard error (crash).
- **Dividend/`d` tickers** are `SPY`, `QQQ`, `BRK-B` — carried by the companion
  script, not the config.
- **Splits for `d`** are a separate, manual, full-file recompute.

## Step-by-step plan

### Step 1 — Write `stocks/update-stocks-massive.py` (raw prices) [executed]

Self-contained; small helpers (`format_line`, monthly writer) copied/adapted from
the stooq script. Uses the `massive` SDK (`get_aggs(..., adjusted=False, sort="asc")`).

**Result:** implemented + verified live. Single-ticker runs confirmed: AAPL append
2026-06-04..07-10 (values match live API & committed history), ET date conversion
correct, pure append (no committed row rewritten), monthly regenerated correctly,
idempotent rerun, and `BRK-B`→`BRK.B`→`BRK_B.ledger` mapping works.

- **CLI (same shape as stooq):** `--historic`, `--ticker TICKER`, `--config`
  (default `config.yaml`, cwd), `--api-key` (falls back to `MASSIVE_API_KEY`),
  `--buffer-days` (default 20), `--suffix` accepted-but-ignored (US-only).
- **Ticker set:** `current_stocks` (+ `historic_stocks` under `--historic`, or just
  `--ticker`).
- **Per-ticker flow:**
  1. API symbol = `ticker.replace("-", ".")` (`BRK-B`→`BRK.B`); output base =
     `ticker.replace("-", "_")`.
  2. Read `<base>.ledger`, parse last non-empty line → `last_date`. Missing/empty
     file (0-byte `GLF.ledger`) → `today − 2y` backfill, logged; empty API results →
     no-op + warn.
  3. Fetch `from = last_date − buffer_days`, `to = today`,
     `adjusted=false&sort=asc&limit=50000`.
  4. Convert each `t` (ms) to an **ET date** (`zoneinfo.ZoneInfo("America/New_York")`);
     take `c`. Append rows `date > last_date`, formatted `P %Y/%m/%d SYM {c:.2f} USD`.
  5. Regenerate `<base>-monthly.ledger` from the **full** daily series (first trading
     day of each month + trailing line for the latest day).
- **Rate limiting:** pacer ≥13 s between calls + retry on HTTP 429 (`Retry-After`).
- **Verification:** `--ticker AAPL` → pure append after 2026-06-03 matching live API;
  rerun → nothing appended; `--ticker GLF` → no crash, file untouched.

### Step 2 — Config: drop dual list, add QQQ [executed]

- Remove `dual_download_tickers` from `stocks/US/config.yaml` and
  `stocks/LSE/config.yaml`; each keeps only `current_stocks` + `historic_stocks`.
- Add `QQQ` to `stocks/US/config.yaml` `current_stocks`.

**Result:** done. US `current_stocks` now 31 tickers incl. QQQ; both configs parse
with only `current_stocks` + `historic_stocks`.

### Step 3 — Dividend cache `TICKER-dividend.csv`

For each dividend ticker (`SPY`, `QQQ`, `BRK-B`), in `stocks/US/`:

- **Freshness gate:** if `TICKER-dividend.csv` exists, read its last `pay_date`;
  expected next ≈ `last pay_date + 3 months`. If `today < expected next` → skip the
  download. Non-payers (BRK-B → empty results) are treated as fresh.
- **Fetch + transform** (only when stale):
  ```
  curl -s "https://api.massive.com/stocks/v1/dividends?ticker=$T&limit=5000&apiKey=$KEY" \
    | jq '.results' \
    | mlr --ijson --ocsv reorder -f pay_date then sort -f pay_date \
    > "$T-dividend.csv"
  ```
  → all `.results` fields as CSV, **`pay_date` first column, ascending**. `pay_date`
  is the reinvestment date used by Step 4.
- Orchestrate the loop/gate in a small script so CI calls it once; needs `jq`+`mlr`.
- **SDK alternative (now preferred, TBD at implementation):** since we already use the
  `massive` SDK, `list_stocks_dividends(ticker=…, sort="pay_date.asc")` can produce the
  same CSV in pure Python (write `pay_date` first, sorted asc) — dropping the
  `jq`/`mlr` dependency. Decide when building this step.
- **Verification:** `SPY-dividend.csv` has quarterly rows through the latest payout;
  rerunning before the next expected pay date makes no API call and no diff.

### Step 4 — Regenerate `d` (DRIP total-return) ledgers

Rebuild each `TICKERd.ledger` as the DRIP benchmark (hold + reinvest taxed
dividends), from the committed **raw** `TICKER.ledger` + `TICKER-dividend.csv`.

- **Reinvest on `pay_date`, net of tax:** `net_div = cash_amount × (1 − tax_rate)`
  (`tax_rate` a configurable const, default **0.15** — see open question).
- **Chain** (one raw close per trading day):
  `adj_t = adj_{t-1} × (close_t + net_div_t) / close_{t-1}`, where `net_div_t` is the
  taxed dividend with `pay_date == t`, else 0. Between dividends this is
  `adj_t = adj_{t-1} × close_t/close_{t-1}` → each raw close scaled by one constant
  DRIP factor; every `pay_date` steps the factor up.
- **History-preserving with crash guard:** recompute from a committed anchor a few
  days *before the most-recent `pay_date`* (seed = the committed `d` value there),
  forward through today. Every recomputed date already present in `TICKERd.ledger`
  **must equal** the committed value; if any differs → **crash** with a clear
  message (late/early dividend, data revision, unhandled split, or bug — we stop
  rather than rewrite history). New dates are appended.
- Regenerate `TICKERd-monthly.ledger` like the raw monthly files.
- BRK-B: empty dividend CSV → `net_div = 0` → `BRK_Bd` tracks the raw close.
- **Verification:** hand-check one `pay_date` row (steps up by `net_div/close_pay`);
  between-dividend `d` matches raw growth; recompute reproduces committed rows (no
  crash) and appends after 2026-06-03.

### Step 5 — Splits: separate, manual, full recompute

Splits are **not** handled by daily Step 4 (a split makes the raw close jump; the
crash guard only catches changes to *committed* rows, not new ones, so an unhandled
split silently corrupts the chain — the user triggers this recompute when a split
happens).

- Scripted split download:
  `curl "…/stocks/v1/splits?ticker=$T&apiKey=$KEY" | jq '.results' | mlr --ijson --ocsv … > "$T-split.csv"`.
- Manual recompute rewrites the **entire** `TICKERd.ledger` with the split applied
  (affected historical prices rescaled by the split ratio), then resumes forward
  chaining. Exact split-adjustment convention TBD when first needed — deferred.

### Step 6 — CI + dependencies (pipenv-managed) [mostly executed]

- **`Pipfile`** [executed]: pipenv-managed. `[packages]` = `massive`, `pyyaml`,
  `requests` (requests still used by stooq/PSE/currency). Dropped unused
  `yfinance`/`gnureadline`. `python_version = "3.10"` (only 3.10 is available on the
  dev box; bump + re-lock on a 3.11 host if desired). `Pipfile.lock` regenerated via
  `pipenv install` (massive + certifi/charset-normalizer/idna/urllib3/websockets).
  Both `Pipfile` and `Pipfile.lock` were previously untracked — commit them.
- **`.github/workflows/automation.yml`** [executed]: added `actions/setup-python@v5`
  (3.10) + `pip install pipenv` + `pipenv install --deploy`; job-level
  `PIPENV_PIPFILE`; every script now runs via `pipenv run`. US step → massive
  (`MASSIVE_API_KEY` secret — **user must add it**); **UK step removed**.
- **Remaining (deferred, needs Steps 3–5):** add a CI step running the dividend
  cache + `d` regeneration. No `jq`/`mlr` needed if Step 3 uses the SDK.
- **Verification:** local `pipenv install` + `pipenv run ../update-stocks-massive.py
  --ticker AAPL` succeed; workflow YAML parses. Full `workflow_dispatch` pending the
  `MASSIVE_API_KEY` secret.

## Risks & open questions

- **Tax rate:** confirmed **0.15** (US treaty withholding for a CZ resident with
  W-8BEN); a single configurable const.
- **Dividend-timing vs crash guard:** if a payout lands slightly before the
  `last + 3 months` gate re-downloads it (or the API publishes it a day late), a
  committed `d` row may have been computed without it → the recompute crashes. This
  is by design (you asked to crash + investigate), but may need a small grace window
  in practice.
- **Splits silently corrupt** the chain between manual recomputes (crash guard won't
  catch them). Possible enhancement: have Step 4 read `TICKER-split.csv` and crash on
  any split newer than the last committed `d` date. Flag only.
