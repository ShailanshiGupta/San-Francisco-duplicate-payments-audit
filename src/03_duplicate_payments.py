"""
Step 3: Apply scope and run the duplicate payment test

Input:  data/processed/payments.parquet            (from Step 2)
SQL:    sql/03a_voucher_key_check.sql
        sql/03b_scope.sql
        sql/03c_duplicate_payments.sql
Output: data/processed/scoped_payments.parquet
        outputs/scope_summary.csv
        outputs/exceptions/duplicate_payment_pairs.csv
        outputs/logs/03_duplicate_payments.txt

All test logic lives in the SQL files. Settings come from src/config.py.
"""

import duckdb

import config
from common import Logger, money, run_sql_file

SETTINGS = {
    "IN_SCOPE_CHARACTERS": config.IN_SCOPE_CHARACTERS,
    "EXCLUDED_OBJECTS": config.EXCLUDED_OBJECTS,
    "MIN_AMOUNT": config.MIN_AMOUNT,
    "HIGH_WINDOW_DAYS": config.HIGH_WINDOW_DAYS,
    "MEDIUM_WINDOW_DAYS": config.MEDIUM_WINDOW_DAYS,
    "RECURRING_MIN_COUNT": config.RECURRING_MIN_COUNT,
}

log = Logger("03_duplicate_payments")
section = log.section

con = duckdb.connect()
con.execute(f"CREATE OR REPLACE VIEW payments AS SELECT * FROM read_parquet('{config.PAYMENTS_FILE}')")

log("SETTINGS USED")
for k, v in SETTINGS.items():
    log(f"- {k}: {v}")


# ---------------------------------------------------------------
# 3A. What identifies a payment?
# ---------------------------------------------------------------
section("3A. VOUCHER KEY CHECK")
total, by_dept, by_vendor, by_po, by_contract = run_sql_file(con, "03a_voucher_key_check.sql", SETTINGS).fetchone()
log(f"Vouchers appearing on more than one row: {total:,}")
log(f"- rows differ by department: {by_dept:,}")
log(f"- rows differ by vendor:     {by_vendor:,}")
log(f"- rows differ by PO:         {by_po:,}")
log(f"- rows differ by contract:   {by_contract:,}")
log("(one voucher can differ on more than one field)")


# ---------------------------------------------------------------
# 3B. Scope
# ---------------------------------------------------------------
section("3B. SCOPE")
run_sql_file(con, "03b_scope.sql", SETTINGS)

rows = con.execute("""
    SELECT scope_status, COUNT(*) AS payments, SUM(amount_paid) AS amount
    FROM scoped GROUP BY scope_status ORDER BY amount DESC
""").fetchall()
log(f"{'Status':<35}{'payments':>12}{'amount paid':>24}")
for status, n, amt in rows:
    log(f"{status:<35}{n:>12,}{money(amt):>24}")

scoped_total = con.execute("SELECT ROUND(SUM(amount_paid), 2) FROM scoped").fetchone()[0]
payments_total = con.execute("SELECT ROUND(SUM(amount_paid), 2) FROM payments").fetchone()[0]
log(f"\nControl total: scoped {money(scoped_total)} vs payments {money(payments_total)} -> "
    f"{'TIES' if abs(scoped_total - payments_total) < 0.01 else 'DOES NOT TIE'}")

n_test, amt_test = con.execute(f"""
    SELECT COUNT(*), SUM(amount_paid) FROM scoped
    WHERE scope_status = 'IN SCOPE' AND amount_paid >= {SETTINGS['MIN_AMOUNT']}
""").fetchone()
log(f"\nPayments tested for duplicates (in scope and >= ${SETTINGS['MIN_AMOUNT']:,}): "
    f"{n_test:,} payments, {money(amt_test)}")

log("\nIn-scope spending by category:")
for char, n, amt in con.execute("""
    SELECT character, COUNT(*), SUM(amount_paid) FROM scoped
    WHERE scope_status = 'IN SCOPE' GROUP BY character ORDER BY 3 DESC
""").fetchall():
    log(f"- {char}: {n:,} payments, {money(amt)}")

con.execute(f"COPY scoped TO '{config.SCOPED_FILE}' (FORMAT PARQUET)")
con.execute(f"""
    COPY (
        SELECT scope_status, character_code, character, COUNT(*) AS payments,
               ROUND(SUM(amount_paid), 2) AS amount_paid
        FROM scoped GROUP BY ALL ORDER BY scope_status, amount_paid DESC
    ) TO '{config.SCOPE_SUMMARY_FILE}' (HEADER, DELIMITER ',')
""")


