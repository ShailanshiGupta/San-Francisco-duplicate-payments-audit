-- 05c_cross_vendor_payments.sql
-- Purpose: the payoff of the vendor test. For every pair of similar vendor
-- names, look for the same amount paid to BOTH names within
-- {{CROSS_VENDOR_WINDOW_DAYS}} days. This is how a duplicate vendor record
-- turns into a duplicate payment, and why Step 3 alone cannot see it
-- (Step 3 only compares payments made to the same standardized name).
-- Only in-scope payments of at least {{MIN_AMOUNT}} dollars are compared.

CREATE OR REPLACE TABLE cross_vendor_matches AS
WITH base AS (
    SELECT
        row_id,
        voucher_key,
        vendor,
        ROUND(amount_paid, 2) AS amount,
        approx_date,
        department,
        purchase_order,
        object
    FROM scoped
    WHERE scope_status = 'IN SCOPE'
      AND amount_paid >= {{MIN_AMOUNT}}
)
SELECT
    c.candidate_id,
    c.confidence,
    c.match_type,
    a.amount,
    a.vendor          AS vendor_1,
    b.vendor          AS vendor_2,
    a.department      AS department_1,
    b.department      AS department_2,
    a.purchase_order  AS po_1,
    b.purchase_order  AS po_2,
    a.approx_date     AS date_1,
    b.approx_date     AS date_2,
    ABS(DATE_DIFF('day', a.approx_date, b.approx_date)) AS days_apart,
    a.object          AS spend_type
FROM vendor_candidates c
JOIN base a
  ON a.vendor = c.vendor_1
JOIN base b
  ON  b.vendor = c.vendor_2
  AND b.amount = a.amount
  AND b.voucher_key <> a.voucher_key
WHERE ABS(DATE_DIFF('day', a.approx_date, b.approx_date)) <= {{CROSS_VENDOR_WINDOW_DAYS}};
