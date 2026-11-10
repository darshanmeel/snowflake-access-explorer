-- Who reaches an object: the roles that hold a grant on it, the roles above them and the users at the end.
-- OBJECT_NAME: DB, DB.SCHEMA, DB.SCHEMA.OBJECT, or an account object (a warehouse, ...). Only grants on
-- that exact object count: a grant on its schema or database is not followed. PRIVILEGE = '' means any.
-- Inputs: the SET lines below. Run the whole file (Snowsight: select all, then Run).
-- Output: one row per grantee and privilege: GRANTEE, GRANTEE_KIND (USER | ROLE | DATABASE ROLE), PRIVILEGE,
--   GRANTED_ON, HOLDER (the role that holds the grant, DEPTH 1), DEPTH, PATH (grantee > ... > holder), WAYS
-- Needs: read access to SNOWFLAKE.ACCOUNT_USAGE (IMPORTED PRIVILEGES on database SNOWFLAKE, or the database role
--   SNOWFLAKE.SECURITY_VIEWER or SNOWFLAKE.GOVERNANCE_VIEWER). ACCOUNT_USAGE lags up to about 2 hours.
-- Same rules as the app (access.py): active rows only (DELETED_ON IS NULL); role link = USAGE on a ROLE or
--   DATABASE_ROLE; a database role is named DB.ROLE; links granted to an admin role (ACCOUNTADMIN, SECURITYADMIN,
--   SYSADMIN, USERADMIN, ORGADMIN) are left out, holding an admin role is kept; DEPTH = roles from the start to the
--   role, that role included (a user is not a role); every user holds PUBLIC; names compare exactly as stored
--   (unquoted names are upper case). No future grants (not in ACCOUNT_USAGE).
-- One row per answer with its shortest PATH ('A > B > C') and WAYS = how many role paths lead there. Every path
--   instead: remove the QUALIFY line. Role cycles stop by themselves.
-- MAX_DEPTH (NULL = 50, the app's limit) cuts longer chains: roles past it are left out and WAYS counts only the
--   paths within it, with no sign in the output; to check, rerun with a higher value and compare the row count.
-- SHOW_BUILTIN = TRUE also lists Snowflake's own grants via PUBLIC (SNOWFLAKE.* database roles, system pools ...).

SET OBJECT_NAME = 'SALES.CORE.TBL_CUSTOMER';
SET PRIVILEGE = '';
SET MAX_DEPTH = 50;
SET SHOW_BUILTIN = FALSE;

WITH RECURSIVE
ARGS AS (SELECT CAST($OBJECT_NAME AS VARCHAR) AS A_OBJ, CAST($PRIVILEGE AS VARCHAR) AS A_PRIV,
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
PRIV AS (   -- every other grant is a privilege on an object (OWNERSHIP of a role too)
    SELECT G.GRANTEE, CASE WHEN G.GRANTED_TO = 'DATABASE_ROLE' THEN 'DATABASE ROLE' ELSE 'ROLE' END AS KIND,
           G.PRIVILEGE, G.GRANTED_ON, G.OBJ
    FROM GR G
    WHERE NOT (G.GRANTED_ON IN ('ROLE', 'DATABASE_ROLE') AND G.PRIVILEGE = 'USAGE')),
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
HELD AS (   -- the grants on the object
    SELECT P.GRANTEE, P.KIND, P.PRIVILEGE, P.GRANTED_ON
    FROM PRIV P CROSS JOIN ARGS A
    WHERE P.OBJ = A.A_OBJ AND (COALESCE(A.A_PRIV, '') = '' OR P.PRIVILEGE = A.A_PRIV) AND A.A_MAX >= 1),
UP (HOLDER, HOLDER_KIND, NODE, KIND, DEPTH, PATH, SEEN) AS (   -- every simple path up, once per holder, not per privilege
    SELECT CAST(P.GRANTEE AS VARCHAR), CAST(P.KIND AS VARCHAR), CAST(P.GRANTEE AS VARCHAR), CAST(P.KIND AS VARCHAR),
           CAST(1 AS INTEGER), CAST(P.GRANTEE AS VARCHAR), CAST(CHR(31) || P.GRANTEE || CHR(31) AS VARCHAR)
    FROM (SELECT DISTINCT X.GRANTEE, X.KIND FROM HELD X) P
    UNION ALL
    SELECT U.HOLDER, U.HOLDER_KIND, E.PARENT, E.PARENT_KIND, U.DEPTH + 1, E.PARENT || ' > ' || U.PATH,
           U.SEEN || E.PARENT || CHR(31)
    FROM UP U JOIN EDGE E ON E.CHILD = U.NODE CROSS JOIN ARGS A
    WHERE U.DEPTH < A.A_MAX AND POSITION(CHR(31) || E.PARENT || CHR(31) IN U.SEEN) = 0),
H AS (   -- the paths up, then each privilege of their holder joined back
    SELECT W.GRANTEE, W.GRANTEE_KIND, P.PRIVILEGE, P.GRANTED_ON, W.HOLDER, W.DEPTH, W.PATH
    FROM (SELECT U.NODE AS GRANTEE, U.KIND AS GRANTEE_KIND, U.HOLDER, U.HOLDER_KIND, U.DEPTH, U.PATH FROM UP U
          UNION ALL
          SELECT M.USR, 'USER', U.HOLDER, U.HOLDER_KIND, U.DEPTH, M.USR || ' > ' || U.PATH
          FROM UP U JOIN MEMBER M ON M.NODE = U.NODE) W
    JOIN HELD P ON P.GRANTEE = W.HOLDER AND P.KIND = W.HOLDER_KIND)
SELECT H.GRANTEE, H.GRANTEE_KIND, H.PRIVILEGE, H.GRANTED_ON, H.HOLDER, H.DEPTH, H.PATH,
       COUNT(*) OVER (PARTITION BY H.GRANTEE, H.GRANTEE_KIND, H.PRIVILEGE, H.GRANTED_ON) AS WAYS
FROM H
QUALIFY ROW_NUMBER() OVER (PARTITION BY H.GRANTEE, H.GRANTEE_KIND, H.PRIVILEGE, H.GRANTED_ON
                           ORDER BY H.DEPTH, H.PATH) = 1
ORDER BY H.GRANTEE_KIND DESC, H.GRANTEE, H.PRIVILEGE;
