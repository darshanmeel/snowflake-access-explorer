// Screen 1: My access / a person or role. Answer first, one row per object at its highest level, "How?" on demand.
import { Fragment, useEffect, useState } from "react";
import { download as saveCsv, useApi } from "../api/client";
import type { AccessObject, AccessPage, ListItem, RolePage } from "../api/types";
import { Card, Figs, Tabs, EmptyState, FilterChips, FindingChip, IdentityCard, ListToolbar, Pager, Toggle } from "../components";
import { apiParams, AppCtx, useApp, useOpen } from "../ctx";
import { ActivityTab } from "./Activity";
import { ChangeFeed } from "./Changes";
import { RolePageView, roleTabs } from "./Role";
import { UserPage } from "./User";
import { Load, Pick, PickFirst, Risks, Sel, unread } from "./common";
import { recent, remember } from "./Home";
import { groupKey, type GroupBy } from "./screens";
import { doOf } from "./verdict";

const nameOf = (o: AccessObject) => o.label ?? o.object;
/** A long role name cut in the middle, where technical role names differ least (T_DB_SCHEMA_..._READ). */
export const mid = (s: string, n = 30) => (s.length > n ? `${s.slice(0, Math.ceil(n / 2) - 1)}…${s.slice(-Math.floor(n / 2))}` : s);
const HEAT_MIN = 15; // the server's HEAT: more schemas than this get a search box
const ROLE_PARTS = ["privs", "held", "holds", "sees", "rw"]; // the Role page's parts, a role's own tabs here
const plural = (n: number, w: string, ws = `${w}s`) => `${n.toLocaleString("en-US")} ${n === 1 ? w : ws}`;

const subjectOf = (c: ReturnType<typeof useApp>) => {
  const role = c.params.role ?? "";
  return { view: c.view, ...(role ? { role } : { user: c.params.user ?? c.meta.default_user ?? "" }) };
};

