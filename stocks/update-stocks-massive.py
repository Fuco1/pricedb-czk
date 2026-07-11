#!/usr/bin/env python3
"""Download and process US stock data from massive.com.

Replaces the stooq scraper (dead: anti-bot + login + daily hit limit). massive.com
is a Polygon.io-compatible market-data API; it is US-only, which covers ~99% of what
the stooq script was used for. Uses massive.com's official Python SDK (``massive``).

Prices are fetched **raw** (``adjusted=False``): no split or dividend adjustment.
Splits are handled manually in ledger by editing lots, so the committed price series
must stay raw. This also caches dividends (``<ticker>-dividend.csv``) for the
``also_dividend_adjusted`` tickers; the dividend-adjusted ("d") price series itself
is computed by a separate step.

Because the free plan only serves ~2 years of history, this script is
**incremental**: it reads the last date already in the committed ``<base>.ledger``,
fetches from ``last_date - buffer`` to today, and appends only the missing days.
With ``to = today`` this covers any gap since the last run regardless of size.
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from massive import RESTClient

# massive/Polygon daily-bar timestamps mark the start of the trading day in US
# Eastern time; convert with this zone to get the correct calendar date.
MARKET_TZ = ZoneInfo("America/New_York")
# Free plan: 5 requests / minute (rolling). Pace calls proactively; the SDK also
# retries 429s, but its default backoff is too small for a per-minute cap.
MIN_REQUEST_INTERVAL = 13.0
# How far back to fetch when a ledger file is missing/empty (free-plan history cap).
BACKFILL_DAYS = 730
# Refetch a ticker's dividend cache only once we're ~a quarter past its last payout.
DIVIDEND_CACHE_MONTHS = 3
# Columns for <ticker>-dividend.csv (pay_date first: the reinvestment date).
DIVIDEND_COLUMNS = [
    "pay_date", "ex_dividend_date", "record_date", "declaration_date",
    "cash_amount", "currency", "frequency", "distribution_type",
    "historical_adjustment_factor", "split_adjusted_cash_amount", "ticker", "id",
]

# Module-level client, initialised in main() once the API key is known.
_client = None


class MassiveClient:
    """Wraps the massive SDK RESTClient and paces calls under the rate limit."""

    def __init__(self, api_key):
        self.client = RESTClient(api_key, retries=5)
        self._last_call = 0.0

    def _throttle(self):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def daily_bars(self, symbol, from_date, to_date):
        """Return raw daily OHLC bars (list of Agg) for ``symbol``."""
        self._throttle()
        try:
            aggs = self.client.get_aggs(
                ticker=symbol,
                multiplier=1,
                timespan="day",
                from_=from_date.isoformat(),
                to=to_date.isoformat(),
                adjusted=False,
                sort="asc",
                limit=50000,
            )
        finally:
            self._last_call = time.monotonic()
        return aggs or []

    def dividends(self, symbol):
        """Return all dividends (list of StockDividend) for ``symbol``."""
        self._throttle()
        try:
            divs = list(self.client.list_stocks_dividends(ticker=symbol, limit=1000))
        finally:
            self._last_call = time.monotonic()
        return divs


def load_config(config_path="config.yaml"):
    """Load stock configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}
    return (
        config.get("current_stocks", []),
        config.get("historic_stocks", []),
        config.get("also_dividend_adjusted", []),
    )


def output_base(ticker):
    """Ledger commodity / filename stem for a ticker. Config lists tickers as the
    API expects them (e.g. BRK.B), but a ledger commodity name can't contain '.' or
    '-', so map every non-alphanumeric char to '_' (BRK.B -> BRK_B)."""
    return re.sub(r"[^A-Za-z0-9]", "_", ticker)


def format_line(date, ticker, close_value, currency="USD"):
    """Format one ledger price line, e.g. 'P 2026/06/03 AAPL 310.26 USD'."""
    return f"P {date.strftime('%Y/%m/%d')} {ticker} {close_value:.2f} {currency}"


def parse_ledger(text):
    """Parse a .ledger price file into a sorted list of (date, close) tuples."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "P":
            continue
        try:
            date = datetime.strptime(parts[1], "%Y/%m/%d").date()
            close = float(parts[3])
        except ValueError:
            continue
        rows.append((date, close))
    rows.sort(key=lambda r: r[0])
    return rows


def et_date(ts_ms):
    """Calendar (ET) date for a daily bar's millisecond timestamp."""
    return (
        datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        .astimezone(MARKET_TZ)
        .date()
    )


def write_monthly(path, rows, ticker):
    """Write the monthly ledger: first trading day of each month, plus the very
    last available line so the latest price is present even mid-month."""
    lines = []
    last_month = None
    month_date = None
    last_line = None
    date = None
    for date, close in rows:
        line = format_line(date, ticker, close)
        month_key = (date.year, date.month)
        if last_month != month_key:
            lines.append(line)
            last_month = month_key
            month_date = date
        last_line = line
    if rows and date != month_date:
        lines.append(last_line)
    path.write_text("".join(l + "\n" for l in lines), encoding="utf-8")


