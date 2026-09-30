"""
Step 1: Extract. Download one full fiscal year of San Francisco vendor payments

Fiscal year 2026 = July 1, 2025 to June 30, 2026 (about 511,000 rows)

What this does:
  1. Asks SF's data portal how many rows exist for fiscal year 2026
  2. Downloads them in pages of 50,000 rows (so a dropped connection
     doesn't mean starting over; just run the script again and it
     picks up where it left off)
  3. Combines the pages into one file, saved as both CSV and Parquet
  4. Prints a summary so we can check the data before analyzing it

Everything printed is also saved to outputs/logs/01_extract.txt.
"""

import io
import os
import shutil
import sys
import time

import duckdb
import pandas as pd
import requests

import config

DATASET_ID = config.DATASET_ID
DOMAINS = config.DOMAINS
FISCAL_YEAR = config.FISCAL_YEAR
PAGE_SIZE = 50000
TIMEOUT = 180
RETRIES = 3

RAW_DIR = os.path.join("data", "raw")
PAGE_DIR = os.path.join(RAW_DIR, "pages")
CSV_OUT = os.path.join(RAW_DIR, f"sf_vouchers_fy{FISCAL_YEAR}.csv")
PARQUET_OUT = os.path.join(RAW_DIR, f"sf_vouchers_fy{FISCAL_YEAR}.parquet")
LOG_FILE = "outputs/logs/01_extract.txt"

NUMERIC_COLS = ["vouchers_paid", "vouchers_pending", "vouchers_pending_retainage"]

lines = []


def log(text=""):
    print(text)
    lines.append(str(text))


def save_log():
    with open(LOG_FILE, "w") as f:
        f.write("\n".join(lines))


def fetch(path, params, as_text=False):
    """Try each SF domain, retrying a few times with a pause between tries."""
    last_error = None
    for attempt in range(1, RETRIES + 1):
        for domain in DOMAINS:
            try:
                r = requests.get(f"https://{domain}{path}", params=params, timeout=TIMEOUT)
                r.raise_for_status()
                return r.text if as_text else r.json()
            except Exception as e:
                last_error = e
        wait = 10 * attempt
        print(f"   Connection problem, retrying in {wait} seconds...")
        time.sleep(wait)
    raise RuntimeError(f"Failed after {RETRIES} attempts. Last error: {last_error}")


def money(x):
    return f"${x:,.2f}"


# ---------------------------------------------------------------
# 1. How many rows?
# ---------------------------------------------------------------
os.makedirs(PAGE_DIR, exist_ok=True)
where = f"fiscal_year = '{FISCAL_YEAR}'"

log("=" * 70)
log(f"STEP 1: DOWNLOADING FISCAL YEAR {FISCAL_YEAR}")
log("=" * 70)

try:
    count_result = fetch(
        f"/resource/{DATASET_ID}.json",
        {"$select": "count(*) AS n", "$where": where},
    )
    expected_rows = int(count_result[0]["n"])
except Exception as e:
    log(f"ERROR getting row count: {e}")
    save_log()
    sys.exit(1)

n_pages = (expected_rows + PAGE_SIZE - 1) // PAGE_SIZE
log(f"Rows on SF's portal: {expected_rows:,}")
log(f"Downloading in {n_pages} pages of up to {PAGE_SIZE:,} rows\n")

# ---------------------------------------------------------------
# 2. Download page by page
# ---------------------------------------------------------------
for i in range(n_pages):
    page_file = os.path.join(PAGE_DIR, f"page_{i:03d}.csv")
    if os.path.exists(page_file) and os.path.getsize(page_file) > 0:
        print(f"Page {i + 1}/{n_pages}: already downloaded, skipping")
        continue

    print(f"Page {i + 1}/{n_pages}: downloading...")
    try:
        text = fetch(
            f"/resource/{DATASET_ID}.csv",
            {
                "$where": where,
                "$order": ":id",
                "$limit": PAGE_SIZE,
                "$offset": i * PAGE_SIZE,
            },
            as_text=True,
        )
    except Exception as e:
        log(f"ERROR on page {i + 1}: {e}")
        log("Just run the script again. It will continue from this page.")
        save_log()
        sys.exit(1)

    with open(page_file, "w") as f:
        f.write(text)

