#!/usr/bin/env python3
import requests
import argparse
from datetime import datetime
from pathlib import Path

# === Stock mapping ===
CURRENT_STOCKS = {
    "CZ0009008942": "BAACZGCE",  # COLTCZ
    "CZ0005112300": "BAACEZ",  # ČEZ
    "CZ1008000310": "BAADSPW",  # DOOSAN ŠKODA POWER
    "AT0000652011": "BAAERBAG",  # ERSTE GROUP BANK
    "SK1000025322": "BAAGEVOR",  # GEVORKYAN
    "CZ0009000121": "BABKOFOL",  # KOFOLA ČS
    "CZ0008019106": "BAAKOMB",  # KOMERČNÍ BANKA
    "CZ0008040318": "BAAGECBA",  # MONETA MONEY BANK
    "CZ0005135970": "BAAPRIUA",  # PRIMOCO UAV
    "AT0000908504": "BAAVIG",  # VIG
    "CS0008418869": "BAATABAK",  # Philip Morris
}

HISTORIC_STOCKS = {
    "CZ0009093209": "BAATELEC",  # went private
    "BMG200452024": "BAACETV",  # CETV
}

API_URL = "https://www.pse.cz/api/instrument-chart"


def fetch_stock_data(isin):
    """Fetch JSON data for a given ISIN from the PSE API."""
    resp = requests.get(
        API_URL,
        headers={"X-API-Key": "PSE"},
        params={"isin": isin, "range": "_MAX"},
    )
    resp.raise_for_status()
    return resp.json()


def format_line(ts_ms, stock_name, value, currency):
    """Format one ledger line."""
    dt = datetime.utcfromtimestamp(ts_ms / 1000)
    return f"P {dt.strftime('%Y/%m/%d')} {stock_name} {value:.2f} {currency}"


def process_stock(isin, stock_name):
    """Download stock data and write full and monthly ledgers."""
    data = fetch_stock_data(isin)
    currency = data["data"]["additional"]["currency"]
    values = data["data"]["value"]

    full_path = Path(f"{stock_name}.ledger")
    monthly_path = Path(f"{stock_name}-monthly.ledger")

    with open(full_path, "w", encoding="utf-8") as full_file, open(
        monthly_path, "w", encoding="utf-8"
    ) as monthly_file:
        last_month = None
        for ts_ms, price in values:
            line = format_line(ts_ms, stock_name, price, currency)
            full_file.write(line + "\n")

            dt = datetime.utcfromtimestamp(ts_ms / 1000)
            month_key = (dt.year, dt.month)
            if last_month != month_key:
                monthly_file.write(line + "\n")
                last_month = month_key


def main():
    parser = argparse.ArgumentParser(description="Download and process PSE stock data.")
    parser.add_argument(
        "--historic", action="store_true", help="Include historic stocks."
    )
    args = parser.parse_args()

    stocks = CURRENT_STOCKS.copy()
    if args.historic:
        stocks.update(HISTORIC_STOCKS)

    for isin, name in stocks.items():
        print(f"Processing {name} ({isin})...")
        process_stock(isin, name)


if __name__ == "__main__":
    main()
