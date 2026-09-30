-- 02_prepare.sql
-- Purpose: turn raw payment rows into one row per payment, and add a
-- standardized vendor name for matching.

-- RULE A: One row per payment
-- A voucher can be split across several rows when it is charged to more
-- than one fund or budget line. Those rows are added back together.
-- Category fields keep the value from the largest line.
CREATE OR REPLACE TABLE payments AS
SELECT
    voucher,
    vendor,
    purchase_order,
    purchase_order = 'Direct Payments'                        AS is_direct_payment,
    department_code,
    department,
    contract_number,
    contract_title,
    purchasing_authority_title,
    SUM(vouchers_paid)                                        AS amount_paid,
    SUM(vouchers_pending)                                     AS amount_pending,
    SUM(vouchers_pending_retainage)                           AS amount_retainage,
    COUNT(*)                                                  AS n_lines,
    COUNT(DISTINCT character_code)                            AS n_categories,
    ARG_MAX(character_code, ABS(vouchers_paid))               AS character_code,
    ARG_MAX(character,      ABS(vouchers_paid))               AS character,
    ARG_MAX(object,         ABS(vouchers_paid))               AS object,
    ARG_MAX(sub_object,     ABS(vouchers_paid))               AS sub_object,
    MAX(TRY_CAST(SUBSTR(data_as_of, 1, 10) AS DATE))          AS approx_date
FROM raw
GROUP BY
    voucher, vendor, purchase_order, department_code, department,
    contract_number, contract_title, purchasing_authority_title;

-- RULE C: Standardized vendor name
-- Uppercase, turn & into AND, strip punctuation, remove common legal
-- endings (INC, LLC, CORP...) and a leading THE, collapse spaces.
-- Example: "The ABC Construction, Inc." becomes "ABC CONSTRUCTION"
-- Only used to FIND similar names. The original name is kept.
ALTER TABLE payments ADD COLUMN vendor_clean VARCHAR;
UPDATE payments SET vendor_clean = TRIM(
    REGEXP_REPLACE(
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                REPLACE(UPPER(vendor), '&', ' AND '),
                '[^A-Z0-9 ]', ' ', 'g'),
            '\b(INC|INCORPORATED|LLC|L L C|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|LP|LLP|PLLC|PC|NA|THE|DBA)\b',
            ' ', 'g'),
        '\s+', ' ', 'g')
);
