"""
Run the whole project in order with one command:

    python run_pipeline.py              run everything (skips the download if data exists)
    python run_pipeline.py --refresh    download a fresh copy of the data first
    python run_pipeline.py --profile    also run the data profiling step
    python run_pipeline.py --from 4     start from step 4 (reuses earlier outputs)

Each step writes a log to outputs/logs/.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(ROOT, "data", "raw", "sf_vouchers_fy2026.parquet")

STEPS = [
    (0, "00_profile_data.py",       "Profile the source data"),
    (1, "01_extract.py",            "Download fiscal year payments from DataSF"),
    (2, "02_prepare.py",            "One row per payment, standardized vendor names"),
    (3, "03_duplicate_payments.py", "Apply scope, run duplicate payment test"),
    (4, "04_refine_duplicates.py",  "Label explainable flags, score and rank the rest"),
    (5, "05_duplicate_vendors.py",  "Duplicate vendor test and cross-vendor payments"),
    (6, "06_build_workpaper.py",    "Build Excel workpaper and results summary"),
]


def main():
    args = sys.argv[1:]
    refresh = "--refresh" in args
    profile = "--profile" in args
    start = 0
    if "--from" in args:
        start = int(args[args.index("--from") + 1])

    for number, script, description in STEPS:
        if number < start:
            continue
        if number == 0 and not profile:
            continue
        if number == 1 and os.path.exists(RAW_FILE) and not refresh:
            print(f"\n[Step 1] Data already downloaded, skipping (use --refresh to re-download)")
            continue

        print("\n" + "#" * 70)
        print(f"[Step {number}] {description}")
        print("#" * 70)
        t0 = time.time()
        result = subprocess.run([sys.executable, os.path.join("src", script)], cwd=ROOT)
        if result.returncode != 0:
            print(f"\nStep {number} failed. Fix the error above, then rerun with: python run_pipeline.py --from {number}")
            sys.exit(result.returncode)
        print(f"[Step {number}] done in {time.time() - t0:.0f}s")

    print("\nPipeline complete.")
    print("Workpaper: outputs/workpaper/SF_AP_Controls_Workpaper_FY2026.xlsx")
    print("Summary:   docs/results_summary.md")


if __name__ == "__main__":
    main()
