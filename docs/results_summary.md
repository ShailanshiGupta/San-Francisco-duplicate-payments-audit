# Results summary, FY2026

Generated automatically by `src/06_build_workpaper.py`. Do not edit by hand, rerun the pipeline instead.

## Population and scope

| | Payments | Amount |
|---|---:|---:|
| All payments | 503,825 | $16,842,902,152.64 |
| In scope (supplier purchases) | 350,716 | $6,098,334,895.09 |
| Tested for duplicates (at least $1,000) | 133,800 | $6,041,917,297.96 |

## Duplicate payment test

Flagged pairs: 31,126

| Status after refinement | Payments | Amount |
|---|---:|---:|
| Likely recurring: review | 8,913 | $224,921,555.62 |
| Open: needs review | 1,520 | $23,334,400.15 |
| Likely explained: monthly pattern | 140 | $9,920,782.91 |
| Likely explained: multi-unit equipment order | 65 | $6,566,111.73 |
| Likely explained: repeat supply order | 792 | $5,538,712.84 |
| Likely resolved: reversal found | 207 | $2,229,543.85 |

**Still open after refinement:** 1,520 payments, $23,334,400.15 (0.39% of the amount tested).

Top 25 open flags are on the Duplicate Review sheet of the workpaper.

## Duplicate vendor test

Candidate pairs: 100 (High 25, Medium 8, Low 67)

Same amount paid to both names within 30 days: 5 matches, $20,947.81

## Recurring overpayment check

Months where a monthly bill was paid more than once: 1,016, extra amount in those months $18,885,187.77

| Pattern | Months | Extra in those months |
|---|---:|---:|
| Catch-up: within months covered | 569 | $10,502,908.40 |
| Excess: more payments than months covered | 447 | $8,382,279.37 |

**Potential overpayment** (payments beyond the months each bill covers, each bill counted once): 295 bills, 365 payments, $6,614,231.10

## Review status

| Review | Assessment | Items | Amount |
|---|---|---:|---:|
| Duplicate review list | Likely legitimate | 7 | $945,426.08 |
| Duplicate review list | Needs inquiry | 18 | $3,775,782.22 |
| Vendor candidates | Not yet reviewed | 57 | |
| Vendor candidates | Same supplier | 20 | |
| Vendor candidates | Needs inquiry | 14 | |
| Vendor candidates | Different suppliers | 9 | |
