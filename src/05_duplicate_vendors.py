"""
Step 5: Duplicate vendor test

The city's data has no vendor ID, only the vendor name. If one supplier
exists under two names ("ACME SUPPLY INC" and "Acme Supply"), a bill can
be paid once under each name and a normal duplicate check would miss it.

This step:
  A. Lists every vendor name with its payment activity        (SQL)
  B. Finds pairs of names that look like the same supplier      (Python)
       - identical after cleanup: only capitalization, punctuation
         or a legal ending (INC, LLC...) differs
       - similar: fuzzy name similarity of at least the threshold
         in config, with the same numbers in both names
  C. Adds evidence and a confidence rating to each pair         (SQL)
  D. Looks for the same amount paid to both names close together (SQL)

Input:  data/processed/scoped_payments.parquet   (from Step 3)
SQL:    sql/05a_vendor_list.sql
        sql/05b_vendor_candidates.sql
        sql/05c_cross_vendor_payments.sql
Output: outputs/exceptions/vendor_duplicate_candidates.csv
        outputs/exceptions/cross_vendor_payment_matches.csv
        outputs/logs/05_duplicate_vendors.txt
"""

import re
from itertools import combinations

import duckdb
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

import config
from common import Logger, money, run_sql_file

SETTINGS = {
    "SCOPED_FILE": config.SCOPED_FILE,
    "MIN_AMOUNT": config.MIN_AMOUNT,
    "CROSS_VENDOR_WINDOW_DAYS": config.CROSS_VENDOR_WINDOW_DAYS,
}

log = Logger("05_duplicate_vendors")
con = duckdb.connect()

log("SETTINGS USED")
log(f"- VENDOR_MATCH_THRESHOLD: {config.VENDOR_MATCH_THRESHOLD}")
log(f"- VENDOR_MIN_NAME_LENGTH: {config.VENDOR_MIN_NAME_LENGTH}")
log(f"- CROSS_VENDOR_WINDOW_DAYS: {config.CROSS_VENDOR_WINDOW_DAYS}")
log(f"- MIN_AMOUNT: {config.MIN_AMOUNT}")


# ---------------------------------------------------------------
# A. Vendor list
# ---------------------------------------------------------------
log.section("5A. VENDOR LIST")
run_sql_file(con, "05a_vendor_list.sql", SETTINGS)
vendors = con.execute("SELECT vendor, vendor_clean FROM vendor_list").df()
log(f"Vendor names as written:     {len(vendors):,}")
log(f"Standardized vendor names:   {vendors['vendor_clean'].nunique():,}")


# ---------------------------------------------------------------
# B. Name matching
# ---------------------------------------------------------------
log.section("5B. NAME MATCHING")
pairs = []

# B1. Identical after cleanup
for clean, group in vendors.groupby("vendor_clean"):
    raw_names = sorted(group["vendor"].unique())
    for v1, v2 in combinations(raw_names, 2):
        pairs.append(("Identical after cleanup", 100, v1, v2))
n_identical = len(pairs)
log(f"Pairs identical after cleanup: {n_identical:,}")


