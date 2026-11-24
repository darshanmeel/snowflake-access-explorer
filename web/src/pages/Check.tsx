// Can they? (screens 3 and 12): a sentence question, the verdict Yes / Partly / No with the privileges held, then tabs.
// Inside (a database or schema: each table and view inside; the default then), Answer (the diagram), Routes (lanes,
// where to cut, the table of routes), Ways in (No) and Rows & columns (grant, rows, columns, what they see).
// The subject is a person (name=) or a role (role=).
import { useEffect, useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { CheckPage, Inside, ListItem, Path, Refs } from "../api/types";
import { Fold, Banner, Card, CodeOutput, DataTable, EmptyState, FilterChips, MiniBar, NameList, Pager, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { accessLines, cutLabel, cutTexts, cutWhatIf, needOf, nearestNote, nearestTitle, pickSubject, sideEffects, subjectIn, subjectLink, usedAnyway, verdictLine, warehouseNote } from "./verdict";
import { BuiltinNote, col, CutBanner, GraphCard, Load, NameLink, PathCell, pathCol, Pick, PickFirst, Risks, Sel, StateTag } from "./common";
import { UseLine } from "./Activity";
import { changeOfPath, WhatIfButton, whatIf } from "./Whatif";

export function CheckPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const asked = subjectIn(c.params);
  const name = asked.name ?? c.meta.default_user ?? "";
  const s = useApi<CheckPage>(name ? "check" : null, { ...apiParams(c), ...(asked.role ? { role: name } : { name }) });
  return (
    <>
      <h2 className="ae-sr">Can they?</h2>
      <div className="ae-ask" role="group" aria-label="Question">
        <span className="ae-ask-w">Can</span>
        {mine ? <span className="ae-mono ae-ask-w">{s.data?.user ?? "you"}</span>
          : <Pick label="Person or role" value={name} user={!asked.role} what="users,roles" onPick={(v, i) => c.set({ ...pickSubject(v, i.kind === "user" ? [v] : [], i.kind === "user" ? [] : [v]), obj: c.params.obj ?? s.data?.object ?? null })} />}
        {s.data && <Sel label="Privilege" value={s.data.priv} onPick={(v) => c.set({ priv: v, do: null })}
          options={[...s.data.privileges.map((p): [string, string] => [p, p === "*" ? "do anything to" : p]),
            ...s.data.not_applicable.map((p): [string, string] => [p, `${p} · not for this ${s.data!.type.toLowerCase()}`])]} />}
        <Pick label="Object" value={c.params.obj ?? s.data?.object ?? ""} width={340} what="objects" onPick={(v) => c.set({ obj: v })} />
        <span className="ae-ask-w">?</span>
      </div>
      {name ? <Load s={s}>{(d) => <Body key={`${d.subject.kind}:${d.user}:${d.object}:${d.priv}`} d={d} />}</Load> : <PickFirst />}
    </>
  );
}

const MARK = { yes: "✓", partly: "½", no: "✕", blocked: "⊘", na: "–" } as const;
const WORD = { yes: "Yes", partly: "Partly", no: "No", blocked: "Blocked", na: "Not applicable" } as const;

function Body({ d }: { d: CheckPage }) {
  const c = useApp();
  const show = c.params.show ?? "answer";
  const [all, setAll] = useState(false); // the privileges not held too
  const lacks = d.held.filter((p) => !p.held && p.privilege !== d.priv).length;
  const tabs = [
    ...(d.inside ? [{ key: "inside", label: "Inside", count: d.inside.total }] : []),
    { key: "answer", label: "Answer" },
    ...(d.lanes_total && d.view !== "mine" ? [{ key: "cut", label: "Take it away" }] : []),
    ...(d.lanes_total ? [{ key: "routes", label: "Routes", count: d.lanes_total }] : []),
    ...(d.verdict === "no" ? [{ key: "nearest", label: "Ways in", count: d.nearest?.length ?? null }] : []),
    ...(d.layers || d.read ? [{ key: "layers", label: "Rows & columns", tone: d.verdict === "partly" ? ("warn" as const) : null }] : []),
  ];
  const first = d.inside ? "inside" : "answer";
  const at = tabs.some((t) => t.key === show) ? show : first;
  return (
    <>
      <BuiltinNote b={d.builtin} />
      <section className={`ae-verdict ae-verdict-${d.verdict}`} aria-label="Answer">
        <div className="ae-verdict-head">
          <span className="ae-verdict-mark" aria-hidden>{MARK[d.verdict]}</span>
          <div className="ae-verdict-word">{WORD[d.verdict]}</div>
          <div>
            {accessLines(d).slice(0, 1).map((t) => <b key={t} className="ae-verdict-kind">{t.replace(/\.$/, "")}</b>)}
            <div>{d.answer.tone === "warn" && <span className="ae-warn-word"> · user is {d.status}{d.dormant_days ? ` · no login for ${d.dormant_days} days` : ""}</span>}
              {!d.subject.user && <span className="ae-muted"> · role {d.user}, held by {d.subject.people} {d.subject.people === 1 ? "person" : "people"}</span>}</div>
            <div className="ae-verdict-line">{answerLine(d)}</div>
            {accessLines(d).slice(1).map((t) => <div key={t} className="ae-muted">{t}</div>)}
            <UsedLine d={d} />
          </div>
        </div>
        <Fold label="Privileges held, warehouses">
        {d.verdict !== "na" && <WarehouseLine d={d} />}
        <ul className="ae-privrow" aria-label={`Privileges on ${d.object}`}>
          {(all ? d.held : d.held.filter((p) => p.held || p.privilege === d.priv)).map((p) => (
            <li key={p.privilege} className={p.held ? "on" : ""}>
              <span aria-hidden>{p.held ? "✓" : "✕"}</span>{p.privilege}<span className="ae-sr">{p.held ? " held" : " not held"}</span>
            </li>
          ))}
          {d.usage.map((u) => (
            <li key={u.name} className={u.held ? "on" : ""} title={`Snowflake checks USAGE on the ${u.type.toLowerCase()} first`}>
              <span aria-hidden>{u.held ? "✓" : "✕"}</span>USAGE on {u.type.toLowerCase()}<span className="ae-sr">{u.held ? " held" : " not held"}</span>
            </li>
          ))}
          {lacks > 0 && <li className="more"><button type="button" className="ae-link" onClick={() => setAll(!all)}>{all ? "show fewer" : `${lacks} not held`}</button></li>}
        </ul>
        </Fold>
      </section>
      <Tabs nav active={at} onChange={(k) => c.set({ show: k === first ? null : k, part: null })} tabs={tabs} />
      {at === "inside" && d.inside && <InsideCard d={d} x={d.inside} />}
      {at === "answer" && <Answer d={d} />}
      {at === "routes" && <Routes d={d} />}
      {at === "cut" && <Routes d={d} only="cut" />}
      {at === "nearest" && <NearestWays d={d} />}
      {at === "layers" && <Layers d={d} />}
      {d.verdict !== "no" && <Risks list={d.risks} quiet />}
    </>
  );
}

const MODES: [string, string][] = [["read", "Read tables"], ["dml", "Read and change data (DML)"], ["ddl", "Own: DDL (ALTER, DROP)"]];

type Row = Inside["rows"][number];

/** A database or schema: what they can and cannot do on each table and view inside, for read, DML or DDL. */
function InsideCard({ d, x }: { d: CheckPage; x: Inside }) {
  const c = useApp();
  const [q, setQ] = useState(c.params.in_q ?? "");
  useEffect(() => { const t = setTimeout(() => { if (q !== (c.params.in_q ?? "")) c.set({ in_q: q || null, offset: null }); }, 300); return () => clearTimeout(t); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const word = MODES.find(([k]) => k === x.mode)?.[1].toLowerCase() ?? "";
  return (
    <Card title={`Inside ${d.object}`} sub={`${x.can} of ${x.total} tables and views: they can ${word}${x.blocked ? ` · ${x.blocked} blocked by a missing USAGE` : ""}`
      + (d.type === "SCHEMA" ? ` · new objects: ${x.create.length ? x.create.join(", ") : "no CREATE on the schema"}` : "")}>
      <div className="ae-row">
        <FilterChips label="What to check" value={x.mode} onPick={(v) => c.set({ inside: v === "read" ? null : v, offset: null })}
          items={MODES.map(([key, label]) => ({ key, label }))} />
        <FilterChips label="Show" value={x.show} onPick={(v) => c.set({ show_in: v === "all" ? null : v, offset: null })}
          items={[{ key: "all", label: "All", count: x.total }, { key: "can", label: "Can", count: x.can }, { key: "cannot", label: "Cannot", count: x.cannot }]} />
        <input className="ae-input" placeholder="Filter objects" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter objects" />
      </div>
      {!x.rows.length ? <EmptyState title={x.total ? "Nothing matches" : "No tables or views inside"}>{x.total ? "Change the filter." : ""}</EmptyState> : (
        <DataTable csv={`${d.object}_${x.mode}.csv`} rows={x.rows} columns={[
          col("o", "Object", (r: Row) => r.object, { wrap: "nowrap", render: (r: Row) => (
            <button type="button" className="ae-link ae-mono" onClick={() => c.set({ obj: r.object, priv: null })}>{r.object}</button>) }),
          col("t", "Type", (r: Row) => r.type.toLowerCase()),
          col("a", "Answer", (r: Row) => (r.ok ? "Can" : r.blocked ? `Blocked: ${r.blocked}` : "Cannot"), { render: (r: Row) => (
            <span className={r.ok ? "ae-ok-word" : "ae-bad"}>{r.ok ? "✓ Can" : r.blocked ? `⊘ Blocked: ${r.blocked}` : "✕ Cannot"}</span>) }),
          col("h", "Holds", (r: Row) => r.has.join(", ") || "—", { wrap: "wrap" }),
          col("m", "Missing", (r: Row) => r.missing.join(", ") || "—", { wrap: "wrap" })]} />
      )}
      {x.matched > x.limit && <Pager at={x.offset / x.limit} size={x.limit} total={x.matched} onPage={(n) => c.set({ offset: n ? String(n * x.limit) : null })} />}
    </Card>
  );
}

/** Use the activity shows although the grants say No; a person's opens the object's Activity for them. */
function UsedLine({ d }: { d: CheckPage }) {
  const c = useApp();
  const text = usedAnyway(d);
  if (!text) return null;
  if (!d.subject.user) return <div className="ae-warn-word">{text}</div>;
  return <div><button type="button" className="ae-link ae-warn-word"
    onClick={() => c.nav("object", { name: d.object, show: "activity", as: d.user, ...(c.params.builtin && { builtin: c.params.builtin }) })}>{text}</button></div>;
}

/** Which warehouses a query can run on: a query needs one. */
function WarehouseLine({ d }: { d: CheckPage }) {
  const w = warehouseNote(d.warehouses);
  return <div className={w.bad ? "ae-blocked" : "ae-muted"}>{w.text}</div>;
}

/** The one answer sentence: routes (never "paths") and the shortest depth; ownership or an admin role say how. */
export function answerLine(d: CheckPage): string {
  if (d.verdict !== "yes") return verdictLine(d);
  if (!d.lanes_total) return d.answer.text;
  const depth = d.answer.stats.find(([l]) => l === "Shortest depth")?.[1];
  const line = verdictLine(d);
  return `${line[0].toUpperCase()}${line.slice(1)}${typeof depth === "number" ? ` · shortest ${depth} role${depth === 1 ? "" : "s"} deep` : ""}.`;
}

const KIND_WORD: Record<string, string> = {
  user: "User", functional: "Functional role", technical: "Technical role", group: "Group role", database_role: "Database role",
  admin: "Admin role", object: "Object", new: "New account role",
};

/** One route, left to right: user (or the role asked about), roles, the grant, the object. cut: nodes on every route;
 * missing: the dashed red link. */
function Lane({ path, grant, refs, cut = [], missing, user = true }: { path: Path; grant: string; refs: Refs; cut?: string[]; missing?: number; user?: boolean }) {
  const o = useOpen(refs);
  const obj = path[path.length - 1];
  const parts = obj.split(".");
  return (
    <div className="ae-route">
      {path.slice(0, -1).map((n, i) => {
        const k = i === 0 && user ? "user" : n === "<NEW_ROLE>" ? "new" : refs.kinds[n] ?? "group";
        const gap = missing === i - 1;
        return (
          <span key={i} className="ae-route-step">
            {i > 0 && <span className={`ae-route-link${gap ? " missing" : ""}`}>{gap && <span className="ae-route-miss">missing</span>}</span>}
            <button type="button" className={`ae-route-node ae-route-${k}${cut.includes(n) ? " cut" : ""}`} disabled={k === "new"}
              onClick={() => o.open(n)} title={cut.includes(n) ? `${n}: on every route, a place to cut` : n}>
              <span className="ae-mono">{n === "PUBLIC" ? "PUBLIC (everyone)" : n}</span>
              <span className="ae-muted">{KIND_WORD[k] ?? k}</span>
            </button>
          </span>
        );
      })}
      <span className="ae-route-link ae-route-grant"><span className="ae-lvl ae-lvl-read">{grant}</span></span>
      <button type="button" className="ae-route-node ae-route-object" onClick={() => o.open(obj)} title={obj}>
        <span className="ae-mono">{parts[parts.length - 1]}</span>
        <span className="ae-muted">{(refs.types[obj] ?? "object").toLowerCase()}{parts.length > 1 ? ` · ${parts.slice(0, -1).join(".")}` : ""}</span>
      </button>
    </div>
  );
}

function Routes({ d, only }: { d: CheckPage; only?: string }) {
  const c = useApp();
  const [sel, setSel] = useState(0);
  const cut = d.cuts[sel];
  const tabs = [{ key: "routes", label: "Routes", count: d.lanes_total }, { key: "cut", label: "Where to cut", count: d.cuts.length },
    { key: "table", label: "Table", count: d.paths_total ?? d.paths.length }];
  const part = only ?? (tabs.some((t) => t.key === c.params.part) ? c.params.part : "routes");
  return (
    <>
      {!only && <Tabs nav={2} active={part} onChange={(k) => c.set({ part: k === "routes" ? null : k })} tabs={tabs} />}
      {part === "routes" && <Card title="How the access gets there" sub={`One lane per route, read left to right${d.lanes_total > d.lanes.length ? ` · first ${d.lanes.length} of ${d.lanes_total}` : ""}`}>
        <div className="ae-routes">
          {d.lanes.map((l, i) => <Lane key={i} path={l.path} grant={l.privileges.join(", ")} refs={d.refs} cut={d.cut} user={d.subject.user} />)}
        </div>
        <div className="ae-route-legend">
          <span><span className="ae-route-key cut" />In every route: a place to cut</span>
          <span><span className="ae-route-key" />Only in this route</span>
        </div>
      </Card>}
      {part === "cut" && (
        <Card title={d.cuts.length ? `${d.cuts.length} ${d.cuts.length === 1 ? "place" : "places"} to take it away` : "Take it away"} sub={d.cuts.length ? "Removing one of these links removes this access. The side effects differ."
          : d.view === "mine" ? "Not worked out in My access: it needs everyone's grants." : "No single link is on every route: each route needs its own cut, below."}>
          <ul className="ae-cuts">
            {d.cuts.map((x, i) => (
              <li key={i} className={i === sel ? "on" : ""}>
                <button type="button" className="ae-cut-main" aria-pressed={i === sel} onClick={() => setSel(i)}>
                  <b>{cutLabel(x.edges)}</b>
                  <span className="ae-muted">{x.people.length > 1
                    ? <>Ends this access for {x.people.length} people:<NameList items={x.people} max={4} plain /></>
                    : x.people.length ? `Ends this access only for ${x.people[0]}.` : `Ends it for ${d.user} only: no one holds it.`}{x.lost > 0 ? ` ${d.user} also loses ${x.lost} other privilege${x.lost === 1 ? "" : "s"}.` : ""}</span>
                </button>
                <span className="ae-cut-side">
                  {sideEffects(x.people.length, x.lost).map((b) => <span key={b.text} className={`ae-sfx ae-sfx-${b.tone}`}>{b.text}</span>)}
                  <button type="button" className="ae-btn ae-btn-s" title="Simulate it on the What if page: nothing changes in Snowflake" onClick={() => whatIf(c, cutWhatIf(x.edges))}>Simulate</button>
                </span>
              </li>
            ))}
          </ul>
          {cut && <CodeOutput changes={[]} texts={cutTexts(cut, d.user)} name={`revoke_${d.user.toLowerCase()}`} />}
          {!d.cuts.length && <RemoveOptions d={d} />}
        </Card>
      )}
      {part === "table" && <RouteTable d={d} />}
    </>
  );
}

/** The routes as a table (one row per privilege), the admin routes and ownership. */
function RouteTable({ d }: { d: CheckPage }) {
  return (
    <>
      {d.paths.length > 0 && (
        <Card title="Routes, one row per privilege" sub={`${(d.paths_total ?? d.paths.length).toLocaleString("en-US")} row(s) for ${d.priv === "*" ? "any privilege" : d.priv} on ${d.object}${
          (d.paths_total ?? 0) > d.paths.length ? `: first ${d.paths.length} listed` : ""}`}>
          <DataTable csv="check_paths.csv" rows={d.paths}
            columns={[...(d.priv === "*" ? [col("p", "Privilege", (r: CheckPage["paths"][number]) => r.privilege, { wrap: "nowrap" })] : []),
              col("d", "Depth", (r: CheckPage["paths"][number]) => r.depth, { num: true }),
              col("h", "Held by", (r: CheckPage["paths"][number]) => r.holder, { render: (r: CheckPage["paths"][number]) => <NameLink id={r.holder} refs={d.refs} /> }),
              col("w", "How", (r: CheckPage["paths"][number]) => r.how, { wrap: "wrap" }), pathCol<CheckPage["paths"][number]>(d.refs),
              col("act", "", () => "", { render: (r: CheckPage["paths"][number]) => { const ch = changeOfPath(r.path, d.refs.kinds); return ch && <WhatIfButton ch={[ch]} />; } })]} />
        </Card>
      )}
      {d.admin_paths.length > 0 && (
        <Banner tone="bad" title={`Reached through the roles granted to an admin role`} lines={d.admin_paths.map((p, i) => <PathCell key={i} path={p} refs={d.refs} />)} />
      )}
      {d.owner.length > 0 && (
        <Card title="Through ownership" sub="The owner of an object can do everything on it">
          {d.owner.map((p, i) => <div key={i}><PathCell path={p} refs={d.refs} /></div>)}
        </Card>
      )}
    </>
  );
}

/** The nearest ways in, asked for when the tab opens (near=1): the slow part of a No on a big account. */
function NearestWays({ d, first }: { d: CheckPage; first?: boolean }) {
  const c = useApp();
  const asked = subjectIn(c.params);
  const s = useApi<CheckPage>(d.nearest ? null : "check", { ...apiParams(c), ...(asked.role ? { role: d.user } : { name: d.user }), obj: d.object, near: "1" });
  if (d.nearest) return <NearestList d={d} first={first} />;
  return <Load s={s} wait="Looking for the closest roles that lead there">{(x) => <NearestList d={x} first={first} />}</Load>;
}

/** first: the best way only, under the verdict (Answer tab), the rest on Ways in. */
function NearestList({ d, first }: { d: CheckPage; first?: boolean }) {
  if (d.view === "mine") return <EmptyState title="Not worked out in My access" art="wait">The nearest ways in need everyone's grants: open the shared snapshot.</EmptyState>;
  const own = !first && d.nearest_own?.length ? <WayList d={d} ways={d.nearest_own} priv="OWNERSHIP" title="To own it" /> : null;
  return (
    <>
      {d.narrow && <Narrow d={d} n={d.narrow} />}
      {d.nearest?.length ? <WayList d={d} ways={d.nearest} priv={d.ask_priv} first={first} title={d.nearest_own ? `To use it (${d.ask_priv})` : undefined} />
        : !d.narrow && <EmptyState title="No way in to suggest" art="search">No role that can be suggested reaches {d.ask_priv} on {d.object} (admin and build roles are never suggested).</EmptyState>}
      {own}
    </>
  );
}

/** The narrowest way in: only the privilege asked, granted to a role they already reach that can see the schema. */
function Narrow({ d, n }: { d: CheckPage; n: NonNullable<CheckPage["narrow"]> }) {
  return (
    <Card title="Narrowest way in" sub={`Only ${n.privilege}, granted to ${n.role}, which ${d.user} already reaches (its ${n.holders} holders get it too)`}>
      <CodeOutput changes={[n.change]} name={`grant_${n.privilege.toLowerCase()}_${n.role.toLowerCase()}`} />
    </Card>
  );
}

function WayList({ d, ways: all, priv, first, title }: { d: CheckPage; ways: NonNullable<CheckPage["nearest"]>; priv: string; first?: boolean; title?: string }) {
  const c = useApp();
  const ways = first ? all.slice(0, 1) : all;
  const more = all.length - ways.length;
  return (
    <Card title={title ?? (first ? "Nearest way in" : "Nearest ways in")} sub={<span title="Fewest missing links first, then the fewest people who would get it too, then the least else it brings">{`For ${priv}. Dashed red: the missing link.`}</span>}>
      <div className="ae-near">
        {ways.map((n, i) => (
          <div key={i} className={`ae-near-row${n.broad || n.rule1 ? " warn" : ""}`}>
            <Lane path={n.path} grant={priv} refs={d.refs} missing={n.missing} user={d.subject.user} />
            <div className="ae-near-foot">
              <div>
                <b>{nearestTitle(n)}</b> · <span className="ae-muted">{nearestNote(n, d.approver)}</span>
                {n.extra > 0 && <div className={n.extra >= WIDE ? "ae-warn-word" : "ae-muted"}>
                  <MiniBar of={n.extra + 1} parts={[{ key: "need", label: "Needed", value: 1, cls: "lvl-read" }, { key: "extra", label: "Also brings", value: n.extra, cls: n.extra >= WIDE ? "medium" : "low" }]}
                    text={`${(n.extra + 1).toLocaleString("en-US")} privileges, you need 1`} />{n.extra >= WIDE && " · much more than asked for"}</div>}
                {n.broad && <div className="ae-warn-word">Too broad: {n.broad}. Not recommended.</div>}
              </div>
              <div className="ae-row">
                <button type="button" className={`ae-btn${i === 0 && !n.broad ? " ae-btn-primary" : ""}`}
                  onClick={() => c.nav("request", { ...subjectLink(d.subject, "request"), obj: d.object, need: needOf(priv), role: n.role,
                    ...(n.to_user || !d.subject.user ? {} : { to: n.to }) })}>
                  {n.broad ? "Request anyway" : `Request ${n.cost > 1 ? "a new role" : n.role}`}
                </button>
                <button type="button" className="ae-btn" title="Everything this role gives: the effect of granting it" onClick={() => c.nav("access", { role: n.role })}>What it brings</button>
              </div>
            </div>
            {n.change && (i === 0 ? <CodeOutput changes={[n.change]} name={`grant_${n.role.toLowerCase()}`} />
              : <details className="ae-near-sql"><summary>Grant text</summary><CodeOutput changes={[n.change]} name={`grant_${n.role.toLowerCase()}`} /></details>)}
          </div>
        ))}
      </div>
      {more > 0 && <button type="button" className="ae-link" onClick={() => c.set({ show: "nearest" })}>{more} more on Ways in</button>}
    </Card>
  );
}

const WIDE = 10; // a way in that brings this many other privileges is flagged: far more than the one asked for

function Layers({ d }: { d: CheckPage }) {
  return (
    <>
      {d.layers && <Card title="Three layers, checked in order" sub="The grant lets the query run; a row access policy decides the rows; masking policies decide the columns.">
        <div className="ae-layers">
          {(d.layers ?? []).map((l, i) => (
            <div key={l.step} className={`ae-layer ${l.ok ? "ok" : l.result === "Not reached" ? "skip" : "bad"}`}>
              <div className="ae-muted">{i + 1} · {l.step}</div>
              <b>{l.result}</b>
              <div className="ae-layer-why">{l.reason}</div>
            </div>
          ))}
        </div>
      </Card>}
      {d.read && (
        <Card title="What they see" sub={d.read.summary}>
          {d.use_role && (
            <>
              <p>Use role <NameLink id={d.use_role} refs={d.refs} />{d.warehouse ? ` with warehouse ${d.warehouse}` : ""}:</p>
              <pre className="ae-code">{`USE ROLE ${d.use_role};${d.warehouse ? `\nUSE WAREHOUSE ${d.warehouse};` : ""}`}</pre>
            </>
          )}
          {d.read.role_only && <p className="ae-muted">{d.read.role_only}</p>}
          {d.read.rows && <p>Rows: {StateTag(d.read.rows)} <span className="ae-muted">{d.read.rows.reason}</span></p>}
          {d.read.columns.length > 0 && (
            <DataTable csv="check_columns.csv" rows={d.read.columns}
              columns={[col("c", "Column", (r: any) => r.column), col("s", "State", (r: any) => r.state, { render: (r: any) => StateTag(r) }),
                col("r", "Why", (r: any) => r.reason, { wrap: "wrap" })]} />
          )}
        </Card>
      )}
    </>
  );
}

/** When no single link is on every route: the server's ways to remove the access, one per route. */
function RemoveOptions({ d }: { d: CheckPage }) {
  if (!d.options.length) return null;
  return (
    <div className="ae-options">
      {d.options.map((x, i) => (
        <div key={i} className="ae-option">
          <p><strong>Option {i + 1}</strong> · {x.affects} privilege(s) lost · {x.users.length} user(s) affected</p>
          <pre className="ae-code">{x.iac}</pre><pre className="ae-code">{x.sql}</pre>
        </div>
      ))}
    </div>
  );
}

/** Why a held privilege is blocked: what is held, the USAGE missing, then one grant per line that fixes it. */
export function Blocked({ d, fix }: { d: CheckPage; fix: { iac: string; sql: string } }) {
  const has = [...new Set(d.paths.map((x) => x.privilege))].join(", ") || "OWNERSHIP";
  const todo = fix.iac.split(/; (?=Add )/).map((x) => x.replace(/^Add in the infrastructure-as-code repo: /, ""));
  return (
    <>
      <ul className="ae-unblock">
        <li><span className="ae-tag ae-tag-ok">✓ Has</span> <span><strong>{has}</strong> on <span className="ae-mono">{d.object}</span></span></li>
        {d.usage.map((x) => (
          <li key={x.type}><span className={`ae-tag ae-tag-${x.held ? "ok" : "bad"}`}>{x.held ? "✓ Has" : "✕ Missing"}</span>{" "}
            <span><strong>USAGE</strong> on {x.type.toLowerCase()} <span className="ae-mono">{x.name}</span></span></li>
        ))}
      </ul>
      <h4>Smallest fix, in the infrastructure-as-code repo</h4>
      <ul className="ae-unblock">{todo.map((x) => <li key={x}><span className="ae-tag ae-tag-warn">+ Add</span> <span>{x}</span></li>)}</ul>
      <p className="ae-muted">The same as SQL (this app never runs it):</p>
      <pre className="ae-code">{fix.sql.replace(/; (?=GRANT )/g, ";\n")}</pre>
    </>
  );
}

/** The answer tab: the nearest way in (No), why it is blocked, the graph of how the access gets there. Without
 * routes (no Routes tab) the table of routes and the ways to remove it stay here. */
/** "2 of 3 columns in clear" */
const columnsTitle = (cs: { state: string }[]) => `${cs.filter((x) => x.state === "clear").length} of ${cs.length} ${cs.length === 1 ? "column" : "columns"} in clear`;

function Answer({ d }: { d: CheckPage }) {
  const a = d.answer;
  if (d.verdict === "na") return null;
  return (
    <>
      {d.verdict === "no" && d.view !== "mine" && <NearestWays d={d} first />}
      {d.unblock && (
        <Card title="Why it is blocked" sub="USAGE on the database and schema is checked first.">
          <Blocked d={d} fix={d.unblock} />
        </Card>
      )}
      <CutBanner capped={d.capped} no={d.verdict === "no"} />
      <GraphCard g={d.graph} refs={d.refs} title={d.lanes_total === 1 && d.lanes[0] ? `They get in through ${d.lanes[0].path.length - 2} ${d.lanes[0].path.length === 3 ? "role" : "roles"}` : d.lanes_total ? `They get in ${d.lanes_total} ways` : undefined} />
      {!d.lanes_total && <RouteTable d={d} />}
      {a.yes && d.view !== "mine" && (
        <div className="ae-two">
          {d.read && d.read.columns.length > 0 && <Card title={columnsTitle(d.read.columns)}>
            <DataTable rows={d.read.columns} filter={false}
              columns={[col("c", "Column", (r: any) => r.column), col("s", "They see", (r: any) => r.state, { render: (r: any) => StateTag(r) }), col("r", "Why", (r: any) => r.reason, { wrap: "wrap" })]} />
          </Card>}
          {d.subject.user && <Card title="Used by them"><UseLine name={d.object} user={d.user} /></Card>}
        </div>
      )}
      {d.options.length > 0 && !d.lanes_total && <Card title="Ways to remove this access" sub="Text to copy into your infrastructure as code. This app never runs it."><RemoveOptions d={d} /></Card>}
    </>
  );
}
