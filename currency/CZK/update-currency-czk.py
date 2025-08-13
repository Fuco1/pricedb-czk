#!/usr/bin/env python3

import requests
from datetime import datetime
import sys
import argparse
import os
import re

# Still existing currencies
currencies_existing = [
    "AUD",  # Australian Dollar
    "BGN",  # Bulgarian Lev
    "BRL",  # Brazilian Real
    "CAD",  # Canadian Dollar
    "CHF",  # Swiss Franc
    "CNY",  # Chinese Yuan
    "DKK",  # Danish Krone
    "EUR",  # Euro
    "GBP",  # British Pound
    "HKD",  # Hong Kong Dollar
    "HUF",  # Hungarian Forint
    "IDR",  # Indonesian Rupiah
    "ILS",  # Israeli New Shekel
    "INR",  # Indian Rupee
    "ISK",  # Icelandic Krona
    "JPY",  # Japanese Yen
    "KRW",  # South Korean Won
    "MXN",  # Mexican Peso
    "MYR",  # Malaysian Ringgit
    "NOK",  # Norwegian Krone
    "NZD",  # New Zealand Dollar
    "PHP",  # Philippine Peso
    "PLN",  # Polish Zloty
    "RON",  # Romanian Leu
    "RUB",  # Russian Ruble
    "SEK",  # Swedish Krona
    "SGD",  # Singapore Dollar
    "THB",  # Thai Baht
    "TRY",  # Turkish Lira
    "USD",  # US Dollar
    "XDR",  # IMF Special Drawing Rights
    "ZAR",  # South African Rand
]

# Discontinued or replaced currencies
currencies_discontinued = [
    "ATS",  # Austrian Schilling → EUR 1999/2002
    "BEF",  # Belgian Franc → EUR 1999/2002
    "CYP",  # Cypriot Pound → EUR 2008
    "DEM",  # German Mark → EUR 1999/2002
    "EEK",  # Estonian Kroon → EUR 2011
    "ESP",  # Spanish Peseta → EUR 1999/2002
    "FIM",  # Finnish Markka → EUR 1999/2002
    "FRF",  # French Franc → EUR 1999/2002
    "GRD",  # Greek Drachma → EUR 2001/2002
    "HRK",  # Croatian Kuna → EUR 2023
    "IEP",  # Irish Pound → EUR 1999/2002
    "ITL",  # Italian Lira → EUR 1999/2002
    "LTL",  # Lithuanian Litas → EUR 2015
    "LUF",  # Luxembourg Franc → EUR 1999/2002
    "LVL",  # Latvian Lats → EUR 2014
    "MTL",  # Maltese Lira → EUR 2008
    "NLG",  # Dutch Guilder → EUR 1999/2002
    "PTE",  # Portuguese Escudo → EUR 1999/2002
    "ROL",  # Old Romanian Leu → RON 2005
    "SIT",  # Slovenian Tolar → EUR 2007
    "SKK",  # Slovak Koruna → EUR 2009
    "TRL",  # Old Turkish Lira → TRY 2005
]


def main():
    parser = argparse.ArgumentParser(
        description="Download CNB exchange rates and convert to ledger format."
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.today().strftime("%Y-%m-%d"),
        help="End date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--historic",
        action="store_true",
        help="Include discontinued currencies in processing",
    )
    args = parser.parse_args()

    # Convert YYYY-MM-DD to DD.MM.YYYY
    try:
        end_date_obj = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        print("Error: Invalid date format. Use YYYY-MM-DD.")
        sys.exit(1)
    end_date_str = end_date_obj.strftime("%d.%m.%Y")

    base_url = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/vybrane.txt"
    params_template = "?od=01.01.2000&do={end_date}&mena={currency}&format=txt"

    if args.historic:
        currencies = currencies_existing + currencies_discontinued
    else:
        currencies = currencies_existing

    for currency in currencies:
        url = base_url + params_template.format(
            end_date=end_date_str, currency=currency
        )
        print(f"Downloading {currency}...")
        try:
            response = requests.get(url)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Failed to download {currency}: {e}")
            continue

        lines = response.text.strip().split("\n")
        if len(lines) < 2:
            print(f"No data for {currency}")
            continue

        match = re.search(r"Množství: (\d+)", lines[0])
        if match:
            quantity = int(match.group(1))
        else:
            quantity = 1

        data_lines = lines[1:]  # Remove header line

        ledger_lines = []
        monthly_lines = []
        last_month = None
        for line in data_lines:
            parts = line.split("|")
            if len(parts) < 2:
                continue
            date_str = parts[0].strip()
            rate_str = parts[1].strip().replace(",", ".")
            try:
                date_obj = datetime.strptime(date_str, "%d.%m.%Y")
                rate = float(rate_str) / quantity
            except ValueError:
                continue

            ledger_line = (
                f"P {date_obj.strftime('%Y/%m/%d')} {currency} {round(rate, 7)} CZK"
            )
            ledger_lines.append(ledger_line)

            # Monthly filter: first available entry for each month
            month_key = (date_obj.year, date_obj.month)
            if month_key != last_month:
                monthly_lines.append(ledger_line)
                last_month = month_key

        ledger_filename = f"{currency}CZK.ledger"
        with open(ledger_filename, "w", encoding="utf-8") as f:
            f.write("\n".join(ledger_lines))

        monthly_filename = f"{currency}CZK-monthly.ledger"
        with open(monthly_filename, "w", encoding="utf-8") as f:
            f.write("\n".join(monthly_lines))

        print(f"{currency}: {len(ledger_lines)} entries saved.")


if __name__ == "__main__":
    main()
