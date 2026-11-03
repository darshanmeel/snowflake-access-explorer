# snowflake-utilities

Run plain SQL on Snowflake from your machine (connection + cursor).

## Setup
```
python -m venv .venv
.venv\Scripts\activate
pip install snowflake-connector-python
```

Set env vars (PowerShell):
```
$env:SNOWFLAKE_ACCOUNT="<org>-<account>"
$env:SNOWFLAKE_USER="<your user>"
$env:SNOWFLAKE_ROLE="<role>"            # optional
$env:SNOWFLAKE_WAREHOUSE="<warehouse>"  # optional
# key pair instead of browser SSO:
# $env:SNOWFLAKE_PRIVATE_KEY_FILE="C:\path\rsa_key.p8"
# $env:SNOWFLAKE_PRIVATE_KEY_PWD="<passphrase>"   # if the key is encrypted
```
Two logins only: key pair when `SNOWFLAKE_PRIVATE_KEY_FILE` is set, else browser SSO. Passwords are not supported.
## Use
```
python sf.py "select current_user(), current_role(), current_warehouse()"
python sf.py -f query.sql
```
```python
from sf import connect, run
cols, rows = run("select 1")
```

## Notes
- User, role and warehouse come from the platform team; roles and grants are managed as infrastructure as code.
- Do not create or change databases, roles or grants from here; that causes drift.
- Accounts behind a private endpoint need that network or VPN.

## Guardrail: no company terms in commits
- `.githooks/pre-commit` blocks a commit if a staged file or file name matches a term in `~/.company-terms.txt` (one regex per line, kept outside the repo).
- Turn it on once after `git init`: `git config core.hooksPath .githooks`. No list file = commit blocked.