def add_months(d, months):
    """Add calendar months to a date, clamping the day to the month's length."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, days_in_month[month - 1]))


def last_dividend_pay_date(path):
    """Latest pay_date in a dividend CSV, or None if it lists no dividends."""
    latest = None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value = row.get("pay_date")
            if not value:
                continue
            try:
                pay = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                continue
            if latest is None or pay > latest:
                latest = pay
    return latest


def dividend_cache_fresh(path):
    """True if the cached dividend CSV is recent enough to skip re-fetching."""
    if not path.exists():
        return False
    last_pay = last_dividend_pay_date(path)
    if last_pay is None:
        # File exists but lists no dividends (a non-payer) -> don't re-hit the API.
        return True
    today = datetime.now(MARKET_TZ).date()
    return today < add_months(last_pay, DIVIDEND_CACHE_MONTHS)


def write_dividend_csv(path, dividends):
    """Write dividends to CSV: pay_date first column, sorted ascending by pay_date."""
    dividends = sorted(dividends, key=lambda d: d.pay_date or "")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(DIVIDEND_COLUMNS)
        for div in dividends:
            writer.writerow(
                [
                    "" if getattr(div, col, None) is None else getattr(div, col)
                    for col in DIVIDEND_COLUMNS
                ]
            )


def process_dividends(ticker):
    """Refresh <base>-dividend.csv for one ticker, honoring the freshness gate."""
    base = output_base(ticker)
    path = Path(f"{base}-dividend.csv")
    if dividend_cache_fresh(path):
        print("  dividends fresh; skipping fetch")
        return
    dividends = _client.dividends(ticker)
    write_dividend_csv(path, dividends)
    print(f"  cached {len(dividends)} dividend(s) -> {path.name}")


def process_stock(ticker, buffer_days):
    """Incrementally update the raw daily and monthly ledgers for one ticker."""
    base = output_base(ticker)
    daily_path = Path(f"{base}.ledger")
    monthly_path = Path(f"{base}-monthly.ledger")

    existing_raw = daily_path.read_text(encoding="utf-8") if daily_path.exists() else ""
    existing_rows = parse_ledger(existing_raw)
    last_date = existing_rows[-1][0] if existing_rows else None

    today = datetime.now(MARKET_TZ).date()
    if last_date is not None:
        from_date = last_date - timedelta(days=buffer_days)
    else:
        from_date = today - timedelta(days=BACKFILL_DAYS)
        print(f"  no existing data; backfilling from {from_date}")

    bars = _client.daily_bars(ticker, from_date, today)

    new_rows = []
    for bar in bars:
        if bar.close is None:
            continue
        date = et_date(bar.timestamp)
        if last_date is None or date > last_date:
            new_rows.append((date, float(bar.close)))
    new_rows.sort(key=lambda r: r[0])

    if not new_rows:
        print(f"  up to date (last {last_date}); nothing to append")
        return

    with open(daily_path, "a", encoding="utf-8") as f:
        if existing_raw and not existing_raw.endswith("\n"):
            f.write("\n")
        for date, close in new_rows:
            f.write(format_line(date, base, close) + "\n")

    all_rows = existing_rows + new_rows
    write_monthly(monthly_path, all_rows, base)

    print(f"  appended {len(new_rows)} day(s): {new_rows[0][0]} .. {new_rows[-1][0]}")


def main():
    parser = argparse.ArgumentParser(
        description="Download and process US stock data from massive.com."
    )
    parser.add_argument(
        "--historic", action="store_true", help="Include historic stocks."
    )
    parser.add_argument(
        "--ticker", help="Process only this single ticker (e.g., AAPL)", type=str
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Path to YAML config file"
    )
    parser.add_argument(
        "--buffer-days",
        type=int,
        default=20,
        help="Days of backward overlap when fetching the incremental update.",
    )
    parser.add_argument(
        "--api-key",
        help="massive.com API key. Falls back to the MASSIVE_API_KEY env var.",
    )
    parser.add_argument(
        "--suffix",
        default=".us",
        help="Accepted for CLI compatibility with the stooq script; ignored "
        "(massive.com is US-only).",
    )
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        sys.exit(
            "Error: no massive.com API key provided. Pass --api-key or set the "
            "MASSIVE_API_KEY environment variable."
        )

    global _client
    _client = MassiveClient(api_key)

    current_stocks, historic_stocks, dividend_tickers = load_config(args.config)

    stocks = list(current_stocks)
    if args.historic:
        stocks.extend(historic_stocks)
    if args.ticker is not None:
        stocks = [args.ticker]

    for ticker in stocks:
        print(f"Processing {ticker}...")
        process_stock(ticker, args.buffer_days)

    if args.ticker is not None:
        div_targets = [args.ticker] if args.ticker in dividend_tickers else []
    else:
        div_targets = list(dividend_tickers)

    for ticker in div_targets:
        print(f"Dividends for {ticker}...")
        process_dividends(ticker)


if __name__ == "__main__":
    main()
