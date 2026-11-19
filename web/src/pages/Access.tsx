// Screen 1: My access / a person or role. Answer first, one row per object at its highest level, "How?" on demand.
import { Fragment, useEffect, useState } from "react";
import { download as saveCsv, useApi } from "../api/client";
import type { AccessObject, AccessPage, ListItem } from "../api/types";
import { AccessPill, Card, Tabs, EmptyState, FilterChips, FindingChip, IdentityCard, ListToolbar, PathChips, SensitiveCell, Pager, StackBar, Toggle } from "../components";
import { AppCtx, useApp, useOpen } from "../ctx";
import { ActivityTab } from "./Activity";
import { ChangeFeed } from "./Changes";
import { RolePageView } from "./Role";
import { UserPage } from "./User";
import { Load, Pick, PickFirst, unread } from "./common";
import { ladderParts, recent, remember } from "./Home";
import { HowGraph } from "./Object";
import { groupKey, type GroupBy } from "./screens";
import { doOf } from "./verdict";

const nameOf = (o: AccessObject) => o.label ?? o.object;
/** A long role name cut in the middle, where technical role names differ least (T_DB_SCHEMA_..._READ). */
export const mid = (s: string, n = 30) => (s.length > n ? `${s.slice(0, Math.ceil(n / 2) - 1)}…${s.slice(-Math.floor(n / 2))}` : s);
const HEAT_MIN = 15; // the server's HEAT: more schemas than this get a search box
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

const subjectOf = (c: ReturnType<typeof useApp>) => {
  const role = c.params.role ?? "";
  return { view: c.view, ...(role ? { role } : { user: c.params.user ?? c.meta.default_user ?? "" }) };
};

export function AccessPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user ?? "");
  const s = useApi<AccessPage>(role || user ? "access" : null, subjectOf(c));
  const pick = (v: string, i: ListItem) => c.set(i.kind !== "user" ? { role: v, user: null } : { user: v, role: null });
  return (
    <>
      <div className="ae-headrow">
        <div>
          {mine ? <h2 className="ae-h1">My access</h2> : (
            <div className="ae-h1 ae-h1-pick">Access for <Pick label="Person or role" value={role || user} user={!role} what="users,roles" onPick={pick} width={260} />
              {recent().filter((r) => (r.page === "user" || r.page === "role") && r.id !== (role || user)).slice(0, 4).map((r) => (
                <button type="button" key={r.id} className="ae-pchip" title="Recently viewed" onClick={() => c.set(r.page === "role" ? { role: r.id, user: null } : { user: r.label, role: null })}>{r.label}</button>))}
            </div>
          )}
        </div>
      </div>
      {role || user ? <Load s={s}>{(d) => <Body key={`${d.who.kind}:${d.who.id}`} d={d} />}</Load> : <PickFirst />}
    </>
  );
}

