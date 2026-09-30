"""
Step 0: Data profiling (schema check) for San Francisco Vendor Payments (Vouchers)

What this does:
  1. Lists every column in the dataset with its type and description
  2. Shows row counts by fiscal year
  3. Pulls a sample of the most recent complete fiscal year and reports
     how complete each column is (missing values, unique values)
  4. Shows 5 example rows

Nothing is analyzed yet. The output tells us which control tests the data
can actually support. Everything printed is also saved to outputs/logs/00_profile_data.txt.
"""

import sys
import requests
import pandas as pd

import config

DATASET_ID = config.DATASET_ID
DOMAINS = config.DOMAINS
OUTPUT_FILE = "outputs/logs/00_profile_data.txt"
TIMEOUT = 90
SAMPLE_SIZE = 5000

lines = []


def log(text=""):
    print(text)
    lines.append(str(text))


def get_json(path, params=None):
    """Try each SF domain until one responds."""
    last_error = None
    for domain in DOMAINS:
        url = f"https://{domain}{path}"
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Could not fetch {path}. Last error: {last_error}")


def save_and_exit(code=0):
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(lines))
    print(f"\nSaved output to {OUTPUT_FILE}")
    sys.exit(code)


# ---------------------------------------------------------------
# 1. Column list
# ---------------------------------------------------------------
log("=" * 70)
log("1. COLUMNS")
log("=" * 70)
try:
    meta = get_json(f"/api/views/{DATASET_ID}.json")
except RuntimeError as e:
    log(f"ERROR: {e}")
    save_and_exit(1)

log(f"Dataset: {meta.get('name')}")
columns = meta.get("columns", [])
log(f"Number of columns: {len(columns)}\n")
for c in columns:
    desc = (c.get("description") or "").replace("\n", " ")
    if len(desc) > 120:
        desc = desc[:120] + "..."
    log(f"- {c.get('fieldName')}  |  {c.get('dataTypeName')}  |  {c.get('name')}")
    if desc:
        log(f"    {desc}")

# ---------------------------------------------------------------
# 2. Row counts by fiscal year
# ---------------------------------------------------------------
log("\n" + "=" * 70)
log("2. ROWS BY FISCAL YEAR")
log("=" * 70)
try:
    fy_counts = get_json(
        f"/resource/{DATASET_ID}.json",
        params={
            "$select": "fiscal_year, count(*) AS n",
            "$group": "fiscal_year",
            "$order": "fiscal_year",
        },
    )
except RuntimeError as e:
    log(f"ERROR: {e}")
    save_and_exit(1)

for row in fy_counts:
    log(f"{row.get('fiscal_year')}: {int(row.get('n', 0)):,} rows")

# Pick the most recent complete fiscal year (July 2025 to June 2026)
years = [r.get("fiscal_year") for r in fy_counts if r.get("fiscal_year")]
target_fy = next((y for y in years if "2025" in y and "2026" in y), None)
if target_fy is None and len(years) >= 2:
    target_fy = years[-2]
log(f"\nTarget fiscal year for the project: {target_fy}")

# ---------------------------------------------------------------
# 3. Completeness check on a sample of the target year
# ---------------------------------------------------------------
log("\n" + "=" * 70)
log(f"3. DATA COMPLETENESS (sample of {SAMPLE_SIZE:,} rows from {target_fy})")
log("=" * 70)
try:
    sample = get_json(
        f"/resource/{DATASET_ID}.json",
        params={"$where": f"fiscal_year = '{target_fy}'", "$limit": SAMPLE_SIZE},
    )
except RuntimeError as e:
    log(f"ERROR: {e}")
    save_and_exit(1)

df = pd.DataFrame(sample)
log(f"Rows returned: {len(df):,}\n")
log(f"{'column':<40}{'% missing':>12}{'unique values':>16}")
for col in df.columns:
    pct_missing = df[col].isna().mean() * 100
    n_unique = df[col].nunique(dropna=True)
    log(f"{col:<40}{pct_missing:>11.1f}%{n_unique:>16,}")

# Date ranges for anything that looks like a date
date_cols = [c for c in df.columns if "date" in c.lower()]
if date_cols:
    log("\nDate ranges in sample:")
    for col in date_cols:
        d = pd.to_datetime(df[col], errors="coerce")
        log(f"- {col}: {d.min()} to {d.max()}")
else:
    log("\nNo date columns found in sample.")

# ---------------------------------------------------------------
# 4. Example rows
# ---------------------------------------------------------------
log("\n" + "=" * 70)
log("4. EXAMPLE ROWS")
log("=" * 70)
for i, row in df.head(5).iterrows():
    log(f"\n--- Row {i + 1} ---")
    for col, val in row.items():
        val = str(val)
        if len(val) > 80:
            val = val[:80] + "..."
        log(f"{col}: {val}")

save_and_exit(0)
