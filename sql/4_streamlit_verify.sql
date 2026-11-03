-- Verification of 4_streamlit.sql. SnowSQL: !source sql/4_streamlit_verify.sql (shows the rows; no verdict).

-- name: STREAMLIT (expect 1)
SHOW STREAMLITS LIKE 'ST_ACCESS_EXPLORER' IN SCHEMA &DB.&SCHEMA;

-- app files on the stage: 8 at the root (9 with sis/.env), plus web/dist-st
-- name: STAGE_FILES
LIST @&DB.&SCHEMA.STG_ACCESS_APP;

-- name: GRANT_STREAMLIT
SHOW GRANTS ON STREAMLIT &DB.&SCHEMA.ST_ACCESS_EXPLORER;
