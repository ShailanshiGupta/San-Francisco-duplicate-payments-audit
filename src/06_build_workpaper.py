"""
Step 6: Build the Excel audit workpaper and the results summary

Collects every result from Steps 3 to 5 into one workbook a reviewer can
work through, plus a markdown summary of the key numbers for the README
and memo.

Input:  data/processed/scoped_payments.parquet
        outputs/scope_summary.csv
        outputs/exceptions/duplicate_flags_refined.csv
        outputs/review/top25_review_list.csv
        outputs/exceptions/vendor_duplicate_candidates.csv
        outputs/exceptions/cross_vendor_payment_matches.csv
        outputs/exceptions/recurring_overpayments.csv
        review_notes/*.csv                     (reviewer assessments, optional)
Output: outputs/workpaper/SF_AP_Controls_Workpaper_FY2026.xlsx
        docs/results_summary.md
        docs/audit_memo.md                     (filled from docs/audit_memo_template.md)

Sheets:
  Overview              purpose, legend, settings, how to review
  Summary               key figures, flag status, review progress (formulas)
  Scope                 what was tested and what was excluded, with a tie-out
  Duplicate Review      top flags, with columns for the reviewer's assessment
  Open Duplicate Flags  every flag still open after refinement
  All Duplicate Flags   every flag from Step 3, for the audit trail
  Vendor Candidates     similar vendor names, with columns for assessment
  Cross-Vendor Matches  same amount paid to both names of a candidate pair
  Recurring Overpayments monthly bills paid more than once in a month
  Methodology           how each test works and its limits
"""

import datetime as dt
import os

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import config
from common import Logger, money

FONT = "Arial"
MONEY_FMT = '$#,##0.00;($#,##0.00);"-"'
INT_FMT = '#,##0;(#,##0);"-"'
DATE_FMT = "yyyy-mm-dd"
HEADER_FILL = PatternFill("solid", start_color="1F3864")
INPUT_FILL = PatternFill("solid", start_color="FFFF00")
SECTION_FILL = PatternFill("solid", start_color="D9E1F2")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

DUP_ASSESSMENTS = ["Likely legitimate", "Needs inquiry", "Likely duplicate"]
VENDOR_ASSESSMENTS = ["Same supplier", "Different suppliers", "Needs inquiry"]

OPEN = "Open: needs review"


# ===================================================================
# Collect results
# ===================================================================
def compute_metrics():
    import duckdb

    con = duckdb.connect()
    con.execute(f"CREATE VIEW scoped AS SELECT * FROM read_parquet('{config.SCOPED_FILE}')")
    m = {}
    m["total_payments"], m["total_paid"] = con.execute(
        "SELECT COUNT(*), ROUND(SUM(amount_paid), 2) FROM scoped").fetchone()
    m["vendor_names"] = con.execute("SELECT COUNT(DISTINCT vendor) FROM scoped").fetchone()[0]
    m["in_scope_payments"], m["in_scope_paid"] = con.execute(
        "SELECT COUNT(*), ROUND(SUM(amount_paid), 2) FROM scoped WHERE scope_status = 'IN SCOPE'").fetchone()
    m["tested_payments"], m["tested_paid"] = con.execute(
        f"SELECT COUNT(*), ROUND(SUM(amount_paid), 2) FROM scoped "
        f"WHERE scope_status = 'IN SCOPE' AND amount_paid >= {config.MIN_AMOUNT}").fetchone()
    con.close()
    return m


ID_COLS = ["po_1", "po_2", "voucher_1", "voucher_2", "purchase_orders", "vouchers",
           "contract_number", "purchase_order"]


def read_csv(path, dates=()):
    """Read a pipeline CSV, keeping PO and voucher numbers as text (leading zeros)."""
    cols = pd.read_csv(path, nrows=0).columns
    df = pd.read_csv(path, dtype={c: str for c in cols if c in ID_COLS})
    for col in dates:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def load_frames():
    date_cols = ["date_1", "date_2", "first_payment_1", "last_payment_1",
                 "first_payment_2", "last_payment_2", "pay_month", "first_date", "last_date"]
    frames = {
        "scope": read_csv(config.SCOPE_SUMMARY_FILE),
        "refined": read_csv(config.REFINED_FILE, date_cols),
        "review": read_csv(config.REVIEW_FILE, date_cols),
        "vendors": read_csv(config.VENDOR_CANDIDATES_FILE, date_cols),
        "cross": read_csv(config.CROSS_VENDOR_FILE, date_cols),
        "overflow": read_csv(config.OVERFLOW_FILE, date_cols),
    }
    for col in ["reviewer_assessment", "rationale", "next_step"]:
        frames["overflow"][col] = None
    return frames


def _amount_key(series):
    return series.astype(float).round(2).map("{:.2f}".format)