# ---------------------------------------------------------------
# 3C. Duplicate payment test
# ---------------------------------------------------------------
section("3C. DUPLICATE PAYMENT TEST")
run_sql_file(con, "03c_duplicate_payments.sql", SETTINGS)

n_pairs = con.execute("SELECT COUNT(*) FROM duplicate_pairs").fetchone()[0]
log(f"Flagged pairs: {n_pairs:,}\n")

log(f"{'Risk':<8}{'Status':<36}{'pairs':>8}{'amount (sum of 2nd payments)':>32}")
for tier, status, n, amt in con.execute("""
    SELECT risk_tier, status, COUNT(*), SUM(amount)
    FROM duplicate_pairs GROUP BY risk_tier, status ORDER BY risk_tier, status
""").fetchall():
    log(f"{tier:<8}{status:<36}{n:>8,}{money(amt):>32}")

log("\nPotential exposure on OPEN flags (each second payment counted once):")
for tier, n, amt in con.execute("""
    SELECT risk_tier, COUNT(*), SUM(amount) FROM (
        SELECT DISTINCT risk_tier, row_id_2, amount
        FROM duplicate_pairs WHERE status = 'Open: needs review'
    ) GROUP BY risk_tier ORDER BY risk_tier
""").fetchall():
    log(f"- {tier}: {n:,} payments, {money(amt)}")

n_name = con.execute("""
    SELECT COUNT(*) FROM duplicate_pairs WHERE vendor_name_differs
""").fetchone()[0]
log(f"\nFlagged pairs where the two payments used different spellings of the vendor name: {n_name:,}")

n_cross = con.execute("""
    SELECT COUNT(*) FROM duplicate_pairs WHERE NOT same_department
""").fetchone()[0]
log(f"Flagged pairs paid by two different departments: {n_cross:,}")

log("\nDays between the two payments (open flags):")
for bucket, n in con.execute("""
    SELECT CASE WHEN days_apart = 0 THEN 'same day'
                WHEN days_apart <= 3 THEN '1-3 days'
                WHEN days_apart <= 7 THEN '4-7 days'
                WHEN days_apart <= 14 THEN '8-14 days'
                ELSE '15-30 days' END AS bucket,
           COUNT(*)
    FROM duplicate_pairs WHERE status = 'Open: needs review'
    GROUP BY bucket ORDER BY MIN(days_apart)
""").fetchall():
    log(f"- {bucket}: {n:,}")

log("\nTop 20 OPEN flags by amount:")
for row in con.execute("""
    SELECT flag_id, risk_tier, amount, vendor_1, vendor_2, department_1, department_2,
           po_1, po_2, date_1, date_2, days_apart, spend_type_1
    FROM duplicate_pairs WHERE status = 'Open: needs review'
    ORDER BY amount DESC LIMIT 20
""").fetchall():
    (fid, tier, amt, v1, v2, d1, d2, p1, p2, dt1, dt2, days, spend) = row
    log(f"\n#{fid} [{tier}] {money(amt)}  {spend}")
    log(f"   1: {v1} | {d1} | PO {p1} | {dt1}")
    log(f"   2: {v2} | {d2} | PO {p2} | {dt2}  ({days} days later)")

log("\nTop 10 vendors by OPEN flagged amount:")
for vendor, n, amt in con.execute("""
    SELECT vendor_clean, COUNT(*), SUM(amount) FROM duplicate_pairs
    WHERE status = 'Open: needs review'
    GROUP BY vendor_clean ORDER BY 3 DESC LIMIT 10
""").fetchall():
    log(f"- {vendor}: {n:,} flags, {money(amt)}")

log("\nTop 10 departments by OPEN flagged amount:")
for dept, n, amt in con.execute("""
    SELECT department_2, COUNT(*), SUM(amount) FROM duplicate_pairs
    WHERE status = 'Open: needs review'
    GROUP BY department_2 ORDER BY 3 DESC LIMIT 10
""").fetchall():
    log(f"- {dept}: {n:,} flags, {money(amt)}")

con.execute(f"""
    COPY (SELECT * FROM duplicate_pairs ORDER BY flag_id)
    TO '{config.PAIRS_FILE}' (HEADER, DELIMITER ',')
""")
con.close()

log(f"\nSaved: {config.SCOPED_FILE}")
log(f"Saved: {config.SCOPE_SUMMARY_FILE}")
log(f"Saved: {config.PAIRS_FILE}")

log.save()
