-- Names: database, schema, warehouse, roles. Template: copy to settings.local.sql (git-ignored) and fill in.
-- run_sql.py and SnowSQL (!source sql/*.sql) read settings.local.sql. Account and user: env vars of sf.py (.env).
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