def apply_notes(frames, log=print):
    """Fill the reviewer columns from the notes files in review_notes/."""
    review, vendors = frames["review"], frames["vendors"]
    note_cols = ["reviewer_assessment", "rationale", "next_step"]

    if os.path.exists(config.DUP_NOTES_FILE) and len(review):
        notes = pd.read_csv(config.DUP_NOTES_FILE, dtype={"po_2": str})
        notes["_key"] = notes["vendor"] + "|" + _amount_key(notes["amount"]) + "|" + notes["po_2"]
        review["_key"] = review["vendor"] + "|" + _amount_key(review["amount"]) + "|" + review["po_2"].astype(str)
        lookup = notes.drop_duplicates("_key").set_index("_key")
        for col in note_cols:
            review[col] = review[col].astype(object)
            review[col] = review["_key"].map(lookup[col]).combine_first(review[col])
        matched = review["_key"].isin(lookup.index).sum()
        unused = (~lookup.index.isin(review["_key"])).sum()
        log(f"Duplicate review notes applied to {matched} of {len(review)} review rows"
            + (f" ({unused} notes did not match any row, check if the data changed)" if unused else ""))
        review.drop(columns="_key", inplace=True)

    if os.path.exists(config.VENDOR_NOTES_FILE) and len(vendors):
        notes = pd.read_csv(config.VENDOR_NOTES_FILE)
        pair_key = lambda a, b: a.combine(b, lambda x, y: "|".join(sorted([str(x), str(y)])))
        notes["_key"] = pair_key(notes["vendor_1"], notes["vendor_2"])
        vendors["_key"] = pair_key(vendors["vendor_1"], vendors["vendor_2"])
        lookup = notes.drop_duplicates("_key").set_index("_key")
        for col in ["reviewer_assessment", "rationale"]:
            vendors[col] = vendors[col].astype(object)
            vendors[col] = vendors["_key"].map(lookup[col]).combine_first(vendors[col])
        matched = vendors["_key"].isin(lookup.index).sum()
        log(f"Vendor review notes applied to {matched} of {len(vendors)} candidate pairs")
        vendors.drop(columns="_key", inplace=True)
    return frames


def excess_bills(overflow):
    """One row per monthly bill paid more times than the months it covers."""
    if not len(overflow):
        return overflow
    x = overflow[overflow["pattern"].str.startswith("Excess")]
    return x.drop_duplicates(subset=["vendor", "amount", "payments_in_year", "span_months"])


def flag_status_table(refined):
    """One row per questioned payment, keeping 'open' if any of its pairs is open."""
    df = refined.copy()
    df["_open_first"] = (df["refined_status"] != OPEN).astype(int)
    df = df.sort_values(["row_id_2", "_open_first"]).drop_duplicates("row_id_2")
    out = (df.groupby("refined_status")
             .agg(payments=("row_id_2", "count"), amount=("amount", "sum"))
             .reset_index()
             .sort_values("amount", ascending=False))
    return out


# ===================================================================
# Formatting helpers
# ===================================================================
def style_header(cell):
    cell.font = Font(name=FONT, bold=True, color="FFFFFF")
    cell.fill = HEADER_FILL
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    cell.border = BORDER


def write_title(ws, title, subtitle=None):
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    if subtitle:
        ws["A2"] = subtitle
        ws["A2"].font = Font(name=FONT, italic=True, color="595959")


def write_table(ws, df, start_row, money_cols=(), int_cols=(), input_cols=(),
                widths=None, freeze=True, autofilter=True):
    """Write a DataFrame as a formatted table. Returns (first_data_row, last_data_row, col_letters)."""
    cols = list(df.columns)
    letters = {c: get_column_letter(i + 1) for i, c in enumerate(cols)}
    for i, col in enumerate(cols, start=1):
        style_header(ws.cell(row=start_row, column=i, value=col))
    for r, row in enumerate(df.itertuples(index=False), start=start_row + 1):
        for i, (col, value) in enumerate(zip(cols, row), start=1):
            if isinstance(value, float) and pd.isna(value):
                value = None
            elif isinstance(value, pd.Timestamp):
                value = None if pd.isna(value) else value.to_pydatetime()
            cell = ws.cell(row=r, column=i, value=value)
            cell.font = Font(name=FONT)
            cell.border = BORDER
            if col in money_cols:
                cell.number_format = MONEY_FMT
            elif col in int_cols:
                cell.number_format = INT_FMT
            elif isinstance(value, (dt.datetime, dt.date)):
                cell.number_format = DATE_FMT
            if col in input_cols:
                cell.fill = INPUT_FILL
    last = start_row + len(df)
    for i, col in enumerate(cols, start=1):
        width = (widths or {}).get(col)
        if width is None:
            sample = [len(str(col))] + [len(str(v)) for v in df[col].head(200).tolist()]
            width = min(max(sample) + 2, 45)
        ws.column_dimensions[get_column_letter(i)].width = width
    if freeze:
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    if autofilter and len(df):
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(cols))}{last}"
    return start_row + 1, last, letters


