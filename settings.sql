-- Names: database, schema, warehouse, roles. Template: copy to settings.local.sql (git-ignored) and fill in.
-- run_sql.py and SnowSQL (!source sql/*.sql) read settings.local.sql; run_sql.py takes a name it lacks from here, SnowSQL
-- needs every name in it. Account and user: env vars of sf.py (.env).
!set variable_substitution=true
-- database and schema of the snapshot tables and the procedure
!define DB=<DB>
!define SCHEMA=<SCHEMA>
-- warehouse for the procedure and the app
!define WH=<WH>
-- developer role: creates and owns the tables and the procedure; the procedure reads grants with its rights
!define DEV_ROLE=<DEV_ROLE>
-- the app's role: SELECT on the snapshot tables only (may be the developer role)
!define APP_ROLE=<APP_ROLE>
-- SnowSQL only (run_sql.py fills it in): absolute path of the repo folder, forward slashes, for PUT
!define HERE=<HERE>
-- name of the Streamlit app inside Snowflake (letters, digits, - and _ only); must match STREAMLIT_APP in .env and sis/.env
!define STREAMLIT_APP=ST_ACCESS_EXPLORER
-- query tag on the local app's connection, left out of the activity (letters, digits, - and _ only); must match QUERY_TAG in .env and sis/.env
!define QUERY_TAG=access-explorer
-- seconds each statement of SP_ACCESS_SNAPSHOT may run, 0 = Snowflake's own (STATEMENT_TIMEOUT in .env: the app's)
!define STATEMENT_TIMEOUT=300
-- heavy reads of SP_ACCESS_SNAPSHOT at once (ACCESS_HISTORY, QUERY_HISTORY), 1 = one after another
!define WORKERS=3
-- 0: SP_ACCESS_SNAPSHOT reads no ACCESS_HISTORY (object use, activity: the Activity tabs and rules 24-28 are off)
!define ACTIVITY=1
