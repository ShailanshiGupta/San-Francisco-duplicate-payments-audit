# Memo: Accounts Payable Controls Review, San Francisco FY2026

**To:** Controller's Office (illustrative audience)
**From:** Shailanshi Gupta
**Subject:** Potential duplicate payments and duplicate vendor records, fiscal year 2026

*Numbers in this memo are filled in automatically from the pipeline results (`src/06_build_workpaper.py`), so they always match the data. The wording is in `docs/audit_memo_template.md`.*

## Summary

I tested one year of San Francisco's published vendor payments for three common accounts payable problems: the same bill paid twice, a monthly bill paid more often than monthly, and one supplier set up under two names. Of $6,098,334,895.09 in supplier payments, 1,520 payments totaling $23,334,400.15 (0.39% of the amount tested) could not be explained by a normal pattern. From the 25 highest-priority cases, I recommend 18 ($3,775,782.22) for inquiry. I also found 295 monthly bills paid more times than the months they cover ($6,614,231.10), and 20 suppliers that appear to exist twice in the vendor list. None of this confirms an error, because the public data has no invoice numbers, but it gives the city a short, ranked list to check.

## What I tested

The city paid $16,842,902,152.64 across 503,825 payments in fiscal year 2026 (July 2025 to June 2026). About two thirds of that is not buying from suppliers: payroll tax remittances, debt service, employee benefits, grants and refunds. I focused on the $6,098,334,895.09 spent on services, supplies, equipment and construction, and tested every payment of $1,000 or more: 133,800 payments worth $6,041,917,297.96.

## What I found

**Duplicate payments.** A first pass flagged 31,126 pairs of payments to the same vendor for the same amount within a short window. Most had a clear explanation. 8,913 payments involved amounts the vendor is paid regularly, and 207 were followed by a matching reversal, which suggests the city's own controls caught them. After also setting aside monthly bills, multi-unit equipment orders and standing supply orders, 1,520 payments ($23,334,400.15) remained.

I reviewed the 25 highest-priority cases. 7 ($945,426.08) look legitimate, mostly contracts paid in equal installments that add up exactly to the order total. 18 ($3,775,782.22) need inquiry. The strongest are:

- **Conard House, $219,589 twice on the same date, with no purchase order.** Without a PO, the usual order-level approval did not apply.
- **Clark Construction, $767,640.91 twice, four days apart.** Construction progress payments rarely repeat to the cent.
- **Alstom Transport, $901,825.45 three times in July 2025,** two on the same date. This could be catch-up of earlier months' fees, but at this size it should be confirmed.
- **Genfare and Exygy,** where the order's entire annual total is exactly two identical payments. That fits two installments, and it also fits one invoice paid twice.

**Monthly bills paid more than monthly.** Recurring payments are easy to wave through, so I checked them separately. 1,016 months showed a monthly bill paid more than once. Most of these are catch-up, not overpayment: 569 months ($10,502,908.40) belong to bills that were still paid no more times than the months they cover, such as several months of rent paid together at the start of the fiscal year. The rest point to 295 bills paid more times than the months they cover, 365 extra payments worth $6,614,231.10. The largest is PROLOGIS L.P., paid 7 times at $345,860.13 over 5 months. This figure is an upper bound: the check measures each bill from its first payment of the year, so July payments that cover months from the previous fiscal year will look like extras.

**Duplicate vendors.** Name matching found 100 pairs of similar vendor names. On review, 20 look like the same supplier set up twice. The largest is ComputerLand of Silicon Valley, with 1,016 payments ($15.6M) under one record and 98 ($1.7M) under another. City Auto Supply has two active records used by the same five departments, and Pacific Auxiliary Fire Alarm had the same purchase orders paid under both of its names. In the 5 cases where the same amount went to both names ($20,947.81), the pattern mostly looked like one monthly payment alternating between two records rather than a double payment. That is still a control weakness, since split records are how duplicates slip through.

## Recommendations

1. **Check the flagged payments against invoices,** starting with the Duplicate Review list and the excess monthly bills. Recover any confirmed duplicates from the vendor.
2. **Merge duplicate vendor records,** starting with ComputerLand, City Auto Supply and Pacific Auxiliary Fire Alarm, and block new records whose names match an existing vendor after removing punctuation, capitalization and legal endings.
3. **Match on invoice number before payment.** A check on vendor, invoice number and amount at entry would prevent most of these patterns instead of finding them afterward.
4. **Require a PO for large direct payments,** since the highest-priority flag had none.
5. **Publish invoice numbers and payment dates** in the open dataset, so anyone can run these tests with far more precision.

## Limits

Every flag is a lead, not a finding. The data has no invoice numbers, dates are approximate (the date a record was last updated), and vendors are identified only by name. Some flags will turn out to be legitimate. The full method and every threshold are in `docs/methodology.md`, and every flag is listed in the workpaper.
