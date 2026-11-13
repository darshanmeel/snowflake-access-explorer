// Activity tab of an object, a person or a role: who used which tables, with which role and client, per day over the
// last ACTIVITY_DAYS (ACCESS_HISTORY + QUERY_HISTORY + SESSIONS). Query metadata only, never query text.
import { useState } from "react";
import { useApi } from "../api/client";
import type { ActivityBy, ActivityKey, ActivityPage, ActivityRow } from "../api/types";
import { Banner, Card, DataTable, EmptyState, FilterChips, FindingChip, KpiRow, Tabs } from "../components";
import { useApp } from "../ctx";
import { col, Load } from "./common";
import { bars } from "./history";

const LABEL: Record<ActivityKey, string> = { user: "User", role: "Role", client: "Client", type: "Statement", object: "Table" };
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const sum = (b: ActivityBy) => b.read + b.write + b.ddl;

export function ActivityTab({ what, name }: { what: ActivityPage["what"]; name: string }) {
  const c = useApp();
  const s = useApi<ActivityPage>("activity", { view: c.view, [what === "object" ? "name" : what]: name });
  return <Load s={s}>{(d) => <Activity d={d} />}</Load>;
}

function Activity({ d }: { d: ActivityPage }) {
  const c = useApp();
  const [part, setPart] = useState("summary");
  if (!d.available) return <Card><EmptyState title="– No table activity" art="wait">{d.reason}</EmptyState></Card>;
  const by = d.by!, days = d.daily!;
  if (!d.rows!.length) return <Card><EmptyState title="No activity" art="clear">Nothing used {d.name} between {d.first} and {d.last}.</EmptyState></Card>;
  const open = (k: ActivityKey, v: string) => k === "object" ? c.nav("object", { name: v, show: "activity" })
    : k === "user" ? c.nav("access", { user: v, show: "activity" }) : k === "role" && v !== "–" ? c.nav("access", { role: v, show: "activity" }) : undefined;
  const total = days.reduce((n, v) => n + v, 0);
  const active = days.filter(Boolean).length;
  return (
    <>
      {d.note && <Banner title="Activity partly read" lines={[d.note]} />}
      <KpiRow items={[
        { label: "Queries", value: total, caption: `${active} of ${d.days} days`, help: "Per action: a MERGE that reads and changes a table counts twice" },
        ...(["user", "role", "client", d.what === "object" ? "type" : "object"] as ActivityKey[]).filter((k) => k !== d.what)
          .map((k) => ({ label: `${LABEL[k]}s`, value: by[k].length })),
        { label: "DDL changes", value: d.ddl!.reduce((n, r) => n + r.queries, 0), tone: d.ddl!.length ? "warn" as const : null },
      ]} />
      {d.findings!.length > 0 && <div className="ae-row">{d.findings!.map((f, i) => (
        <FindingChip key={i} num={f.num} severity={f.severity} label={`${f.title}: ${f.grantee}`} onOpen={() => c.nav("rules", { rule: f.num })} />))}</div>}
      <Tabs active={part} onChange={setPart} tabs={[
        { key: "summary", label: "Per day & by" },
        { key: "rows", label: "Who, role, client", count: d.total },
        { key: "ddl", label: "DDL changes", count: d.ddl!.length, tone: d.ddl!.length ? "warn" : null },
      ]} />
      {part === "summary" && <Summary d={d} open={open} />}
      {part === "rows" && <Rows d={d} rows={d.rows!} open={open} />}
      {part === "ddl" && (d.ddl!.length ? <Rows d={d} rows={d.ddl!} open={open} />
        : <Card><EmptyState title="No DDL" art="clear">No CREATE, ALTER or DROP between {d.first} and {d.last}.</EmptyState></Card>)}
    </>
  );
}

function Summary({ d, open }: { d: ActivityPage; open: (k: ActivityKey, v: string) => void }) {
  const keys = (["user", "role", "client", "type", "object"] as ActivityKey[]).filter((k) => k !== d.what);
  const [k, setK] = useState<ActivityKey>(keys[0]);
  const days = d.daily!, hs = bars(days);
  const date = (i: number) => new Date(Date.parse(d.first!) + i * 864e5).toISOString().slice(0, 10);
  return (
    <>
      <Card title="Queries per day" sub={`${d.first} → ${d.last}`}>
        <span className="ae-bars" role="img" aria-label={`Queries per day over ${days.length} days`}>
          {hs.map((h, i) => <span key={i} className={days[i] ? "on" : ""} style={{ height: h }} title={`${date(i)}: ${days[i]} quer${days[i] === 1 ? "y" : "ies"}`} />)}
        </span>
      </Card>
      <Card title={`By ${LABEL[k].toLowerCase()}`} right={<FilterChips label="By" value={k} onPick={(v) => setK(v as ActivityKey)}
        items={keys.map((x) => ({ key: x, label: LABEL[x], count: d.by![x].length }))} />}>
        <DataTable rows={d.by![k]} csv={`${d.name}_activity_by_${k}.csv`} sort={{ key: "all", dir: -1 }}
          onRowClick={k === "user" || k === "role" || k === "object" ? (r) => open(k, r.key) : undefined} columns={[
            col<ActivityBy>("key", LABEL[k], (r) => r.key, { render: (r) => <span className="ae-mono">{r.key}</span> }),
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

function Rows({ d, rows, open }: { d: ActivityPage; rows: ActivityRow[]; open: (k: ActivityKey, v: string) => void }) {
  const cols = (["user", "role", "client", "object", "type"] as ActivityKey[]).filter((k) => k !== d.what);
  return (
    <Card sub={rows.length < (d.total ?? 0) && rows === d.rows ? `First ${rows.length} of ${plural(d.total!, "row")}, most queries first` : undefined}>
      <DataTable rows={rows} csv={`${d.name}_activity.csv`} sort={{ key: "queries", dir: -1 }} rowTone={(r) => r.action === "DDL" ? "warn" : null} columns={[
        ...cols.map((k) => col<ActivityRow>(k, LABEL[k], (r) => r[k], k === "user" || k === "role" || k === "object"
          ? { render: (r) => <button type="button" className="ae-link ae-mono" onClick={() => open(k, r[k])}>{r[k]}</button> } : {})),
        col<ActivityRow>("action", "Action", (r) => r.action),
        col<ActivityRow>("queries", "Queries", (r) => r.queries, { num: true }),
        col<ActivityRow>("days", "Days", (r) => r.days, { num: true }),
        col<ActivityRow>("last", "Last", (r) => r.last),
      ]} />
    </Card>
  );
}
