// Activity tab of an object, a person or a role: who used which tables, with which role and client, per day over the
// last ACTIVITY_DAYS (ACCESS_HISTORY + QUERY_HISTORY + SESSIONS), the grant paths behind it and what they see of
// sensitive data. Query metadata only, never query text.
import { useState } from "react";
import { useApi } from "../api/client";
import type { ActivityBy, ActivityKey, ActivityPage, ActivityRow, ActivitySensitive } from "../api/types";
import { Banner, Card, CodeOutput, DataTable, DayStack, EmptyState, FilterChips, FindingChip, KpiRow, Tabs } from "../components";
import { useApp } from "../ctx";
import { col, GraphCard, Load } from "./common";
import { bars } from "./history";

const LABEL: Record<ActivityKey, string> = { user: "User", role: "Role", client: "Client", type: "Statement", object: "Table" };
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const sum = (b: ActivityBy) => b.read + b.write + b.ddl;
const ROWS = { all: "all rows", filtered: "filtered rows", none: "no rows", unknown: "rows unknown" } as const;

export function ActivityTab({ what, name, user }: { what: ActivityPage["what"]; name: string; user?: string }) {
  const c = useApp();
  const s = useApi<ActivityPage>("activity", { view: c.view, [what === "object" ? "name" : what]: name, as: user });
  return <Load s={s}>{(d) => <>{d.user && <Only d={d} />}<Activity d={d} /></>}</Load>;
}

/** The object page's "Access for" person narrows the tab to their use; one click shows everyone again. */
function Only({ d }: { d: ActivityPage }) {
  const c = useApp();
  return (
    <div className="ae-row">
      <span className="ae-chip ae-chip-plain">Only {d.user}'s use</span>
      <button type="button" className="ae-btn" onClick={() => c.set({ as: null })}>All users</button>
    </div>
  );
}

/** One line for the "Access for" strip: what this person did on the object in the activity window. */
export function UseLine({ name, user }: { name: string; user: string }) {
  const c = useApp();
  const s = useApi<ActivityPage>(user ? "activity" : null, { view: c.view, name, as: user });
  const d = s.data;
  if (!d) return null;
  if (!d.available) return <span className="ae-muted" title={d.reason ?? ""}>Use: –</span>;
  const n = d.daily!.reduce((a, v) => a + v, 0);
  if (!n) return <span className="ae-muted">Not used in {d.days} days</span>;
  const last = d.by!.user[0]?.last.slice(0, 10);
  return (
    <button type="button" className="ae-link" onClick={() => c.set({ show: "activity", as: user })}>
      Used: {n} quer{n === 1 ? "y" : "ies"} in {d.days} days as {d.by!.role.map((r) => r.key).join(", ")} ({d.by!.client.map((r) => r.key).join(", ")}), last {last}
    </button>
  );
}

function Activity({ d }: { d: ActivityPage }) {
  const c = useApp();
  const [part, setPart] = useState("summary");
  if (!d.available) return <Card><EmptyState title="– No table activity" art="wait">{d.reason}</EmptyState></Card>;
  const by = d.by!, days = d.daily!, sens = d.sensitive!;
  if (!d.rows!.length) return <Card><EmptyState title="No activity" art="clear">{d.user ? `${d.user} did not use` : "Nothing used"} {d.name} between {d.first} and {d.last}.</EmptyState></Card>;
  const open = (k: ActivityKey, v: string) => k === "object" ? c.nav("object", { name: v, show: "activity" })
    : k === "user" ? c.nav("access", { user: v, show: "activity" }) : k === "role" && v !== "–" ? c.nav("access", { role: v, show: "activity" }) : undefined;
  const total = days.reduce((n, v) => n + v, 0);
  const clear = sens.reduce((n, o) => n + o.people.filter((p) => p.clear.length).length, 0);
  return (
    <>
      {d.note && <Banner title="Activity partly read" lines={[d.note]} />}
      <KpiRow items={[
        { label: "Queries", value: total, caption: `${days.filter(Boolean).length} of ${d.days} days`, help: "Per action: a MERGE that reads and changes a table counts twice" },
        ...(["user", "role", "client", d.what === "object" ? "type" : "object"] as ActivityKey[]).filter((k) => k !== d.what)
          .map((k) => ({ label: `${LABEL[k]}s`, value: by[k].length })),
        { label: "Sensitive seen in clear", value: clear, caption: `${plural(sens.length, "table")} with sensitive data or policies`, tone: clear ? "bad" as const : null },
        { label: "DDL changes", value: d.ddl!.reduce((n, r) => n + r.queries, 0), tone: d.ddl!.length ? "warn" as const : null },
      ]} />
      {d.findings!.length > 0 && <div className="ae-row">{d.findings!.map((f, i) => (
        <FindingChip key={i} num={f.num} severity={f.severity} label={`${f.title}: ${f.grantee}`} onOpen={() => c.nav("rules", { rule: f.num })} />))}</div>}
      <Tabs active={part} onChange={setPart} tabs={[
        { key: "summary", label: "Per day & by" },
        { key: "paths", label: "Paths", count: d.gone!.length ? d.gone!.length : null, tone: d.gone!.length ? "warn" : null },
        { key: "rows", label: "Who, role, client", count: d.total },
        { key: "sensitive", label: "Sensitive", count: sens.length, tone: clear ? "bad" : null },
        { key: "ddl", label: "DDL changes", count: d.ddl!.length, tone: d.ddl!.length ? "warn" : null },
      ]} />
      {part === "summary" && <Summary d={d} open={open} />}
      {part === "paths" && <Paths d={d} />}
      {part === "rows" && <Rows d={d} rows={d.rows!} open={open} />}
      {part === "sensitive" && <Sensitive d={d} />}
      {part === "ddl" && (d.ddl!.length ? <Rows d={d} rows={d.ddl!} open={open} />
        : <Card><EmptyState title="No DDL" art="clear">No CREATE, ALTER or DROP between {d.first} and {d.last}.</EmptyState></Card>)}
    </>
  );
}