def add_dropdown(ws, col_letter, first, last, options):
    if last < first:
        return
    dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
    dv.error = "Pick one of the listed options"
    dv.prompt = "Choose: " + ", ".join(options)
    ws.add_data_validation(dv)
    dv.add(f"{col_letter}{first}:{col_letter}{last}")


def label(ws, cell, text, bold=False):
    ws[cell] = text
    ws[cell].font = Font(name=FONT, bold=bold)


def section_row(ws, row, text, ncols=4):
    for c in range(1, ncols + 1):
        ws.cell(row=row, column=c).fill = SECTION_FILL
    ws.cell(row=row, column=1, value=text).font = Font(name=FONT, bold=True)


def value_cell(ws, cell, value, fmt=None, source=None):
    """A hardcoded number from the pipeline: blue font, with its source noted."""
    ws[cell] = value
    ws[cell].font = Font(name=FONT, color="0000FF")
    if fmt:
        ws[cell].number_format = fmt
    if source:
        ws[cell].comment = Comment(f"Source: {source}", "pipeline")


def formula_cell(ws, cell, formula, fmt=None, bold=False):
    ws[cell] = formula
    ws[cell].font = Font(name=FONT, bold=bold)
    if fmt:
        ws[cell].number_format = fmt


# ===================================================================
# Build workbook
# ===================================================================
def build_workpaper(m, frames, path):
    wb = Workbook()
    ws_over = wb.active
    ws_over.title = "Overview"
    ws_sum = wb.create_sheet("Summary")
    ws_scope = wb.create_sheet("Scope")
    ws_rev = wb.create_sheet("Duplicate Review")
    ws_open = wb.create_sheet("Open Duplicate Flags")
    ws_all = wb.create_sheet("All Duplicate Flags")
    ws_ven = wb.create_sheet("Vendor Candidates")
    ws_cross = wb.create_sheet("Cross-Vendor Matches")
    ws_over_pay = wb.create_sheet("Recurring Overpayments")
    ws_meth = wb.create_sheet("Methodology")

    refined = frames["refined"]

    # ---------------- Scope ----------------
    write_title(ws_scope, "Scope: what was tested and what was excluded",
                "Every payment in the fiscal year carries exactly one scope label. Totals tie back to the full dataset.")
    scope = frames["scope"]
    s_first, s_last, s_cols = write_table(
        ws_scope, scope, 4, money_cols=["amount_paid"], int_cols=["payments"],
        widths={"scope_status": 32, "character_code": 20, "character": 38}, autofilter=True)
    tot = s_last + 2
    label(ws_scope, f"A{tot}", "Total, all labels", bold=True)
    formula_cell(ws_scope, f"{s_cols['payments']}{tot}",
                 f"=SUM({s_cols['payments']}{s_first}:{s_cols['payments']}{s_last})", INT_FMT, True)
    formula_cell(ws_scope, f"{s_cols['amount_paid']}{tot}",
                 f"=SUM({s_cols['amount_paid']}{s_first}:{s_cols['amount_paid']}{s_last})", MONEY_FMT, True)
    label(ws_scope, f"A{tot + 1}", "Difference from Summary total (should be zero)")
    formula_cell(ws_scope, f"{s_cols['amount_paid']}{tot + 1}",
                 f"=ROUND({s_cols['amount_paid']}{tot}-Summary!$B$6,2)", MONEY_FMT)
    ws_scope.freeze_panes = "A5"

    # ---------------- Duplicate Review ----------------
    write_title(ws_rev, f"Duplicate payment review: top {config.REVIEW_LIST_SIZE} open flags",
                "Yellow columns are for the reviewer. Pick an assessment from the dropdown and note the reasoning.")
    review = frames["review"]
    r_first, r_last, r_cols = write_table(
        ws_rev, review, 4,
        money_cols=["amount", "po_total_paid"], int_cols=["po_payment_count"],
        input_cols=["reviewer_assessment", "rationale", "next_step"],
        widths={"vendor": 36, "department_1": 28, "department_2": 28, "spend_type": 30,
                "reviewer_assessment": 20, "rationale": 50, "next_step": 30})
    add_dropdown(ws_rev, r_cols["reviewer_assessment"], r_first, r_last, DUP_ASSESSMENTS)
    for r in range(r_first, r_last + 1):
        for c in ["rationale", "next_step"]:
            ws_rev[f"{r_cols[c]}{r}"].alignment = Alignment(wrap_text=True, vertical="top")

    # ---------------- Open / All flags ----------------
    write_title(ws_open, "Every duplicate flag still open after refinement",
                "Sorted by priority score. The Duplicate Review sheet holds the top of this list.")
    open_cols = ["flag_id", "priority_score", "risk_tier", "amount", "vendor_1", "vendor_2",
                 "department_1", "department_2", "po_1", "po_2", "voucher_1", "voucher_2",
                 "date_1", "date_2", "days_apart", "spend_type_2", "same_po", "same_department"]
    open_df = (refined[refined["refined_status"] == OPEN]
               .sort_values(["priority_score", "amount"], ascending=[False, False]))
    write_table(ws_open, open_df[[c for c in open_cols if c in open_df.columns]], 4,
                money_cols=["amount"], widths={"vendor_1": 34, "vendor_2": 34, "spend_type_2": 30})

    write_title(ws_all, "Every pair flagged by the duplicate payment test (audit trail)",
                "status = label from Step 3. refined_status = label after Step 4. Nothing was removed.")
    all_cols = ["flag_id", "risk_tier", "status", "refined_status", "priority_score", "amount",
                "vendor_1", "vendor_2", "department_1", "department_2", "po_1", "po_2",
                "voucher_1", "voucher_2", "date_1", "date_2", "days_apart", "spend_type_2",
                "same_po", "same_department", "times_vendor_paid_this_amount", "months_paid",
                "reversal_found"]
    write_table(ws_all, refined.sort_values("flag_id")[[c for c in all_cols if c in refined.columns]], 4,
                money_cols=["amount"], widths={"status": 32, "refined_status": 42, "vendor_1": 34, "vendor_2": 34})

    # ---------------- Vendor Candidates ----------------
    write_title(ws_ven, "Duplicate vendor candidates: similar names that may be one supplier",
                "Yellow columns are for the reviewer. High = shared contract or PO, or identical after cleanup.")
    vendors = frames["vendors"]
    v_first, v_last, v_cols = write_table(
        ws_ven, vendors, 4,
        money_cols=["total_paid_1", "total_paid_2", "same_amount_total"],
        int_cols=["payments_1", "payments_2"],
        input_cols=["reviewer_assessment", "rationale"],
        widths={"vendor_1": 36, "vendor_2": 36, "departments_1": 22, "departments_2": 22,
                "reviewer_assessment": 20, "rationale": 50})
    add_dropdown(ws_ven, v_cols["reviewer_assessment"], v_first, v_last, VENDOR_ASSESSMENTS)

    write_title(ws_cross, "Same amount paid to both names of a vendor candidate pair",
                f"Within {config.CROSS_VENDOR_WINDOW_DAYS} days, payments of at least ${config.MIN_AMOUNT:,}.")
    cross = frames["cross"]
    write_table(ws_cross, cross, 4, money_cols=["amount"],
                widths={"vendor_1": 34, "vendor_2": 34, "spend_type": 30})

    # ---------------- Recurring Overpayments ----------------
    write_title(ws_over_pay, "Monthly bills paid more than once in a month",
                "A vendor + amount paid in most months about once a month, where some month shows extra payments. Yellow columns are for the reviewer.")
    overflow = frames["overflow"]
    o_first, o_last, o_cols = write_table(
        ws_over_pay, overflow, 4,
        money_cols=["amount", "extra_amount", "excess_amount_in_year"],
        input_cols=["reviewer_assessment", "rationale", "next_step"],
        widths={"vendor": 36, "departments": 28, "pattern": 40, "purchase_orders": 26, "vouchers": 30,
                "spend_type": 30, "reviewer_assessment": 20, "rationale": 50, "next_step": 30})
    add_dropdown(ws_over_pay, o_cols["reviewer_assessment"], o_first, o_last, DUP_ASSESSMENTS)

    # ---------------- Summary ----------------
    write_title(ws_sum, f"Summary: San Francisco AP controls review, FY{config.FISCAL_YEAR}",
                "Blue = value from the pipeline (hover for source). Black = formula.")
    ws_sum.column_dimensions["A"].width = 58
    ws_sum.column_dimensions["B"].width = 22
    ws_sum.column_dimensions["C"].width = 22
    ws_sum.column_dimensions["D"].width = 40

    section_row(ws_sum, 4, "A. Population and scope")
    label(ws_sum, "B5", "Amount", True)
    label(ws_sum, "C5", "Payments", True)
    rows = [
        ("All payments, fiscal year", m["total_paid"], m["total_payments"], "data/processed/scoped_payments.parquet, all rows"),
        ("In scope (supplier purchases)", m["in_scope_paid"], m["in_scope_payments"], "scope_status = IN SCOPE"),
        (f"Tested for duplicates (in scope, at least ${config.MIN_AMOUNT:,})", m["tested_paid"], m["tested_payments"], "Step 3 test_base"),
    ]
    # B6 (all payments, amount) is what the Scope sheet ties out to
    for i, (text, amt, n, src) in enumerate(rows):
        r = 6 + i
        label(ws_sum, f"A{r}", text)
        value_cell(ws_sum, f"B{r}", amt, MONEY_FMT, src)
        value_cell(ws_sum, f"C{r}", n, INT_FMT, src)
    label(ws_sum, "A9", "Share of all spending that is in scope")
    formula_cell(ws_sum, "B9", "=IF(B6=0,0,B7/B6)", "0.0%")

    section_row(ws_sum, 11, "B. Duplicate payment flags (each questioned payment counted once)")
    label(ws_sum, "A12", "Status after refinement", True)
    label(ws_sum, "B12", "Amount", True)
    label(ws_sum, "C12", "Payments", True)
    status_tbl = flag_status_table(refined)
    r = 13
    for _, row in status_tbl.iterrows():
        label(ws_sum, f"A{r}", row["refined_status"])
        value_cell(ws_sum, f"B{r}", float(row["amount"]), MONEY_FMT, "duplicate_flags_refined.csv")
        value_cell(ws_sum, f"C{r}", int(row["payments"]), INT_FMT, "duplicate_flags_refined.csv")
        r += 1
    label(ws_sum, f"A{r}", "Total flagged", True)
    formula_cell(ws_sum, f"B{r}", f"=SUM(B13:B{r - 1})", MONEY_FMT, True)
    formula_cell(ws_sum, f"C{r}", f"=SUM(C13:C{r - 1})", INT_FMT, True)
    open_row = next((13 + i for i, s in enumerate(status_tbl["refined_status"]) if s == OPEN), None)
    r += 1
    label(ws_sum, f"A{r}", "Open flags as a share of amount tested")
    formula_cell(ws_sum, f"B{r}", f"=IF(B8=0,0,B{open_row}/B8)" if open_row else "=0", "0.00%")

    r += 2
    section_row(ws_sum, r, f"C. Duplicate review progress (Duplicate Review sheet, top {config.REVIEW_LIST_SIZE})")
    r += 1
    label(ws_sum, f"A{r}", "Assessment", True)
    label(ws_sum, f"B{r}", "Amount", True)
    label(ws_sum, f"C{r}", "Flags", True)
    a_col, amt_col = r_cols["reviewer_assessment"], r_cols["amount"]
    a_rng = f"'Duplicate Review'!${a_col}${r_first}:${a_col}${max(r_last, r_first)}"
    m_rng = f"'Duplicate Review'!${amt_col}${r_first}:${amt_col}${max(r_last, r_first)}"
    first_assess = r + 1
    for opt in DUP_ASSESSMENTS:
        r += 1
        label(ws_sum, f"A{r}", opt)
        formula_cell(ws_sum, f"B{r}", f'=SUMIF({a_rng},"{opt}",{m_rng})', MONEY_FMT)
        formula_cell(ws_sum, f"C{r}", f'=COUNTIF({a_rng},"{opt}")', INT_FMT)
    r += 1
    label(ws_sum, f"A{r}", "Not yet reviewed")
    formula_cell(ws_sum, f"C{r}", f"={max(len(review), 0)}-SUM(C{first_assess}:C{r - 1})", INT_FMT)
    formula_cell(ws_sum, f"B{r}", f"=SUM({m_rng})-SUM(B{first_assess}:B{r - 1})", MONEY_FMT)

    r += 2
    section_row(ws_sum, r, "D. Duplicate vendor candidates")
    r += 1
    label(ws_sum, f"A{r}", "Confidence", True)
    label(ws_sum, f"C{r}", "Pairs", True)
    c_col = v_cols.get("confidence", "B")
    c_rng = f"'Vendor Candidates'!${c_col}${v_first}:${c_col}${max(v_last, v_first)}"
    for conf in ["High", "Medium", "Low"]:
        r += 1
        label(ws_sum, f"A{r}", conf)
        formula_cell(ws_sum, f"C{r}", f'=COUNTIF({c_rng},"{conf}")', INT_FMT)
    r += 1
    va_col = v_cols["reviewer_assessment"]
    va_rng = f"'Vendor Candidates'!${va_col}${v_first}:${va_col}${max(v_last, v_first)}"
    label(ws_sum, f"A{r}", "Pairs assessed so far")
    formula_cell(ws_sum, f"C{r}", f"=COUNTA({va_rng})", INT_FMT)
    r += 1
    label(ws_sum, f"A{r}", "Same amount paid to both names (Cross-Vendor Matches)")
    cross_amt = float(cross["amount"].sum()) if len(cross) else 0.0
    value_cell(ws_sum, f"B{r}", cross_amt, MONEY_FMT, "cross_vendor_payment_matches.csv")
    value_cell(ws_sum, f"C{r}", len(cross), INT_FMT, "cross_vendor_payment_matches.csv")

    r += 2
    section_row(ws_sum, r, "E. Recurring overpayments (monthly bill paid more than once in a month)")
    r += 1
    label(ws_sum, f"B{r}", "Amount", True)
    label(ws_sum, f"C{r}", "Count", True)
    r += 1
    ea_col = o_cols["extra_amount"]
    pt_col = o_cols["pattern"]
    ea_rng = f"'Recurring Overpayments'!${ea_col}${o_first}:${ea_col}${max(o_last, o_first)}"
    pt_rng = f"'Recurring Overpayments'!${pt_col}${o_first}:${pt_col}${max(o_last, o_first)}"
    label(ws_sum, f"A{r}", "All months with more than one payment of a monthly bill")
    formula_cell(ws_sum, f"B{r}", f"=SUM({ea_rng})", MONEY_FMT)
    formula_cell(ws_sum, f"C{r}", f"=COUNT({ea_rng})", INT_FMT)
    for pat in ["Catch-up: within months covered", "Excess: more payments than months covered"]:
        r += 1
        label(ws_sum, f"A{r}", "   " + pat)
        formula_cell(ws_sum, f"B{r}", f'=SUMIF({pt_rng},"{pat}",{ea_rng})', MONEY_FMT)
        formula_cell(ws_sum, f"C{r}", f'=COUNTIF({pt_rng},"{pat}")', INT_FMT)
    r += 1
    label(ws_sum, f"A{r}", "Potential overpayment: payments beyond the months covered, per bill")
    value_cell(ws_sum, f"B{r}", excess_bills(overflow)["excess_amount_in_year"].sum() if len(overflow) else 0.0,
               MONEY_FMT, "recurring_overpayments.csv, excess bills counted once")
    value_cell(ws_sum, f"C{r}", len(excess_bills(overflow)), INT_FMT, "bills")
    r += 1
    oa_col = o_cols["reviewer_assessment"]
    label(ws_sum, f"A{r}", "Months assessed so far")
    formula_cell(ws_sum, f"C{r}", f"=COUNTA('Recurring Overpayments'!${oa_col}${o_first}:${oa_col}${max(o_last, o_first)})", INT_FMT)

    # ---------------- Overview ----------------
    write_title(ws_over, f"San Francisco Vendor Payments: AP Controls Review, FY{config.FISCAL_YEAR}",
                "Fiscal year July 1, 2025 to June 30, 2026. Source: DataSF, Vendor Payments (Vouchers), dataset n9pm-xkyq.")
    ws_over.column_dimensions["A"].width = 30
    ws_over.column_dimensions["B"].width = 95
    lines = [
        ("Purpose", "Test whether the city's payment records show signs of duplicate payments or duplicate vendor records, two common accounts payable control failures."),
        ("How to review", "1. Read Summary. 2. Work through Duplicate Review: pick an assessment in the yellow column and write a short rationale. 3. Do the same on Vendor Candidates and Recurring Overpayments. Summary updates automatically. Notes saved in review_notes/ fill these columns automatically when the pipeline runs."),
        ("Legend: yellow fill", "Your input. Only edit yellow cells."),
        ("Legend: blue text", "Value produced by the pipeline. Hover over the cell to see its source."),
        ("Legend: black text", "Formula. Do not overwrite."),
        ("Example assessment", "Assessment: Likely legitimate. Rationale: Same PO paid monthly across the year at the same amount, consistent with a fixed service fee. Next step: none."),
        ("Important", "A flag is a lead, not a conclusion. The public data has no invoice numbers and only approximate dates, so no payment can be confirmed as a duplicate without the city's records."),
    ]
    r = 4
    for key, text in lines:
        ws_over[f"A{r}"] = key
        ws_over[f"A{r}"].font = Font(name=FONT, bold=True)
        ws_over[f"B{r}"] = text
        ws_over[f"B{r}"].font = Font(name=FONT)
        ws_over[f"B{r}"].alignment = Alignment(wrap_text=True, vertical="top")
        if key == "Legend: yellow fill":
            ws_over[f"A{r}"].fill = INPUT_FILL
        if key == "Legend: blue text":
            ws_over[f"A{r}"].font = Font(name=FONT, bold=True, color="0000FF")
        r += 1
    r += 1
    section_row(ws_over, r, "Settings used (from src/config.py)", ncols=2)
    settings = [
        ("In-scope categories", ", ".join(config.IN_SCOPE_CHARACTERS)),
        ("Excluded sub-categories", ", ".join(config.EXCLUDED_OBJECTS)),
        ("Minimum payment tested", f"${config.MIN_AMOUNT:,}"),
        ("HIGH risk window (same PO)", f"{config.HIGH_WINDOW_DAYS} days"),
        ("MEDIUM risk window (any PO)", f"{config.MEDIUM_WINDOW_DAYS} days"),
        ("Recurring threshold", f"same amount paid {config.RECURRING_MIN_COUNT}+ times"),
        ("Monthly pattern threshold", f"same vendor, PO and amount in {config.MONTHLY_MIN_MONTHS}+ months"),
        ("Vendor name similarity", f"{config.VENDOR_MATCH_THRESHOLD}+ out of 100"),
        ("Cross-vendor window", f"{config.CROSS_VENDOR_WINDOW_DAYS} days"),
    ]
    for key, text in settings:
        r += 1
        ws_over[f"A{r}"] = key
        ws_over[f"A{r}"].font = Font(name=FONT)
        ws_over[f"B{r}"] = text
        ws_over[f"B{r}"].font = Font(name=FONT, color="0000FF")

    # ---------------- Methodology ----------------
    write_title(ws_meth, "Methodology", "Full detail in docs/methodology.md")
    ws_meth.column_dimensions["A"].width = 120
    meth = [
        "1. Data: every vendor payment San Francisco published for fiscal year 2026, downloaded from DataSF.",
        "2. Payment level: rows split across funds were combined into one row per payment. Control total tied to the cent.",
        "3. Payment ID: department + voucher number. Most repeated vouchers were one payment covering several POs.",
        "4. Scope: Non-Personnel Services, Materials & Supplies and Capital Outlay. Payroll taxes, debt service, benefits, grants, aid and refunds were excluded as not supplier purchases.",
        "5. Duplicate payment test: same standardized vendor name and same amount on two different payments. HIGH = same PO within the HIGH window. MEDIUM = any PO within the MEDIUM window.",
        "6. Status: a later reversal for the same vendor and amount = likely resolved. Same amount paid many times in the year = likely recurring.",
        "7. Refinement: monthly patterns, multi-unit equipment orders and repeat supply orders labeled as likely explained. Remaining flags scored 0 to 9 on timing, same PO, size, spend type and cross-department.",
        "8. Duplicate vendor test: names identical after cleanup, or fuzzy similarity at or above the threshold with the same numbers in both names. Confidence raised when the same contract or PO was paid under both names.",
        "9. Cross-vendor check: same amount paid to both names of a candidate pair within the window.",
        "10. Recurring overpayment check: a vendor and amount paid about once a month in at least the monthly threshold of months, where some month has more than one payment. Closes the gap left by the recurring and monthly labels.",
        "Limits: no invoice numbers, approximate dates (data_as_of), no vendor IDs or addresses. Every flag is a lead for inquiry, not a confirmed error.",
    ]
    for i, text in enumerate(meth, start=4):
        ws_meth[f"A{i}"] = text
        ws_meth[f"A{i}"].font = Font(name=FONT)
        ws_meth[f"A{i}"].alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(path)
    return status_tbl


