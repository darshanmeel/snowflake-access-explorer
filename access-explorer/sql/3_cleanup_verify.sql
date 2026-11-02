-- Verification of 3_cleanup.sql. SnowSQL: !source sql/3_cleanup_verify.sql (shows the rows; no verdict).

-- name: TABLES (expect 0)
SHOW TABLES LIKE 'TBL_ACCESS_%' IN SCHEMA &DB.&SCHEMA;

-- name: PROCEDURE (expect 0)
SHOW PROCEDURES LIKE 'SP_ACCESS_SNAPSHOT' IN SCHEMA &DB.&SCHEMA;