# B2. Similar names (fuzzy matching)
def _roman(n):
    out = ""
    for value, sym in [(40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        while n >= value:
            out += sym
            n -= value
    return out


ROMAN_1_TO_49 = {_roman(n) for n in range(1, 50)}


def numbers_in(name):
    """Digits and Roman numerals in a name. 'MERCY HOUSING CALIFORNIA XIV' -> {'XIV'}"""
    digits = set(re.findall(r"\d+", name))
    romans = {t for t in name.split() if t in ROMAN_1_TO_49}
    return frozenset(digits | romans)


clean_names = sorted(
    n for n in vendors["vendor_clean"].dropna().unique()
    if len(n) >= config.VENDOR_MIN_NAME_LENGTH
)
log(f"Standardized names compared (at least {config.VENDOR_MIN_NAME_LENGTH} characters): {len(clean_names):,}")

scores = process.cdist(
    clean_names, clean_names,
    scorer=fuzz.token_sort_ratio,
    score_cutoff=config.VENDOR_MATCH_THRESHOLD,
    dtype=np.uint8,
    workers=-1,
)
rows_idx, cols_idx = np.nonzero(np.triu(scores, k=1))

raw_by_clean = vendors.groupby("vendor_clean")["vendor"].apply(lambda s: sorted(s.unique())).to_dict()
n_skipped_numbers = 0
for i, j in zip(rows_idx, cols_idx):
    c1, c2 = clean_names[i], clean_names[j]
    # "SFII 1390 MARKET ST" vs "SFII 1400 MARKET ST", or "MERCY HOUSING CALIFORNIA X"
    # vs "MERCY HOUSING CALIFORNIA XIV", are different entities
    if numbers_in(c1) != numbers_in(c2):
        n_skipped_numbers += 1
        continue
    for v1 in raw_by_clean[c1]:
        for v2 in raw_by_clean[c2]:
            a, b = sorted([v1, v2])
            pairs.append(("Similar name", int(scores[i, j]), a, b))

log(f"Similar-name pairs at or above {config.VENDOR_MATCH_THRESHOLD}: {len(pairs) - n_identical:,}")
log(f"Similar pairs skipped because the numbers or Roman numerals in the names differ: {n_skipped_numbers:,}")

name_pairs = pd.DataFrame(pairs, columns=["match_type", "similarity", "vendor_1", "vendor_2"])
name_pairs = name_pairs.drop_duplicates(subset=["vendor_1", "vendor_2"])
name_pairs["similarity"] = name_pairs["similarity"].astype("int64")
con.register("name_pairs", name_pairs)


# ---------------------------------------------------------------
# C. Evidence and confidence
# ---------------------------------------------------------------
log.section("5C. VENDOR DUPLICATE CANDIDATES")
run_sql_file(con, "05b_vendor_candidates.sql", SETTINGS)

log(f"{'Confidence':<12}{'pairs':>8}{'paid to both names combined':>32}")
for conf, n, amt in con.execute("""
    SELECT confidence, COUNT(*), SUM(total_paid_1 + total_paid_2)
    FROM vendor_candidates
    GROUP BY confidence
    ORDER BY CASE confidence WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END
""").fetchall():
    log(f"{conf:<12}{n:>8,}{money(amt):>32}")

n_shared = con.execute(
    "SELECT COUNT(*) FROM vendor_candidates WHERE shared_contracts > 0 OR shared_pos > 0"
).fetchone()[0]
log(f"\nPairs where the same contract or PO was paid under both names: {n_shared:,}")

log("\nTop 20 candidates:")
for row in con.execute("""
    SELECT candidate_id, confidence, match_type, similarity, vendor_1, vendor_2,
           payments_1, payments_2, total_paid_1, total_paid_2,
           departments_1, departments_2, shared_contracts, shared_pos
    FROM vendor_candidates ORDER BY candidate_id LIMIT 20
""").fetchall():
    (cid, conf, mtype, sim, v1, v2, p1, p2, t1, t2, d1, d2, sc, sp) = row
    log(f"\n#{cid} [{conf}] {mtype}, similarity {sim}")
    log(f"   1: {v1}  | {p1:,} payments, {money(t1)} | depts: {d1}")
    log(f"   2: {v2}  | {p2:,} payments, {money(t2)} | depts: {d2}")
    if sc or sp:
        log(f"   shared: {sc} contract(s), {sp} PO(s)")


log("\nAll Medium-confidence candidates:")
for row in con.execute("""
    SELECT candidate_id, similarity, vendor_1, vendor_2, payments_1, payments_2,
           total_paid_1, total_paid_2, departments_1, departments_2
    FROM vendor_candidates WHERE confidence = 'Medium' ORDER BY candidate_id
""").fetchall():
    (cid, sim, v1, v2, p1, p2, t1, t2, d1, d2) = row
    log(f"\n#{cid} [Medium] similarity {sim}")
    log(f"   1: {v1}  | {p1:,} payments, {money(t1)} | depts: {d1}")
    log(f"   2: {v2}  | {p2:,} payments, {money(t2)} | depts: {d2}")

log("\nTop 15 Low-confidence candidates by combined amount:")
for row in con.execute("""
    SELECT candidate_id, similarity, vendor_1, vendor_2, total_paid_1, total_paid_2
    FROM vendor_candidates WHERE confidence = 'Low'
    ORDER BY total_paid_1 + total_paid_2 DESC LIMIT 15
""").fetchall():
    (cid, sim, v1, v2, t1, t2) = row
    log(f"- #{cid} ({sim}): {v1} [{money(t1)}]  vs  {v2} [{money(t2)}]")

log("\nHigh-confidence candidates not shown above:")
for row in con.execute("""
    SELECT candidate_id, match_type, vendor_1, vendor_2, payments_1, payments_2, total_paid_1, total_paid_2
    FROM vendor_candidates WHERE confidence = 'High' AND candidate_id > 20 ORDER BY candidate_id
""").fetchall():
    (cid, mtype, v1, v2, p1, p2, t1, t2) = row
    log(f"- #{cid} {mtype}: {v1} [{p1:,}, {money(t1)}]  vs  {v2} [{p2:,}, {money(t2)}]")


# ---------------------------------------------------------------
# D. Same amount paid to both names
# ---------------------------------------------------------------
log.section("5D. SAME AMOUNT PAID TO BOTH NAMES")
run_sql_file(con, "05c_cross_vendor_payments.sql", SETTINGS)

n_matches, amt_matches = con.execute(
    "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM cross_vendor_matches"
).fetchone()
log(f"Matching payments found: {n_matches:,}, {money(amt_matches)}")

for conf, n, amt in con.execute("""
    SELECT confidence, COUNT(*), SUM(amount) FROM cross_vendor_matches
    GROUP BY confidence ORDER BY CASE confidence WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END
""").fetchall():
    log(f"- {conf} confidence vendor pairs: {n:,} matches, {money(amt)}")

log("\nTop 15 matches by amount:")
for row in con.execute("""
    SELECT candidate_id, confidence, amount, vendor_1, vendor_2, department_1, department_2,
           date_1, date_2, days_apart, spend_type
    FROM cross_vendor_matches ORDER BY amount DESC LIMIT 15
""").fetchall():
    (cid, conf, amt, v1, v2, d1, d2, dt1, dt2, days, spend) = row
    log(f"\ncandidate #{cid} [{conf}] {money(amt)}  {spend}")
    log(f"   1: {v1} | {d1} | {dt1}")
    log(f"   2: {v2} | {d2} | {dt2}  ({days} days apart)")


# ---------------------------------------------------------------
# Save
# ---------------------------------------------------------------
con.execute(f"""
    COPY (
        SELECT c.*,
               COALESCE(m.matches, 0)      AS same_amount_matches,
               COALESCE(m.matched_amt, 0)  AS same_amount_total,
               ''                          AS reviewer_assessment,
               ''                          AS rationale
        FROM vendor_candidates c
        LEFT JOIN (
            SELECT candidate_id, COUNT(*) AS matches, SUM(amount) AS matched_amt
            FROM cross_vendor_matches GROUP BY candidate_id
        ) m USING (candidate_id)
        ORDER BY c.candidate_id
    ) TO '{config.VENDOR_CANDIDATES_FILE}' (HEADER, DELIMITER ',')
""")
con.execute(f"""
    COPY (SELECT * FROM cross_vendor_matches ORDER BY amount DESC)
    TO '{config.CROSS_VENDOR_FILE}' (HEADER, DELIMITER ',')
""")
con.close()

log(f"\nSaved: {config.VENDOR_CANDIDATES_FILE}")
log(f"Saved: {config.CROSS_VENDOR_FILE}")
log.save()
