-- SnowSQL: setup + first snapshot, each with its verification. Names: settings.local.sql. Run from the access-explorer folder:
--   snowsql -a <org>-<account> -u <user> --authenticator externalbrowser -f deploy_snowsql.sql
!source settings.local.sql
!source sql/1_setup.sql
!source sql/1_setup_verify.sql
!source sql/2_snapshot.sql
!source sql/2_snapshot_verify.sql
