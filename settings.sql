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