function Summary({ d, open }: { d: ActivityPage; open: (k: ActivityKey, v: string) => void }) {
  const keys = (["user", "role", "client", "type", "object"] as ActivityKey[]).filter((k) => k !== d.what);
  const [k, setK] = useState<ActivityKey>(keys[0]);
  const list = d.by![k];
  return (
    <>
      <Card title={`Queries per day, by ${LABEL[k].toLowerCase()}`} sub={`${d.first} → ${d.last} · hover a day for its numbers`}
        right={<FilterChips label="By" value={k} onPick={(v) => setK(v as ActivityKey)} items={keys.map((x) => ({ key: x, label: LABEL[x], count: d.by![x].length }))} />}>
        <DayStack first={d.first!} label={d.name} series={list.map((b) => ({ key: b.key, values: b.daily }))} />
      </Card>
      <Card title={`By ${LABEL[k].toLowerCase()}`}>
        <DataTable rows={list} csv={`${d.name}_activity_by_${k}.csv`} sort={{ key: "all", dir: -1 }}
          onRowClick={k === "user" || k === "role" || k === "object" ? (r) => open(k, r.key) : undefined} columns={[
            col<ActivityBy>("key", LABEL[k], (r) => r.key, { render: (r) => <span className="ae-mono">{r.key}</span> }),
            col<ActivityBy>("days", "Per day", (r) => r.daily.filter(Boolean).length, { render: (r) => <Mini d={d} v={r.daily} /> }),
            col<ActivityBy>("all", "Queries", sum, { num: true }),
            col<ActivityBy>("read", "Read", (r) => r.read, { num: true }),
            col<ActivityBy>("write", "Write", (r) => r.write, { num: true }),
            col<ActivityBy>("ddl", "DDL", (r) => r.ddl, { num: true }),
            col<ActivityBy>("last", "Last", (r) => r.last),
          ]} />
      </Card>
    </>
  );
}

/** 60 small bars, one per day; hover gives the date and count. */
function Mini({ d, v }: { d: ActivityPage; v: number[] }) {
  const hs = bars(v, 16);
  const date = (i: number) => new Date(Date.parse(d.first!) + i * 864e5).toISOString().slice(0, 10);
  return (
    <span className="ae-bars ae-bars-sm" role="img" aria-label={`Queries per day: active on ${v.filter(Boolean).length} of ${v.length} days`}>
      {hs.map((h, i) => <span key={i} className={v[i] ? "on" : ""} style={{ height: h }} title={`${date(i)}: ${v[i]}`} />)}
    </span>
  );
}

function Paths({ d }: { d: ActivityPage }) {
  const c = useApp();
  return (
    <>
      {d.graph ? <GraphCard g={d.graph} refs={d.refs} />
        : <Card><EmptyState title="No grant path to draw" art="search">None of the roles used reaches a grant on these tables now.</EmptyState></Card>}
      {d.gone!.length > 0 && (
        <Card title="Used, but with no grant path now" sub="An admin role, or the grant was removed after the query: worth a look.">
          <DataTable rows={d.gone!} csv={`${d.name}_activity_no_path.csv`} rowTone={() => "warn"} columns={[
            col<NonNullable<ActivityPage["gone"]>[number]>("user", "User", (r) => r.user, { render: (r) => <button type="button" className="ae-link ae-mono" onClick={() => c.nav("access", { user: r.user, show: "activity" })}>{r.user}</button> }),
            col<NonNullable<ActivityPage["gone"]>[number]>("role", "Role used", (r) => r.role),
            col<NonNullable<ActivityPage["gone"]>[number]>("object", "Table", (r) => r.object),
            col<NonNullable<ActivityPage["gone"]>[number]>("action", "Action", (r) => r.action),
          ]} />
        </Card>
      )}
    </>
  );
}

