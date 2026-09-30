"""
Step 4: Refine the duplicate payment flags

Step 3 flagged about 2,500 open payments. Many have innocent explanations.
This step:
  1. Labels open flags that match a known legitimate pattern
       - monthly pattern: same vendor, PO and amount paid in 3+ different months
       - multi-unit equipment order: identical amounts on equipment purchases
       - repeat supply order: identical supply purchases on different days
  2. Gives every flag that is still open a priority score (0 to 9)
  3. Builds a top-25 review list with blank columns for your assessment
  4. Checks monthly bills for months paid more than once (the duplicate a
     "recurring" label would otherwise hide)

Input:  outputs/exceptions/duplicate_payment_pairs.csv   (from Step 3)
        data/processed/scoped_payments.parquet            (from Step 3)
SQL:    sql/04_refine_duplicates.sql
        sql/04b_recurring_overflow.sql
Output: outputs/exceptions/duplicate_flags_refined.csv
        outputs/exceptions/recurring_overpayments.csv
        outputs/review/top25_review_list.csv
        outputs/logs/04_refine_duplicates.txt
"""

import duckdb

import config
from common import Logger, money, run_sql_file

SETTINGS = {
    "PAIRS_FILE": config.PAIRS_FILE,
    "SCOPED_FILE": config.SCOPED_FILE,
    "MONTHLY_MIN_MONTHS": config.MONTHLY_MIN_MONTHS,
    "REVIEW_LIST_SIZE": config.REVIEW_LIST_SIZE,
    "MIN_AMOUNT": config.MIN_AMOUNT,
    "OVERFLOW_MAX_RATIO": config.OVERFLOW_MAX_RATIO,
}

log = Logger("04_refine_duplicates")
section = log.section

con = duckdb.connect()
run_sql_file(con, "04_refine_duplicates.sql", SETTINGS)

log("SETTINGS USED")
for k, v in SETTINGS.items():
    log(f"- {k}: {v}")


# ---------------------------------------------------------------
# Refined status summary
# ---------------------------------------------------------------
section("4A. REFINED STATUS OF ALL FLAGS")
log(f"{'Refined status':<48}{'payments':>10}{'amount':>22}")
for status, n, amt in con.execute("""
    SELECT refined_status, COUNT(*), SUM(amount) FROM (
        SELECT DISTINCT ON (row_id_2) row_id_2, amount, refined_status
        FROM refined
        ORDER BY row_id_2,
                 CASE WHEN refined_status = 'Open: needs review' THEN 0 ELSE 1 END
    )
    GROUP BY refined_status ORDER BY 3 DESC
""").fetchall():
    log(f"{status:<48}{n:>10,}{money(amt):>22}")
log("(each questioned payment counted once, so totals do not double count)")


section("4B. WHAT IS STILL OPEN AFTER REFINEMENT")
n_open, amt_open = con.execute("""
    SELECT COUNT(*), SUM(amount) FROM (
        SELECT DISTINCT row_id_2, amount FROM refined
        WHERE refined_status = 'Open: needs review'
    )
""").fetchone()
log(f"Open payments: {n_open:,}, {money(amt_open)}")

log("\nBy priority score (higher = more worth reviewing):")
for score, n, amt in con.execute("""
    SELECT priority_score, COUNT(*), SUM(amount) FROM (
        SELECT row_id_2, MAX(priority_score) AS priority_score, MAX(amount) AS amount
        FROM refined WHERE refined_status = 'Open: needs review'
        GROUP BY row_id_2
    ) GROUP BY priority_score ORDER BY priority_score DESC
""").fetchall():
    log(f"- score {score}: {n:,} payments, {money(amt)}")

log("\nOpen payments by type of spending:")
for spend, n, amt in con.execute("""
    SELECT spend_type_2, COUNT(*), SUM(amount) FROM (
        SELECT DISTINCT row_id_2, amount, spend_type_2 FROM refined
        WHERE refined_status = 'Open: needs review'
    ) GROUP BY spend_type_2 ORDER BY 3 DESC LIMIT 10
""").fetchall():
    log(f"- {spend}: {n:,} payments, {money(amt)}")