function Body({ d }: { d: AccessPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const [lvl, setLvl] = useState(c.params.filter ?? "all");
  const [q, setQ] = useState("");
  const [usage, setUsage] = useState(false);
  const [group, setGroup] = useState<GroupBy>("none");
  const [sort, setSort] = useState("risk");
  const [open, setOpen] = useState<string | null>(null);
  const [cell, setCell] = useState<{ schema: string; min: string } | null>(null);
  const [sq, setSq] = useState(""); // q as sent, a moment after the last key
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => setSq(q), 250); return () => clearTimeout(t); }, [q]);
  const [hq, setHq] = useState("");
  const [sq2, setSq2] = useState(""); // hq as sent
  useEffect(() => { const t = setTimeout(() => setSq2(hq), 250); return () => clearTimeout(t); }, [hq]);
  const hs = useApi<AccessPage>(sq2 ? "access" : null, { ...subjectOf(c), hq: sq2 });
  const heat = sq2 ? hs.data ?? d : d;
  useEffect(() => setPage(0), [lvl, sq, usage, group, sort, cell]);
  const w = d.who, n = d.counts, user = w.kind === "user";
  const adm = d.admin_roles ?? [], adminRole = !user && adm.includes(w.name); // admin role links are dropped: zero would read as safe
  useEffect(() => { if (c.view === "shared") remember({ page: user ? "user" : "role", id: w.id, label: w.name }); }, [w.id, user, w.name, c.view]);
  const show = c.params.show === "summary" || c.params.show === "history" || c.params.show === "activity" ? c.params.show : "detail"; // the diagram first
  // the list is filtered, sorted and paged on the server: a big user has 100k+ objects
  const ask = { ...subjectOf(c), filter: lvl === "all" ? null : lvl, q: sq || null, usage: usage ? "1" : null, group: group === "none" ? null : group,
    sort: sort === "risk" ? null : sort, cell: cell?.schema, min: cell?.min, offset: page ? String(page * d.limit) : null };
  const first = Object.entries(ask).every(([k, v]) => v == null || k === "view" || k === "user" || k === "role");
  const l = useApi<AccessPage>(first ? null : "access", ask);
  const list = first ? d : l.data ?? d;
  const lo = useOpen(list.refs);
  const shown = list.objects;
  const groups = group !== "none" ? [...new Set(shown.map((x) => groupKey(x, group)))] : [""];
  const runs = d.runs, tagsOff = unread(c.meta, "tags");
  const powers = d.powers;
  const ruleLink = (num: string) => c.nav("rules", { rule: num });
  const status = w.status ? `${w.disabled ? "disabled" : w.status === "never" ? "never logged in" : w.status}${  // "never" says it once
    w.last_login && w.status !== "never" ? ` · last login ${w.last_login}` : ""}` : "";
  return (
    <>
      <IdentityCard name={w.name} tag={c.view === "mine" ? "You" : "Viewing"}
        line={user ? `${w.type === "SERVICE" ? "Service user" : "Person"} · ${status}` : `${w.type} · held by ${plural(w.held_by?.users ?? 0, "person")} and ${plural(w.held_by?.roles ?? 0, "role")}`}
        roles={user ? d.why.map((r) => ({ id: r.role, note: r.note === "everyone" ? "" : r.note, kind: r.kind })) : undefined} />
      <div className="ae-actions">
        <button type="button" className="ae-btn" onClick={() => c.nav("check", user ? { name: w.name } : { role: w.name })}>Can they?</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("graph", user ? { user: w.name } : { role: w.name })}>Show as graph</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("see", user ? { user: w.name } : { role: w.name })}>What they see</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("compare", { a: w.id })}>Compare with…</button>
        <button type="button" className="ae-btn" title="Every grant next to the query history: up to a minute for a big person or role" onClick={() => c.nav("usage", user ? { user: w.name } : { role: w.name })}>Granted vs used</button>
      </div>
      {adminRole ? <p className="ae-answer">
        <span className="ae-mono">{w.name}</span> <b className="ae-bad">is an admin role: it can do everything below it, not listed here.</b>
        {" "}Only its own account powers are listed. <button type="button" className="ae-link" onClick={() => c.nav("rules", { part: "admins" })}>People with admin roles</button>
      </p> : <p className="ae-answer">
        <span className="ae-mono">{w.name}</span> can <b>read data in {plural(n.read, "object")}</b> across {plural(n.schemas, "schema")}.
        {" "}{user ? "They" : "It"} can <b>change {n.change}</b> of them and <b>own {n.own}</b>.
        {n.sensitive > 0 && <> <span className="ae-sens-word">{n.sensitive} hold sensitive columns</span> seen unmasked.</>}
        {n.admin > 0 && <> <b className="ae-bad">{n.admin} through an admin role.</b></>}
        {(n.future ?? 0) > 0 && <> Plus {plural(n.future ?? 0, "future grant")} (every new object in those schemas).</>}
        {adm.length > 0 && <> <b className="ae-bad">Holds {adm.join(", ")}: can also do everything below {adm.length > 1 ? "them" : "it"}, not counted here.</b>
          {" "}<button type="button" className="ae-link" onClick={() => c.nav("rules", { part: "admins" })}>People with admin roles</button></>}
      </p>}
      <div className="ae-ladder">
        <div className="ae-ladder-bar">
          <div className="ae-ladder-h"><b>{n.read}</b> objects with data <span className="ae-muted">· click a part to list them</span></div>
          <StackBar label="Access ladder: read only, read and change, owns" parts={ladderParts(n)} on={lvl}
            onPick={(k) => { setLvl(lvl === k ? "all" : k); c.set({ show: "summary" }); }} />
        </div>
        <div className="ae-tile ae-tile-sens" title={tagsOff ? `${tagsOff.title}: sensitivity unknown` : undefined}><span className="ae-tile-l">Sensitive, unmasked</span><span className="ae-tile-v">{tagsOff ? "not read" : n.sensitive}</span></div>
        <button type="button" className="ae-tile" onClick={() => { c.set({ show: "summary" }); setTimeout(() => document.getElementById("runs")?.scrollIntoView(), 50); }}><span className="ae-tile-l">Can run</span><span className="ae-tile-v">{n.runnable}</span><span className="ae-muted ae-tile-c">warehouses, tasks, functions, procedures</span></button>
      </div>
      <Tabs nav active={show} onChange={(k) => c.set({ show: k === "detail" ? null : k })} tabs={[
        { key: "detail", label: user ? "Diagram & privileges" : "Diagram, held by & holds" },
        { key: "summary", label: "One row per object", count: d.data },
        { key: "activity", label: "Activity" },
        { key: "history", label: "History" },
      ]} />
      {show === "detail" && <Detail name={w.name} user={user} />}
      {show === "activity" && <ActivityTab what={user ? "user" : "role"} name={w.name} />}
      {show === "history" && <ChangeFeed subject={w.id} />}
      {show === "summary" && <>
      <div className="ae-two">
        <Card title="Where the access is" sub={`Objects per schema, each at the most they can do; riskiest ${d.heat_total > HEAT_MIN ? `${heat.heat.length} of ${d.heat_total} ` : ""}schemas first. Click a cell to filter the list.`}>
          {d.heat_total > HEAT_MIN && <input className="ae-input" placeholder={`Search ${d.heat_total} schemas`} value={hq} onChange={(e) => setHq(e.target.value)} aria-label="Search schemas" />}
          {heat.heat.length ? (
            <div className={`ae-heat${sq2 && hs.loading ? " ae-fade" : ""}`} role="table">
              <div role="row" className="ae-heat-h"><span>Schema</span><span>Read only</span><span>Change</span><span>Own</span><span>Sensitive</span></div>
              {heat.heat.map((h) => (
                <div role="row" key={h.schema}>
                  <span className="ae-mono">{h.schema}</span>
                  {(["read", "change", "own", "sensitive"] as const).map((k) => (
                    <button type="button" key={k} disabled={!h[k]} className={`ae-heat-c ${h[k] ? (k === "sensitive" ? "ae-sens-tag" : `ae-lvl-${k}`) : ""}${cell?.schema === h.schema && cell.min === k ? " on" : ""}`}
                      onClick={() => setCell(cell?.schema === h.schema && cell.min === k ? null : { schema: h.schema, min: k })}>{h[k] || "·"}</button>
                  ))}
                </div>
              ))}
              {heat.heat_total > heat.heat.length && <div role="row" className="ae-muted">{plural(heat.heat_total - heat.heat.length, "more schema")}: search to find one</div>}
            </div>
          ) : sq2 ? <EmptyState title="No schema matches">Clear the search.</EmptyState> : <EmptyState title="No data objects">Only names, runnable things or account powers.</EmptyState>}
        </Card>
        <Card title="Why they have it" sub={`${plural(d.roles, "role")} · deepest ${d.deepest}`}>
          <ul className="ae-why">
            {d.why.map((r) => (
              <li key={r.role}>
                <div><button type="button" className={`ae-pchip ae-pchip-${r.kind}`} onClick={() => o.open(r.role)}>{r.role}</button> <span className="ae-muted">{r.note}</span></div>
                {r.kids.length > 0 && <div className="ae-why-kids">{r.kids.map((k) => <button type="button" key={k} className="ae-pchip" onClick={() => o.open(k)}>{k}</button>)}
                  {r.kids_total > r.kids.length && <button type="button" className="ae-link" onClick={() => c.nav("role", { name: r.role })}>+{r.kids_total - r.kids.length} more</button>}</div>}
              </li>
            ))}
          </ul>
          {d.why_more > 0 && <p className="ae-muted">{plural(d.why_more, "more role")} hold{d.why_more === 1 ? "s" : ""} it: <button type="button" className="ae-link" onClick={() => c.nav("role", { name: w.name })}>Role paths</button></p>}
          {w.secondary_all && <p className="ae-note">Secondary roles are <b>ALL</b>, so every query uses all of these roles at once.</p>}
        </Card>
      </div>
      <Card title="Data they can access" sub="One row per object, at the most it allows. Riskiest first.">
        <ListToolbar search={q} onSearch={setQ} onCsv={() => saveCsv("access.csv", { ...ask, offset: null }, `${w.name}_access.csv`)}>
          <FilterChips label="Filter by access" value={lvl} onPick={setLvl} items={[
            { key: "all", label: "All", count: list.data }, { key: "read", label: "Read only" }, { key: "change", label: "Can change" },
            { key: "own", label: "Owns" }, { key: "multi", label: "More than one way" }]} />
          <Toggle label={`Show ${n.usage} database/schema USAGE grants`} on={usage} onPick={setUsage} />
          <FilterChips label="Group by" value={group} onPick={(k) => setGroup(k as GroupBy)} items={[{ key: "none", label: "No groups" }, { key: "schema", label: "Schema" }, { key: "type", label: "Type" }]} />
          <FilterChips label="Sort" value={sort} onPick={setSort} items={[{ key: "risk", label: "Riskiest first" }, { key: "name", label: "Name" }]} />
          {cell && <button type="button" className="ae-chip ae-chip-plain" onClick={() => setCell(null)}>{cell.schema} · {cell.min} ×</button>}
        </ListToolbar>
        {!shown.length ? <EmptyState title="Nothing matches">Change the filter, or clear the search.</EmptyState> : (
          <div className={`ae-olist${l.loading ? " ae-fade" : ""}`} role="table">
            <div className="ae-orow ae-orow-h" role="row"><span>Object</span><span>Access</span><span>Sensitive columns</span><span>Granted through</span><span /></div>
            {groups.map((g) => (
              <Fragment key={g}>
                {g && <div className="ae-ogroup" role="row"><span className="ae-mono">{g}</span> <span className="ae-muted">{list.groups[g] ?? 0}</span></div>}
                {shown.filter((x) => !g || groupKey(x, group) === g).map((x) => {
                  const id = x.object + x.category;
                  const isOpen = open === id;
                  return (
                    <Fragment key={id}>
                      <div className="ae-orow" role="row">
                        <span className="ae-ocell">
                          <button type="button" className="ae-link ae-mono ae-oname" onClick={() => lo.open(x.object)}>{x.label ?? x.object.split(".").pop()}</button>
                          <span className="ae-muted ae-osub">{x.type.toLowerCase()}{x.schema ? ` · ${x.database}.${x.schema}` : ""}</span>
                          {x.findings.length > 0 && <span className="ae-ochips">{x.findings.map((f) => <FindingChip key={f.num} {...f} onOpen={() => ruleLink(f.num)} />)}</span>}
                        </span>
                        <AccessPill level={x.level} privileges={x.privileges} />
                        <SensitiveCell sensitive={x.sensitive} columns={x.columns} />
                        <PathChips first={x.first} holder={x.holder} ways={x.ways} kinds={list.refs.kinds} onOpen={lo.open} />
                        <button type="button" className="ae-btn" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : id)}>{isOpen ? "Close" : "How?"}</button>
                      </div>
                      {isOpen && <How x={x} who={w.name} user={user} />}
                    </Fragment>
                  );
                })}
              </Fragment>
            ))}
          </div>
        )}
        {list.total > list.limit && <Pager at={page} size={list.limit} total={list.total} onPage={setPage} />}
      </Card>
      <div className="ae-two" id="runs">
        <Card title="Things they can run" sub="Warehouses, tasks, functions and procedures: not on the ladder.">
          {runs.length ? <Items xs={runs} open={o.open} rule={ruleLink} /> : <EmptyState title="Nothing to run" />}
          {d.runs_total > runs.length && <p className="ae-muted">First {runs.length} of {d.runs_total}.</p>}
        </Card>
        <Card title="Powers over the account" sub="Account privileges, and CREATE or MODIFY on a database or schema.">
          {powers.length ? <Items xs={powers} open={o.open} rule={ruleLink} power /> : <EmptyState title="No account powers" />}
          {d.powers_total > powers.length && <p className="ae-muted">First {powers.length} of {d.powers_total}.</p>}
        </Card>
      </div>
      </>}
    </>
  );
}

