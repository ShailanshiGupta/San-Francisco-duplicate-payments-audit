-- 04_refine_duplicates.sql
-- Purpose: separate open duplicate flags that match a known legitimate
-- pattern from the ones that genuinely need review, then rank what is left.
-- Nothing is removed. Every flag keeps its original Step 3 status plus a
-- refined status, so the reasoning can be traced.

CREATE OR REPLACE TABLE pairs AS
SELECT * FROM read_csv_auto('{{PAIRS_FILE}}', header = true);

CREATE OR REPLACE VIEW scoped AS
SELECT * FROM read_parquet('{{SCOPED_FILE}}');


-- In how many different months was each vendor + PO + amount paid?
-- Rent or a fixed monthly fee shows up in many months.
-- A duplicate usually shows up in one or two.
CREATE OR REPLACE TABLE po_amount_months AS
SELECT
    vendor_clean,
    purchase_order,
    ROUND(amount_paid, 2)                              AS amount,
    COUNT(DISTINCT DATE_TRUNC('month', approx_date))   AS months_paid
FROM scoped
WHERE scope_status = 'IN SCOPE'
GROUP BY ALL;


-- Context for the reviewer: how many payments and how much in total
-- went out on each PO during the year
CREATE OR REPLACE TABLE po_context AS
SELECT
    purchase_order,
    vendor_clean,
    COUNT(*)                      AS po_payment_count,
    ROUND(SUM(amount_paid), 2)    AS po_total_paid
FROM scoped
WHERE scope_status = 'IN SCOPE'
  AND NOT is_direct_payment
GROUP BY ALL;


-- Refined status and priority score
CREATE OR REPLACE TABLE refined AS
WITH base AS (
    SELECT
        p.*,
        s.character      AS category_2,
        m.months_paid
    FROM pairs p
    JOIN scoped s
      ON s.row_id = p.row_id_2
    LEFT JOIN po_amount_months m
      ON  m.vendor_clean   = p.vendor_clean
      AND m.purchase_order = p.po_2
      AND m.amount         = p.amount
),
labeled AS (
    SELECT
        *,
        CASE
            WHEN status <> 'Open: needs review'
                THEN status
            WHEN same_po AND months_paid >= {{MONTHLY_MIN_MONTHS}}
                THEN 'Likely explained: monthly pattern'
            WHEN spend_type_2 = 'Equipment Purchase'
                THEN 'Likely explained: multi-unit equipment order'
            WHEN category_2 = 'Materials & Supplies' AND days_apart > 0
                THEN 'Likely explained: repeat supply order'
            ELSE 'Open: needs review'
        END AS refined_status
    FROM base
)
SELECT
    *,
    CASE WHEN refined_status = 'Open: needs review' THEN
          -- timing: the closer together, the more it looks like double entry
          (CASE WHEN days_apart = 0  THEN 3
                WHEN days_apart <= 7 THEN 2
                WHEN days_apart <= 14 THEN 1
                ELSE 0 END)
          -- same PO: the same order was paid twice
        + (CASE WHEN same_po THEN 1 ELSE 0 END)
          -- size: bigger payments matter more
        + (CASE WHEN amount >= 100000 THEN 3
                WHEN amount >= 25000  THEN 2
                WHEN amount >= 5000   THEN 1
                ELSE 0 END)
          -- construction and professional services rarely repeat an exact amount
        + (CASE WHEN spend_type_2 LIKE 'Bldg%'
                  OR spend_type_2 LIKE 'Professional%' THEN 1 ELSE 0 END)
          -- two departments paying the same vendor the same amount
        + (CASE WHEN NOT same_department THEN 1 ELSE 0 END)
    END AS priority_score
FROM labeled;


-- Top review list: one row per questioned payment, highest priority first
CREATE OR REPLACE TABLE review_list AS
WITH open_payments AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY row_id_2
            ORDER BY priority_score DESC, days_apart, row_id_1
        ) AS rn
    FROM refined
    WHERE refined_status = 'Open: needs review'
)
SELECT
    ROW_NUMBER() OVER (ORDER BY o.priority_score DESC, o.amount DESC, o.row_id_2) AS review_rank,
    o.flag_id,
    o.priority_score,
    o.risk_tier,
    o.amount,
    o.vendor_2            AS vendor,
    o.department_1,
    o.department_2,
    o.po_1,
    o.po_2,
    o.voucher_1,
    o.voucher_2,
    o.date_1,
    o.date_2,
    o.days_apart,
    o.spend_type_2        AS spend_type,
    o.same_po,
    o.same_department,
    c.po_payment_count,
    c.po_total_paid,
    ''                    AS reviewer_assessment,
    ''                    AS rationale,
    ''                    AS next_step
FROM open_payments o
LEFT JOIN po_context c
  ON  c.purchase_order = o.po_2
  AND c.vendor_clean   = o.vendor_clean
WHERE o.rn = 1
ORDER BY review_rank
LIMIT {{REVIEW_LIST_SIZE}};