# ---------------------------------------------------------------
# Review list
# ---------------------------------------------------------------
section(f"4C. TOP {SETTINGS['REVIEW_LIST_SIZE']} REVIEW LIST")
for row in con.execute("""
    SELECT review_rank, priority_score, risk_tier, amount, vendor, department_1, department_2,
           po_1, po_2, date_1, date_2, days_apart, spend_type, po_payment_count, po_total_paid
    FROM review_list ORDER BY review_rank
""").fetchall():
    (rank, score, tier, amt, vendor, d1, d2, p1, p2, dt1, dt2, days, spend, po_n, po_tot) = row
    log(f"\n#{rank}  score {score}  [{tier}]  {money(amt)}  {vendor}")
    log(f"    {spend}")
    log(f"    payment 1: {d1} | PO {p1} | {dt1}")
    log(f"    payment 2: {d2} | PO {p2} | {dt2}  ({days} days later)")
    if po_n:
        log(f"    this PO overall: {po_n:,} payments, {money(po_tot)} paid this year")


# ---------------------------------------------------------------
# Recurring overpayments (monthly bill paid more than once in a month)
# ---------------------------------------------------------------
section("4D. RECURRING OVERPAYMENT CHECK")
run_sql_file(con, "04b_recurring_overflow.sql", SETTINGS)
n_bills = con.execute("SELECT COUNT(*) FROM monthly_bills").fetchone()[0]
log(f"Monthly bills with at least one month paid more than once: {n_bills:,}")
n_months, n_extra, amt_extra = con.execute(
    "SELECT COUNT(*), COALESCE(SUM(extra_payments), 0), COALESCE(SUM(extra_amount), 0) FROM recurring_overflow"
).fetchone()
log(f"Months flagged: {n_months:,}  |  extra payments: {n_extra:,}  |  extra amount: {money(amt_extra)}")
n_rev, amt_rev = con.execute(
    "SELECT COUNT(*), COALESCE(SUM(extra_amount), 0) FROM recurring_overflow WHERE reversal_found"
).fetchone()
log(f"Of these, a later reversal exists for the same vendor and amount: {n_rev:,} months, {money(amt_rev)}")

log("\nBy pattern (months flagged, and extra payments in those months):")
for pat, n, amt in con.execute("""
    SELECT pattern, COUNT(*), SUM(extra_amount) FROM recurring_overflow GROUP BY pattern ORDER BY pattern
""").fetchall():
    log(f"- {pat}: {n:,} months, {money(amt)}")

n_bills_x, n_pay_x, amt_x = con.execute("""
    SELECT COUNT(*), COALESCE(SUM(excess_payments_in_year), 0), COALESCE(SUM(excess_amount_in_year), 0) FROM (
        SELECT DISTINCT vendor_clean, amount, excess_payments_in_year, excess_amount_in_year
        FROM recurring_overflow WHERE pattern LIKE 'Excess%'
    )
""").fetchone()
log(f"\nPotential overpayment (payments beyond the months covered, each bill counted once):")
log(f"- {n_bills_x:,} bills, {n_pay_x:,} extra payments, {money(amt_x)}")

log("\nTop 20 EXCESS bills by amount beyond the months covered:")
for row in con.execute("""
    SELECT vendor, amount, payments_in_year, span_months, excess_payments_in_year, excess_amount_in_year,
           STRING_AGG(STRFTIME(pay_month, '%Y-%m'), ', ' ORDER BY pay_month) AS doubled_months,
           ANY_VALUE(departments), ANY_VALUE(purchase_orders), ANY_VALUE(spend_type), BOOL_OR(reversal_found)
    FROM recurring_overflow WHERE pattern LIKE 'Excess%'
    GROUP BY vendor, vendor_clean, amount, payments_in_year, span_months, excess_payments_in_year, excess_amount_in_year
    ORDER BY excess_amount_in_year DESC LIMIT 20
""").fetchall():
    (vendor, amt, n_y, span, n_x, amt_x1, months, depts, pos, spend, rev) = row
    log(f"\n{vendor}  {money(amt)}: paid {n_y} times over {span} months ({n_x} extra, {money(amt_x1)})")
    log(f"    {spend} | {depts} | PO(s): {pos}")
    log(f"    months with more than one payment: {months}{'  | reversal found' if rev else ''}")

con.execute(f"COPY (SELECT * EXCLUDE (vendor_clean) FROM recurring_overflow ORDER BY overflow_id) "
            f"TO '{config.OVERFLOW_FILE}' (HEADER, DELIMITER ',')")
log(f"\nSaved: {config.OVERFLOW_FILE}")


con.execute(f"COPY (SELECT * FROM refined ORDER BY flag_id) TO '{config.REFINED_FILE}' (HEADER, DELIMITER ',')")
con.execute(f"COPY (SELECT * FROM review_list ORDER BY review_rank) TO '{config.REVIEW_FILE}' (HEADER, DELIMITER ',')")
con.close()

log(f"\nSaved: {config.REFINED_FILE}")
log(f"Saved: {config.REVIEW_FILE}")

log.save()
