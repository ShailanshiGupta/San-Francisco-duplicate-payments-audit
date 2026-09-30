-- 03b_scope.sql
-- Purpose: label every payment as in scope or out of scope, with a reason.
-- Nothing is deleted. Every payment keeps a label so totals can be
-- reconciled back to the full dataset.
--
-- In scope = goods and services the city buys from suppliers:
--   Non-Personnel Services, Materials and Supplies, Capital Outlay
-- Out of scope = payroll taxes, debt service, benefits, grants, aid,
--   revenue refunds, and other non-purchasing activity
--
-- A payment is identified by department + voucher, because voucher
-- numbers are not guaranteed to be unique across departments.
-- Values in {{double braces}} are filled in from src/config.py.

CREATE OR REPLACE TABLE scoped AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY department_code, voucher, vendor, purchase_order
    )                                         AS row_id,
    department_code || '-' || voucher         AS voucher_key,
    p.*,
    CASE
        WHEN vendor = 'Single Payment Payees'
            THEN 'OUT: placeholder payee'
        WHEN character_code NOT IN ({{IN_SCOPE_CHARACTERS}})
            THEN 'OUT: not procurement spending'
        WHEN object IN ({{EXCLUDED_OBJECTS}})
            THEN 'OUT: taxes and permits'
        WHEN amount_paid = 0
            THEN 'OUT: zero amount'
        WHEN amount_paid < 0
            THEN 'REVERSAL: kept for matching'
        ELSE 'IN SCOPE'
    END                                       AS scope_status
FROM payments p
