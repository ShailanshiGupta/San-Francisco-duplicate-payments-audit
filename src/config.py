"""
Project settings. Every threshold and rule parameter lives here, so the
tests can be adjusted in one place and every run is reproducible.
"""

import os

# ---------------------------------------------------------------
# Data source
# ---------------------------------------------------------------
DATASET_ID = "n9pm-xkyq"                  # SF Vendor Payments (Vouchers)
DOMAINS = ["data.sfgov.org", "data.sf.gov"]
FISCAL_YEAR = "2026"                      # July 1, 2025 to June 30, 2026

# ---------------------------------------------------------------
# Scope
# ---------------------------------------------------------------
# Spending categories treated as purchasing from suppliers
IN_SCOPE_CHARACTERS = ["NON_PERS_SVCS", "MTL_SUPP", "CAP_OUTLAY"]
# Sub-categories inside those that are not purchases
EXCLUDED_OBJECTS = ["Taxes: Licenses/Permits"]

# ---------------------------------------------------------------
# Duplicate payment test (Steps 3 and 4)
# ---------------------------------------------------------------
MIN_AMOUNT = 1000              # smallest payment tested
HIGH_WINDOW_DAYS = 30          # same PO within this many days = HIGH risk
MEDIUM_WINDOW_DAYS = 14        # any PO within this many days = MEDIUM risk
RECURRING_MIN_COUNT = 4        # same exact amount this many times = recurring
MONTHLY_MIN_MONTHS = 3         # same vendor + PO + amount in this many months = monthly
REVIEW_LIST_SIZE = 25          # flags on the manual review list
# Recurring overpayment check: a vendor + amount paid in at least MONTHLY_MIN_MONTHS
# months, usually once a month (payments no more than this multiple of months),
# where some month has more than one payment
OVERFLOW_MAX_RATIO = 1.5

# ---------------------------------------------------------------
# Duplicate vendor test (Step 5)
# ---------------------------------------------------------------
VENDOR_MATCH_THRESHOLD = 90     # name similarity score (0-100) to flag a pair
VENDOR_MIN_NAME_LENGTH = 6      # skip very short names, which match too easily
CROSS_VENDOR_WINDOW_DAYS = 30   # same amount to both names within this window

# ---------------------------------------------------------------
# Paths (all relative to the project folder)
# ---------------------------------------------------------------
RAW_DIR = os.path.join("data", "raw")
PROCESSED_DIR = os.path.join("data", "processed")
SQL_DIR = "sql"
OUTPUT_DIR = "outputs"
EXCEPTIONS_DIR = os.path.join(OUTPUT_DIR, "exceptions")
REVIEW_DIR = os.path.join(OUTPUT_DIR, "review")
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
WORKPAPER_DIR = os.path.join(OUTPUT_DIR, "workpaper")
DOCS_DIR = "docs"

RAW_FILE = os.path.join(RAW_DIR, f"sf_vouchers_fy{FISCAL_YEAR}.parquet")
RAW_CSV = os.path.join(RAW_DIR, f"sf_vouchers_fy{FISCAL_YEAR}.csv")
PAYMENTS_FILE = os.path.join(PROCESSED_DIR, "payments.parquet")
SCOPED_FILE = os.path.join(PROCESSED_DIR, "scoped_payments.parquet")
SCOPE_SUMMARY_FILE = os.path.join(OUTPUT_DIR, "scope_summary.csv")
PAIRS_FILE = os.path.join(EXCEPTIONS_DIR, "duplicate_payment_pairs.csv")
REFINED_FILE = os.path.join(EXCEPTIONS_DIR, "duplicate_flags_refined.csv")
REVIEW_FILE = os.path.join(REVIEW_DIR, "top25_review_list.csv")
VENDOR_CANDIDATES_FILE = os.path.join(EXCEPTIONS_DIR, "vendor_duplicate_candidates.csv")
CROSS_VENDOR_FILE = os.path.join(EXCEPTIONS_DIR, "cross_vendor_payment_matches.csv")
WORKPAPER_FILE = os.path.join(WORKPAPER_DIR, f"SF_AP_Controls_Workpaper_FY{FISCAL_YEAR}.xlsx")
RESULTS_SUMMARY_FILE = os.path.join(DOCS_DIR, "results_summary.md")
OVERFLOW_FILE = os.path.join(EXCEPTIONS_DIR, "recurring_overpayments.csv")

# Reviewer notes: written by a person, merged into the workpaper
NOTES_DIR = "review_notes"
DUP_NOTES_FILE = os.path.join(NOTES_DIR, "duplicate_review_notes.csv")
VENDOR_NOTES_FILE = os.path.join(NOTES_DIR, "vendor_review_notes.csv")

for _d in [RAW_DIR, PROCESSED_DIR, EXCEPTIONS_DIR, REVIEW_DIR, LOG_DIR, WORKPAPER_DIR, DOCS_DIR, NOTES_DIR]:
    os.makedirs(_d, exist_ok=True)
