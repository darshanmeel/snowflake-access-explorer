// Activity tab, laid out as an access log and shaped by what is open: a table or view (who used it and how), a
// Streamlit app (who opened it, who could, who saw its owner's sensitive data), a database or schema (every object in
// it), a warehouse (who ran queries on it), a person or a role (the objects they used). Sections: off-hours use, hours
// of use (UTC, working hours on a slider), objects busiest first, an object in detail (clients, statements, role x
// client, per day), who used it, sensitive data seen, grant paths, every query as copy-only SQL, the checks.
// ACCESS_HISTORY + QUERY_HISTORY + SESSIONS metadata only, never query text.
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useApi } from "../api/client";
import type { ActivityBy, ActivityKey, ActivityPage, ActivityRow, ActivitySensitive } from "../api/types";
import { Banner, Card, CodeOutput, copyText, DataTable, DayStack, EmptyState, FilterChips } from "../components";
import { useApp } from "../ctx";
import { col, GraphCard, Load, Pick } from "./common";

const LABEL: Record<ActivityKey, string> = { user: "User", role: "Role", client: "Client", type: "Statement", object: "Table" };
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const fmt = (n: number) => n.toLocaleString("en-US");
const sum = (b: ActivityBy) => b.read + b.write + b.ddl;
const ROWS = { all: "all rows", filtered: "filtered rows", none: "no rows", unknown: "rows unknown" } as const;
const ACT = { WRITE: "var(--ae-e_write)", READ: "var(--ae-warn_ink)", DDL: "var(--ae-ok_ink)" } as const;
const ACT_LABEL = { WRITE: "Writes", READ: "Reads", DDL: "DDL" } as const;
const ACTS = ["WRITE", "READ", "DDL"] as const;
type Work = { start: number; end: number; tz: number }; // business hours, local; tz: local = UTC + tz hours
type Open = (k: ActivityKey, v: string) => void;
/** Off-hours queries of a row: weekends, plus weekday hours outside [start, end) local time (UTC + tz). */
export const offOf = (r: Pick<ActivityRow, "hours" | "weekend">, w: Work) =>  // rows already in business time (localize)
  r.weekend + r.hours.reduce((n, v, h) => n + (h < w.start || h >= w.end ? v : 0), 0);

/** Rows moved from UTC to business time (UTC + tz hours): each query to its local day and hour (dh), weekends by the
 * local day; queries shifted out of the window at either end drop out. */
