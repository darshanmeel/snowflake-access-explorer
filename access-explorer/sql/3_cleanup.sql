-- 3 · cleanup (developer role): deletes the procedure and the 7 snapshot tables with their data. The schema stays.
-- SnowSQL: !source sql/3_cleanup.sql (from the access-explorer folder)
!source settings.local.sql
USE ROLE &DEV_ROLE;
USE SECONDARY ROLES NONE;   -- as inside the owner's-rights procedure
USE WAREHOUSE &WH;
USE DATABASE &DB;
-- Cannot be undone.

-- name: DROP_PROCEDURE (may fail)
DROP PROCEDURE IF EXISTS &DB.&SCHEMA.SP_ACCESS_SNAPSHOT(VARCHAR);

-- name: DROP_TABLE_RUN (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_RUN;

-- name: DROP_TABLE_GRANT (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_GRANT;

-- name: DROP_TABLE_USER_ROLE (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_USER_ROLE;

-- name: DROP_TABLE_USER (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_USER;

-- name: DROP_TABLE_USAGE (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_USAGE;

-- name: DROP_TABLE_TAG (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_TAG;

-- name: DROP_TABLE_POLICY (may fail)
DROP TABLE IF EXISTS &DB.&SCHEMA.TBL_ACCESS_POLICY;