function Sensitive({ d }: { d: ActivityPage }) {
  const c = useApp();
  type P = ActivitySensitive["people"][number] & { object: string };
  const people: P[] = d.sensitive!.flatMap((o) => o.people.map((p) => ({ ...p, object: o.object })));
  return (
    <>
      {d.sensitive!.length > 0 && (
        <Card title="Sensitive data and policies" sub="From tags (SENSITIVE_TAGS), masking and row access policies.">
          <DataTable rows={d.sensitive!} csv={`${d.name}_sensitive_tables.csv`} filter={false} columns={[
            col<ActivitySensitive>("object", "Table", (o) => o.object, { render: (o) => <button type="button" className="ae-link ae-mono" onClick={() => c.nav("object", { name: o.object, show: "activity" })}>{o.object}</button> }),
            col<ActivitySensitive>("cols", "Sensitive", (o) => !o.sensitive ? "not tagged" : o.whole ? "whole table" : o.columns.join(", ")),
            col<ActivitySensitive>("masking", "Column masking", (o) => Object.entries(o.masking).map(([k, ps]) => `${k}: ${ps.map((p) => p.split(".").pop()).join(", ")}`).join("; ") || "none"),
            col<ActivitySensitive>("rls", "Row access policy", (o) => o.row_policies.map((p) => p.split(".").pop()).join(", ") || "none"),
          ]} />
        </Card>
      )}
      {people.length > 0 && (
        <Card title="What each user and role used sees" sub="From the policy text for the role the query ran with: sensitive columns in clear are the risk.">
          <DataTable rows={people} csv={`${d.name}_activity_sensitive.csv`} rowTone={(r) => r.clear.length ? "bad" : null} columns={[
            ...(d.what === "object" ? [] : [col<P>("object", "Table", (r) => r.object, { render: (r) => <span className="ae-mono">{r.object}</span> })]),
            col<P>("user", "User", (r) => r.user),
            col<P>("role", "Role used", (r) => r.role),
            col<P>("clear", "Sensitive in clear", (r) => r.clear.join(", ") || "none", { render: (r) => r.clear.length ? <b className="ae-bad">{r.clear.join(", ")}</b> : <span className="ae-muted">none</span> }),
            col<P>("masked", "Masked", (r) => r.masked.join(", ") || "–"),
            col<P>("rows", "Rows", (r) => ROWS[r.rows]),
            col<P>("read", "Can read now", (r) => r.read ? "yes" : "no"),
          ]} />
        </Card>
      )}
      {!d.sensitive!.length && !d.mark && <Card><EmptyState title="No sensitive data" art="clear">None of these tables carries a sensitive tag or a masking or row access policy.</EmptyState></Card>}
      {d.mark && (
        <Card title="Mark this table as sensitive" sub={`It has no sensitive tag. Tag it with ${d.mark.tag} = '${d.mark.value}', or let Snowflake classify its columns.`}>
          <CodeOutput changes={[]} name={`${d.name}_mark_sensitive`} texts={{ sql: d.mark.sql, tf: d.mark.tf, ticket: d.mark.ticket }} />
        </Card>
      )}
    </>
  );
}

function Rows({ d, rows, open }: { d: ActivityPage; rows: ActivityRow[]; open: (k: ActivityKey, v: string) => void }) {
  const cols = (["user", "role", "client", "object", "type"] as ActivityKey[]).filter((k) => k !== d.what);
  return (
    <Card sub={rows.length < (d.total ?? 0) && rows === d.rows ? `First ${rows.length} of ${plural(d.total!, "row")}, most queries first` : undefined}>
      <DataTable rows={rows} csv={`${d.name}_activity.csv`} sort={{ key: "queries", dir: -1 }} rowTone={(r) => r.action === "DDL" ? "warn" : null} columns={[
        ...cols.map((k) => col<ActivityRow>(k, LABEL[k], (r) => r[k], k === "user" || k === "role" || k === "object"
          ? { render: (r) => <button type="button" className="ae-link ae-mono" onClick={() => open(k, r[k])}>{r[k]}</button> } : {})),
        col<ActivityRow>("action", "Action", (r) => r.action),
        col<ActivityRow>("daily", "Per day", (r) => r.daily.filter(Boolean).length, { render: (r) => <Mini d={d} v={r.daily} /> }),
        col<ActivityRow>("queries", "Queries", (r) => r.queries, { num: true }),
        col<ActivityRow>("days", "Days", (r) => r.days, { num: true }),
        col<ActivityRow>("last", "Last", (r) => r.last),
      ]} />
    </Card>
  );
}