export function AccessPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user ?? "");
  const s = useApi<AccessPage>(role || user ? "access" : null, { ...subjectOf(c), short: "1" });
  const kind = role || c.params.kind === "role" ? "role" : "person"; // the menu has an entry for each
  const pick = (v: string, i: ListItem) => c.set(i.kind !== "user" ? { role: v, user: null, kind: null } : { user: v, role: null, kind: null });
  return (
    <>
      <div className="ae-headrow">
        <div>
          {mine ? <h2 className="ae-h1">My access</h2> : (
            <div className="ae-h1 ae-h1-pick">What can <Pick label={kind === "role" ? "Role" : "Person"} value={role || user} user={!role} what={kind === "role" ? "roles" : "users"} onPick={pick} width={300} /> {kind === "role" ? "open?" : "do?"}
              {recent().filter((r) => (r.page === "user" || r.page === "role") && r.id !== (role || user)).slice(0, 4).map((r) => (
                <button type="button" key={r.id} className="ae-pchip" title="Recently viewed" onClick={() => c.set(r.page === "role" ? { role: r.id, user: null } : { user: r.label, role: null })}>{r.label}</button>))}
            </div>
          )}
        </div>
      </div>
      {role || user ? <Load s={s}>{(d) => <Body key={`${d.who.kind}:${d.who.id}`} d={d} />}</Load> : <PickFirst what={kind === "role" ? "a role" : "a person"} />}
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
  const [otype, setOtype] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [cell, setCell] = useState<{ schema: string; min: string } | null>(null);
  const [whyAll, setWhyAll] = useState(false);
  const [rest, setRest] = useState(false); // schemas and future grants in the list too
  const [sq, setSq] = useState(""); // q as sent, a moment after the last key
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => setSq(q), 250); return () => clearTimeout(t); }, [q]);
  const [hq, setHq] = useState("");
  const [sq2, setSq2] = useState(""); // hq as sent
  useEffect(() => { const t = setTimeout(() => setSq2(hq), 250); return () => clearTimeout(t); }, [hq]);
  const hs = useApi<AccessPage>(sq2 ? "access" : null, { ...subjectOf(c), hq: sq2 });
  const heat = sq2 ? hs.data ?? d : d;
  useEffect(() => setPage(0), [lvl, sq, usage, group, sort, cell, otype, rest]);
  const w = d.who, n = d.counts, tb = n.tables ?? { read: n.read, change: n.change, own: n.own, clear: n.sensitive }, nm = n.names ?? { clear: [], change: [], schemas: [] }, user = w.kind === "user";
  const adm = d.admin_roles ?? [], adminRole = !user && adm.includes(w.name); // admin role links are dropped: zero would read as safe
  useEffect(() => { if (c.view === "shared") remember({ page: user ? "user" : "role", id: w.id, label: w.name }); }, [w.id, user, w.name, c.view]);
  const rd = useApi<RolePage>(user ? null : "role", { ...apiParams(inner(c, w.name, false)), name: w.name }).data; // a role's own tabs, the same fetch they show
  const rtabs = user ? [] : roleTabs(rd);
  const part = !user && c.params.show === "detail" && ROLE_PARTS.includes(c.params.part ?? "") ? c.params.part! : c.params.show ?? ""; // old links: show=detail&part=held
  const keys = ["summary", "privs", "detail", "runs", "history", "activity", ...(user ? [] : ROLE_PARTS)];
  const show = keys.includes(part) ? part : "overview"; // the summary first, the long lists on their own tabs
  // the list is filtered, sorted and paged on the server: a big user has 100k+ objects
  const ask = { ...subjectOf(c), filter: lvl === "all" ? null : lvl, q: sq || null, usage: usage ? "1" : null, group: group === "none" ? null : group,
    sort: sort === "risk" ? null : sort, otype: otype || null, short: "1", more: rest ? "1" : null, cell: cell?.schema, min: cell?.min, offset: page ? String(page * d.limit) : null };
  const first = Object.entries(ask).every(([k, v]) => v == null || k === "view" || k === "user" || k === "role" || k === "short");
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
  const objects_ = (
      <Card title={tagsOff || !tb.clear ? (user ? "What they can access" : "What it opens") : `${tb.clear.toLocaleString("en-US")} of ${tb.read.toLocaleString("en-US")} show sensitive columns in clear`}>
        <details className="ae-filter" open={lvl !== "all" || !!q || usage || group !== "none" || !!otype || !!cell || undefined}><summary>Filter, group, CSV</summary>
        <ListToolbar search={q} onSearch={setQ} onCsv={() => saveCsv("access.csv", { ...ask, offset: null }, `${w.name}_access.csv`)}>
          <FilterChips label="Filter by access" value={lvl} onPick={setLvl} items={[
            { key: "all", label: "All", count: list.data }, { key: "read", label: "Read only" }, { key: "change", label: "Can change" },
            { key: "own", label: "Owns" }, { key: "multi", label: "More than one way" }]} />
          <Toggle label={`Show ${n.usage} database/schema USAGE grants`} on={usage} onPick={setUsage} />
          <Sel label="Type" value={otype} onPick={setOtype}
            options={[["", "Every type"], ...(list.types ?? d.types ?? []).map((t): [string, string] => [t.type, `${t.type.toLowerCase()} (${t.n})`])]} />
          <FilterChips label="Group by" value={group} onPick={(k) => setGroup(k as GroupBy)} items={[{ key: "none", label: "No groups" }, { key: "schema", label: "Schema" }, { key: "type", label: "Type" }]} />
          <FilterChips label="Sort" value={sort} onPick={setSort} items={[{ key: "risk", label: "Riskiest first" }, { key: "name", label: "Name" }]} />
          {cell && <button type="button" className="ae-chip ae-chip-plain" onClick={() => setCell(null)}>{cell.schema} · {cell.min} ×</button>}
        </ListToolbar>
        </details>
        {show === "overview" && d.data > list.total && !rest && lvl === "all" && !q && <p><button type="button" className="ae-link" onClick={() => setRest(true)}>+{(d.data - list.total).toLocaleString("en-US")} schemas, future grants and the like</button></p>}
        {show === "overview" && d.heat_total > 1 && <p><button type="button" className="ae-link" onClick={() => c.set({ show: "summary" })}>Objects per schema</button></p>}
        {!shown.length ? <EmptyState title="Nothing matches">Change the filter, or clear the search.</EmptyState> : (
          <div className={`ae-olist${!first && l.loading ? " ae-fade" : ""}`} role="table">
            <div className="ae-orow ae-orow-h" role="row"><span>Object</span><span className="ae-marks"><i>Read</i><i>Change</i><i>Own</i></span><span>Sensitive columns</span><span>Used, 60 days</span><span>Granted through</span><span /></div>
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
                          {x.findings.length > 0 && isOpen && <span className="ae-ochips">{x.findings.map((f) => <FindingChip key={f.num} {...f} onOpen={() => ruleLink(f.num)} />)}</span>}
                        </span>
                        <Marks level={x.level} privileges={x.privileges} />
                        <Clear x={x} />
                        <span>{x.used == null ? <span className="ae-muted">not read</span> : x.used.queries ? <>{x.used.queries.toLocaleString("en-US")} queries, {x.used.last.slice(5)}</> : <span className="ae-muted">no use recorded</span>}</span>
                        <span className="ae-mono ae-osub">{[x.first, x.holder].filter((v, i, xs) => v && xs.indexOf(v) === i).join(" → ")}{x.ways > 1 && <span className="ae-muted"> +{x.ways - 1}</span>}</span>
                        <button type="button" className="ae-link" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : id)}>{isOpen ? "Close" : "How?"}</button>
                      </div>
                      {isOpen && <How x={x} who={w.name} user={user} />}
                    </Fragment>
                  );
                })}
              </Fragment>
            ))}
          </div>
        )}
        <div className="ae-bar-legend ae-mt"><span><span className="ae-dot2 ae-lvl-read" />Read</span><span><span className="ae-dot2 ae-lvl-change" />Change</span><span><span className="ae-dot2 ae-lvl-own" />Own</span><span className="ae-bad">red = seen in clear</span></div>
        {list.total > list.limit && <Pager at={page} size={list.limit} total={list.total} onPage={setPage} />}
      </Card>
  );
  return (
    <>
      <Tabs nav active={show} onChange={(k) => c.set({ show: k === "overview" ? null : k, part: null })} tabs={[
        { key: "overview", label: user ? "Can do" : "Opens" },
        ...rtabs.filter((t) => t.key === "held"),
        { key: "detail", label: "Graph & trace" },
        { key: "activity", label: "Activity" },
        { key: "history", label: "History" },
        user ? { key: "privs", label: "Privileges" } : rtabs[0],
        ...rtabs.slice(1).filter((t) => t.key !== "held"),
        { key: "runs", label: "Can run", count: d.runs_total + d.powers_total, tone: d.powers_total > 0 ? "bad" as const : null },
      ]} />
      {show === "detail" && <p className="ae-answer"><span className="ae-mono">{w.name}</span> {user ? "reaches" : "opens"} {plural(tb.read, "table and view", "tables and views")} through {plural(d.roles, "role")}</p>}
      {show === "held" && <p className="ae-answer">{plural(w.held_by?.users ?? 0, "person", "people")}{(w.held_by?.roles ?? 0) > 0 && <> and {plural(w.held_by!.roles, "role")}</>} {(w.held_by?.users ?? 0) + (w.held_by?.roles ?? 0) === 1 ? "holds" : "hold"} <span className="ae-mono">{w.name}</span></p>}
      {show === "detail" ? <Detail name={w.name} user={user} pane="diagram" />
        : ROLE_PARTS.includes(show) ? <Detail name={w.name} user={user} pane={show} /> : null}
      {show === "activity" && <ActivityTab what={user ? "user" : "role"} name={w.name} />}
      {show === "history" && <ChangeFeed subject={w.id} />}
      {show === "overview" && <>
      {adminRole ? <p className="ae-answer">
        <span className="ae-mono">{w.name}</span> <b className="ae-bad">is an admin role: it can do everything below it, not listed here.</b>
        {" "}Only its own account powers are listed. <button type="button" className="ae-link" onClick={() => c.nav("rules", { part: "admins" })}>People with admin roles</button>
      </p> : <p className="ae-answer">
        {adm.length > 0 && <><span className="ae-mono">{w.name}</span> <b className="ae-bad">holds {adm.join(", ")}: can do everything below {adm.length > 1 ? "them" : "it"}, not counted here.</b>
          {" "}<button type="button" className="ae-link" onClick={() => c.nav("rules", { part: "admins" })}>People with admin roles</button> Without {adm.length > 1 ? "them" : "it"}: </>}
        <span className="ae-mono">{w.name}</span> {!tb.read ? "reads no tables or views" : user ? <>can change {tb.change.toLocaleString("en-US")} of {plural(tb.read, "table and view", "tables and views")}{tb.own > 0 && <>, owns {tb.own.toLocaleString("en-US")}</>}{tb.clear > 0 && <>, {tb.clear === tb.read ? "all" : tb.clear.toLocaleString("en-US")} with sensitive columns in clear</>}</> : <>opens {plural(tb.read, "table and view", "tables and views")}{tb.clear > 0 && <>, {tb.clear.toLocaleString("en-US")} of them sensitive</>}</>}
        {n.admin > 0 && <>, <b className="ae-bad">{n.admin} through an admin role</b></>}
      </p>}
      <Figs items={[
        user ? { key: "read", n: tb.read.toLocaleString("en-US"), text: "tables and views they can read", note: nm.schemas.join(", ") || undefined }
          : { key: "held", n: (w.held_by?.users ?? 0).toLocaleString("en-US"), text: w.held_by?.users === 1 ? "person holds it" : "people hold it", note: w.held_by?.roles ? `and ${plural(w.held_by.roles, "role")}` : undefined, go: () => c.set({ show: "held" }) },
        user ? { key: "sens", n: tagsOff ? "not read" : tb.clear.toLocaleString("en-US"), text: "with sensitive columns seen in clear", bad: !tagsOff && tb.clear > 0, note: tagsOff ? `${tagsOff.title}: sensitivity unknown` : nm.clear.join(", ") || undefined }
          : { key: "chg", n: tb.change.toLocaleString("en-US"), text: "objects it can change", note: nm.change.join(", ") || undefined },
        d.risks?.length ? { key: "risk", n: d.risks.reduce((t, r) => t + r.n, 0).toLocaleString("en-US"), text: "risks to look at", bad: d.risks.some((r) => r.severity === "bad"), note: d.risks[0].text }
          : { key: "run", n: d.runs_total.toLocaleString("en-US"), text: "things to run", go: () => c.set({ show: "runs" }) },
      ]} />
      {n.read > 0 && objects_}
      {d.runs_total + d.powers_total > 0 && <Card title="Can also run">
        <ul className="ae-runlist">{[...powers.slice(0, 2), ...runs.slice(0, 5)].map((x) => <li key={x.object + x.privileges.join()}><span><b className="ae-mono">{x.category === "account" ? x.privileges.join(", ") : x.object.split(".").pop()}</b> <span className={x.category === "account" ? "ae-bad" : "ae-muted"}>{x.category === "account" ? "account power" : `${x.type.toLowerCase()}${x.level === "own" ? " (owns)" : ""}`}</span></span><span className="ae-mono ae-muted">{x.holder === "PUBLIC" ? "PUBLIC (everyone)" : x.holder}</span></li>)}</ul>
        {d.runs_total + d.powers_total > Math.min(2, powers.length) + Math.min(5, runs.length) && <button type="button" className="ae-link" onClick={() => c.set({ show: "runs" })}>All {(d.runs_total + d.powers_total).toLocaleString("en-US")}</button>}
      </Card>}
      <details className="ae-fold"><summary>Why, risks, identity, other questions</summary><div className="ae-fold-in">
      <div>
        <Card title={user ? "Why they have it" : "Who holds it, what it holds"} sub={`${plural(d.roles, "role")} · deepest ${d.deepest}`}>
          <ul className="ae-why">
            {(whyAll ? d.why : d.why.slice(0, 3)).map((r) => (
              <li key={r.role}>
                <div><button type="button" className={`ae-pchip ae-pchip-${r.kind}`} onClick={() => o.open(r.role)}>{r.role}</button> <span className="ae-muted">{r.note}</span></div>
                {r.kids.length > 0 && <div className="ae-why-kids">{r.kids.map((k) => <button type="button" key={k} className="ae-pchip" onClick={() => o.open(k)}>{k}</button>)}
                  {r.kids_total > r.kids.length && <button type="button" className="ae-link" onClick={() => c.nav("role", { name: r.role })}>+{r.kids_total - r.kids.length} more</button>}</div>}
              </li>
            ))}
          </ul>
          {d.why.length > 3 && <button type="button" className="ae-link" onClick={() => setWhyAll(!whyAll)}>{whyAll ? "show less" : `+${d.why.length - 3} more`}</button>}
          {d.why_more > 0 && <p className="ae-muted">{plural(d.why_more, "more role")} hold{d.why_more === 1 ? "s" : ""} it: <button type="button" className="ae-link" onClick={() => c.set({ show: "held", part: null })}>Held by</button></p>}
          {w.secondary_all && <p className="ae-note">Secondary roles are <b>ALL</b>, so every query uses all of these roles at once.</p>}
        </Card>
      </div>
      <Risks list={d.risks} />
      <div className="ae-actions">
        <button type="button" className="ae-btn" onClick={() => c.nav("check", user ? { name: w.name } : { role: w.name })}>Can they?</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("graph", user ? { user: w.name } : { role: w.name })}>Show as graph</button>
        <details className="ae-more"><summary className="ae-btn">More</summary>
          <button type="button" className="ae-btn" onClick={() => c.nav("see", user ? { user: w.name } : { role: w.name })}>What they see</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("compare", { a: w.id })}>Compare with…</button>
          <button type="button" className="ae-btn" title="Every grant next to the query history: up to a minute for a big person or role" onClick={() => c.nav("usage", user ? { user: w.name } : { role: w.name })}>Granted vs used</button>
        </details>
      </div>
      </div></details>
      </>}
      {show === "runs" && <>
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
      {show === "summary" && <>
      <Card title="Where the access is" sub={`Objects per schema, each at the most they can do; riskiest ${d.heat_total > HEAT_MIN ? `${heat.heat.length} of ${d.heat_total} ` : ""}schemas first. Click a cell to filter the list.`}>
        {d.heat_total > HEAT_MIN && <input className="ae-input" placeholder={`Search ${d.heat_total} schemas`} value={hq} onChange={(e) => setHq(e.target.value)} aria-label="Search schemas" />}
        {heat.heat.length ? (
          <div className={`ae-heat${sq2 && hs.loading ? " ae-fade" : ""}`} role="table">
            <div role="row" className="ae-heat-h"><span>Database</span><span>Schema</span><span>Read only</span><span>Change</span><span>Own</span><span>Sensitive</span></div>
            {heat.heat.map((h) => (
              <div role="row" key={h.schema}>
                <span className="ae-mono" title={h.database}>{h.database}</span>
                <span className="ae-mono" title={h.name}>{h.name || "·"}</span>
                {(["read", "change", "own", "sensitive"] as const).map((k) => (
                  <button type="button" key={k} disabled={!h[k]} className={`ae-heat-c ${h[k] ? (k === "sensitive" ? "ae-sens-tag" : `ae-lvl-${k}`) : ""}${cell?.schema === h.schema && cell.min === k ? " on" : ""}`}
                    onClick={() => { setCell({ schema: h.schema, min: k }); c.set({ show: "summary" }); }}>{h[k] || "·"}</button>
                ))}
              </div>
            ))}
            {heat.heat_total > heat.heat.length && <div role="row" className="ae-muted">{plural(heat.heat_total - heat.heat.length, "more schema")}: search to find one</div>}
          </div>
        ) : sq2 ? <EmptyState title="No schema matches">Clear the search.</EmptyState> : <EmptyState title="No data objects">Only names, runnable things or account powers.</EmptyState>}
      </Card>
      </>}
      {show === "summary" && objects_}
      <IdentityCard name={w.name} tag={c.view === "mine" ? "You" : "Viewing"}
        line={user ? `${w.type === "SERVICE" ? "Service user" : "Person"} · ${status} · default role ${w.default_role ?? "none"} · secondary roles ${w.secondary_all ? "ALL" : "none"} · default warehouse ${w.default_warehouse ?? "none"}`
          : <span className={adminRole ? "ae-bad" : undefined}>{w.type}{w.owner.length ? ` · owner ${w.owner.join(", ")}` : ""} · held by {plural(w.held_by?.users ?? 0, "person")} and {plural(w.held_by?.roles ?? 0, "role")}</span>}
        roles={user ? d.why.map((r) => ({ id: r.role, note: r.note === "everyone" ? "" : r.note, kind: r.kind })) : undefined} />
    </>
  );
}

