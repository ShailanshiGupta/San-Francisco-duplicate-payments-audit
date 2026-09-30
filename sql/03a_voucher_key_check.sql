-- 03a_voucher_key_check.sql
-- Purpose: some voucher numbers appear on more than one payment row.
-- This checks WHICH field differs between those rows, to decide what
-- uniquely identifies a payment.
--   If department differs  -> voucher numbers repeat across departments
--   If PO differs          -> one payment request covers several POs
--   If vendor differs      -> same number used for different payees

WITH multi AS (
    SELECT voucher
    FROM payments
    GROUP BY voucher
    HAVING COUNT(*) > 1
),
detail AS (
    SELECT
        voucher,
        COUNT(DISTINCT department_code)                  AS n_departments,
        COUNT(DISTINCT vendor)                           AS n_vendors,
        COUNT(DISTINCT purchase_order)                   AS n_pos,
        COUNT(DISTINCT COALESCE(contract_number, 'none')) AS n_contracts
    FROM payments
    WHERE voucher IN (SELECT voucher FROM multi)
    GROUP BY voucher
)
SELECT
    COUNT(*)                          AS vouchers_on_multiple_rows,
    COUNT_IF(n_departments > 1)       AS differ_by_department,
    COUNT_IF(n_vendors > 1)           AS differ_by_vendor,
    COUNT_IF(n_pos > 1)               AS differ_by_po,
    COUNT_IF(n_contracts > 1)         AS differ_by_contract
FROM detail
