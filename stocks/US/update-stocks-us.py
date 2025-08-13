#!/usr/bin/env python3
import argparse
import csv
import requests
from datetime import datetime
from pathlib import Path
from io import StringIO

# === Stock lists ===
CURRENT_STOCKS = [
    "AAPL",
    "AMD",
    "AMZN",
    "AVGO",
    "DIS",
    "GM",
    "GOOG",
    "GPC",
    "M",
    "MA",
    "MO",
    "MSFT",
    "NVDA",
    "O",
    "PYPL",
    "STAG",
    "SPY",
    "T",
    "TDW",
    "TSLA",
    "VLO",
    "WFC",
    "XOM",
]

dual_download_tickers = ["SPY", "QQQ"]

HISTORIC_STOCKS = [
    "GLF",
    "JWN",
    "NMM",
    "XLNX",
]

BASE_URL = "https://stooq.com/q/d/l/"
USDCZK_FILE = Path("../../currency/CZK/USDCZK.ledger")


def load_usdczk_rates():
    """Load USD to CZK rates from a ledger file."""
    rates = {}
    if not USDCZK_FILE.exists():
        return rates
    with open(USDCZK_FILE, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4 and parts[0] == "P":
                date_str = parts[1]
                try:
                    date_obj = datetime.strptime(date_str, "%Y/%m/%d")
                except ValueError:
                    continue
                rate = float(parts[3])
                rates[date_obj] = rate
    return rates


def fetch_stock_data(ticker, skip_div_adjustment=True):
    """Fetch daily CSV data for a US ticker from Stooq."""
    today_str = datetime.today().strftime("%Y%m%d")
    # First bit: skip splits = 1, Second bit: skip dividend adjustment
    split_bit = "1"
    div_bit = "1" if skip_div_adjustment else "0"
    o_param = f"{split_bit}{div_bit}00000"
    url = f"{BASE_URL}?s={ticker}.us&f=20150101&t={today_str}&i=d&o={o_param}"
    r = requests.get(url)
    r.raise_for_status()
    return r.text


def format_line(date_str, ticker, close_value, currency="USD"):
    """Format one ledger line without time component."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"P {dt.strftime('%Y/%m/%d')} {ticker} {close_value:.2f} {currency}"


usdczk_rates = None


def process_stock(ticker, skip_div_adjustment=True, dividend_adjusted=False):
    """Download stock CSV and write full and monthly ledgers."""
    global usdczk_rates
    csv_data = fetch_stock_data(ticker, skip_div_adjustment)
    reader = csv.DictReader(StringIO(csv_data))

    ticker_output = ticker
    if dividend_adjusted:
        ticker_output = ticker_output + "d"

    full_path = Path(f"{ticker_output}.ledger")
    monthly_path = Path(f"{ticker_output}-monthly.ledger")

    # For SPY/QQQ also prepare CZK files
    do_czk = ticker in {"SPY", "QQQ"}
    if do_czk and usdczk_rates is None:
        usdczk_rates = load_usdczk_rates()
    if do_czk:
        full_czk_path = Path(f"{ticker_output}CZK.ledger")
        monthly_czk_path = Path(f"{ticker_output}CZK-monthly.ledger")

    with open(full_path, "w", encoding="utf-8") as full_file, open(
        monthly_path, "w", encoding="utf-8"
    ) as monthly_file, (
        open(full_czk_path, "w", encoding="utf-8")
        if do_czk
        else open(Path("/dev/null"), "w")
    ) as full_czk_file, (
        open(monthly_czk_path, "w", encoding="utf-8")
        if do_czk
        else open(Path("/dev/null"), "w")
    ) as monthly_czk_file:
        last_month = None
        last_month_czk = None

        for row in reader:
            if not row["Close"]:
                continue  # skip empty or malformed rows

            close_price = float(row["Close"])
            date_str = row["Date"]
            line_usd = format_line(date_str, ticker_output, close_price, "USD")
            full_file.write(line_usd + "\n")

            dt = datetime.strptime(date_str, "%Y-%m-%d")
            month_key = (dt.year, dt.month)
            if last_month != month_key:
                monthly_file.write(line_usd + "\n")
                last_month = month_key

            # Handle CZK conversion for SPY/QQQ
            if do_czk:
                rate = usdczk_rates.get(dt)
                if rate:
                    czk_price = close_price * rate
                    line_czk = format_line(
                        date_str, f"{ticker_output}CZK", czk_price, "CZK"
                    )
                    full_czk_file.write(line_czk + "\n")
                    if last_month_czk != month_key:
                        monthly_czk_file.write(line_czk + "\n")
                        last_month_czk = month_key


def main():
    parser = argparse.ArgumentParser(
        description="Download and process US stock data from Stooq."
    )
    parser.add_argument(
        "--historic", action="store_true", help="Include historic stocks."
    )
    parser.add_argument(
        "--ticker", help="Process only this single ticker (e.g., AAPL)", type=str
    )

    args = parser.parse_args()

    stocks = list(CURRENT_STOCKS)
    if args.historic:
        stocks.extend(HISTORIC_STOCKS)
    if args.ticker is not None:
        stocks = [args.ticker]

    for ticker in stocks:
        print(f"Processing {ticker}...")
        process_stock(ticker)

        if ticker in dual_download_tickers:
            print(f"Processing {ticker}d...")
            process_stock(ticker, False, True)


if __name__ == "__main__":
    main()
