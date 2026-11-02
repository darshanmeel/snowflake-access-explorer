-- 2 · snapshot (developer role): fills the TBL_ACCESS_ tables. Run by hand when the app needs fresh data (no task yet).
-- P_SOURCE: 'AUTO' (ACCOUNT_USAGE where readable, else SHOW), 'ACCOUNT_USAGE' or 'SHOW' (live, slower: 2 queries per role).
-- ACCOUNT_USAGE lags up to ~2 hours; SHOW is live. The result lists the source used per dataset and why.
-- SnowSQL: !source sql/2_snapshot.sql (from the access-explorer folder)
!source settings.local.sql
USE ROLE &DEV_ROLE;
USE SECONDARY ROLES NONE;   -- as inside the owner's-rights procedure
USE WAREHOUSE &WH;
USE DATABASE &DB;

-- name: SNAPSHOT
CALL &DB.&SCHEMA.SP_ACCESS_SNAPSHOT('AUTO');
