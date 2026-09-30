-- 05b_vendor_candidates.sql
-- Purpose: add evidence to each pair of similar vendor names found by the
-- Python name matching (table name_pairs), and rate how likely it is that
-- the two names are the same supplier.
--
-- Evidence used:
--   shared contract or PO = the same contract or PO was paid under both
--                           names, which strongly suggests one supplier
--   match type            = identical after cleanup (only capitalization,
--                           punctuation or legal ending differs) vs similar
--   similarity score      = 0 to 100, from the name comparison
--
-- Confidence:
--   High   = shared contract or PO, or identical after cleanup
--   Medium = similarity of 95 or more
--   Low    = everything else, likely different suppliers with similar names

CREATE OR REPLACE TABLE vendor_candidates AS
WITH contracts AS (
    SELECT DISTINCT vendor, contract_number
    FROM scoped
    WHERE contract_number IS NOT NULL
),
pos AS (
    SELECT DISTINCT vendor, purchase_order
    FROM scoped
    WHERE NOT is_direct_payment
),
shared_contracts AS (
    SELECT n.vendor_1, n.vendor_2, COUNT(*) AS shared_contracts
    FROM name_pairs n
    JOIN contracts x ON x.vendor = n.vendor_1
    JOIN contracts y ON y.vendor = n.vendor_2 AND y.contract_number = x.contract_number
    GROUP BY n.vendor_1, n.vendor_2
),
shared_pos AS (
    SELECT n.vendor_1, n.vendor_2, COUNT(*) AS shared_pos
    FROM name_pairs n
    JOIN pos x ON x.vendor = n.vendor_1
    JOIN pos y ON y.vendor = n.vendor_2 AND y.purchase_order = x.purchase_order
    GROUP BY n.vendor_1, n.vendor_2
),
evidence AS (
    SELECT
        n.match_type,
        n.similarity,
        n.vendor_1,
        n.vendor_2,
        v1.payments          AS payments_1,
        v2.payments          AS payments_2,
        v1.total_paid        AS total_paid_1,
        v2.total_paid        AS total_paid_2,
        v1.department_codes  AS departments_1,
        v2.department_codes  AS departments_2,
        v1.first_payment     AS first_payment_1,
        v1.last_payment      AS last_payment_1,
        v2.first_payment     AS first_payment_2,
        v2.last_payment      AS last_payment_2,
        COALESCE(c.shared_contracts, 0) AS shared_contracts,
        COALESCE(p.shared_pos, 0)       AS shared_pos
    FROM name_pairs n
    JOIN vendor_list v1 ON v1.vendor = n.vendor_1
    JOIN vendor_list v2 ON v2.vendor = n.vendor_2
    LEFT JOIN shared_contracts c ON c.vendor_1 = n.vendor_1 AND c.vendor_2 = n.vendor_2
    LEFT JOIN shared_pos p       ON p.vendor_1 = n.vendor_1 AND p.vendor_2 = n.vendor_2
),
rated AS (
    SELECT
        *,
        CASE
            WHEN shared_contracts > 0 OR shared_pos > 0       THEN 'High'
            WHEN match_type = 'Identical after cleanup'       THEN 'High'
            WHEN similarity >= 95                             THEN 'Medium'
            ELSE 'Low'
        END AS confidence
    FROM evidence
)
SELECT
    ROW_NUMBER() OVER (
        ORDER BY CASE confidence WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                 total_paid_1 + total_paid_2 DESC
    ) AS candidate_id,
    *
FROM rated;
