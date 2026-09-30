# Methodology

This document explains every rule the pipeline applies, why it was chosen, and what it cannot do. All settings referenced here live in `src/config.py`, and every rule lives in a file in `sql/`.

## 1. Source data

San Francisco's Vendor Payments (Vouchers) dataset on DataSF, published by the Controller's Office. Each row is a payment, or part of a payment, to a supplier or other payee. The project uses fiscal year 2026 (July 1, 2025 to June 30, 2026), the most recent complete year at the time of analysis: 511,226 rows.

Three limits of the data shaped every later decision:

- **No payment date.** The closest field is `data_as_of`, the date the record was last updated. Its monthly distribution matches what payment dates would look like, so it is used as an approximate date, and every day count in this project is approximate.
- **No vendor ID.** Vendors are identified only by name. This is why the duplicate vendor test exists.
- **No invoice numbers.** A duplicate can never be confirmed from this data alone.

## 2. Preparing the data (`sql/02_prepare.sql`)

**One row per payment.** A voucher charged to more than one fund appears on several rows. Those rows are summed back together, and category fields keep the value from the largest line. 511,226 rows became 503,825 payments.

**Control total.** The sum of payments after combining must equal the raw sum to the cent. It does: $16,842,902,152.64 on both sides. The same check runs again after scoping.

**Payment ID.** 5,998 voucher numbers still appeared on more than one row. Checking which field differed showed that 5,954 of them were one payment covering several purchase orders. A payment is therefore identified by department plus voucher number, and two lines of the same voucher are never compared with each other as duplicates.

**Standardized vendor name.** Uppercase, `&` to `AND`, punctuation removed, common legal endings removed (INC, LLC, CORP, CO, LTD, LP and similar), and extra spaces collapsed. "The ABC Construction, Inc." becomes "ABC CONSTRUCTION". The standardized name is used only for matching. The original is always kept.

## 3. Scope (`sql/03b_scope.sql`)

Every payment gets exactly one label:

| Label | Rule |
|---|---|
| IN SCOPE | Non-Personnel Services, Materials & Supplies, or Capital Outlay |
| OUT: not procurement spending | any other category: payroll tax remittances, debt service, benefits, grants, aid, revenue refunds |
| OUT: taxes and permits | the "Taxes: Licenses/Permits" sub-category inside Non-Personnel Services |
| OUT: placeholder payee | "Single Payment Payees", which groups many one-time payees under one name |
| OUT: zero amount | payments of $0 |
| REVERSAL: kept for matching | negative in-scope payments, used to check whether a duplicate was later reversed |

Why: the test is about supplier purchases. Including bond payments or insurance premiums would flag every normal monthly transfer, and the placeholder payee would make thousands of unrelated payments look identical.

## 4. Duplicate payment test (`sql/03c_duplicate_payments.sql`)

Only in-scope payments of at least $1,000 are tested (`MIN_AMOUNT`). Below that, the results are dominated by small repeat supply orders, and the dollar risk is low.

A **pair** is two different payments to the same standardized vendor name for the exact same amount:

- **HIGH:** same purchase order, within 30 days (`HIGH_WINDOW_DAYS`)
- **MEDIUM:** any PO or no PO, within 14 days (`MEDIUM_WINDOW_DAYS`)

Each pair then gets a status:

- **Likely resolved:** a reversal for the same vendor and amount appears on or after the first payment. If the error happened, the city appears to have caught it.
- **Likely recurring:** the vendor was paid that exact amount 4 or more times in the year (`RECURRING_MIN_COUNT`), typical of rent, subscriptions and fixed fees.
- **Open:** everything else.

## 5. Refinement (`sql/04_refine_duplicates.sql`)

The first pass leaves too many open flags to review by hand, and many share an obvious legitimate pattern. Refinement labels them rather than deleting them:

- **Monthly pattern:** same vendor, same PO and same amount paid in 3 or more different months (`MONTHLY_MIN_MONTHS`). This catches monthly bills that did not reach the 4-payment recurring threshold.
- **Multi-unit equipment order:** identical amounts on equipment purchases. Buying several identical vehicles or units on one order produces identical payments.
- **Repeat supply order:** identical Materials & Supplies purchases on different days, typical of standing hospital and warehouse orders. Same-day supply pairs stay open.

Every flag still open gets a **priority score from 0 to 9**:

| Factor | Points |
|---|---|
| Timing | same day 3, within a week 2, within two weeks 1 |
| Same PO | 1 |
| Amount | $100,000+ 3, $25,000+ 2, $5,000+ 1 |
| Construction or professional services | 1 (these rarely repeat an exact amount) |
| Paid by two different departments | 1 |

The top 25 open payments by score, then amount, form the review list, with one row per questioned payment.