# ===================================================================
# Results summary (markdown)
# ===================================================================
def write_results_summary(m, frames, status_tbl, path):
    refined, vendors, cross, review = frames["refined"], frames["vendors"], frames["cross"], frames["review"]
    overflow = frames["overflow"]
    open_row = status_tbl[status_tbl["refined_status"] == OPEN]
    open_n = int(open_row["payments"].sum()) if len(open_row) else 0
    open_amt = float(open_row["amount"].sum()) if len(open_row) else 0.0
    conf = vendors["confidence"].value_counts().to_dict() if len(vendors) else {}
    lines = [
        f"# Results summary, FY{config.FISCAL_YEAR}",
        "",
        "Generated automatically by `src/06_build_workpaper.py`. Do not edit by hand, rerun the pipeline instead.",
        "",
        "## Population and scope",
        "",
        "| | Payments | Amount |",
        "|---|---:|---:|",
        f"| All payments | {m['total_payments']:,} | {money(m['total_paid'])} |",
        f"| In scope (supplier purchases) | {m['in_scope_payments']:,} | {money(m['in_scope_paid'])} |",
        f"| Tested for duplicates (at least ${config.MIN_AMOUNT:,}) | {m['tested_payments']:,} | {money(m['tested_paid'])} |",
        "",
        "## Duplicate payment test",
        "",
        f"Flagged pairs: {len(refined):,}",
        "",
        "| Status after refinement | Payments | Amount |",
        "|---|---:|---:|",
    ]
    for _, row in status_tbl.iterrows():
        lines.append(f"| {row['refined_status']} | {int(row['payments']):,} | {money(float(row['amount']))} |")
    lines += [
        "",
        f"**Still open after refinement:** {open_n:,} payments, {money(open_amt)} "
        f"({(open_amt / m['tested_paid'] * 100) if m['tested_paid'] else 0:.2f}% of the amount tested).",
        "",
        f"Top {len(review)} open flags are on the Duplicate Review sheet of the workpaper.",
        "",
        "## Duplicate vendor test",
        "",
        f"Candidate pairs: {len(vendors):,} "
        f"(High {conf.get('High', 0):,}, Medium {conf.get('Medium', 0):,}, Low {conf.get('Low', 0):,})",
        "",
        f"Same amount paid to both names within {config.CROSS_VENDOR_WINDOW_DAYS} days: "
        f"{len(cross):,} matches, {money(float(cross['amount'].sum()) if len(cross) else 0)}",
        "",
        "## Recurring overpayment check",
        "",
        f"Months where a monthly bill was paid more than once: {len(overflow):,}, "
        f"extra amount in those months {money(float(overflow['extra_amount'].sum()) if len(overflow) else 0)}",
        "",
        "| Pattern | Months | Extra in those months |",
        "|---|---:|---:|",
    ]
    if len(overflow):
        for pat, grp in overflow.groupby("pattern"):
            lines.append(f"| {pat} | {len(grp):,} | {money(float(grp['extra_amount'].sum()))} |")
    xb = excess_bills(overflow)
    lines += [
        "",
        f"**Potential overpayment** (payments beyond the months each bill covers, each bill counted once): "
        f"{len(xb):,} bills, {int(xb['excess_payments_in_year'].sum()) if len(xb) else 0:,} payments, "
        f"{money(float(xb['excess_amount_in_year'].sum()) if len(xb) else 0)}",
        "",
        "## Review status",
        "",
        "| Review | Assessment | Items | Amount |",
        "|---|---|---:|---:|",
    ]
    for name, df, amt_col in [("Duplicate review list", review, "amount")]:
        counts = df.groupby(df["reviewer_assessment"].fillna("Not yet reviewed"))[amt_col].agg(["count", "sum"])
        for assess, row in counts.iterrows():
            lines.append(f"| {name} | {assess} | {int(row['count']):,} | {money(float(row['sum']))} |")
    if len(vendors):
        vc = vendors["reviewer_assessment"].fillna("Not yet reviewed").value_counts()
        for assess, n in vc.items():
            lines.append(f"| Vendor candidates | {assess} | {int(n):,} | |")
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_memo(m, frames, status_tbl, template_path, out_path):
    """Fill the memo template with the current results."""
    review, vendors, cross, overflow = frames["review"], frames["vendors"], frames["cross"], frames["overflow"]
    by_status = status_tbl.set_index("refined_status")

    def stat(name, col):
        return by_status[col].get(name, 0) if len(by_status) else 0

    def assess(df, label, amt_col=None):
        if not len(df):
            return 0, 0.0
        hit = df[df["reviewer_assessment"] == label]
        return len(hit), float(hit[amt_col].sum()) if amt_col else 0.0

    legit_n, legit_amt = assess(review, "Likely legitimate", "amount")
    inq_n, inq_amt = assess(review, "Needs inquiry", "amount")
    same_n, _ = assess(vendors, "Same supplier")
    xb = excess_bills(overflow)
    catch = overflow[overflow["pattern"].str.startswith("Catch-up")] if len(overflow) else overflow
    top_line = ""
    if len(xb):
        t = xb.sort_values("excess_amount_in_year", ascending=False).iloc[0]
        top_line = (f"The largest is {t['vendor']}, paid {int(t['payments_in_year'])} times "
                    f"at {money(float(t['amount']))} over {int(t['span_months'])} months.")
    open_amt = float(stat(OPEN, "amount"))
    values = {
        "total_paid": money(m["total_paid"]),
        "total_payments": f"{m['total_payments']:,}",
        "in_scope_paid": money(m["in_scope_paid"]),
        "tested_n": f"{m['tested_payments']:,}",
        "tested_paid": money(m["tested_paid"]),
        "pairs_n": f"{len(frames['refined']):,}",
        "open_n": f"{int(stat(OPEN, 'payments')):,}",
        "open_amt": money(open_amt),
        "open_pct": f"{(open_amt / m['tested_paid'] * 100) if m['tested_paid'] else 0:.2f}%",
        "recurring_n": f"{int(stat('Likely recurring: review', 'payments')):,} payments",
        "reversed_n": f"{int(stat('Likely resolved: reversal found', 'payments')):,}",
        "review_legit_n": str(legit_n),
        "review_legit_amt": money(legit_amt),
        "review_inquiry_n": str(inq_n),
        "review_inquiry_amt": money(inq_amt),
        "vendor_pairs_n": f"{len(vendors):,}",
        "vendor_same_n": str(same_n),
        "cross_n": f"{len(cross):,}",
        "cross_amt": money(float(cross["amount"].sum()) if len(cross) else 0.0),
        "overflow_months": f"{len(overflow):,}",
        "catchup_months": f"{len(catch):,}",
        "catchup_amt": money(float(catch["extra_amount"].sum()) if len(catch) else 0.0),
        "excess_bills_n": f"{len(xb):,}",
        "excess_payments_n": f"{int(xb['excess_payments_in_year'].sum()) if len(xb) else 0:,}",
        "excess_amt": money(float(xb["excess_amount_in_year"].sum()) if len(xb) else 0.0),
        "top_excess_line": top_line,
    }
    with open(template_path) as f:
        text = f.read()
    with open(out_path, "w") as f:
        f.write(text.format_map(values))


def main():
    log = Logger("06_build_workpaper")
    log("Collecting results...")
    m = compute_metrics()
    frames = load_frames()
    apply_notes(frames, log)
    log("Building workbook...")
    status_tbl = build_workpaper(m, frames, config.WORKPAPER_FILE)
    write_results_summary(m, frames, status_tbl, config.RESULTS_SUMMARY_FILE)
    memo_template = os.path.join(config.DOCS_DIR, "audit_memo_template.md")
    memo_out = os.path.join(config.DOCS_DIR, "audit_memo.md")
    if os.path.exists(memo_template):
        write_memo(m, frames, status_tbl, memo_template, memo_out)
    log(f"Saved: {config.WORKPAPER_FILE}")
    log(f"Saved: {config.RESULTS_SUMMARY_FILE}")
    log(f"Saved: {memo_out}")
    log("")
    with open(config.RESULTS_SUMMARY_FILE) as f:
        for line in f:
            log(line.rstrip())
    log.save()


if __name__ == "__main__":
    main()
