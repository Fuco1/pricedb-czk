#!/usr/bin/env python3
import argparse
import csv
import yaml
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
    "BRK-B",
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

dual_download_tickers = ["SPY", "QQQ", "BRK-B"]

HISTORIC_STOCKS = [
    "GLF",
    "JWN",
    "NMM",
    "XLNX",
]

BASE_URL = "https://stooq.com/q/d/l/"


def load_config(config_path="stocks.yaml"):
    """Load stock configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return (
        config.get("current_stocks", []),
        config.get("dual_download_tickers", []),
        config.get("historic_stocks", []),
    )


def fetch_stock_data(ticker, skip_div_adjustment=True, suffix=".us"):
    """Fetch daily CSV data for a US ticker from Stooq."""
    today_str = datetime.today().strftime("%Y%m%d")
    # First bit: skip splits = 1, Second bit: skip dividend adjustment
    split_bit = "1"
    div_bit = "1" if skip_div_adjustment else "0"
    o_param = f"{split_bit}{div_bit}00000"
    url = f"{BASE_URL}?s={ticker}{suffix}&f=20150101&t={today_str}&i=d&o={o_param}"
    r = requests.get(url)
    r.raise_for_status()
    return r.text


def format_line(date_str, ticker, close_value, currency="USD"):
    """Format one ledger line without time component."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"P {dt.strftime('%Y/%m/%d')} {ticker} {close_value:.2f} {currency}"


def process_stock(ticker, dividend_adjusted=False, suffix=".us"):
    """Download stock CSV and write full and monthly ledgers."""
    csv_data = fetch_stock_data(ticker, not dividend_adjusted, suffix)
    reader = csv.DictReader(StringIO(csv_data))

    ticker_output = ticker
    if dividend_adjusted:
        ticker_output = ticker_output + "d"

    ticker_output = ticker_output.replace("-", "_")

    full_path = Path(f"{ticker_output}.ledger")
    monthly_path = Path(f"{ticker_output}-monthly.ledger")

    with open(full_path, "w", encoding="utf-8") as full_file, open(
        monthly_path, "w", encoding="utf-8"
    ) as monthly_file:
        last_month = None

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
    parser.add_argument(
        "--suffix", default=".us", help="Ticker suffix for URL (default: .us)"
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Path to YAML config file"
    )
    args = parser.parse_args()

    current_stocks, dual_download_tickers, historic_stocks = load_config(args.config)

    stocks = list(current_stocks)
    if args.historic:
        stocks.extend(historic_stocks)
    if args.ticker is not None:
        stocks = [args.ticker]

    for ticker in stocks:
        print(f"Processing {ticker}...")
        process_stock(ticker, suffix=args.suffix)

        if ticker in dual_download_tickers:
            print(f"Processing {ticker}d...")
            process_stock(ticker, True, suffix=args.suffix)


if __name__ == "__main__":
    main()