function Items({ xs, open, rule, power = false }: { xs: AccessObject[]; open: (id: string) => void; rule: (n: string) => void; power?: boolean }) {
  return (
    <ul className="ae-items">
      {xs.map((x) => (
        <li key={x.object + x.privileges.join()}>
          <div>
            <div className="ae-mono">{power ? `${x.privileges.join(", ")}${x.object === "ACCOUNT" ? "" : ` on ${x.object}`}` : <button type="button" className="ae-link ae-mono" onClick={() => open(x.object)}>{x.object}</button>}</div>
            <div className="ae-muted">{power ? (x.object === "ACCOUNT" ? "account privilege" : x.type.toLowerCase()) : `${x.type.toLowerCase()} · ${x.privileges.join(" · ")}`}</div>
            {x.findings.length > 0 && <div className="ae-ochips">{x.findings.map((f) => <FindingChip key={f.num} {...f} onOpen={() => rule(f.num)} />)}</div>}
          </div>
          <div className="ae-muted ae-items-via">via {x.holder === "PUBLIC" ? "PUBLIC (everyone)" : x.holder}</div>
        </li>
      ))}
    </ul>
  );
}

function How({ x, who, user }: { x: AccessObject; who: string; user: boolean }) {
  const c = useApp();
  const steps = x.path.slice(1, -1);
  const use = steps[0] ?? x.holder;
  const [copied, setCopied] = useState(false);
  return (
    <div className="ae-how" role="row">
      <HowGraph who={user ? { name: who } : { role: who }} obj={x.object} level={x.level ?? ""} />
      <div className="ae-muted">Shortest path</div>
      <div className="ae-how-path">
        <span className="ae-pchip" title={who}>{mid(who)}</span>
        {steps.map((s) => <Fragment key={s}><span className="ae-arrow" aria-hidden>→</span><span className="ae-pchip" title={s}>{mid(s)}</span></Fragment>)}
        <span className="ae-arrow" aria-hidden>→</span><span className="ae-privs">{x.privileges.join(" · ")}</span>
        <span className="ae-arrow" aria-hidden>→</span><span className="ae-pchip ae-pchip-obj" title={x.object}>{mid(nameOf(x), 40)}</span>
      </div>
      <p>{x.ways > 1 ? `${x.ways - 1} other way${x.ways === 2 ? "" : "s"} lead here too, so removing one role may not remove the access.` : "This is the only way in: removing any role on it removes the access."}
        {x.columns.length > 0 && ` ${x.columns.map((col) => `${col.column} is ${col.state} (${col.reason})`).join("; ")}.`}</p>
      <div className="ae-how-links">
        <button type="button" className="ae-link" onClick={() => c.nav("object", { name: x.object })}>Who else has access</button>
        <button type="button" className="ae-link" onClick={() => c.nav("check", { ...(user ? { name: who } : { role: who }), obj: x.object, ...doOf(x.level) })}>See all {x.ways} path{x.ways === 1 ? "" : "s"}</button>
        <button type="button" className="ae-link" onClick={() => { navigator.clipboard?.writeText(`USE ROLE ${use};`).then(() => setCopied(true), () => {}); }}>{copied ? "Copied" : "Copy USE ROLE statement"}</button>
      </div>
    </div>
  );
}

/** The full User paths / Role paths page (role hierarchy diagram, privilege tabs with their diagrams, detail tables)
 * inside this screen, for the same subject. */
function Detail({ name, user }: { name: string; user: boolean }) {
  const c = useApp();
  const { user: _u, role: _r, show: _s, ...rest } = c.params;
  const inner = { ...c, page: (user ? "user" : "role") as typeof c.page, params: { ...rest, name }, inside: true };
  return (
    <div className="ae-embed">
      <AppCtx.Provider value={inner}>{user ? <UserPage /> : <RolePageView />}</AppCtx.Provider>
    </div>
  );
}
