-- 03c_duplicate_payments.sql
-- Purpose: find pairs of payments that may be the same bill paid twice.
--
-- A pair is flagged when two DIFFERENT payments (department + voucher)
-- go to the same vendor (standardized name) for the exact same amount:
--   HIGH   = same purchase order, paid within {{HIGH_WINDOW_DAYS}} days
--   MEDIUM = any PO or no PO, paid within {{MEDIUM_WINDOW_DAYS}} days
--
-- Each flag then gets a status:
--   Likely resolved  = a reversal for that vendor and amount appears on
--                      or after the first payment (the error was caught)
--   Likely recurring = that vendor was paid that exact amount
--                      {{RECURRING_MIN_COUNT}}+ times this year (rent,
--                      subscriptions, fixed monthly fees)
--   Open             = everything else, these need a human to review
--
-- Only in-scope payments of at least ${{MIN_AMOUNT}} are tested.
-- Dates are approximate (data_as_of), so day counts are approximate.


-- Step 1: the payments being tested
CREATE OR REPLACE TABLE test_base AS
SELECT
    row_id,
    voucher_key,
    voucher,
    vendor,
    vendor_clean,
    purchase_order,
    is_direct_payment,
    department_code,
    department,
    ROUND(amount_paid, 2) AS amount,
    approx_date,
    object,
    contract_title
FROM scoped
WHERE scope_status = 'IN SCOPE'
  AND amount_paid >= {{MIN_AMOUNT}};


-- Step 2: reversals, stored as positive amounts so they can match
CREATE OR REPLACE TABLE reversals AS
SELECT
    vendor_clean,
    ROUND(-amount_paid, 2) AS amount,
    approx_date
FROM scoped
WHERE scope_status = 'REVERSAL: kept for matching';


-- Step 3: how often each vendor was paid each exact amount
CREATE OR REPLACE TABLE amount_frequency AS
SELECT
    vendor_clean,
    amount,
    COUNT(*) AS times_paid
FROM test_base
GROUP BY vendor_clean, amount;


-- Step 4: find the pairs and label them
CREATE OR REPLACE TABLE duplicate_pairs AS
WITH pairs AS (
    SELECT
        a.vendor_clean,
        a.amount,
        a.row_id             AS row_id_1,
        a.vendor             AS vendor_1,
        a.voucher            AS voucher_1,
        a.department         AS department_1,
        a.purchase_order     AS po_1,
        a.approx_date        AS date_1,
        a.object             AS spend_type_1,
        b.row_id             AS row_id_2,
        b.vendor             AS vendor_2,
        b.voucher            AS voucher_2,
        b.department         AS department_2,
        b.purchase_order     AS po_2,
        b.approx_date        AS date_2,
        b.object             AS spend_type_2,
        DATE_DIFF('day', a.approx_date, b.approx_date)          AS days_apart,
        (a.purchase_order = b.purchase_order
            AND NOT a.is_direct_payment)                         AS same_po,
        (a.department_code = b.department_code)                  AS same_department,
        (a.vendor <> b.vendor)                                   AS vendor_name_differs
    FROM test_base a
    JOIN test_base b
      ON  a.vendor_clean = b.vendor_clean
      AND a.amount       = b.amount
      AND a.voucher_key <> b.voucher_key
      -- keep each pair once, with payment 1 as the earlier one
      AND (a.approx_date < b.approx_date
           OR (a.approx_date = b.approx_date AND a.row_id < b.row_id))
      AND DATE_DIFF('day', a.approx_date, b.approx_date) <= {{HIGH_WINDOW_DAYS}}
),
tiered AS (
    SELECT
        *,
        CASE
            WHEN same_po                              THEN 'HIGH'
            WHEN days_apart <= {{MEDIUM_WINDOW_DAYS}} THEN 'MEDIUM'
        END AS risk_tier
    FROM pairs
),
checked AS (
    SELECT
        t.*,
        f.times_paid AS times_vendor_paid_this_amount,
        EXISTS (
            SELECT 1
            FROM reversals r
            WHERE r.vendor_clean = t.vendor_clean
              AND r.amount       = t.amount
              AND r.approx_date >= t.date_1
        ) AS reversal_found
    FROM tiered t
    JOIN amount_frequency f
      ON  f.vendor_clean = t.vendor_clean
      AND f.amount       = t.amount
    WHERE t.risk_tier IS NOT NULL
)
SELECT
    ROW_NUMBER() OVER (ORDER BY amount DESC, date_1, row_id_1, row_id_2) AS flag_id,
    risk_tier,
    CASE
        WHEN reversal_found
            THEN 'Likely resolved: reversal found'
        WHEN times_vendor_paid_this_amount >= {{RECURRING_MIN_COUNT}}
            THEN 'Likely recurring: review'
        ELSE 'Open: needs review'
    END AS status,
    * EXCLUDE (risk_tier)
FROM checked;
