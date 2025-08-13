# pricedb-czk
Generate Ledger-compatible pricedb files from Czech National Bank historical exchange rates

This project downloads historical exchange rates for multiple currencies from the [Czech National Bank (CNB)](https://www.cnb.cz/) and converts them into [Ledger](https://www.ledger-cli.org/) `pricedb` format.

It was inspired by [kantord/pricedb](https://github.com/kantord/pricedb), which provides ECB-based pricedb data. This version focuses on CNB exchange rates, includes discontinued currencies for historical accounting, and supports monthly price extraction.

## Features
- Downloads CNB exchange rates for all active currencies, with optional historic (discontinued) currencies.
- Outputs **daily** pricedb files: `<currency>CZK.ledger`.
- Outputs **monthly** pricedb files: `<currency>CZK-monthly.ledger` (first available trading day of each month).
- Command-line argument for selecting end date (`YYYY-MM-DD`).
- Optional `--historic` flag to include discontinued currencies (e.g., ATS, DEM, FRF).

## Usage
### Download and process only active currencies:

``` bash
python update.py --end-date 2025-08-10
```

### Download and process both active and discontinued currencies:

``` bash
python update.py --end-date 2025-08-10 --historic
```

### File output example

```
P 2025/08/08 USD 22.784 CZK
P 2025/08/07 USD 22.765 CZK
```

Files are generated in the working directory as `<currency>CZK.ledger` and `<currency>CZK-monthly.ledger`.

## Usage in ledger

### Direct download links
You can download individual pricedb files directly from GitHub.  The files are
automatically updated every day.

- **Daily prices (example):**
  - https://raw.githubusercontent.com/Fuco1/pricedb-czk/master/currency/CZK/USDCZK.ledger
  - https://raw.githubusercontent.com/Fuco1/pricedb-czk/master/currency/CZK/EURCZK.ledger

- **Monthly prices (example):**
  - https://raw.githubusercontent.com/Fuco1/pricedb-czk/master/currency/CZK/USDCZK-monthly.ledger
  - https://raw.githubusercontent.com/Fuco1/pricedb-czk/master/currency/CZK/EURCZK-monthly.ledger

You can download any other currency file by replacing the currency code in the URL.

To include the database in your ledger, use

```
include USDCZK.ledger
```

### Usage with git

Clone the repository:

```bash
git clone https://github.com/Fuco1/pricedb-czk.git
```

and create a crontab to pull changes every day:

```
crontab -e
```

```
0 15 * * * cd <path to repo> && git pull --autostash
```

This will run the git pull every day at 15:00 (3:00 PM).

Include the files you want in your ledger file directly from the repository, for example:

```
include /home/XYZ/dev/ledger/pricedb-czk/EURCZK-monthly.ledger
```

This way you will always have the most up-to date prices without ever having to think about it.

### Using different currency symbols

If you use different currency symbols, for example `€` instead of `EUR`, you can use a modification script `./modify`:

``` bash
./modify.sh --from € --to Kc EURCZK-monthly.ledger
```

This will transform the `EUR` to `€` and `CZK` to `Kc`.  Both `--from` and `--to` are optional.  The result is stored in `<file>-modded.ledger`.   You can add this script to the crontab and include the moddef files instead:

``` bash
0 15 * * * cd <path to repo> && git pull --autostash && /bin/bash modify.sh --from € --to Kc EURCZK-monthly.ledger
```

```
include /home/XYZ/dev/ledger/pricedb-czk/EURCZK-monthly-modded.ledger
```

## Supported currencies

**Active:**
AUD, BGN, BRL, CAD, CHF, CNY, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR, ISK, JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, RUB, SEK, SGD, THB, TRY, USD, XDR, ZAR

**Discontinued:** (available with `--historic`)
ATS, BEF, CYP, DEM, EEK, ESP, FIM, FRF, GRD, HRK, IEP, ITL, LTL, LUF, LVL, MTL, NLG, PTE, ROL, SIT, SKK, TRL

## Inspiration & attribution
This project is based on the idea from [kantord/pricedb](https://github.com/kantord/pricedb), which provides ECB-based pricedb data for Ledger. The CNB version was created to support CZK-based accounting and include currencies that are no longer in circulation.
