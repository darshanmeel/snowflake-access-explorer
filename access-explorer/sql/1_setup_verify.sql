-- Verification of 1_setup.sql: each "-- name:" check prints OK, MISSING, WRONG (row count, "(expect N)") or SKIPPED ("(may fail)"),
-- then VERIFIED or NOT VERIFIED. SnowSQL: !source sql/1_setup_verify.sql (shows the rows; no verdict).

-- name: TABLES (expect 7)
SHOW TABLES LIKE 'TBL_ACCESS_%' IN SCHEMA &DB.&SCHEMA;

-- name: PROCEDURE
DESCRIBE PROCEDURE &DB.&SCHEMA.SP_ACCESS_SNAPSHOT(VARCHAR);

-- which sources the procedure can use: an error here = that dataset uses the SHOW fallback
-- name: ACCOUNT_USAGE_GRANTS_TO_ROLES (may fail)
SELECT COUNT(*) AS N FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES WHERE DELETED_ON IS NULL;

-- name: ACCOUNT_USAGE_GRANTS_TO_USERS (may fail)
SELECT COUNT(*) AS N FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS WHERE DELETED_ON IS NULL;

-- name: ACCOUNT_USAGE_USERS (may fail)
SELECT COUNT(*) AS N FROM SNOWFLAKE.ACCOUNT_USAGE.USERS WHERE DELETED_ON IS NULL;

-- name: ACCOUNT_USAGE_QUERY_HISTORY (may fail)
SELECT COUNT(*) AS N FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(DAY, -1, CURRENT_TIMESTAMP());

-- tags and policies: an error here = per-object INFORMATION_SCHEMA fallback (max 300 tables/views); 0 rows on Standard edition
-- name: ACCOUNT_USAGE_TAG_REFERENCES (may fail)
SELECT COUNT(*) AS N FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES WHERE OBJECT_DELETED IS NULL;

-- name: ACCOUNT_USAGE_POLICY_REFERENCES (may fail)
SELECT COUNT(*) AS N FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES;

-- account privileges of the developer role: MANAGE GRANTS here = the SHOW fallback sees every grant
-- name: DEV_ROLE_GRANTS (may fail)
SHOW GRANTS TO ROLE &DEV_ROLE;
