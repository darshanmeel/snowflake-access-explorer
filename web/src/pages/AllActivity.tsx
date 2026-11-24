// Activity: the whole account's table use. Which users, roles, clients and objects, crossed two by two, over the last
// 7 days, month or the whole window; the server counts (access.activity_all).
import type { ReactNode } from "react";
import { useApi } from "../api/client";
import type { ActDim, AllActivityPage } from "../api/types";
import { Banner, Card, DataTable, EmptyState, FilterChips, Fold, Tabs } from "../components";
import { useApp } from "../ctx";
import { Heat } from "./Activity";
import { col, Head, Load } from "./common";

const ONE: Record<ActDim, string> = { user: "User", role: "Role", client: "Client", object: "Object" };
const TAB: Record<ActDim, string> = { user: "Users", role: "Roles", client: "Clients", object: "Objects" };
const ORDER: ActDim[] = ["user", "role", "object", "client"];
const fmt = (n: number) => n.toLocaleString("en-US");
const tail = (v: string) => v.split(".").slice(-2).join(".");

export function AllActivityPageView() {
  const c = useApp();
  const r = (ORDER as string[]).includes(c.params.r ?? "") ? c.params.r as ActDim : "user";
  const others = ORDER.filter((x) => x !== r);
  const across = others.includes(c.params.c as ActDim) ? c.params.c as ActDim : r === "client" ? "user" : "client";
  const days = c.params.days ?? "30";
  const s = useApi<AllActivityPage>("activity", { view: c.view, days, r, c: across });
  const open = (k: ActDim, v: string) => k === "object" ? c.nav("object", { name: v, show: "activity" })
    : k === "user" ? c.nav("access", { user: v, show: "activity" }) : k === "role" && v !== "–" ? c.nav("access", { role: v, show: "activity" }) : undefined;
  const gone = new Set(s.data?.gone ?? []);
  const link = (k: ActDim, v: string) => k === "client" || /^Other \(\d+\)$/.test(v) ? v
    : gone.has(v) ? <span className="ae-mono" title={`${v}: not in this snapshot`}>{k === "object" ? tail(v) : v}</span>
    : <button type="button" className="ae-link ae-mono" title={v} onClick={() => open(k, v)}>{k === "object" ? tail(v) : v}</button>;
  return (
    <>
      <Head title="Activity" quiet />
      <Tabs nav active={r} onChange={(k) => c.set({ r: k === "user" ? null : k, c: null })} tabs={ORDER.map((k) => ({ key: k, label: TAB[k], count: s.data?.n?.[k] ?? null }))} />
      <Load s={s}>{(d) => !d.available ? <Card><EmptyState title="– No table activity" art="wait">{d.reason}</EmptyState></Card> : (
        <div className="ae-log">
          <FilterChips label="Period" value={days} onPick={(v) => c.set({ days: v === "30" ? null : v })}
            items={d.periods.map((n) => ({ key: String(n), label: n === 7 ? "Last 7 days" : n === 30 ? "Last month" : `Last ${n} days` }))} />
          {d.note && <Banner title="Activity partly read" lines={[d.note]} />}
          {!d.total ? <p className="ae-log-lead">No use recorded in the last {d.days} days.</p> : <>
            <p className="ae-log-lead">{r === "object" ? tail(d.dims![r][0].key) : d.dims![r][0].key} {r === "object" ? "gets" : r === "client" ? "brings" : "makes"} {Math.round((100 * d.dims![r][0].n) / d.total)}% of all queries</p>
            <div className="ae-log-tiles ae-log-three">
              <Tile label="Queries" value={fmt(d.total)} cap={`${fmt(d.reads!)} reads · ${fmt(d.writes!)} writes · ${fmt(d.ddl!)} definition changes · ${d.days} days`} />
              <Tile label="Main client" value={d.dims!.client[0].key} cap={`${Math.round((100 * d.dims!.client[0].n) / d.total)}% of the queries${d.dims!.client.length > 1 ? `, then ${d.dims!.client.slice(1, 4).map((x) => x.key).join(", ")}` : ""}`} />
              <Tile label="Outside business hours" value={d.hours === false ? "not recorded" : fmt(d.off!)} warn={d.hours !== false && d.off! > 0} cap={d.hours === false ? "this snapshot has no hours" : `${Math.round((100 * d.off!) / d.total)}% · weekends or outside ${String(d.work.start).padStart(2, "0")}:00–${d.work.end}:00 UTC`} />
            </div>
            <Card title={`${ONE[r]}s by ${ONE[across].toLowerCase()}`} sub="Red: of these, outside business hours."
              right={<FilterChips label="Across" value={across} onPick={(v) => c.set({ c: v })} items={others.map((k) => ({ key: k, label: `× ${ONE[k].toLowerCase()}` }))} />}>
              <Cross d={d} link={link} />
            </Card>
            <Card title="Who did what, with what, and when last" sub={d.who_total! > d.who!.length ? `The busiest ${d.who!.length} of ${fmt(d.who_total!)}` : undefined}>
              <DataTable csv="activity.csv" rows={d.who!} columns={[
                col("user", "User", (x: Who) => x.user, { wrap: "wrap", render: (x: Who) => <>{link("user", x.user)}{x.kind === "service" && <span className="ae-muted"> service</span>}</> }),
                col("role", "Role used", (x: Who) => x.role, { wrap: "wrap", render: (x: Who) => link("role", x.role) }),
                col("client", "Client", (x: Who) => x.client, { wrap: "wrap" }),
                col("object", "Object", (x: Who) => x.object, { wrap: "wrap", render: (x: Who) => <>{link("object", x.object)}{x.sensitive && <span className="ae-sens-dot" title="sensitive" aria-label="sensitive" />}</> }),
                col("rd", "Reads", (x: Who) => x.read, { num: true }), col("w", "Writes", (x: Who) => x.write, { num: true }),
                col("ddl", "Defs", (x: Who) => x.ddl, { num: true, help: "Definition changes: CREATE, ALTER, DROP" }),
                col("off", "Off-hours", (x: Who) => x.off, { num: true }), col("last", "Last", (x: Who) => x.last, { wrap: "nowrap", render: (x: Who) => x.last.slice(5) }),
              ]} />
              <p className="ae-muted"><span className="ae-sens-dot" /> sensitive</p>
            </Card>
            <When d={d} />
            <p className="ae-muted">ACCESS_HISTORY with QUERY_HISTORY and SESSIONS, {d.days} days to {d.last}. No query text.</p>
          </>}
        </div>
      )}</Load>
    </>
  );
}

const DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Per day, and per weekday and hour, folded. */
function When({ d }: { d: AllActivityPage }) {
  const xs = d.daily ?? [], top = Math.max(1, ...xs.map((x) => x.queries)), hs = d.by_hour ?? [], most = Math.max(1, ...hs.flat());
  if (!xs.length) return null;
  return (
    <Fold label="When: per day and hour">
      <Card title="Queries per day" sub={`${xs[0].day} to ${xs[xs.length - 1].day}. Red: outside business hours.`}>
        <div className="ae-daybars" role="img" aria-label={`Queries per day, at most ${fmt(top)}`}>
          {xs.map((x) => <span key={x.day} title={`${x.day}: ${fmt(x.queries)} queries, ${fmt(x.off)} outside business hours`} style={{ height: `${(100 * x.queries) / top}%` }}><i style={{ height: `${x.queries ? (100 * x.off) / x.queries : 0}%` }} /></span>)}</div>
      </Card>
      {d.hours !== false && <Card title="Queries per weekday and hour (UTC)">
        <div className="ae-hourgrid" role="img" aria-label="Queries per weekday and hour">
          {hs.map((row, i) => <div key={DAY[i]}><span className="ae-muted">{DAY[i]}</span>{row.map((n, h) => <i key={h} title={`${DAY[i]} ${h}:00: ${fmt(n)}`} style={{ background: n ? `color-mix(in srgb, var(--ae-accent) ${10 + (70 * n) / most}%, var(--ae-panel))` : undefined }} />)}</div>)}
          <div><span />{Array.from({ length: 24 }, (_, h) => <b key={h} className="ae-muted">{h % 3 ? "" : h}</b>)}</div></div>
      </Card>}
    </Fold>
  );
}

type Who = NonNullable<AllActivityPage["who"]>[number];

function Cross({ d, link }: { d: AllActivityPage; link: (k: ActDim, v: string) => ReactNode }) {
  const x = d.cross!, ri = new Map(x.rows.map((v, i) => [v, i])), ci = new Map(x.cols.map((v, i) => [v, i]));
  return <Heat corner={ONE[x.r]} colName={ONE[x.c]} rows={x.rows} cols={x.cols} color="var(--ae-accent)"
    value={(p, q) => x.cells[ri.get(p)!]?.[ci.get(q)!] ?? 0} off={(p, q) => x.off[ri.get(p)!]?.[ci.get(q)!] ?? 0}
    rowHead={(p) => link(x.r, p)} colHead={(q) => link(x.c, q)} />;
}

function Tile({ label, value, cap, warn }: { label: string; value: string; cap: string; warn?: boolean }) {
  return <div className={`ae-log-tile${warn ? " ae-tone-warn" : ""}`}><span className="ae-log-tl">{label}</span><span className="ae-log-tv">{value}</span><span className="ae-muted">{cap}</span></div>;
}