export function localize(rows: ActivityRow[], tz: number, first: string, days: number): ActivityRow[] {
  if (!tz) return rows;
  const wd0 = new Date(first + "T00:00:00Z").getUTCDay();
  return rows.map((r) => {
    if (!r.dh?.length) return r;  // a snapshot from before hours were kept
    const daily = Array(days).fill(0) as number[], hours = Array(24).fill(0) as number[], wh = Array(24).fill(0) as number[];
    for (const [i, h, n] of r.dh) {
      const t = i * 24 + h + tz, di = Math.floor(t / 24), lh = ((t % 24) + 24) % 24;
      if (di < 0 || di >= days) continue;
      daily[di] += n;
      ([0, 6].includes((wd0 + di) % 7) ? wh : hours)[lh] += n;
    }
    const weekend = wh.reduce((a, v) => a + v, 0);
    return { ...r, daily, hours, weekend, weekend_hours: wh, queries: daily.reduce((a, v) => a + v, 0), days: daily.filter(Boolean).length };
  }).filter((r) => r.queries > 0);
}
/** "UTC+2", "UTC−5", "UTC+0". */
const tzl = (w: Work) => `UTC${w.tz < 0 ? "−" : "+"}${Math.abs(w.tz)}`;
/** Business hours as text: "07:00–19:00 UTC+2". */
const biz = (w: Work) => `${hh(w.start)}–${hh(w.end)} ${tzl(w)}`;
const short = (d: string) => new Date(d.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
const initials = (n: string) => { const w = n.split(/[_\s.]+/).filter(Boolean); return ((w[0]?.[0] ?? "") + (w[1]?.[0] ?? w[0]?.[1] ?? "")).toUpperCase(); };

export function ActivityTab({ what, name, user }: { what: "object" | "user" | "role"; name: string; user?: string }) {
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
  if (!d || d.what === "warehouse") return null;
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

/** The SQL behind each section (activity_page section_sql), by section key. */
const SectionSql = createContext<Record<string, string>>({});

/** A section card; sql: the key of the query behind it, shown on its SQL button. */
function Sec({ title, sub, right, children, id, sql }: { title: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; id?: string; sql?: string }) {
  return <div id={id}><Card title={title} sub={sub} right={right} sql={useContext(SectionSql)[sql ?? ""]}>{children}</Card></div>;
}

function Seg<K extends string>({ value, items, onPick, label }: { value: K; items: [K, string][]; onPick: (k: K) => void; label: string }) {
  return <FilterChips label={label} value={value} onPick={(k) => onPick(k as K)} items={items.map(([key, l]) => ({ key, label: l }))} />;
}

function Tile({ label, value, cap, tone }: { label: ReactNode; value: ReactNode; cap?: ReactNode; tone?: "warn" | "bad" | null }) {
  return <div className={`ae-log-tile${tone ? ` ae-tone-${tone}` : ""}`}><span className="ae-log-tl">{label}</span><span className="ae-log-tv">{value}</span>{cap != null && <span className="ae-muted">{cap}</span>}</div>;
}

function Activity({ d: raw }: { d: ActivityPage }) {
  const c = useApp();
  const [work, setWork] = useState<Work>({ ...(raw.work ?? { start: 7, end: 19 }), tz: 0 });
  // everything below sees the rows in business time: days, hours, weekends and off-hours follow the slider
  const d = useMemo(() => {
    if (!raw.rows || !work.tz) return raw;
    const rows = localize(raw.rows, work.tz, raw.first!, raw.days ?? 60);
    return { ...raw, rows, daily: rows.reduce((t, r) => t.map((v, i) => v + r.daily[i]), Array(raw.days ?? 60).fill(0) as number[]),
      ddl: rows.filter((r) => r.action === "DDL") };
  }, [raw, work.tz]);
  // each section's SQL with the slider's business time filled in
  const secSql = useMemo(() => Object.fromEntries(Object.entries(raw.section_sql ?? {}).map(([k, v]) => [k, v.replace("SET TZ_HOURS = 0;", `SET TZ_HOURS = ${work.tz};`)])), [raw.section_sql, work.tz]);
  if (d.what === "warehouse") return <Warehouse d={d} />;
  if (!d.available) return <Card><EmptyState title="– No table activity" art="wait">{d.reason}</EmptyState></Card>;
  const rows = d.rows!;
  const open: Open = (k, v) => k === "object" ? c.nav("object", { name: v, show: "activity" })
    : k === "user" ? c.nav("access", { user: v, show: "activity" }) : k === "role" && v !== "–" ? c.nav("access", { role: v, show: "activity" }) : undefined;
  if (!rows.length) return (
    <div className="ae-log">
      {d.what === "app" && d.app && <AppViewers d={d} />}
      <Card><EmptyState title="No activity" art="clear">{d.user ? `${d.user} did not use` : "Nothing used"} {d.name} between {d.first} and {d.last}.
        {d.kind && !["TABLE", "VIEW", "MATERIALIZED VIEW", "DYNAMIC TABLE", "EXTERNAL TABLE", "STREAMLIT", "DATABASE", "SCHEMA", "STAGE", "FUNCTION"].includes(d.kind)
          && ` Snowflake records table and view use in ACCESS_HISTORY; a ${d.kind.toLowerCase()} may not show up there. Who can use it is under Who has access.`}</EmptyState></Card>
    </div>
  );
  const objs = d.by!.object.length, total = d.daily!.reduce((a, v) => a + v, 0);
  const one = d.what === "object" || d.what === "app";
  return (
    <SectionSql.Provider value={secSql}>
    <div className="ae-log">
      {d.note && <Banner title="Activity partly read" lines={[d.note]} />}
      <div className="ae-log-bar-top">
        {d.what !== "user" && d.what !== "role" && <Pick label="Change object" value={d.name} width={320} what="objects" onPick={(v) => c.nav("object", { name: v, show: "activity" })} />}
        <label className="ae-log-slide ae-log-biz"><span className="ae-log-tl">Business time</span><b>{tzl(work)}</b>
          <input type="range" min={-12} max={14} value={work.tz} aria-label="Business time, hours from UTC" onChange={(e) => setWork({ ...work, tz: +e.target.value })} />
          <span className="ae-muted">{hh(work.start)}–{hh(work.end)} local, Monday to Friday · moves every day, hour, weekend and off-hours count on this tab (stored in UTC)</span></label>
      </div>
      <p className="ae-log-lead">{lead(d, objs, total)}</p>
      <p className="ae-muted ae-log-src">Source SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY with QUERY_HISTORY and SESSIONS · {d.first} → {d.last} · days and hours in business time {tzl(work)} · reads, writes and DDL · no query text
        {d.what === "app" && " · the queries this Streamlit app ran for each user; opening it without a table query leaves no row"}</p>
      {d.what === "app" ? <AppViewers d={d} /> : <Tiles d={d} work={work} />}
      {!one && <>  {/* one table, view or app: the PDF's one-object layout, without the overview sections */}
        <OffHours d={d} work={work} open={open} />
        <Touched d={d} work={work} open={open} />
        <Hours d={d} work={work} />
      </>}
      <Detail d={d} work={work} open={open} />
      <WhoUsed d={d} work={work} open={open} />
      <Sensitive d={d} />
      {(d.what === "object" || d.what === "user" || d.what === "role") && <Paths d={d} />}
      {d.ddl!.length > 0 && (
        <Sec title="DDL changes" sub="CREATE, ALTER and DROP, newest first." sql="ddl">
          <Plain d={d} rows={d.ddl!} open={open} />
        </Sec>
      )}
      <div className="ae-log-two">
        <QuerySql d={d} />
        <Checks d={d} />
      </div>
    </div>
    </SectionSql.Provider>
  );
}

function lead(d: ActivityPage, objs: number, total: number): ReactNode {
  const n = <span className="ae-mono">{d.name}</span>;
  if (d.what === "object") return <>{n} was read{d.by!.object[0]?.write ? " and changed" : ""} {fmt(total)} times in {d.days} days{d.ddl!.length ? ", and its definition changed" : ""}. See who touched it, with which role and client, and when.</>;
  if (d.what === "app") return <>The app {n} ran {fmt(total)} queries on {plural(objs, "object")} for {plural(d.by!.user.length, "user")} in {d.days} days, with its owner's rights. See who opened it, who could, and what they saw.</>;
  if (d.what === "scope") return <>{plural(objs, "object")} in {d.kind?.toLowerCase()} {n} {objs === 1 ? "was" : "were"} read or changed {fmt(total)} times in {d.days} days. See who touched them, with which role and client, and when.</>;
  return <>{n} read or changed {plural(objs, "object")} {fmt(total)} times in {d.days} days{d.what === "role" ? " (queries run with this role)" : ""}. See which, with which role and client, and when.</>;
}

function Tiles({ d, work }: { d: ActivityPage; work: Work }) {
  const rows = d.rows!;
  const n = (a: string) => rows.filter((r) => r.action === a).reduce((s, r) => s + r.queries, 0);
  const offU = new Set(rows.filter((r) => offOf(r, work)).map((r) => r.user));
  const busy = d.by!.object[0];
  return (
    <div className="ae-log-tiles">
      {d.what === "object" ? <>
        <Tile label="Reads" value={fmt(n("READ"))} cap={`${plural(new Set(rows.map((r) => r.user)).size, "user")} · ${plural(new Set(rows.map((r) => r.role)).size, "role")}`} />
        <Tile label="Writes" value={fmt(n("WRITE"))} cap={[...new Set(rows.filter((r) => r.action === "WRITE").map((r) => r.type))].join(", ") || "none"} />
        <Tile label="DDL" value={fmt(n("DDL"))} cap="CREATE, ALTER, DROP and the like" tone={n("DDL") ? "warn" : null} />
        <Tile label="Clients" value={new Set(rows.map((r) => r.client)).size} cap={[...new Set(rows.map((r) => r.client))].join(", ")} />
      </> : <>
        <Tile label="Objects touched" value={d.by!.object.length} cap={`${plural(d.by!.user.length, "user")} · ${plural(d.by!.role.length, "role")}`} />
        <Tile label="Busiest object" value={<span className="ae-mono ae-log-tvs">{busy?.key.split(".").slice(-2).join(".")}</span>}
          cap={busy ? `${fmt(sum(busy))} queries · ${plural(new Set(rows.filter((r) => r.object === busy.key).map((r) => r.user)).size, "user")}` : ""} />
        <Tile label="Sensitive objects" value={d.by!.object.filter((b) => d.objects?.[b.key]?.sensitive).length} cap="read or changed in the window" />
      </>}
      <Tile label="People off-hours" value={offU.size} tone={offU.size ? "warn" : null}
        cap={`on ${plural(new Set(rows.filter((r) => offOf(r, work)).map((r) => r.object)).size, "object")} · weekends or outside ${biz(work)}`} />
      <Warn d={d} />
    </div>
  );
}

function Warn({ d }: { d: ActivityPage }) {
  const n = d.findings!.length;
  return (
    <div className={`ae-log-tile ae-log-warn${n ? "" : " ok"}`}>
      <span className="ae-log-tl">{n ? plural(n, "warning") : "No warnings"}</span>
      <span className="ae-muted">{n ? d.findings!.map((f) => `#${f.num} ${f.title}`).join(" · ") : "No activity rule fires here."}</span>
      {n > 0 && <a className="ae-link" href="#ae-log-checks">See checks →</a>}
    </div>
  );
}

/** A Streamlit app: who opened it, who could and never did, who saw its owner's sensitive data they can't read. */
function AppViewers({ d }: { d: ActivityPage }) {
  const c = useApp();
  const a = d.app!;
  const can = Object.keys(a.can), opened = Object.keys(a.opened), saw = Object.keys(a.saw);
  const people = [...new Set([...can, ...opened])].sort((x, y) => (a.opened[y]?.queries ?? 0) - (a.opened[x]?.queries ?? 0));
  return (
    <>
      <div className="ae-log-tiles">
        <Tile label="Opened it" value={opened.length} cap={`of ${can.length === 1 ? "1 person" : `${can.length} people`} who can · ${d.days} days`} />
        <Tile label="Can open, never did" value={a.never.length} cap={a.never.length ? "access nobody uses: worth trimming" : "everyone with access used it"} tone={a.never.length ? "warn" : null} />
        <Tile label="Saw data they can't read" value={saw.length} cap="sensitive data its owner reads, through the app" tone={saw.length ? "bad" : null} />
        <Tile label="Opened without access now" value={opened.filter((u) => !a.can[u]).length} cap="used it, but no longer hold USAGE" tone={opened.some((u) => !a.can[u]) ? "warn" : null} />
        <Warn d={d} />
      </div>
      <Sec title="Who can open it, and who did" sub="Everyone holding USAGE on the app (through which role) next to who ran it in the window. The app runs with its owner's rights.">
        <table className="ae-log-table">
          <thead><tr><th>User</th><th>Can open through</th><th className="num">Queries</th><th>Last opened</th><th>Saw sensitive data they can't read</th></tr></thead>
          <tbody>{people.map((u) => (
            <tr key={u} className={a.saw[u] ? "bad" : !a.opened[u] ? "muted" : ""}>
              <td><button type="button" className="ae-link ae-mono" onClick={() => c.nav("access", { user: u })}>{u}</button></td>
              <td className="ae-mono">{a.can[u] ?? <span className="ae-bad">no USAGE now</span>}</td>
              <td className="num">{a.opened[u] ? fmt(a.opened[u].queries) : <span className="ae-muted">never</span>}</td>
              <td className="ae-muted">{a.opened[u]?.last.slice(0, 16) ?? "—"}</td>
              <td>{a.saw[u] ? <b className="ae-bad">{a.saw[u].join(", ")}</b> : <span className="ae-muted">—</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      </Sec>
    </>
  );
}

/** A warehouse: who ran queries on it (QUERY_HISTORY), and who can use it but did not. */
function Warehouse({ d }: { d: ActivityPage }) {
  const c = useApp();
  if (!d.available) return <Card><EmptyState title="– No query history" art="wait">{d.reason}</EmptyState></Card>;
  const w = d.warehouse!;
  const top = Math.max(1, ...w.used.map((r) => r.queries));
  return (
    <div className="ae-log">
      <p className="ae-log-lead"><span className="ae-mono">{d.name}</span> ran queries for {plural(w.used.length, "user")}. {w.unused.length === 1 ? "1 other person" : `${w.unused.length} other people`} can use it but did not.</p>
      <p className="ae-muted ae-log-src">Source QUERY_HISTORY as the snapshot read it ({d.source}): queries per user, 30 days · a warehouse has no ACCESS_HISTORY rows</p>
      <div className="ae-log-tiles">
        <Tile label="Users" value={w.used.length} cap={`${fmt(w.used.reduce((n, r) => n + r.queries, 0))} queries`} />
        <Tile label="Can use, didn't" value={w.unused.length} cap="USAGE, OPERATE or ownership, no queries" tone={w.unused.length ? "warn" : null} />
      </div>
      <Sec title="Who ran queries on it" sub="Most queries first">
        <table className="ae-log-table">
          <thead><tr><th>User</th><th>Queries</th><th>Last used</th></tr></thead>
          <tbody>{w.used.map((r) => (
            <tr key={r.user}><td><button type="button" className="ae-link ae-mono" onClick={() => c.nav("access", { user: r.user })}>{r.user}</button></td>
              <td><span className="ae-log-act" style={{ width: `${Math.max(3, (100 * r.queries) / top)}%` }}><i style={{ flex: 1, background: ACT.WRITE }} /></span> <b>{fmt(r.queries)}</b></td>
              <td className="ae-muted">{r.last}</td></tr>
          ))}</tbody>
        </table>
      </Sec>
      {w.unused.length > 0 && <Sec title="Can use it, did not" sub="Access nobody used in the window: candidates to trim (Granted vs used)."><p className="ae-mono">{w.unused.join(", ")}</p></Sec>}
    </div>
  );
}

/** People who used the objects off-hours, each with the objects they touched; next to it, who touched what. */
function OffHours({ d, work, open }: { d: ActivityPage; work: Work; open: Open }) {
  const [by, setBy] = useState<"user" | "object">("user");
  const [more, setMore] = useState(false);
  const rows = d.rows!.filter((r) => offOf(r, work) > 0);
  const sub = `Queries at weekends or outside ${biz(work)} (business time at the top) · service users and pipelines left in`;
  if (!rows.length) return <Sec title="Off-hours use by people" sub={sub}><p className="ae-muted">No off-hours use in this window.</p></Sec>;
  const group = (k: "user" | "object") => {
    const m = new Map<string, ActivityRow[]>();
    rows.forEach((r) => m.set(r[k], [...(m.get(r[k]) ?? []), r]));
    return [...m.entries()].map(([key, rs]) => ({ key, rs, off: rs.reduce((n, r) => n + offOf(r, work), 0) })).sort((a, b) => b.off - a.off);
  };
  const gs = group(by), shown = more ? gs : gs.slice(0, 4);
  const max = Math.max(1, ...gs.flatMap((g) => g.rs.map((r) => offOf(r, work))));
  const kind = new Map(d.rows!.map((r) => [r.user, r.kind]));
  return (
    <Sec title="Off-hours use by people" sub={sub} sql="off" right={<Seg label="Group off-hours" value={by} items={[["user", "By user"], ["object", "By object"]]} onPick={setBy} />}>
      <div className="ae-log-people">
          {shown.map((g) => {
            const m = new Map<string, { off: number; types: Set<string>; via: Set<string>; last: string }>();
            g.rs.forEach((r) => { const k = by === "user" ? r.object : r.user; const x = m.get(k) ?? { off: 0, types: new Set(), via: new Set(), last: "" };
              x.off += offOf(r, work); x.types.add(r.type); x.via.add(`${r.role} · ${r.client}`); x.last = r.last > x.last ? r.last : x.last; m.set(k, x); });
            return (
              <div key={g.key} className="ae-log-person">
                <div className="ae-log-ph">
                  <span className="ae-log-av">{initials(g.key.split(".").pop() ?? g.key)}</span>
                  <div><button type="button" className="ae-link ae-mono" onClick={() => open(by, g.key)}>{g.key}</button>
                    {by === "user" && kind.get(g.key) !== "person" && <span className={`ae-otag ae-log-k-${kind.get(g.key)}`}>{kind.get(g.key)}</span>}
                    {by === "object" && d.objects?.[g.key]?.sensitive && <span className="ae-otag ae-sens-tag">sensitive</span>}
                    <div className="ae-muted">{plural(m.size, by === "user" ? "object" : "user")} · last {short([...m.values()].map((x) => x.last).sort().pop() ?? "")}</div></div>
                  <span className="ae-log-offn"><b>{g.off}</b> off-hours queries</span>
                </div>
                {[...m.entries()].sort((a, b) => b[1].off - a[1].off).map(([k, x]) => (
                  <div key={k} className="ae-log-prow">
                    <span className="ae-mono ae-log-trunc" title={k}>{k}{by === "user" && d.objects?.[k]?.sensitive && <span className="ae-otag ae-sens-tag">sensitive</span>}</span>
                    <span className="ae-log-bar"><i style={{ width: `${(100 * x.off) / max}%` }} /></span>
                    <b className="ae-log-num">{x.off}</b>
                    <span className="ae-log-small"><span className="ae-mono">{[...x.types].join(", ")}</span><br /><span className="ae-muted">{[...x.via].join("; ")}</span></span>
                    <span className="ae-muted">{short(x.last)}</span>
                  </div>
                ))}
              </div>
            );
          })}
          {gs.length > 4 && <button type="button" className="ae-link" onClick={() => setMore(!more)}>{more ? "Show fewer" : `Show ${gs.length - 4} more`}</button>}
      </div>
    </Sec>
  );
}

/** A heat grid: rows down, columns across, each cell a count (darker = more), row and column totals. Columns are
 * named, or days (narrow cells, a date every 5 days, weekends marked). */
function Heat({ corner, rows, cols, value, color, rowHead, colHead, days }: {
  corner: string; rows: string[]; cols: string[]; value: (r: string, c: string) => number; color: string;
  rowHead?: (r: string) => ReactNode; colHead?: (c: string) => ReactNode; days?: boolean;
}) {
  const top = Math.max(1, ...rows.flatMap((r) => cols.map((c) => value(r, c))));
  const rt = (r: string) => cols.reduce((n, c) => n + value(r, c), 0), ct = (c: string) => rows.reduce((n, r) => n + value(r, c), 0);
  const weekend = (c: string) => days && [0, 6].includes(new Date(c + "T00:00:00Z").getUTCDay());
  return (
    <div className="ae-scroll">
      <table className={`ae-log-heat${days ? " ae-log-heat-days" : ""}`}>
        <thead><tr><th>{corner}</th>
          {cols.map((c, i) => <th key={c} title={c} className={weekend(c) ? "wk" : ""}>{days ? (i % 5 === 0 || i === cols.length - 1 ? short(c) : "") : colHead ? colHead(c) : c}</th>)}
          <th className="tot">Total</th></tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r}><th className="ae-mono">{rowHead ? rowHead(r) : r}</th>
            {cols.map((c) => { const v = value(r, c);
              return <td key={c} title={`${r} · ${days ? c : c}: ${fmt(v)}`} className={weekend(c) ? "wk" : ""}
                style={{ background: v ? `color-mix(in srgb, ${color} ${12 + (78 * v) / top}%, var(--ae-panel))` : undefined, color: v / top > 0.55 ? "#fff" : undefined }}>
                {days ? "" : v ? fmt(v) : "·"}</td>; })}
            <td className="tot"><b>{fmt(rt(r))}</b></td></tr>)}
          <tr className="sum"><th>Total</th>{cols.map((c) => <td key={c}>{days ? "" : <b>{fmt(ct(c))}</b>}</td>)}<td className="tot"><b>{fmt(rows.reduce((n, r) => n + rt(r), 0))}</b></td></tr>
        </tbody>
      </table>
      <p className="ae-muted ae-log-legend">Fewer <i className="ae-log-ramp" style={{ background: `linear-gradient(90deg, color-mix(in srgb, ${color} 12%, var(--ae-panel)), ${color})` }} /> More</p>
    </div>
  );
}

/** Last 30 days of the window as dates, oldest first, and the index of each in a row's daily counts. */
function lastDays(d: ActivityPage, n = 30) {
  const all = d.days ?? 60, from = Math.max(0, all - n);
  return Array.from({ length: all - from }, (_, i) => ({ i: from + i, day: new Date(Date.parse(d.first!) + (from + i) * 864e5).toISOString().slice(0, 10) }));
}

/** Who touched what: one dimension down, another across (objects, roles, clients, statements, or the days one by
 * one), over the last 30 days (default) or the whole window; all queries or off-hours only. */
function Touched({ d, work, open }: { d: ActivityPage; work: Work; open: Open }) {
  type K = "user" | "role" | "client" | "object" | "type";
  const NAME: Record<K | "day", string> = { user: "Users", role: "Roles", client: "Clients", object: "Objects", type: "Statements", day: "Days" };
  const [rk, setRk] = useState<K>("user");
  const [ck, setCk] = useState<K | "day">("object");
  const [period, setPeriod] = useState<"30" | "all">("30");
  const [only, setOnly] = useState<"all" | "off">("all");
  const [objs, setObjs] = useState<"all" | "sens">("all");
  const all = d.days ?? 60, from = period === "30" ? Math.max(0, all - 30) : 0;
  const days = Array.from({ length: all - from }, (_, i) => ({ i: from + i, day: new Date(Date.parse(d.first!) + (from + i) * 864e5).toISOString().slice(0, 10) }));
  const at = new Map(days.map((x) => [x.day, x.i]));
  // off-hours are kept per row, not per day: a row's off-hours share spreads over its days
  const share = (r: ActivityRow) => (only === "off" ? offOf(r, work) / Math.max(1, r.queries) : 1);
  const inPeriod = (r: ActivityRow) => days.reduce((n, x) => n + r.daily[x.i], 0) * share(r);
  const rows = d.rows!.filter((r) => inPeriod(r) > 0 && (objs === "all" || d.objects?.[r.object]?.sensitive));
  const tot = (k: K, v: string) => rows.filter((r) => r[k] === v).reduce((s, r) => s + inPeriod(r), 0);
  const across = ck === rk ? (rk === "object" ? "user" : "object") : ck;  // never the same dimension both ways
  const people = [...new Set(rows.map((r) => r[rk]))].sort((a, b) => tot(rk, b) - tot(rk, a)).slice(0, 12);
  const cols = across === "day" ? days.map((x) => x.day)
    : [...new Set(rows.map((r) => r[across]))].sort((a, b) => tot(across, b) - tot(across, a)).slice(0, 10);
  const value = (p: string, c: string) => Math.round(across === "day"
    ? rows.filter((r) => r[rk] === p).reduce((s, r) => s + r.daily[at.get(c)!] * share(r), 0)
    : rows.filter((r) => r[rk] === p && r[across] === c).reduce((s, r) => s + inPeriod(r), 0));
  const link = (k: K, v: string) => k === "client" || k === "type" ? <span className="ae-mono">{v}</span>
    : <><button type="button" className="ae-link ae-mono" title={v} onClick={() => open(k, v)}>{k === "object" ? v.split(".").slice(-2).join(".") : v}</button>
      {k === "object" && d.objects?.[v]?.sensitive && <span className="ae-otag ae-sens-tag">sensitive</span>}</>;
  const keys = (["user", "role", "client", "object", "type"] as K[]);
  return (
    <Sec title="Who touched what" sql="touched" sub={`${NAME[rk]} down, ${NAME[across].toLowerCase()} across · ${period === "30" ? "last 30 days" : `all ${all} days`} · ${only === "off" ? `off-hours queries (weekends or outside ${biz(work)})` : "all queries"} · darker = more`}
      right={<div className="ae-row"><span className="ae-muted">Rows</span><Seg label="Rows" value={rk} items={keys.filter((k) => k !== "type").map((k) => [k, NAME[k]])} onPick={setRk} />
        <span className="ae-muted">Across</span><Seg label="Across" value={across} items={[...keys.filter((k) => k !== rk).map((k) => [k, NAME[k]] as [K | "day", string]), ["day", "Days"]]} onPick={setCk} />
        <Seg label="Objects" value={objs} items={[["sens", "Sensitive objects"], ["all", "All objects"]]} onPick={setObjs} />
        <Seg label="Period" value={period} items={[["30", "Last 30 days"], ["all", "Overall"]]} onPick={setPeriod} />
        <Seg label="Count" value={only} items={[["all", "All queries"], ["off", "Off-hours"]]} onPick={setOnly} /></div>}>
      {!rows.length ? <p className="ae-muted">No {only === "off" ? "off-hours " : ""}queries{objs === "sens" ? " on sensitive objects" : ""} in this period.</p> : (
        <Heat corner={NAME[rk].replace(/s$/, "")} rows={people} cols={cols} value={value} days={across === "day"}
          color={only === "off" ? "var(--ae-warn_ink)" : "var(--ae-accent)"} rowHead={(p) => link(rk, p)} colHead={(c) => link(across as K, c)} />
      )}
    </Sec>
  );
}

/** Queries by UTC hour of day per user (or object): one column per hour, business hours shaded, each bar weekday
 * (on or off hours) and weekend (off) queries stacked; then the on / off split and off per 1 on. */
function Hours({ d, work }: { d: ActivityPage; work: Work }) {
  const [by, setBy] = useState<"user" | "object">("user");
  const m = new Map<string, { hours: number[]; we: number[]; n: number; sens: Set<string> }>();
  d.rows!.forEach((r) => { const k = r[by]; const x = m.get(k) ?? { hours: Array(24).fill(0), we: Array(24).fill(0), n: 0, sens: new Set<string>() };
    r.hours.forEach((v, h) => { x.hours[h] += v; }); r.weekend_hours.forEach((v, h) => { x.we[h] += v; }); x.n += r.queries;
    if (d.objects?.[r.object]?.sensitive) x.sens.add(by === "user" ? r.object : r.user); m.set(k, x); });
  const list = [...m.entries()].map(([k, x]) => ({ k, x, off: offOf({ hours: x.hours, weekend: x.we.reduce((a, v) => a + v, 0) }, work) }))
    .sort((a, b) => b.off / Math.max(1, b.x.n) - a.off / Math.max(1, a.x.n)).slice(0, 10);
  const top = Math.max(1, ...list.flatMap(({ x }) => x.hours.map((v, h) => v + x.we[h])));
  const inside = (h: number) => h >= work.start && h < work.end;
  const utc = (l: number) => l;  // rows are already in business time (localize)
  return (
    <Sec title="Hours of use" sql="hours" sub={`Queries by hour of day, ${tzl(work)} (stored in UTC; slide to your business time: ${hh(work.start)}–${hh(work.end)} local, Monday to Friday) · business hours ${hh(work.start)}–${hh(work.end)} shaded · weekends count as off hours · most off-hours first · business time at the top`}
      right={<div className="ae-row">
        <Seg label="Hours of use by" value={by} items={[["user", "Users"], ["object", "Objects"]]} onPick={setBy} />
      </div>}>
      <div className="ae-log-hours">
        <div className="ae-log-hh"><span>{by === "user" ? "User" : "Object"}</span>
          <span className="ae-log-hx">{[0, 6, 12, 18, 23].map((h) => <i key={h} style={{ left: `${(h / 24) * 100}%` }}>{String(h).padStart(2, "0")}</i>)}</span>
          <span>On vs off hours</span><span className="num">Off : on</span></div>
        {list.map(({ k, x, off }) => {
          const on = x.n - off, pc = (v: number) => Math.round((100 * v) / Math.max(1, x.n)), ratio = off / Math.max(1, on);
          return (
            <div key={k} className="ae-log-hrow">
              <span className="ae-log-trunc"><b className="ae-mono" title={k}>{k}</b><br /><span className="ae-muted">{plural(x.sens.size, by === "user" ? "sensitive object" : "user of sensitive data")}</span></span>
              <span className="ae-log-hbars">
                {x.hours.map((_, h) => {
                  const v = x.hours[utc(h)], offv = (inside(h) ? 0 : v) + x.we[utc(h)], onv = inside(h) ? v : 0;
                  return (
                    <span key={h} className={inside(h) ? "biz" : ""} title={`${hh(h)} ${tzl(work)} · ${onv} on hours · ${offv} off hours`}>
                      {offv > 0 && <em style={{ height: `${Math.max(4, (100 * offv) / top)}%` }} />}
                      {onv > 0 && <i style={{ height: `${Math.max(4, (100 * onv) / top)}%` }} />}
                    </span>
                  );
                })}
              </span>
              <span className="ae-log-onoff"><span><i style={{ width: `${pc(on)}%` }} /><em style={{ width: `${pc(off)}%` }} /></span>
                <small><span>{pc(on)}% on · {fmt(on)}</span><span className="ae-warn-ink">{pc(off)}% off · {fmt(off)}</span></small></span>
              <span className="ae-log-ratio"><b className={ratio >= 0.5 ? "ae-warn-ink" : ""}>{ratio.toFixed(2)}</b><small className="ae-muted">off per 1 on</small></span>
            </div>
          );
        })}
      </div>
      <p className="ae-muted ae-log-legend"><span><i className="ae-log-on" />On hours</span><span><i className="ae-log-off" />Off hours</span><span><i className="ae-log-wk" />Business hours</span><span>top {list.length} of {m.size}</span></p>
    </Sec>
  );
}

/** Objects busiest first (person, role, app, database, schema), then the picked one in detail. */
function Detail({ d, work, open }: { d: ActivityPage; work: Work; open: Open }) {
  const list = d.by!.object;
  const [sel, setSel] = useState(list[0]?.key ?? "");
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<"all" | "sens">("all");
  const one = d.what === "object";
  const obj = one ? d.name : sel;
  const rows = one ? d.rows! : d.rows!.filter((r) => r.object === obj);
  const users = (o: string) => new Set(d.rows!.filter((r) => r.object === o).map((r) => r.user)).size;
  const shown = list.filter((b) => (!q || b.key.toLowerCase().includes(q.toLowerCase())) && (only === "all" || d.objects?.[b.key]?.sensitive));
  const top = Math.max(1, ...list.map(sum));
  return (
    <>
      {!one && (
        <Sec title={d.what === "app" ? "Tables it read for its viewers" : "Objects, busiest first"} sql="objects" sub={`All queries in the window · ${plural(list.length, "object")} · click one for its detail below`}
          right={<div className="ae-row"><input className="ae-input" placeholder="Filter tables, views and stages" value={q} onChange={(e) => setQ(e.target.value)} />
            <Seg label="Objects shown" value={only} items={[["all", "All"], ["sens", "Sensitive"]]} onPick={setOnly} /></div>}>
          <table className="ae-log-table">
            <thead><tr><th>Object</th><th>Kind</th><th>Activity</th><th className="num">Reads</th><th className="num">Writes</th><th className="num">DDL</th><th className="num">Users</th><th>Last</th></tr></thead>
            <tbody>{shown.slice(0, 50).map((b) => (
              <tr key={b.key} className={`ae-log-click${b.key === sel ? " on" : ""}`} onClick={() => setSel(b.key)}>
                <td><span className="ae-mono">{b.key}</span>{d.objects?.[b.key]?.sensitive && <span className="ae-otag ae-sens-tag">sensitive</span>}{b.key === sel && <span className="ae-otag">details below</span>}</td>
                <td className="ae-muted">{d.objects?.[b.key]?.kind}</td>
                <td><Act n={{ WRITE: b.write, READ: b.read, DDL: b.ddl }} w={(100 * sum(b)) / top} /></td>
                <td className="num">{fmt(b.read)}</td><td className="num">{fmt(b.write)}</td><td className="num">{fmt(b.ddl)}</td><td className="num">{users(b.key)}</td><td className="ae-muted">{short(b.last)}</td>
              </tr>
            ))}</tbody>
          </table>
          {shown.length > 50 && <p className="ae-muted">First 50 of {shown.length}; filter to find the rest.</p>}
          <Legend />
        </Sec>
      )}
      {obj && rows.length > 0 && (
        <>
          {!one && <div className="ae-log-objhead"><span className="ae-muted">OBJECT DETAIL</span><button type="button" className="ae-link ae-mono" onClick={() => open("object", obj)}>{obj}</button>
            {d.objects?.[obj]?.sensitive && <span className="ae-otag ae-sens-tag">sensitive</span>}<span className="ae-otag">{d.objects?.[obj]?.kind}</span></div>}
          {!one && <ObjTiles rows={rows} />}
          <div className="ae-log-two">
            <ByClient rows={rows} />
            <Kinds rows={rows} />
          </div>
          <Matrix d={d} rows={rows} />
          <ByType d={d} rows={rows} work={work} />
        </>
      )}
    </>
  );
}

function Act({ n, w }: { n: Record<"WRITE" | "READ" | "DDL", number>; w: number }) {
  return <span className="ae-log-act" style={{ width: `${Math.max(3, w)}%` }}>{ACTS.map((a) => n[a] ? <i key={a} style={{ flex: n[a], background: ACT[a] }} /> : null)}</span>;
}

function Legend() {
  return <p className="ae-muted ae-log-legend">{ACTS.map((a) => <span key={a}><i style={{ background: ACT[a] }} />{ACT_LABEL[a]}</span>)}</p>;
}

function ObjTiles({ rows }: { rows: ActivityRow[] }) {
  const n = (a: string) => rows.filter((r) => r.action === a).reduce((s, r) => s + r.queries, 0);
  return (
    <div className="ae-log-tiles">
      <Tile label="Reads" value={fmt(n("READ"))} cap={`${plural(new Set(rows.map((r) => r.user)).size, "user")} · ${plural(new Set(rows.map((r) => r.role)).size, "role")}`} />
      <Tile label="Writes" value={fmt(n("WRITE"))} cap={[...new Set(rows.filter((r) => r.action === "WRITE").map((r) => r.type))].join(", ") || "none"} />
      <Tile label="DDL" value={fmt(n("DDL"))} cap="CREATE, ALTER, DROP and the like" />
      <Tile label="Clients" value={new Set(rows.map((r) => r.client)).size} cap={[...new Set(rows.map((r) => r.client))].join(", ")} />
    </div>
  );
}

/** Queries per client (or role, user, action): writes, reads and DDL summed, most first; under each name its objects
 * and roles (or users). */
function ByClient({ rows }: { rows: ActivityRow[] }) {
  const [k, setK] = useState<"client" | "role" | "user" | "action">("client");
  const m = new Map<string, { n: Record<"WRITE" | "READ" | "DDL", number>; objs: Set<string>; via: Set<string> }>();
  rows.forEach((r) => { const x = m.get(r[k]) ?? { n: { WRITE: 0, READ: 0, DDL: 0 }, objs: new Set<string>(), via: new Set<string>() };
    x.n[r.action] += r.queries; x.objs.add(r.object); x.via.add(k === "role" ? r.user : `${r.role}`); if (k === "user" || k === "action") x.via.add(r.client); m.set(r[k], x); });
  const all = [...m.entries()].map(([key, x]) => ({ key, x, t: x.n.WRITE + x.n.READ + x.n.DDL })).sort((a, b) => b.t - a.t);
  const list = all.slice(0, 8), top = Math.max(1, ...all.map((l) => l.t));
  const label = (key: string) => k === "action" ? { WRITE: "DML · writes", READ: "Reads", DDL: "DDL" }[key as "WRITE"] : key;
  return (
    <Sec title={`Queries by ${k === "action" ? "DML / DDL / read" : k}`} sql="client" sub="Writes, reads and DDL summed per row · sorted by volume"
      right={<Seg label="Queries by" value={k} items={[["client", "Client"], ["role", "Role"], ["user", "User"], ["action", "DML / DDL / Read"]]} onPick={setK} />}>
      {list.map((l) => (
        <div key={l.key} className="ae-log-crow">
          <div className="ae-log-trunc"><b className="ae-mono">{label(l.key)}</b><div className="ae-muted ae-log-trunc">{plural(l.x.objs.size, "object")} · {[...l.x.via].join(", ")}</div></div>
          <span><Act n={l.x.n} w={(100 * l.t) / top} /></span>
          <b className="ae-log-num">{fmt(l.t)}</b>
        </div>
      ))}
      {all.length > list.length && <p className="ae-muted">Top {list.length} of {all.length}</p>}
      <Legend />
    </Sec>
  );
}

/** Statement kinds: queries per statement type, and on how many objects and user · role · client rows it ran. */
function Kinds({ rows }: { rows: ActivityRow[] }) {
  const m = new Map<string, { n: number; objs: Set<string>; combos: Set<string>; action: keyof typeof ACT }>();
  rows.forEach((r) => { const x = m.get(r.type) ?? { n: 0, objs: new Set(), combos: new Set(), action: r.action };
    x.n += r.queries; x.objs.add(r.object); x.combos.add(`${r.user}|${r.role}|${r.client}`); m.set(r.type, x); });
  const all = [...m.entries()].sort((a, b) => b[1].n - a[1].n), list = all.slice(0, 12);
  const top = Math.max(1, ...all.map(([, x]) => x.n));
  return (
    <Sec title="Statement kinds" sub="Queries per statement type" sql="kinds">
      {list.map(([t, x]) => (
        <div key={t} className="ae-log-krow">
          <span className="ae-mono ae-log-trunc"><i style={{ background: ACT[x.action] }} />{t}</span>
          <span className="ae-log-bar"><i style={{ width: `${(100 * x.n) / top}%`, background: ACT[x.action] }} /></span>
          <b className="ae-log-num">{fmt(x.n)}</b>
          <span className="ae-muted ae-log-num">{x.objs.size} obj · {plural(x.combos.size, "combo")}</span>
        </div>
      ))}
      {all.length > list.length && <p className="ae-muted">Top {list.length} of {all.length} statement types</p>}
      <Legend />
    </Sec>
  );
}

/** Queries in each cell of two dimensions (role x client by default; columns can be DML / Read / DDL, the statement,
 * or the last 30 days), with row and column totals. */
function Matrix({ d, rows }: { d: ActivityPage; rows: ActivityRow[] }) {
  const [rk, setRk] = useState<"role" | "client" | "user">("role");
  const [ck, setCk] = useState<"client" | "action" | "type" | "day">("client");
  const days = lastDays(d), at = new Map(days.map((x) => [x.day, x.i]));
  const rt = (a: string) => rows.filter((r) => r[rk] === a).reduce((n, r) => n + r.queries, 0);
  const rs = [...new Set(rows.map((r) => r[rk]))].sort((a, b) => rt(b) - rt(a));
  const ct = (b: string) => rows.filter((r) => r[ck as "client" | "action" | "type"] === b).reduce((n, r) => n + r.queries, 0);
  const cs = ck === "day" ? days.map((x) => x.day) : ck === "action" ? ACTS.filter((a) => ct(a)) : [...new Set(rows.map((r) => r[ck]))].sort((a, b) => ct(b) - ct(a));
  const value = (a: string, b: string) => ck === "day"
    ? rows.filter((r) => r[rk] === a).reduce((n, r) => n + r.daily[at.get(b)!], 0)
    : rows.filter((r) => r[rk] === a && r[ck] === b).reduce((n, r) => n + r.queries, 0);
  const name = { client: "client", action: "statement type", type: "statement", day: "day (last 30)" }[ck];
  return (
    <Sec title={`${LABEL[rk]} × ${name}`} sql="matrix" sub="Queries in each cell · row and column totals"
      right={<div className="ae-row"><span className="ae-muted">Rows</span><Seg label="Rows" value={rk} items={[["role", "Role"], ["client", "Client"], ["user", "User"]]} onPick={setRk} />
        <span className="ae-muted">Columns</span><Seg label="Columns" value={ck} items={[["client", "Client"], ["action", "Statement type"], ["type", "Statement"], ["day", "Last 30 days"]]} onPick={setCk} /></div>}>
      <Heat corner={LABEL[rk]} rows={rs} cols={cs} value={value} color="var(--ae-e_write)" days={ck === "day"}
        colHead={(b) => ck === "action" ? <span className="ae-log-colh"><i style={{ background: ACT[b as keyof typeof ACT] }} />{{ WRITE: "DML", READ: "Read", DDL: "DDL" }[b as "WRITE"]}</span> : <span className="ae-mono">{b}</span>} />
    </Sec>
  );
}

type Dim = ActivityKey | "action" | "okind";
const DIM: Record<Dim, string> = { ...LABEL, action: "R / W / DDL", okind: "Object kind" };
const ACT_NAME = { WRITE: "DML · writes", READ: "Reads", DDL: "DDL" } as Record<string, string>;
type Row = ActivityRow & { okind?: string };

/** Activity rows summed per combination of dims ("F_ENGINEER · Snowsight · INSERT"), most queries first; day: only
 * that day's queries. A row's okind is its object's kind (table, view, stage, ...). */
export function combine(rows: Row[], dims: Dim[], day: number | null = null): ActivityBy[] {
  const out = new Map<string, ActivityBy>();
  for (const r of rows) {
    const q = day == null ? r.queries : r.daily[day];
    if (!q) continue;
    const key = dims.map((k) => k === "okind" ? r.okind ?? "–" : k === "action" ? ACT_NAME[r.action] : r[k]).join(" · ");
    const b = out.get(key) ?? { key, read: 0, write: 0, ddl: 0, last: "", daily: r.daily.map(() => 0) };
    b[r.action.toLowerCase() as "read" | "write" | "ddl"] += q;
    b.last = r.last > b.last ? r.last : b.last;
    r.daily.forEach((v, i) => { b.daily[i] += v; });
    out.set(key, b);
  }
  return [...out.values()].sort((x, y) => sum(y) - sum(x));
}

/** The busiest (or pinned) day spelled out: date, average, active days, its total and split. */
function DayPanel({ d, rows, pin, work }: { d: ActivityPage; rows: ActivityRow[]; pin: number | null; work: Work }) {
  const days = d.days ?? 60, total = rows.reduce((n, r) => n + r.queries, 0), avg = total / days;
  const daily = rows.reduce((t, r) => t.map((v, i) => v + r.daily[i]), Array(days).fill(0) as number[]);
  const day = pin ?? daily.indexOf(Math.max(...daily));
  const date = new Date(Date.parse(d.first!) + day * 864e5).toISOString().slice(0, 10);
  const on = (a: string) => rows.filter((r) => r.action === a).reduce((s, r) => s + r.daily[day], 0);
  return (
    <div className="ae-log-day">
      <div><span className="ae-log-tl">{pin == null ? "Busiest day" : "Selected day"}</span><b>{short(date)}</b><span className="ae-muted">{new Date(date + "T00:00:00Z").toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" })}</span></div>
      <div><span className="ae-log-tl">Average a day</span><b>~{fmt(Math.round(avg))}</b></div>
      <div><span className="ae-log-tl">Active days</span><b>{daily.filter(Boolean).length} of {days}</b></div>
      <div><span className="ae-log-tl">That day</span><b>{fmt(daily[day])}</b><span className="ae-muted">{avg ? `${daily[day] >= avg ? "+" : ""}${Math.round((100 * (daily[day] - avg)) / avg)}% vs average` : ""}</span></div>
      <div><span className="ae-log-tl">DML</span><b>{fmt(on("WRITE"))}</b></div>
      <div><span className="ae-log-tl">Reads</span><b>{fmt(on("READ"))}</b></div>
      <div><span className="ae-log-tl">DDL</span><b>{fmt(on("DDL"))}</b></div>
      <div><span className="ae-log-tl">Off-hours</span><b>{fmt(rows.reduce((s, r) => s + offOf(r, work), 0))}</b><span className="ae-muted">in the window</span></div>
    </div>
  );
}

/** Queries by statement type: the DML / reads / DDL split, then per day by DML / reads / DDL with the busiest or the
 * picked day spelled out; then queries per day by user, role, client, statement, R / W / DDL or object kind. */
function ByType({ d, rows, work }: { d: ActivityPage; rows: ActivityRow[]; work: Work }) {
  const [pin, setPin] = useState<number | null>(null);
  const days = d.days ?? 60;
  const total = rows.reduce((n, r) => n + r.queries, 0);
  const n = (a: string) => rows.filter((r) => r.action === a).reduce((s, r) => s + r.queries, 0);
  const types = (a: string) => [...new Set(rows.filter((r) => r.action === a).map((r) => r.type))].join(" · ") || "none";
  const daily = rows.reduce((t, r) => t.map((v, i) => v + r.daily[i]), Array(days).fill(0) as number[]);
  const lane = (label: string, color: string, f: (r: ActivityRow) => boolean) => ({ label, color, days: daily.map((_, i) => rows.some((r) => f(r) && r.daily[i] > 0)) });
  const lanes = [lane("A person changed a table's definition (DDL)", "var(--ae-bad_ink)", (r) => r.action === "DDL" && r.kind === "person"),
    lane("A person wrote data", "var(--ae-warn_ink)", (r) => r.action === "WRITE" && r.kind === "person"),
    lane("A service user from Snowsight, SnowSQL or the CLI", "var(--ae-accent)", (r) => r.kind === "service" && r.interactive)].filter((l) => l.days.some(Boolean));
  const acts = ACTS.filter((a) => n(a));
  const series = acts.map((a) => ({ key: ACT_NAME[a], values: rows.filter((r) => r.action === a).reduce((t, r) => t.map((v, i) => v + r.daily[i]), Array(days).fill(0) as number[]) }));
  return (
    <>
      <Sec title="Queries by statement type" sql="type_day" sub={`Per day · ${short(d.first!)} → ${short(d.last!)} · ${fmt(total)} queries · weekends shaded · click a day to pin it`}>
        <div className="ae-log-tiles">
          {([["WRITE", "DML · writes"], ["READ", "Reads"], ["DDL", "DDL"]] as const).map(([a, l]) => (
            <Tile key={a} label={<><i style={{ background: ACT[a] }} className="ae-log-dot" />{l}</>}
              value={<>{fmt(n(a))} <small className="ae-muted">{total ? ((100 * n(a)) / total).toFixed(1) : 0}%</small></>} cap={<span className="ae-mono">{types(a)}</span>} />))}
        </div>
        <span className="ae-log-act ae-log-share">{ACTS.map((a) => n(a) ? <i key={a} style={{ flex: n(a), background: ACT[a] }} /> : null)}</span>
        <DayStack first={d.first!} label={d.name} series={series} colors={acts.map((a) => ACT[a])} pinned={pin} onPin={setPin} lanes={lanes} />
        <DayPanel d={d} rows={rows} pin={pin} work={work} />
      </Sec>
      <ByDay d={d} rows={rows} />
    </>
  );
}

/** Queries per day by user (role, client, statement, R / W / DDL, object kind, or any combination): the top 4 and
 * Other, as a chart or as a table with a row per day. */
function ByDay({ d, rows }: { d: ActivityPage; rows: ActivityRow[] }) {
  const dims: Dim[] = ["user", "role", "client", "type", "action", "okind"];
  const [ks, setKs] = useState<Dim[]>(["user"]);
  const [table, setTable] = useState(false);
  const [pin, setPin] = useState<number | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const days = d.days ?? 60;
  const all = combine(rows.map((r) => ({ ...r, okind: d.objects?.[r.object]?.kind ?? "–" })), ks);
  const name = ks.map((k) => (k === "action" ? DIM[k] : DIM[k].toLowerCase())).join(" + ");
  const toggle = (k: Dim) => { setFocus(null); setKs(ks.includes(k) ? (ks.length > 1 ? ks.filter((x) => x !== k) : ks) : dims.filter((x) => ks.includes(x) || x === k)); };
  const shown = all.slice(0, 4), rest = all.slice(4);
  const cols = [...shown, ...(rest.length ? [{ key: `Other (${rest.length})`, daily: Array.from({ length: days }, (_, i) => rest.reduce((s, b) => s + b.daily[i], 0)) }] : [])];
  type DayRow = { day: string; total: number } & Record<string, number | string>;
  const dayRows: DayRow[] = Array.from({ length: days }, (_, i) => ({
    day: new Date(Date.parse(d.first!) + i * 864e5).toISOString().slice(0, 10), total: cols.reduce((s, c) => s + c.daily[i], 0),
    ...Object.fromEntries(cols.map((c) => [c.key, c.daily[i]])) })).filter((r) => r.total).reverse();
  return (
    <Sec title={`Queries per day, by ${name}`} sql="by_day" sub={`Every day of the window · the top 4 and Other · pick one or more for combinations${table ? "" : " · click a day to pin it, a name to show only it"}`}
      right={<div className="ae-row"><div className="ae-seg2" role="group" aria-label="Per day by, pick one or more">{dims.map((k) => (
        <button key={k} type="button" aria-pressed={ks.includes(k)} className={ks.includes(k) ? "on" : ""} onClick={() => toggle(k)}>{DIM[k]}</button>))}</div>
        <button type="button" className={`ae-btn${table ? " ae-btn-primary" : ""}`} aria-pressed={table} onClick={() => setTable(!table)}>Table</button></div>}>
      {table ? (
        <DataTable rows={dayRows} csv={`${d.name}_per_day_by_${ks.join("_")}.csv`} sort={{ key: "day", dir: -1 }} filter={false} columns={[
          col<DayRow>("day", "Day", (r) => r.day, { render: (r) => <span className="ae-mono">{r.day}</span> }),
          ...cols.map((c) => col<DayRow>(c.key, c.key, (r) => Number(r[c.key]), { num: true, render: (r) => Number(r[c.key]) ? fmt(Number(r[c.key])) : <span className="ae-muted">·</span> })),
          col<DayRow>("total", "Total", (r) => r.total, { num: true, render: (r) => <b>{fmt(r.total)}</b> }),
        ]} />
      ) : (
        <DayStack first={d.first!} label={d.name} series={all.map((b) => ({ key: b.key, values: b.daily }))} top={4} pinned={pin} onPin={setPin} focus={focus} onFocus={setFocus} />
      )}
    </Sec>
  );
}

/** One row per user, role and client: statements, queries, off-hours and the days active in the window. */
function WhoUsed({ d, work, open }: { d: ActivityPage; work: Work; open: Open }) {
  const [sort, setSort] = useState<"volume" | "days" | "last">("volume");
  const [who, setWho] = useState<"all" | "people">("all");
  const [more, setMore] = useState(false);
  const rows = d.rows!;
  const list = useMemo(() => {
    const m = new Map<string, { user: string; role: string; client: string; kind: string; types: Map<string, string>; n: Record<"WRITE" | "READ" | "DDL", number>; off: number; days: Set<number>; first: string; last: string }>();
    rows.forEach((r) => { const k = `${r.user}|${r.role}|${r.client}`;
      const x = m.get(k) ?? { user: r.user, role: r.role, client: r.client, kind: r.kind, types: new Map(), n: { WRITE: 0, READ: 0, DDL: 0 }, off: 0, days: new Set<number>(), first: r.first_day, last: "" };
      x.types.set(r.type, r.action); x.n[r.action] += r.queries; x.off += offOf(r, work);
      r.daily.forEach((v, i) => { if (v) x.days.add(i); }); x.first = r.first_day < x.first ? r.first_day : x.first; x.last = r.last > x.last ? r.last : x.last; m.set(k, x); });
    return [...m.values()];
  }, [rows, work]);
  const tot = (x: (typeof list)[number]) => x.n.WRITE + x.n.READ + x.n.DDL;
  const shown = list.filter((x) => who === "all" || x.kind === "person")
    .sort((a, b) => sort === "volume" ? tot(b) - tot(a) : sort === "days" ? b.days.size - a.days.size : b.last.localeCompare(a.last));
  const top = Math.max(1, ...list.map(tot)), days = d.days ?? 60;
  return (
    <Sec title={d.what === "app" ? "Who opened it" : "Who used it"} sql="who" sub={`One row per user · role · client · ${list.length} rows${rows.length < (d.total ?? 0) ? ` (from the ${rows.length} busiest of ${d.total})` : ""}`}
      right={<div className="ae-row"><span className="ae-muted">Sort</span><Seg label="Sort" value={sort} items={[["volume", "Volume"], ["days", "Active days"], ["last", "Last seen"]]} onPick={setSort} />
        <Seg label="Who" value={who} items={[["all", "Everyone"], ["people", "People only"]]} onPick={setWho} /></div>}>
      <table className="ae-log-table ae-log-who">
        <thead><tr><th>User</th><th>Role · client</th><th>Statements</th><th>Queries</th><th className="num">Off-hrs</th><th>Activity · {short(d.first!)} – {short(d.last!)}</th></tr></thead>
        <tbody>{(more ? shown : shown.slice(0, 15)).map((x) => {
          const a = [...x.days].sort((p, q) => p - q);
          return (
            <tr key={`${x.user}|${x.role}|${x.client}`} className={x.kind === "person" && (x.n.WRITE || x.n.DDL) ? "warn" : ""}>
              <td><button type="button" className="ae-link ae-mono" onClick={() => open("user", x.user)}>{x.user}</button><div><span className={`ae-otag ae-log-k-${x.kind}`}>{x.kind[0].toUpperCase() + x.kind.slice(1)}</span></div></td>
              <td><span className="ae-mono">{x.role}</span><div className="ae-muted">{x.client}</div></td>
              <td>{[...x.types].map(([t, act]) => <span key={t} className="ae-log-chip" style={{ borderColor: ACT[act as keyof typeof ACT], color: ACT[act as keyof typeof ACT] }}>{t}</span>)}</td>
              <td className="ae-log-qcell"><Act n={x.n} w={(100 * Math.sqrt(tot(x))) / Math.sqrt(top)} /><b>{fmt(tot(x))}</b> <span className="ae-muted">{x.n.WRITE} DML · {x.n.READ} reads{x.n.DDL ? ` · ${x.n.DDL} DDL` : ""}</span></td>
              <td className="num">{x.off ? <b className="ae-warn-ink">{x.off}</b> : <span className="ae-muted">—</span>}</td>
              <td><span className="ae-log-window"><i style={{ left: `${(100 * (a[0] ?? 0)) / days}%`, width: `${Math.max(1.5, (100 * ((a[a.length - 1] ?? 0) - (a[0] ?? 0) + 1)) / days)}%`, opacity: Math.min(1, 0.35 + x.days.size / days) }} /></span>
                <span className="ae-muted"><b>{x.days.size}</b> of {days} days · {short(x.first)} → {short(x.last)}</span></td>
            </tr>
          );
        })}</tbody>
      </table>
      <p className="ae-muted ae-log-legend"><span className="ae-otag ae-log-k-person">Person</span><span className="ae-otag ae-log-k-service">Service</span><span className="ae-otag ae-log-k-system">System</span>
        <span>bar length on a square-root scale so small users stay visible · timeline = first → last seen, shade = how busy in between</span>
        {shown.length > 15 && <button type="button" className="ae-link" onClick={() => setMore(!more)}>{more ? "Show fewer" : `Show ${shown.length - 15} more`}</button>}</p>
    </Sec>
  );
}

function Plain({ d, rows, open }: { d: ActivityPage; rows: ActivityRow[]; open: Open }) {
  const cols = (["user", "role", "client", "object", "type"] as ActivityKey[]).filter((k) => !(k === "object" && d.what === "object"));
  return (
    <DataTable rows={rows} csv={`${d.name}_ddl.csv`} sort={{ key: "last", dir: -1 }} filter={false} columns={[
      ...cols.map((k) => col<ActivityRow>(k, LABEL[k], (r) => r[k], k === "user" || k === "role" || k === "object"
        ? { render: (r) => <button type="button" className="ae-link ae-mono" onClick={() => open(k, r[k])}>{r[k]}</button> } : {})),
      col<ActivityRow>("queries", "Queries", (r) => r.queries, { num: true }),
      col<ActivityRow>("last", "Last", (r) => r.last),
    ]} />
  );
}

function Paths({ d }: { d: ActivityPage }) {
  const c = useApp();
  type G = NonNullable<ActivityPage["gone"]>[number];
  if (!d.graph && !d.gone!.length) return null;
  return (
    <>
      {d.graph && <GraphCard g={d.graph} refs={d.refs} />}
      {d.gone!.length > 0 && (
        <Sec title="Used, but with no grant path now" sub="An admin role, or the grant was removed after the query: worth a look.">
          <DataTable rows={d.gone!} csv={`${d.name}_activity_no_path.csv`} rowTone={() => "warn"} filter={false} columns={[
            col<G>("user", "User", (r) => r.user, { render: (r) => <button type="button" className="ae-link ae-mono" onClick={() => c.nav("access", { user: r.user, show: "activity" })}>{r.user}</button> }),
            col<G>("role", "Role used", (r) => r.role),
            col<G>("object", "Table", (r) => r.object),
            col<G>("action", "Action", (r) => r.action),
          ]} />
        </Sec>
      )}
    </>
  );
}

/** What each user and role used sees of sensitive data: one column per sensitive or masked column. */
function Sensitive({ d }: { d: ActivityPage }) {
  type P = ActivitySensitive["people"][number] & { object: string };
  const people: P[] = d.sensitive!.flatMap((o) => o.people.map((p) => ({ ...p, object: o.object })));
  return (
    <>
      {d.sensitive!.filter((o) => o.people.length).map((o) => {
        const cols = [...new Set([...o.columns, ...Object.keys(o.masking)])].sort();
        return (
          <Sec key={o.object} title={<>What each user and role used sees{d.what !== "object" && <> in <span className="ae-mono">{o.object}</span></>}</>}
            sub={`One column per sensitive or masked column, from the policy text for the role the query ran with · red: readable in clear · ${o.row_policies.length ? `row access policy ${o.row_policies.map((p) => p.split(".").pop()).join(", ")}` : "no row access policy"}`}>
            <DataTable rows={people.filter((p) => p.object === o.object)} csv={`${o.object}_seen.csv`} filter={false} rowTone={(r) => r.clear.length ? "bad" : null} columns={[
              col<P>("user", "User · role used", (r) => `${r.user} ${r.role}`, { render: (r) => <><span className="ae-mono">{r.user}</span><div className="ae-muted">{r.role}</div></> }),
              ...cols.map((c) => col<P>(c, `${c} · ${o.masking[c] ? o.masking[c].map((x) => x.split(".").pop()).join(", ") : "no policy"}`, (r) => r.clear.includes(c) ? "in clear" : r.masked.includes(c) ? "masked" : "–", {
                render: (r) => r.clear.includes(c) ? <b className="ae-bad">in clear</b> : r.masked.includes(c) ? <span className="ae-muted">masked</span> : <span className="ae-muted">–</span> })),
              col<P>("rows", "Rows", (r) => ROWS[r.rows]),
              col<P>("read", "Can read now", (r) => r.read ? "yes" : "no"),
            ]} />
          </Sec>
        );
      })}
      {d.mark && (
        <Sec title="Mark this table as sensitive" sub={`It has no sensitive tag. Tag it with ${d.mark.tag} = '${d.mark.value}', or let Snowflake classify its columns.`}>
          <CodeOutput changes={[]} name={`${d.name}_mark_sensitive`} texts={{ sql: d.mark.sql, tf: d.mark.tf, ticket: d.mark.ticket }} />
        </Sec>
      )}
    </>
  );
}

/** Every query behind the tab, one by one: SQL to run in Snowflake (query ids, times, users, roles; no query text). */
function QuerySql({ d }: { d: ActivityPage }) {
  const [done, setDone] = useState("");
  return (
    <section className="ae-log-sql">
      <div className="ae-log-sqlh"><div><h3>Every query, one by one</h3><p>Run in Snowflake for the query ids and times behind these counts (no query text). The app never runs it.</p></div>
        <button type="button" className="ae-btn" onClick={() => copyText(d.query_sql ?? "").then((ok) => { setDone(ok ? "Copied" : "Select and copy"); setTimeout(() => setDone(""), 1500); })}>{done || "Copy"}</button></div>
      <pre tabIndex={0}>{d.query_sql}</pre>
    </section>
  );
}

function Checks({ d }: { d: ActivityPage }) {
  const c = useApp();
  return (
    <Sec id="ae-log-checks" title="Checks on this tab" sub={plural(d.findings!.length, "finding")}>
      {d.findings!.length ? d.findings!.map((f, i) => (
        <div key={i} className={`ae-log-check ae-log-check-${f.severity.toLowerCase()}`}>
          <b>{f.severity} · #{f.num} {f.title}</b>
          <span>{f.grantee}: {f.detail}</span>
          <button type="button" className="ae-link" onClick={() => c.nav("rules", { rule: f.num })}>Open finding and fix →</button>
        </div>
      )) : <p className="ae-muted">No activity rule fires here.</p>}
    </Sec>
  );
}
