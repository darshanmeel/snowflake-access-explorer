-- Every privilege a user reaches through its roles: what the user can finally do, on which object.
-- Inputs: the SET lines below. Run the whole file (Snowsight: select all, then Run).
-- Output: one row per privilege and object: PRIVILEGE, GRANTED_ON, OBJECT_NAME (DB, DB.SCHEMA, DB.SCHEMA.OBJECT, or the bare
--   name of an account object), VIA_ROLE (the role that holds the grant), DEPTH, PATH, WAYS
-- Needs: read access to SNOWFLAKE.ACCOUNT_USAGE (IMPORTED PRIVILEGES on database SNOWFLAKE, or the database role
--   SNOWFLAKE.SECURITY_VIEWER or SNOWFLAKE.GOVERNANCE_VIEWER). ACCOUNT_USAGE lags up to about 2 hours.
-- Same rules as the app (access.py): active rows only (DELETED_ON IS NULL); role link = USAGE on a ROLE or
--   DATABASE_ROLE; a database role is named DB.ROLE; links granted to an admin role (ACCOUNTADMIN, SECURITYADMIN,
--   SYSADMIN, USERADMIN, ORGADMIN) are left out, holding an admin role is kept; DEPTH = roles from the start to the
--   role, that role included (a user is not a role); every user holds PUBLIC; names compare exactly as stored
--   (unquoted names are upper case). No future grants (not in ACCOUNT_USAGE).
-- One row per answer with its shortest PATH ('A > B > C') and WAYS = how many role paths lead there. Paths are
--   counted per role (ROLES), then summed per object, never listed per privilege. Every path to each role:
--   SELECT * FROM WALK in place of the last SELECT. Role cycles stop by themselves.
-- MAX_DEPTH (NULL = 50, the app's limit) cuts longer chains: roles past it are left out and WAYS counts only the
--   paths within it, with no sign in the output; to check, rerun with a higher value and compare the row count.
-- SHOW_BUILTIN = TRUE also lists Snowflake's own grants via PUBLIC (SNOWFLAKE.* database roles, system pools ...).

SET USER_NAME = 'ANALYST_01';
SET MAX_DEPTH = 50;
SET SHOW_BUILTIN = FALSE;

WITH RECURSIVE
ARGS AS (SELECT CAST($USER_NAME AS VARCHAR) AS A_USER,
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
    SELECT G.GRANTEE AS PARENT, G.OBJ AS CHILD
    FROM GR G
    WHERE G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE'
      AND G.GRANTEE NOT IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN', 'ORGADMIN')),
PRIV AS (   -- every other grant is a privilege on an object (OWNERSHIP of a role too)
    SELECT G.GRANTEE, G.PRIVILEGE, G.GRANTED_ON, G.OBJ
    FROM GR G
    WHERE NOT (G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE')),
UR AS (
    SELECT U.GRANTEE_NAME AS USR, U.ROLE AS ROLE_NAME
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS U WHERE U.DELETED_ON IS NULL),
ALL_USERS AS (   -- every user holds PUBLIC, granted or not
    SELECT U.USR FROM UR U
    UNION
    SELECT U.NAME FROM SNOWFLAKE.ACCOUNT_USAGE.USERS U WHERE U.DELETED_ON IS NULL),
ME AS (   -- joins, not IN: a NULL name would empty NOT IN
    SELECT (SELECT COUNT(*) FROM ALL_USERS X JOIN ARGS A ON X.USR = A.A_USER) AS IS_USER,
           (SELECT COUNT(*) FROM UR U JOIN ARGS A ON U.USR = A.A_USER WHERE U.ROLE_NAME = 'PUBLIC') AS HAS_PUBLIC),
STARTS AS (   -- the user's granted roles, plus PUBLIC when it is not granted
    SELECT U.ROLE_NAME AS NODE FROM UR U JOIN ARGS A ON U.USR = A.A_USER
    UNION ALL
    SELECT 'PUBLIC' FROM ME M WHERE M.IS_USER > 0 AND M.HAS_PUBLIC = 0),
WALK (NODE, DEPTH, PATH, SEEN) AS (   -- every simple path down; SEEN = the roles on it, so a cycle stops
    SELECT CAST(S.NODE AS VARCHAR), CAST(1 AS INTEGER),
           CAST(A.A_USER || ' > ' || S.NODE AS VARCHAR), CAST(CHR(31) || S.NODE || CHR(31) AS VARCHAR)
    FROM STARTS S CROSS JOIN ARGS A
    WHERE A.A_MAX >= 1
    UNION ALL
    SELECT E.CHILD, W.DEPTH + 1, W.PATH || ' > ' || E.CHILD, W.SEEN || E.CHILD || CHR(31)
    FROM WALK W JOIN EDGE E ON E.PARENT = W.NODE CROSS JOIN ARGS A
    WHERE W.DEPTH < A.A_MAX AND POSITION(CHR(31) || E.CHILD || CHR(31) IN W.SEEN) = 0),
ROLES AS (   -- one row per role reached: its shortest path, and how many paths lead to it
    SELECT W.NODE, W.DEPTH, W.PATH, COUNT(*) OVER (PARTITION BY W.NODE) AS ROLE_WAYS
    FROM WALK W
    QUALIFY ROW_NUMBER() OVER (PARTITION BY W.NODE ORDER BY W.DEPTH, W.PATH) = 1)
SELECT P.PRIVILEGE, P.GRANTED_ON, P.OBJ AS OBJECT_NAME, W.NODE AS VIA_ROLE, W.DEPTH, W.PATH,
       SUM(W.ROLE_WAYS) OVER (PARTITION BY P.PRIVILEGE, P.GRANTED_ON, P.OBJ) AS WAYS
FROM ROLES W JOIN PRIV P ON P.GRANTEE = W.NODE
QUALIFY ROW_NUMBER() OVER (PARTITION BY P.PRIVILEGE, P.GRANTED_ON, P.OBJ ORDER BY W.DEPTH, W.PATH) = 1
ORDER BY OBJECT_NAME, PRIVILEGE;