**Why there is no automatic "installment" rule.** During review, the strongest evidence of a legitimate pattern turned out to be the PO total: when a PO's whole year is three or four identical payments that add up exactly to the total, it is an installment schedule. This was deliberately *not* made an automatic rule. When a PO has only two payments of the same amount, "PO total equals two times the amount" is also exactly what one invoice paid twice looks like, so the rule would hide the very cases the test exists to find. It is used as reviewer evidence instead.

## 5b. Recurring overpayment check (`sql/04b_recurring_overflow.sql`)

Payments labeled "likely recurring" or "monthly pattern" are not reviewed, which leaves a gap: the most common duplicate of all is a recurring bill paid twice in the same month.

A vendor and amount counts as a **monthly bill** when it was paid in at least 3 different months (`MONTHLY_MIN_MONTHS`) and usually once a month, meaning total payments are no more than 1.5 times the number of months (`OVERFLOW_MAX_RATIO`). The ratio keeps out weekly or daily standing orders, where several payments a month are normal. Any month where a monthly bill was paid more than once is flagged. A later reversal for the same vendor and amount is noted.

**Catch-up vs excess.** The first run of this check showed that bunching is not the same as overpaying. Lombard Hotel Group, for example, was paid four times in one day in July 2025, but only twelve times across the whole year: a year of rent with several months paid together. So each bill is compared with the number of months it covers, from its first to its last payment month. If total payments stay within that span, the flagged month is labeled **catch-up**. If there are more payments than months, the bill is labeled **excess**, and only the payments beyond the span count as potential overpayment, with each bill counted once.

## 6. Duplicate vendor test (`src/05_duplicate_vendors.py`, `sql/05a` to `05c`)

Two kinds of candidate pairs:

- **Identical after cleanup:** two names that differ only in capitalization, punctuation or legal ending, such as "PACIFIC OCEAN SPORTS" and "Pacific Ocean Sports".
- **Similar name:** standardized names with a fuzzy similarity of at least 90 out of 100 (`VENDOR_MATCH_THRESHOLD`, token sort ratio from rapidfuzz). Names shorter than 6 characters are skipped, and pairs whose numbers differ are rejected, including Roman numerals: "1390 MARKET ST" vs "1400 MARKET ST" are different buildings, and "MERCY HOUSING CALIFORNIA X" vs "MERCY HOUSING CALIFORNIA XIV" are different housing partnerships. The Roman numeral rule was added after the first run showed numbered partnerships being matched to each other.

**Confidence:**

- **High:** the same contract or PO was paid under both names, or the names are identical after cleanup
- **Medium:** similarity of 95 or more
- **Low:** everything else, often genuinely different suppliers with similar names

**Cross-vendor check:** for each candidate pair, any in-scope payment of at least $1,000 made to one name that matches the amount of a payment to the other name within 30 days (`CROSS_VENDOR_WINDOW_DAYS`). This is the scenario the duplicate payment test cannot see on its own, since it compares only payments made to the same standardized name.

Confidence is a starting point, not a verdict. Word order and abbreviations lower the similarity score, so some low-confidence pairs are plainly the same entity ("COUNTY OF SAN MATEO" vs "SAN MATEO COUNTY"), which is why the medium-confidence pairs and the largest low-confidence pairs were read by a person. The remaining low-confidence pairs are listed in the workpaper but have not been reviewed individually.

Note that a name change can be legitimate. A company that converts from INC to LLC, or a joint venture set up as a separate partnership, may correctly appear twice. That is a vendor master hygiene question, not necessarily an error.

## 7. Review

The workpaper (`outputs/workpaper/`) has yellow columns for the reviewer's assessment on the Duplicate Review, Vendor Candidates and Recurring Overpayments sheets, and the Summary sheet counts assessments by formula.

Assessments are stored as data in `review_notes/`, not typed only into Excel, so they are versioned with the code and survive a rerun. Duplicate notes are matched to review rows by vendor, amount and PO. Vendor notes are matched by the pair of names in either order. If the underlying data changes and a note no longer matches, the pipeline log says so.

Assessment options: **Likely legitimate** (a documented pattern explains it), **Needs inquiry** (no pattern explains it, so invoices are needed), **Likely duplicate** (reserved for cases the data itself makes clear; none met that bar here, because without invoice numbers the data cannot show two payments were for the same invoice).

## 8. Limits

- No invoice numbers: duplicates can be identified as likely, never confirmed.
- Approximate dates: day counts can be off, and same-day flags may partly reflect batch processing.
- Name-only vendor identity: without tax IDs or addresses, vendor matches rest on names and shared contracts or POs.
- The city removes some sensitive payments before publishing, so the dataset is not the complete ledger.
- Thresholds are judgment calls. They are set in one file so their effect can be tested by changing them and rerunning.
