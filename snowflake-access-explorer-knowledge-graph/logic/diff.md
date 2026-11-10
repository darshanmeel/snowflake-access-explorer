# What changed (facts, diff)

What changed compares the loaded snapshot with the previous one: `facts()` per data set, `diff(prev)` turns differences into events.

```mermaid
flowchart LR
  CP["server.changes_page<br/>server.py:1646-1667"] -->|FAKE| FP["a.fake_previous()<br/>access.py:387-398"]
  CP -->|snowflake, local| PR["cache.prev(KEY)<br/>cache.py:84-90"]
  CP --> D["a.diff(prev)<br/>access.py:4370-4452"]
  D --> FN["facts() now<br/>access.py:4242-4268"]
  D --> LD["loaded(prev): facts() old<br/>access.py:4229-4237"]
  D --> GE["grant_events()<br/>access.py:4330-4353"]
  D --> EV[events + counts]
```

## facts() (`access.py:4242-4268`)
- `access {(user, object): (level, privileges)}` on tables/views, merging per granted role `table_reach()`; users with the same granted roles share the work (`access.py:4248-4260`).
- `table_reach(r)` / `own_tables(h)` cached per role (`access.py:4271-4293`); `table_level()` gives the ladder level (`access.py:4301-4308`).
- `grants` keyed `(grantee, privilege, granted on, object)` -> `GRANTED_BY`; admin role links and hidden built-ins left out (`access.py:4262-4263`).
- `user_roles`, `findings` (keyed num, grantee, user, detail), `status`, `sens`, `run` (`access.py:4264-4267`).

## diff(prev) (`access.py:4370-4452`)
- Old side built with `loaded(prev)` (save, build, restore) (`access.py:4379`, `4203-4211`).
- Gained / lost = new pair or higher level on `LEVELS` (`access.py:4381-4384`, `LEVELS` `access.py:1071`).
- Findings: same (rule, grantee, user) counts as the same finding (`access.py:4385-4387`).
- Grant events for removed and added grants and user-role links (`access.py:4388-4393`), each with impact text (`impact_text`, `access.py:4319-4327`).
- User status changes (new, gone, dormant, disabled) (`access.py:4417-4427`); new/fixed findings not tied to a grant event (`access.py:4428-4442`).
- Sort `risk, gain, lose, user, fixed` (`access.py:4443-4444`); counts per filter `event_counts()` (`access.py:4356-4360`); severity strips (`access.py:4447-4449`).
- Server caches per previous run: `a.cached(("diff", cache.run_of(prev)), ...)` (`server.py:1664`).
- Not available on My access view, inside Snowflake, or with `CACHE_HOURS=0` (`server.py:1650-1662`).

## Example (fake data, verified)
- `fake_previous()`: a week earlier, GRP_ANALYSTS without F_ANALYST, READ role without INSERT, F_MARKETING with SALES.CORE write, F_ANALYST with an OWNER role, ANALYST_02 not dormant (`access.py:387-398`).
- `diff(fake_previous())` -> counts `all 11, gain 2, lose 2, risk 6, sensitive 7`; new 9, fixed 2; runs `2026-10-26 07:00` -> `2026-11-02 07:00`.
- First event: `risk` - `New high finding · #7 Dormant or disabled person can read sensitive data: ANALYST_02`.