# ---------------------------------------------------------------
# 3. Combine pages and save
# ---------------------------------------------------------------
print("\nCombining pages...")
page_files = sorted(
    os.path.join(PAGE_DIR, f) for f in os.listdir(PAGE_DIR) if f.endswith(".csv")
)
df = pd.concat(
    (pd.read_csv(f, dtype=str, keep_default_na=False, na_values=[""]) for f in page_files),
    ignore_index=True,
)

for col in NUMERIC_COLS:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

log(f"Rows downloaded: {len(df):,}")
if len(df) != expected_rows:
    log(
        f"NOTE: expected {expected_rows:,}. A small difference can happen if SF "
        "updated the data during the download. A big difference means something went wrong."
    )

df.to_csv(CSV_OUT, index=False)
con = duckdb.connect()
con.register("df_view", df)
con.execute(f"COPY df_view TO '{PARQUET_OUT}' (FORMAT PARQUET)")
con.close()
log(f"Saved: {CSV_OUT}")
log(f"Saved: {PARQUET_OUT}")

shutil.rmtree(PAGE_DIR)

# ---------------------------------------------------------------
# 4. Summary checks
# ---------------------------------------------------------------
log("\n" + "=" * 70)
log("SUMMARY")
log("=" * 70)

paid = df["vouchers_paid"]
log(f"Total paid:                {money(paid.sum())}")
log(f"Unique vendors (by name):  {df['vendor'].nunique():,}")
log(f"Unique vouchers:           {df['voucher'].nunique():,}")
log(f"Unique purchase orders:    {df['purchase_order'].nunique():,}")
log(f"Unique departments:        {df['department'].nunique():,}")

log("\nPayment amount checks:")
log(f"- Rows with a negative amount (reversals or credits): {(paid < 0).sum():,}  totaling {money(paid[paid < 0].sum())}")
log(f"- Rows with a zero amount:                            {(paid == 0).sum():,}")
log(f"- Rows with a positive amount:                        {(paid > 0).sum():,}")

log("\nHow many rows each voucher has (1 = one row per payment):")
rows_per_voucher = df.groupby("voucher").size().value_counts().sort_index()
for n_rows, n_vouchers in rows_per_voucher.head(8).items():
    log(f"- {n_rows} row(s): {n_vouchers:,} vouchers")
if len(rows_per_voucher) > 8:
    log(f"- more than 8 rows: {rows_per_voucher.iloc[8:].sum():,} vouchers")

log("\nPurchase order checks:")
po = df["purchase_order"].fillna("").astype(str).str.strip()
log(f"- Missing PO:              {(po == '').sum():,} rows")
log(f"- PO made of only zeros:   {((po != '') & (po.str.strip('0') == '')).sum():,} rows")
log("- 10 most common PO numbers (a placeholder would show up here):")
for value, count in po.value_counts().head(10).items():
    log(f"    {value}: {count:,} rows")

log("\nContract checks:")
log(f"- Rows with no contract number: {df['contract_number'].isna().sum():,} ({df['contract_number'].isna().mean() * 100:.1f}%)")

log("\ndata_as_of (possible stand-in for payment date):")
as_of = pd.to_datetime(df["data_as_of"], errors="coerce", utc=True)
log(f"- Earliest: {as_of.min()}")
log(f"- Latest:   {as_of.max()}")
log(f"- Could not read: {as_of.isna().sum():,} rows")
log("- Rows by month:")
by_month = as_of.dt.tz_convert("America/Los_Angeles").dt.to_period("M").value_counts().sort_index()
for month, count in by_month.items():
    log(f"    {month}: {count:,}")

log("\nTop 10 departments by amount paid:")
for dept, amt in df.groupby("department")["vouchers_paid"].sum().nlargest(10).items():
    log(f"- {dept}: {money(amt)}")

log("\nTop 10 purchasing authorities by amount paid:")
for auth, amt in df.groupby("purchasing_authority_title")["vouchers_paid"].sum().nlargest(10).items():
    auth = auth if len(auth) <= 70 else auth[:70] + "..."
    log(f"- {auth}: {money(amt)}")

log("\nTop 10 vendors by amount paid:")
for vendor, amt in df.groupby("vendor")["vouchers_paid"].sum().nlargest(10).items():
    log(f"- {vendor}: {money(amt)}")

save_log()
print(f"\nDone. Summary saved to {LOG_FILE}")
