"""
Step 2: Prepare the data for testing

Input:  data/raw/sf_vouchers_fy2026.parquet   (from Step 1)
SQL:    sql/02_prepare.sql
Output: data/processed/payments.parquet       (one row per payment)
        outputs/logs/02_prepare.txt

What this does:
  A. Combines split rows into one row per payment (voucher)
  B. Checks that the total still ties to the raw data (control total)
  C. Standardizes vendor names so near-identical names can be compared
  D. Prints a spending breakdown by category, so we can decide exactly
     which kinds of spending belong in scope for the tests

Nothing is flagged or excluded yet. Scope is decided after reviewing
the breakdown in section D.

All data rules live in sql/02_prepare.sql and run through DuckDB.
"""

import os
import duckdb

import config
from common import run_sql_file

RAW_FILE = config.RAW_FILE
OUT_DIR = config.PROCESSED_DIR
PAYMENTS_OUT = config.PAYMENTS_FILE
LOG_FILE = "outputs/logs/02_prepare.txt"

os.makedirs(OUT_DIR, exist_ok=True)
lines = []


def log(text=""):
    print(text)
    lines.append(str(text))


def money(x):
    return f"${x:,.2f}" if x is not None else "$0.00"


def section(title):
    log("\n" + "=" * 70)
    log(title)
    log("=" * 70)


con = duckdb.connect()
con.execute(f"CREATE OR REPLACE VIEW raw AS SELECT * FROM read_parquet('{RAW_FILE}')")


run_sql_file(con, "02_prepare.sql")


# -------------------------------------------------------------------
# A. Payment-level table
# -------------------------------------------------------------------
section("A. ONE ROW PER PAYMENT")
raw_rows = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
pay_rows = con.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
log(f"Raw rows:          {raw_rows:,}")
log(f"Payment rows:      {pay_rows:,}")

dup_vouchers = con.execute("""
    SELECT COUNT(*) FROM (
        SELECT voucher FROM payments GROUP BY voucher HAVING COUNT(*) > 1
    )
""").fetchone()[0]
log(f"Vouchers that still appear on more than one row: {dup_vouchers:,}")
log("  (should be 0 or close to it; if not, one voucher has different vendors,")
log("   POs, or departments on its lines, which is a data quality finding itself)")

multi_cat = con.execute("SELECT COUNT(*) FROM payments WHERE n_categories > 1").fetchone()[0]
log(f"Payments charged to more than one spending category: {multi_cat:,}")

missing_date = con.execute("SELECT COUNT(*) FROM payments WHERE approx_date IS NULL").fetchone()[0]
log(f"Payments with no readable approximate date: {missing_date:,}")


# -------------------------------------------------------------------
# B. Control total: does the payment table tie to the raw data?
# -------------------------------------------------------------------
section("B. CONTROL TOTAL CHECK")
raw_total = con.execute("SELECT ROUND(SUM(vouchers_paid), 2) FROM raw").fetchone()[0]
pay_total = con.execute("SELECT ROUND(SUM(amount_paid), 2) FROM payments").fetchone()[0]
log(f"Raw total paid:      {money(raw_total)}")
log(f"Payment table total: {money(pay_total)}")
diff = round((raw_total or 0) - (pay_total or 0), 2)
log(f"Difference:          {money(diff)}  -> {'TIES' if abs(diff) < 0.01 else 'DOES NOT TIE, INVESTIGATE'}")

log("\nPayments by sign:")
for label, cond in [("Positive", "> 0"), ("Zero", "= 0"), ("Negative (reversals/credits)", "< 0")]:
    n, amt = con.execute(
        f"SELECT COUNT(*), COALESCE(SUM(amount_paid), 0) FROM payments WHERE amount_paid {cond}"
    ).fetchone()
    log(f"- {label:<30} {n:>9,} payments   {money(amt)}")

n_direct, amt_direct = con.execute(
    "SELECT COUNT(*), SUM(amount_paid) FROM payments WHERE is_direct_payment"
).fetchone()
log(f"\nDirect payments (no PO): {n_direct:,} payments, {money(amt_direct)}")

n_spp, amt_spp = con.execute(
    "SELECT COUNT(*), COALESCE(SUM(amount_paid), 0) FROM payments WHERE vendor = 'Single Payment Payees'"
).fetchone()
log(f"'Single Payment Payees' placeholder: {n_spp:,} payments, {money(amt_spp)}")


# -------------------------------------------------------------------
# C. Vendor name standardization
# -------------------------------------------------------------------
section("C. VENDOR NAME STANDARDIZATION")
n_raw_names = con.execute("SELECT COUNT(DISTINCT vendor) FROM payments").fetchone()[0]
n_clean_names = con.execute("SELECT COUNT(DISTINCT vendor_clean) FROM payments").fetchone()[0]
log(f"Unique vendor names as written:  {n_raw_names:,}")
log(f"Unique names after standardizing: {n_clean_names:,}")
log(f"Names that merged together:       {n_raw_names - n_clean_names:,}")

log("\nTop 15 standardized names that cover more than one written name (by amount paid):")
rows = con.execute("""
    SELECT vendor_clean,
           COUNT(DISTINCT vendor)                         AS n_variants,
           STRING_AGG(DISTINCT vendor, '  |  ')           AS variants,
           SUM(amount_paid)                               AS total_paid
    FROM payments
    GROUP BY vendor_clean
    HAVING COUNT(DISTINCT vendor) > 1
    ORDER BY total_paid DESC
    LIMIT 15
""").fetchall()
for clean, n_var, variants, total in rows:
    log(f"\n- {clean}  ({n_var} variants, {money(total)})")
    log(f"    {variants[:300]}")


# -------------------------------------------------------------------
# D. Spending by category (to decide scope)
# -------------------------------------------------------------------
section("D. SPENDING BY CATEGORY (for deciding scope)")
log(f"{'Category (character)':<45}{'payments':>12}{'amount paid':>22}{'share':>8}")
rows = con.execute("""
    SELECT character_code, character, COUNT(*) AS n, SUM(amount_paid) AS amt,
           SUM(amount_paid) / SUM(SUM(amount_paid)) OVER () * 100 AS pct
    FROM payments
    GROUP BY character_code, character
    ORDER BY amt DESC
""").fetchall()
for code, name, n, amt, pct in rows:
    label = f"{name} [{code}]"
    log(f"{label[:44]:<45}{n:>12,}{money(amt):>22}{pct:>7.1f}%")

log("\nTop 40 sub-categories (object) by amount paid:")
rows = con.execute("""
    SELECT character, object, COUNT(*) AS n, SUM(amount_paid) AS amt
    FROM payments
    GROUP BY character, object
    ORDER BY amt DESC
    LIMIT 40
""").fetchall()
for char, obj, n, amt in rows:
    log(f"- {obj}  (in {char}): {n:,} payments, {money(amt)}")


# -------------------------------------------------------------------
# Save
# -------------------------------------------------------------------
con.execute(f"COPY payments TO '{PAYMENTS_OUT}' (FORMAT PARQUET)")
con.close()
log(f"\nSaved: {PAYMENTS_OUT}")

with open(LOG_FILE, "w") as f:
    f.write("\n".join(lines))
print(f"\nDone. Summary saved to {LOG_FILE}")
