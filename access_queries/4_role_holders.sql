-- Who holds a role, upwards: every role that holds it directly or through other roles, and every user at
-- the end. A database role: ROLE_NAME = 'DB.ROLE'.
-- Inputs: the SET lines below. Run the whole file (Snowsight: select all, then Run).
-- Output: one row per holder: HOLDER, HOLDER_KIND (USER | ROLE | DATABASE ROLE), DEPTH (the role itself is 1),
--   PATH (holder > ... > role), WAYS
-- Needs: read access to SNOWFLAKE.ACCOUNT_USAGE (IMPORTED PRIVILEGES on database SNOWFLAKE, or the database role
--   SNOWFLAKE.SECURITY_VIEWER or SNOWFLAKE.GOVERNANCE_VIEWER). ACCOUNT_USAGE lags up to about 2 hours.
-- Same rules as the app (access.py): active rows only (DELETED_ON IS NULL); role link = USAGE on a ROLE or
--   DATABASE_ROLE; a database role is named DB.ROLE; links granted to an admin role (ACCOUNTADMIN, SECURITYADMIN,
--   SYSADMIN, USERADMIN, ORGADMIN) are left out, holding an admin role is kept; DEPTH = roles from the start to the
--   role, that role included (a user is not a role); every user holds PUBLIC; names compare exactly as stored
--   (unquoted names are upper case). No future grants (not in ACCOUNT_USAGE).
-- Links between admin roles are left out too: for SECURITYADMIN or SYSADMIN also check ROLE_NAME = 'ACCOUNTADMIN'.
-- One row per answer with its shortest PATH ('A > B > C') and WAYS = how many role paths lead there. Every path
--   instead: remove the QUALIFY line. Role cycles stop by themselves.
-- MAX_DEPTH (NULL = 50, the app's limit) cuts longer chains: roles past it are left out and WAYS counts only the
--   paths within it, with no sign in the output; to check, rerun with a higher value and compare the row count.
-- SHOW_BUILTIN = TRUE also lists Snowflake's own grants via PUBLIC (SNOWFLAKE.* database roles, system pools ...).

SET ROLE_NAME = 'T_SALES_CORE_READ';
SET MAX_DEPTH = 50;
SET SHOW_BUILTIN = FALSE;

WITH RECURSIVE
ARGS AS (SELECT CAST($ROLE_NAME AS VARCHAR) AS A_ROLE,
                CAST(COALESCE($MAX_DEPTH, 50) AS INTEGER) AS A_MAX, CAST($SHOW_BUILTIN AS BOOLEAN) AS A_BUILTIN),
G AS (   -- active grants to account and database roles; a database role is named DB.ROLE, as the app does
    SELECT CASE WHEN R.GRANTED_TO = 'DATABASE_ROLE'
                THEN CASE WHEN R.GRANTED_ON = 'DATABASE' THEN R.NAME ELSE R.TABLE_CATALOG END || '.' || R.GRANTEE_NAME
                ELSE R.GRANTEE_NAME END AS GRANTEE,
           R.GRANTED_TO, R.PRIVILEGE, R.GRANTED_ON,
           CASE WHEN R.GRANTED_ON = 'DATABASE' THEN R.NAME   -- DATABASE rows may repeat the name in TABLE_CATALOG
                WHEN R.GRANTED_ON = 'SCHEMA' THEN R.TABLE_CATALOG || '.' || R.NAME
                ELSE COALESCE(R.TABLE_CATALOG || '.', '') || COALESCE(R.TABLE_SCHEMA || '.', '') || R.NAME END AS OBJ
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES R
    WHERE R.DELETED_ON IS NULL AND R.GRANTED_TO IN ('ROLE', 'DATABASE_ROLE')),
GR AS (   -- Snowflake's own grants (SNOWFLAKE.* database roles, system compute pools, ...) only with SHOW_BUILTIN
    SELECT G.* FROM G CROSS JOIN ARGS A
    WHERE A.A_BUILTIN
       OR NOT (LEFT(G.GRANTEE, 10) = 'SNOWFLAKE.' OR LEFT(G.GRANTEE, 7) = 'SYSTEM$'
               OR LEFT(G.GRANTEE, 20) = 'SYSTEM_COMPUTE_POOL_' OR LEFT(G.GRANTEE, 19) = 'SNOWFLAKE_LEARNING_'
               OR (G.GRANTEE = 'PUBLIC' AND (LEFT(G.OBJ, 10) = 'SNOWFLAKE.' OR LEFT(G.OBJ, 7) = 'SYSTEM$'
                   OR LEFT(G.OBJ, 20) = 'SYSTEM_COMPUTE_POOL_' OR LEFT(G.OBJ, 19) = 'SNOWFLAKE_LEARNING_')))),
EDGE AS (   -- role links; links granted to an admin role are left out: every custom role sits under SYSADMIN
    SELECT G.GRANTEE AS PARENT, G.OBJ AS CHILD,
           CASE WHEN G.GRANTED_TO = 'DATABASE_ROLE' THEN 'DATABASE ROLE' ELSE 'ROLE' END AS PARENT_KIND
    FROM GR G
    WHERE G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE'
      AND G.GRANTEE NOT IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN', 'ORGADMIN')),
UR AS (
    SELECT U.GRANTEE_NAME AS USR, U.ROLE AS ROLE_NAME
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS U WHERE U.DELETED_ON IS NULL),
ALL_USERS AS (   -- every user holds PUBLIC, granted or not
    SELECT U.USR FROM UR U
    UNION
    SELECT U.NAME FROM SNOWFLAKE.ACCOUNT_USAGE.USERS U WHERE U.DELETED_ON IS NULL),
MEMBER AS (   -- role -> user; PUBLIC -> every user
    SELECT U.ROLE_NAME AS NODE, U.USR FROM UR U WHERE U.ROLE_NAME <> 'PUBLIC'
    UNION ALL
    SELECT 'PUBLIC', X.USR FROM ALL_USERS X),
UP (NODE, KIND, DEPTH, PATH, SEEN) AS (   -- every simple path up; SEEN = the roles on it, so a cycle stops
    SELECT CAST(A.A_ROLE AS VARCHAR), CAST('ROLE' AS VARCHAR), CAST(1 AS INTEGER), CAST(A.A_ROLE AS VARCHAR),
           CAST(CHR(31) || A.A_ROLE || CHR(31) AS VARCHAR)
    FROM ARGS A
    WHERE A.A_MAX >= 1
    UNION ALL
    SELECT E.PARENT, E.PARENT_KIND, U.DEPTH + 1, E.PARENT || ' > ' || U.PATH, U.SEEN || E.PARENT || CHR(31)
    FROM UP U JOIN EDGE E ON E.CHILD = U.NODE CROSS JOIN ARGS A
    WHERE U.DEPTH < A.A_MAX AND POSITION(CHR(31) || E.PARENT || CHR(31) IN U.SEEN) = 0),
H AS (
    SELECT U.NODE AS HOLDER, U.KIND AS HOLDER_KIND, U.DEPTH, U.PATH FROM UP U WHERE U.DEPTH > 1
    UNION ALL
    SELECT M.USR, 'USER', U.DEPTH, M.USR || ' > ' || U.PATH FROM UP U JOIN MEMBER M ON M.NODE = U.NODE)
SELECT H.HOLDER, H.HOLDER_KIND, H.DEPTH, H.PATH, COUNT(*) OVER (PARTITION BY H.HOLDER, H.HOLDER_KIND) AS WAYS
FROM H
QUALIFY ROW_NUMBER() OVER (PARTITION BY H.HOLDER, H.HOLDER_KIND ORDER BY H.DEPTH, H.PATH) = 1
ORDER BY HOLDER_KIND DESC, DEPTH, HOLDER;
