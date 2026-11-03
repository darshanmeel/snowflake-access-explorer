-- SnowSQL: setup + first snapshot, each with its verification. Names: settings.local.sql. Run from the access-explorer folder:
--   snowsql -a <org>-<account> -u <user> --authenticator externalbrowser -f deploy_snowsql.sql
-- or key pair (passphrase in env var PRIVATE_KEY_PASSPHRASE):
--   snowsql -a <org>-<account> -u <user> --private-key-path <rsa_key.p8> -f deploy_snowsql.sql
-- Browser SSO or key pair only: no password, none in the SnowSQL config.
!source settings.local.sql
!source sql/1_setup.sql
!source sql/1_setup_verify.sql
!source sql/2_snapshot.sql
!source sql/2_snapshot_verify.sql
