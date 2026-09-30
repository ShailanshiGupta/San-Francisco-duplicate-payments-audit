-- 05a_vendor_list.sql
-- Purpose: one row per vendor name exactly as written in the city's data,
-- with the activity needed to judge whether two similar names are the
-- same supplier set up twice in the vendor master.
-- The placeholder payee and zero-dollar rows are left out.

CREATE OR REPLACE VIEW scoped AS
SELECT * FROM read_parquet('{{SCOPED_FILE}}');

CREATE OR REPLACE TABLE vendor_list AS
SELECT
    vendor,
    vendor_clean,
    COUNT(*)                                                        AS payments,
    ROUND(SUM(amount_paid), 2)                                      AS total_paid,
    ROUND(SUM(CASE WHEN scope_status = 'IN SCOPE'
                   THEN amount_paid ELSE 0 END), 2)                 AS in_scope_paid,
    COUNT(DISTINCT department_code)                                 AS departments,
    STRING_AGG(DISTINCT department_code, ', ')                      AS department_codes,
    MIN(approx_date)                                                AS first_payment,
    MAX(approx_date)                                                AS last_payment
FROM scoped
WHERE vendor <> 'Single Payment Payees'
  AND amount_paid <> 0
GROUP BY vendor, vendor_clean;
