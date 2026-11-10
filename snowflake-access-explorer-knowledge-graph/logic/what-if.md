# What if (simulation)

`a.what_if(changes)` removes grants in memory, rebuilds, compares before/after, then restores every lookup; it only prints REVOKE / IaC text, never runs it.

```mermaid
sequenceDiagram
  participant S as server.what_if<br/>server.py:1854-1865
  participant W as access.what_if<br/>access.py:3943-4121
  participant L as lookups (build)
  S->>W: changes JSON list
  W->>W: changes_of(): cut + label/iac/sql (3835-3879)
  W->>W: before: reach per touched user (3950-3956)
  W->>L: saved = state(), was = dict(built) (3998)
  W->>L: build(without_cuts(source.data, cut)) (3978)
  W->>W: after: lost / kept per user, findings(only) (3992-4018)
  W->>L: restore(saved), built put back to was, in finally (4043-4046)
  W-->>S: summary, users, objects, roles, findings, iac, sql, csv
```

## Ops (`WHAT_IF_OPS`, `access.py:3851`)
- `revoke_role_from_user` (role, user), `revoke_role_from_role` (role, grantee): if held further down, cut where it is granted on the user's paths too (`access.py:3865-3880`).
- `revoke_priv` (role, privilege, object) (`access.py:3881-3887`).
- `drop_role` (role): refused for PUBLIC and admin roles (`access.py:3888-3893`).
- `empty_public`: every grant to PUBLIC (`access.py:3894-3898`).
- Unknown op or missing grant -> `ValueError` (`access.py:3872`, `3862`, `3867`, `3877`); server answers 400 `bad_change` (`server.py:1862-1865`).

## Simulation and restore
- `without_cuts(d, cut)`: data set minus removed GRANT / USER_ROLE rows (`access.py:3905-3913`).
- `state()` copies every name in `STATE` (`access.py:3852-3855`, `4210-4213`); `restore()` puts them back in place; `REBOUND` names are rebound (`access.py:4216-4226`).
- Rebuild in `try`, `restore(saved)` in `finally` (`access.py:4000-4046`), so the loaded data set and its cached results (`memo`) come back.
- `built` (the `KEEP_BUILT` sets) is copied first and put back after (`built.clear(); built.update(was)`, `access.py:3998`, `4045-4046`): the simulated build stores the loaded set in `built`, which would otherwise keep a stale or simulated entry. `loaded(d)` does the same (`access.py:4232`, `4238-4239`).
- Rules recheck only scoped names: `only` built from `SCOPED`/`GROW` and touched grantees (`access.py:3983-3990`, `4018`).

## Output
- Per user: lost / kept rows, `kept_roles` (roles under a cut still reached) (`access.py:4064-4072`).
- Objects nobody reaches or without owner; roles left orphan or unreached (`access.py:4081-4084`).
- Findings `fixed` / `new` / `changed` (`access.py:4073-4080`); summary text (`access.py:4096-4103`); CSV rows (`access.py:4104-4119`).
- IaC + SQL text from `fix_text()` / `revoke()` (`access.py:3117-3148`); OWNERSHIP gives a transfer text, not REVOKE (`access.py:3134-3136`).

## Example (fake data, verified)
- Input: `[{"op":"revoke_role_from_user","role":"GRP_ANALYSTS","user":"ANALYST_01"}]`
- Summary: `1 user loses access to 9 objects; 1 keeps access through another path (most via PUBLIC); 1 finding fixed, 0 new`
- SQL: `REVOKE ROLE GRP_ANALYSTS FROM USER ANALYST_01;`
- IaC: `Remove in the infrastructure-as-code repo: role GRP_ANALYSTS granted to user ANALYST_01`
- Finding fixes feed What if via `fix_changes(edges)` (`access.py:4461-4470`).
- Tests: `test_access.py:991-1027` (what_if calls).
