-- 4 · Streamlit in Snowflake (developer role): uploads the app to a stage and creates the Streamlit app the app role may open.
-- Two options (sis/.env, README > Deploy):
--   SOURCE=objects (recommended for a team): run 1_setup.sql and 2_snapshot.sql first; the app reads the TBL_ACCESS_
--     tables, ACCESS_SNAPSHOT=<DB>.<SCHEMA>.
--   SOURCE=direct: only this file, no tables, procedures or task. The app reads ACCOUNT_USAGE live with the owner role
--     (&DEV_ROLE), which needs GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE &DEV_ROLE (or the SNOWFLAKE
--     database roles SECURITY_VIEWER + GOVERNANCE_VIEWER). &DB.&SCHEMA only holds the stage and the app.
-- The React bundle web/dist-st is committed: no npm needed. The app runs with the owner's rights (&DEV_ROLE) and
-- writes nothing. Settings for the app inside Snowflake: sis/.env (required, git-ignored; template sis.env.example),
-- uploaded as the app's .env. Never SNOWFLAKE_ACCOUNT.
-- Safe to run again: files are overwritten and the app is replaced, which loads the new files.
-- SnowSQL: !source sql/4_streamlit.sql (from the repo folder)
!source settings.local.sql
USE ROLE &DEV_ROLE;
USE SECONDARY ROLES NONE;
USE WAREHOUSE &WH;
USE DATABASE &DB;

-- name: STAGE_APP
CREATE STAGE IF NOT EXISTS &DB.&SCHEMA.STG_ACCESS_APP COMMENT = 'Access explorer: Streamlit app files';

-- name: PUT_APP
PUT 'file://&HERE/app.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_ACCESS
PUT 'file://&HERE/access.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_CACHE
PUT 'file://&HERE/cache.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_SERVER
PUT 'file://&HERE/server.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_SF
PUT 'file://&HERE/sf.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_ST_REACT
PUT 'file://&HERE/st_react.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_UI
PUT 'file://&HERE/ui.py' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- packages (streamlit pinned, snowflake-snowpark-python); the rest is the standard library.
-- .streamlit/config.toml is not uploaded: its settings (toolbar, usage stats) are for local runs only.
-- name: PUT_QUERIES
PUT 'file://&HERE/access_queries/*.sql' @&DB.&SCHEMA.STG_ACCESS_APP/access_queries AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_ENVIRONMENT
PUT 'file://&HERE/environment.yml' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_WEB_INDEX
PUT 'file://&HERE/web/dist-st/index.html' @&DB.&SCHEMA.STG_ACCESS_APP/web/dist-st AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- the bundle's file names carry a content hash: remove the old ones, or every redeploy adds another 2 MB copy
-- name: CLEAR_WEB_ASSETS (may fail)
REMOVE @&DB.&SCHEMA.STG_ACCESS_APP/web/dist-st/assets/;

-- name: PUT_WEB_ASSETS
PUT 'file://&HERE/web/dist-st/assets/*' @&DB.&SCHEMA.STG_ACCESS_APP/web/dist-st/assets AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: PUT_SETTINGS
PUT 'file://&HERE/sis/.env' @&DB.&SCHEMA.STG_ACCESS_APP AUTO_COMPRESS = FALSE OVERWRITE = TRUE;

-- name: STREAMLIT
CREATE OR REPLACE STREAMLIT &DB.&SCHEMA.ST_ACCESS_EXPLORER
    FROM @&DB.&SCHEMA.STG_ACCESS_APP
    MAIN_FILE = 'app.py'
    QUERY_WAREHOUSE = &WH
    TITLE = 'Access explorer'
    COMMENT = 'Access explorer: read-only, shows who has what access and through which path';

-- the app role also needs USAGE on the database, schema and warehouse (as 1_setup.sql; here for SOURCE=direct)
-- name: GRANT_DATABASE_APP (may fail)
GRANT USAGE ON DATABASE &DB TO ROLE &APP_ROLE;

-- name: GRANT_SCHEMA_APP (may fail)
GRANT USAGE ON SCHEMA &DB.&SCHEMA TO ROLE &APP_ROLE;

-- name: GRANT_WAREHOUSE_APP (may fail)
GRANT USAGE ON WAREHOUSE &WH TO ROLE &APP_ROLE;

-- name: GRANT_STREAMLIT
GRANT USAGE ON STREAMLIT &DB.&SCHEMA.ST_ACCESS_EXPLORER TO ROLE &APP_ROLE;
