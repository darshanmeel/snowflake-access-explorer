// Screen 1: My access / a person or role. Answer first, one row per object at its highest level, "How?" on demand.
import { Fragment, useEffect, useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { AccessObject, AccessPage, ListItem } from "../api/types";
import { AccessPill, Card, Tabs, EmptyState, FilterChips, FindingChip, IdentityCard, ListToolbar, PathChips, SensitiveCell, StackBar, Toggle, toCsv } from "../components";
import { download } from "../components/table";
import { AppCtx, useApp, useOpen } from "../ctx";
import { ChangeFeed } from "./Changes";
import { RolePageView } from "./Role";
import { UserPage } from "./User";
import { Load, Pick } from "./common";
import { ladderParts, recent, remember } from "./Home";
import { byName, groupKey, type GroupBy } from "./screens";

const RANK = { names: 0, read: 1, change: 2, own: 3, admin: 4 } as const;
const at = (o: AccessObject, min: keyof typeof RANK) => o.level != null && RANK[o.level] >= RANK[min];
const nameOf = (o: AccessObject) => o.label ?? o.object;
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

function save(name: string, rows: AccessObject[]) {
  const head = ["Object", "Type", "Access", "Privileges", "Sensitive columns", "Granted through", "Ways", "Findings"];
  download(`${name}_access.csv`, toCsv(head, rows.map((r) => [r.object, r.type, r.level ?? "", r.privileges.join(" "),
    r.columns.map((c) => `${c.column} ${c.state}`).join("; "), [r.first, r.holder].filter(Boolean).join(" > "), String(r.ways),
    r.findings.map((f) => `${f.severity} #${f.num}`).join("; ")])));
}

export function AccessPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user);
  const s = useApi<AccessPage>("access", { view: c.view, ...(role ? { role } : { user }) });
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
      <Load s={s}>{(d) => <Body key={`${d.who.kind}:${d.who.id}`} d={d} />}</Load>
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
  const w = d.who, n = d.counts, user = w.kind === "user";
  useEffect(() => { if (c.view === "shared") remember({ page: user ? "user" : "role", id: w.id, label: w.name }); }, [w.id, user, w.name, c.view]);
  const show = c.params.show === "summary" || c.params.show === "history" ? c.params.show : "detail"; // the diagram first
  const data = d.objects.filter((x) => x.category === "data" || (usage && x.category === "names"));
  const kept = data.filter((x) =>
    (lvl === "all" || (lvl === "read" ? x.level === "read" : lvl === "change" ? at(x, "change") && x.level !== "own" : lvl === "own" ? at(x, "own") : lvl === "multi" ? x.ways > 1 : true))
    && (!q || x.object.toLowerCase().includes(q.toLowerCase()))
    && (!cell || (`${x.database}.${x.schema}` === cell.schema || x.object === cell.schema) && (cell.min === "sensitive" ? x.sensitive : at(x, cell.min as keyof typeof RANK))));
  const shown = sort === "name" ? byName(kept) : kept;
  const groups = group !== "none" ? [...new Set(shown.map((x) => groupKey(x, group)))] : [""];
  const runs = d.objects.filter((x) => x.category === "runnable");
  const powers = d.objects.filter((x) => x.category === "account");
  const ruleLink = (num: string) => c.nav("rules", { rule: num });
  const status = w.status ? `${w.disabled ? "disabled" : w.status}${w.last_login ? ` · last login ${w.last_login}` : ""}` : "";
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
        <button type="button" className="ae-btn" onClick={() => c.nav("usage", user ? { user: w.name } : { role: w.name })}>Granted vs used</button>
      </div>
      <p className="ae-answer">
        <span className="ae-mono">{w.name}</span> can <b>read data in {plural(n.read, "object")}</b> across {plural(n.schemas, "schema")}.
        {" "}{user ? "They" : "It"} can <b>change {n.change}</b> of them and <b>own {n.own}</b>.
        {n.sensitive > 0 && <> <span className="ae-sens-word">{n.sensitive} hold sensitive columns</span> seen unmasked.</>}
        {n.admin > 0 && <> <b className="ae-bad">{n.admin} through an admin role.</b></>}
      </p>
      <div className="ae-ladder">
        <div className="ae-ladder-bar">
          <div className="ae-ladder-h"><b>{n.read}</b> objects with data <span className="ae-muted">· click a part to list them</span></div>
          <StackBar label="Access ladder: read only, read and change, owns" parts={ladderParts(n)} on={lvl}
            onPick={(k) => { setLvl(lvl === k ? "all" : k); c.set({ show: "summary" }); }} />
        </div>
        <div className="ae-tile ae-tile-sens"><span className="ae-tile-l">Sensitive, unmasked</span><span className="ae-tile-v">{n.sensitive}</span></div>
        <button type="button" className="ae-tile" onClick={() => { c.set({ show: "summary" }); setTimeout(() => document.getElementById("runs")?.scrollIntoView(), 50); }}><span className="ae-tile-l">Can run</span><span className="ae-tile-v">{n.runnable}</span><span className="ae-muted ae-tile-c">warehouses, tasks, functions, procedures</span></button>
      </div>
      <Tabs active={show} onChange={(k) => c.set({ show: k === "detail" ? null : k })} tabs={[
        { key: "detail", label: user ? "Diagram & privileges" : "Diagram, held by & holds" },
        { key: "summary", label: "One row per object", count: data.length },
        { key: "history", label: "History" },
      ]} />
      {show === "detail" && <Detail name={w.name} user={user} />}
      {show === "history" && <ChangeFeed subject={w.id} />}
      {show === "summary" && <>
      <div className="ae-two">
        <Card title="Where the access is" sub="Objects per schema, by the most they can do. Click a cell to filter the list.">
          {d.heat.length ? (
            <div className="ae-heat" role="table">
              <div role="row" className="ae-heat-h"><span>Schema</span><span>Read</span><span>Change</span><span>Own</span><span>Sensitive</span></div>
              {d.heat.map((h) => (
                <div role="row" key={h.schema}>
                  <span className="ae-mono">{h.schema}</span>
                  {(["read", "change", "own", "sensitive"] as const).map((k) => (
                    <button type="button" key={k} disabled={!h[k]} className={`ae-heat-c ${h[k] ? (k === "sensitive" ? "ae-sens-tag" : `ae-lvl-${k}`) : ""}${cell?.schema === h.schema && cell.min === k ? " on" : ""}`}
                      onClick={() => setCell(cell?.schema === h.schema && cell.min === k ? null : { schema: h.schema, min: k })}>{h[k] || "·"}</button>
                  ))}
                </div>
              ))}
            </div>
          ) : <EmptyState title="No data objects">Only names, runnable things or account powers.</EmptyState>}
        </Card>
        <Card title="Why they have it" sub={`${plural(d.roles, "role")} · deepest ${d.deepest}`}>
          <ul className="ae-why">
            {d.why.map((r) => (
              <li key={r.role}>
                <div><button type="button" className={`ae-pchip ae-pchip-${r.kind}`} onClick={() => o.open(r.role)}>{r.role}</button> <span className="ae-muted">{r.note}</span></div>
                {r.kids.length > 0 && <div className="ae-why-kids">{r.kids.map((k) => <button type="button" key={k} className="ae-pchip" onClick={() => o.open(k)}>{k}</button>)}</div>}
              </li>
            ))}
          </ul>
          {w.secondary_all && <p className="ae-note">Secondary roles are <b>ALL</b>, so every query uses all of these roles at once.</p>}
        </Card>
      </div>
      <Card title="Data they can access" sub="One row per object, at the most it allows. Riskiest first.">
        <ListToolbar search={q} onSearch={setQ} onCsv={() => save(w.name, shown)}>
          <FilterChips label="Filter by access" value={lvl} onPick={setLvl} items={[
            { key: "all", label: "All", count: data.length }, { key: "read", label: "Read only" }, { key: "change", label: "Can change" },
            { key: "own", label: "Owns" }, { key: "multi", label: "More than one way" }]} />
          <Toggle label={`Show ${n.usage} database/schema USAGE grants`} on={usage} onPick={setUsage} />
          <FilterChips label="Group by" value={group} onPick={(k) => setGroup(k as GroupBy)} items={[{ key: "none", label: "No groups" }, { key: "schema", label: "Schema" }, { key: "type", label: "Type" }]} />
          <FilterChips label="Sort" value={sort} onPick={setSort} items={[{ key: "risk", label: "Riskiest first" }, { key: "name", label: "Name" }]} />
          {cell && <button type="button" className="ae-chip ae-chip-plain" onClick={() => setCell(null)}>{cell.schema} · {cell.min} ×</button>}
        </ListToolbar>
        {!shown.length ? <EmptyState title="Nothing matches">Change the filter, or clear the search.</EmptyState> : (
          <div className="ae-olist" role="table">
            <div className="ae-orow ae-orow-h" role="row"><span>Object</span><span>Access</span><span>Sensitive columns</span><span>Granted through</span><span /></div>
            {groups.map((g) => (
              <Fragment key={g}>
                {g && <div className="ae-ogroup" role="row"><span className="ae-mono">{g}</span> <span className="ae-muted">{shown.filter((x) => groupKey(x, group) === g).length}</span></div>}
                {shown.filter((x) => !g || groupKey(x, group) === g).map((x) => {
                  const id = x.object + x.category;
                  const isOpen = open === id;
                  return (
                    <Fragment key={id}>
                      <div className="ae-orow" role="row">
                        <span className="ae-ocell">
                          <button type="button" className="ae-link ae-mono ae-oname" onClick={() => o.open(x.object)}>{x.label ?? x.object.split(".").pop()}</button>
                          <span className="ae-muted ae-osub">{x.type.toLowerCase()}{x.schema ? ` · ${x.database}.${x.schema}` : ""}</span>
                          {x.findings.length > 0 && <span className="ae-ochips">{x.findings.map((f) => <FindingChip key={f.num} {...f} onOpen={() => ruleLink(f.num)} />)}</span>}
                        </span>
                        <AccessPill level={x.level} privileges={x.privileges} />
                        <SensitiveCell sensitive={x.sensitive} columns={x.columns} />
                        <PathChips first={x.first} holder={x.holder} ways={x.ways} kinds={d.refs.kinds} onOpen={o.open} />
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
      </Card>
      <div className="ae-two" id="runs">
        <Card title="Things they can run" sub="Warehouses, tasks, functions and procedures: not on the ladder.">
          {runs.length ? <Items xs={runs} open={o.open} rule={ruleLink} /> : <EmptyState title="Nothing to run" />}
        </Card>
        <Card title="Powers over the account" sub="Account privileges, and CREATE or MODIFY on a database or schema.">
          {powers.length ? <Items xs={powers} open={o.open} rule={ruleLink} power /> : <EmptyState title="No account powers" />}
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
      <div className="ae-muted">Shortest path</div>
      <div className="ae-how-path">
        <span className="ae-pchip">{who}</span>
        {steps.map((s) => <Fragment key={s}><span className="ae-arrow" aria-hidden>→</span><span className="ae-pchip">{s}</span></Fragment>)}
        <span className="ae-arrow" aria-hidden>→</span><span className="ae-privs">{x.privileges.join(" · ")}</span>
        <span className="ae-arrow" aria-hidden>→</span><span className="ae-pchip ae-pchip-obj">{nameOf(x)}</span>
      </div>
      <p>{x.ways > 1 ? `${x.ways - 1} other way${x.ways === 2 ? "" : "s"} lead here too, so removing one role may not remove the access.` : "This is the only way in: removing any role on it removes the access."}
        {x.columns.length > 0 && ` ${x.columns.map((col) => `${col.column} is ${col.state} (${col.reason})`).join("; ")}.`}</p>
      <div className="ae-how-links">
        <button type="button" className="ae-link" onClick={() => c.nav("object", { name: x.object })}>Who else has access</button>
        <button type="button" className="ae-link" onClick={() => c.nav("check", { ...(user ? { name: who } : { role: who }), obj: x.object })}>See all {x.ways} path{x.ways === 1 ? "" : "s"}</button>
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
  const inner = { ...c, page: (user ? "user" : "role") as typeof c.page, params: { ...rest, name } };
  return (
    <div className="ae-embed">
      <AppCtx.Provider value={inner}>{user ? <UserPage /> : <RolePageView />}</AppCtx.Provider>
    </div>
  );
}