/** The sensitive columns and how many are seen in clear. */
function Clear({ x }: { x: AccessObject }) {
  if (!x.sensitive && !x.columns.length) return <span className="ae-muted">no sensitive tag</span>;
  const c = x.columns.filter((k) => k.state !== "masked"), tip = x.columns.map((k) => `${k.column}: ${k.state} (${k.reason})`).join("\n");
  if (!x.columns.length) return <span className="ae-bad" title="The whole object is tagged sensitive">sensitive, clear</span>;
  return <span className={c.length ? "ae-bad" : undefined} title={tip}>{!c.length ? "masked" : x.columns.length === 1 ? `${x.columns[0].column} clear` : `${c.length} of ${x.columns.length} clear`}</span>;
}

/** Read, change, own as filled marks: each level holds the ones before it. */
function Marks({ level, privileges }: { level: AccessObject["level"]; privileges: string[] }) {
  const at = level === "own" || level === "admin" ? 3 : level === "change" ? 2 : level === "read" ? 1 : 0;
  if (!at) return <span className="ae-privs">{privileges.join(" · ")}</span>;
  return (
    <span className="ae-marks" title={privileges.join(" · ")}>
      {(["read", "change", "own"] as const).map((k, i) => <i key={k} className={i < at ? `on ae-lvl-${k}` : ""} aria-label={i < at ? k : `no ${k}`} />)}
    </span>
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

/** The User or Role page's context inside this screen, for the same subject: `pane` is the one part it shows. */
const inner = (c: ReturnType<typeof useApp>, name: string, user: boolean, pane?: string) => {
  const { user: _u, role: _r, show: _s, ...rest } = c.params;
  return { ...c, page: (user ? "user" : "role") as typeof c.page, params: { ...rest, name, ...(pane ? { pane } : {}) }, inside: true };
};

/** One part of the User or Role page (its diagram, privilege tabs, held by, ...) as this screen's tab. */
function Detail({ name, user, pane }: { name: string; user: boolean; pane: string }) {
  const c = useApp();
  return (
    <div className="ae-embed">
      <AppCtx.Provider value={inner(c, name, user, pane)}>{user ? <UserPage /> : <RolePageView />}</AppCtx.Provider>
    </div>
  );
}
