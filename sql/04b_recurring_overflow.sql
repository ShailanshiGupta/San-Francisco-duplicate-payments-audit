-- 04b_recurring_overflow.sql
-- Purpose: close the blind spot in the duplicate test. Payments labeled
-- "likely recurring" or "monthly pattern" are never reviewed, but the most
-- common duplicate of all is a recurring bill paid twice in one month.
--
-- A vendor + amount counts as a MONTHLY bill when it was paid in at least
-- {{MONTHLY_MIN_MONTHS}} different months and usually once a month (total
-- payments no more than {{OVERFLOW_MAX_RATIO}} times the number of months).
-- This keeps out weekly or daily standing orders, where several payments a
-- month are normal.
--
-- Any month where a monthly bill was paid more than once is flagged.
--
-- Bunching is not the same as overpaying. A city often pays several months
-- of rent at once, for example at the start of the fiscal year. So each
-- bill is also compared with the number of months it covers (first to last
-- payment month). If total payments stay within that span, the flagged
-- month is labeled CATCH-UP. If there are more payments than months in the
-- span, the bill is labeled EXCESS, and only the payments beyond the span
-- count as potential overpayment.
-- Only in-scope payments of at least {{MIN_AMOUNT}} dollars are checked.

CREATE OR REPLACE TABLE overflow_base AS
SELECT
    row_id,
    vendor,
    vendor_clean,
    voucher,
    department,
    purchase_order,
    object,
    ROUND(amount_paid, 2)                  AS amount,
    approx_date,
    DATE_TRUNC('month', approx_date)       AS pay_month
FROM scoped
WHERE scope_status = 'IN SCOPE'
  AND amount_paid >= {{MIN_AMOUNT}};


CREATE OR REPLACE TABLE monthly_bills AS
SELECT
    vendor_clean,
    amount,
    COUNT(*)                                              AS payments_in_year,
    COUNT(DISTINCT pay_month)                             AS months_paid,
    MIN(pay_month)                                        AS first_month,
    MAX(pay_month)                                        AS last_month,
    DATE_DIFF('month', MIN(pay_month), MAX(pay_month)) + 1 AS span_months
FROM overflow_base
GROUP BY vendor_clean, amount
HAVING COUNT(DISTINCT pay_month) >= {{MONTHLY_MIN_MONTHS}}
   AND COUNT(*) >  COUNT(DISTINCT pay_month)
   AND COUNT(*) <= COUNT(DISTINCT pay_month) * {{OVERFLOW_MAX_RATIO}};


CREATE OR REPLACE TABLE overflow_reversals AS
SELECT
    vendor_clean,
    ROUND(-amount_paid, 2)               AS amount,
    DATE_TRUNC('month', approx_date)     AS reversal_month
FROM scoped
WHERE scope_status = 'REVERSAL: kept for matching';


CREATE OR REPLACE TABLE recurring_overflow AS
WITH months_over AS (
    SELECT
        b.vendor_clean,
        b.amount,
        b.pay_month,
        ANY_VALUE(b.vendor)                              AS vendor,
        ANY_VALUE(b.object)                              AS spend_type,
        COUNT(*)                                         AS payments_in_month,
        STRING_AGG(DISTINCT b.department, ' | ')          AS departments,
        STRING_AGG(DISTINCT b.purchase_order, ' | ')      AS purchase_orders,
        STRING_AGG(b.voucher, ' | ' ORDER BY b.voucher)   AS vouchers,
        MIN(b.approx_date)                               AS first_date,
        MAX(b.approx_date)                               AS last_date
    FROM overflow_base b
    JOIN monthly_bills m
      ON m.vendor_clean = b.vendor_clean AND m.amount = b.amount
    GROUP BY b.vendor_clean, b.amount, b.pay_month
    HAVING COUNT(*) > 1
)
SELECT
    ROW_NUMBER() OVER (
        ORDER BY (o.payments_in_month - 1) * o.amount DESC, o.vendor_clean, o.pay_month
    )                                                    AS overflow_id,
    o.vendor,
    o.amount,
    o.pay_month,
    o.payments_in_month,
    o.payments_in_month - 1                              AS extra_payments,
    ROUND((o.payments_in_month - 1) * o.amount, 2)       AS extra_amount,
    m.payments_in_year,
    m.months_paid,
    m.span_months,
    CASE WHEN m.payments_in_year > m.span_months
         THEN 'Excess: more payments than months covered'
         ELSE 'Catch-up: within months covered'
    END                                                  AS pattern,
    GREATEST(m.payments_in_year - m.span_months, 0)      AS excess_payments_in_year,
    ROUND(GREATEST(m.payments_in_year - m.span_months, 0) * o.amount, 2) AS excess_amount_in_year,
    o.departments,
    o.purchase_orders,
    o.vouchers,
    o.first_date,
    o.last_date,
    o.spend_type,
    EXISTS (
        SELECT 1 FROM overflow_reversals r
        WHERE r.vendor_clean = o.vendor_clean
          AND r.amount = o.amount
          AND r.reversal_month >= o.pay_month
    )                                                    AS reversal_found,
    o.vendor_clean
FROM months_over o
JOIN monthly_bills m
  ON m.vendor_clean = o.vendor_clean AND m.amount = o.amount;
