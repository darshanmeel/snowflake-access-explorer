// Screen 2: who has access to a table (or any object), or to the admin roles (preset=admin). Overview (the object page's
// summary and graph) first; People by level, by path and users × privileges; Columns; Activity; History.
import { Fragment, useEffect, useState } from "react";
import { download as saveCsv, useApi } from "../api/client";
import type { ListItem, MatrixRow, ObjectPage, RulesPage, WhoEntry, WhoPage, WhoPerson, WhoRole, WhoState } from "../api/types";
import { Banner, Card, Chips, DataTable, EmptyState, FilterChips, GroupedGrantees, KpiRow, ListToolbar, MiniBar, NameList, PathChips, Tabs, Toggle, useCsv } from "../components";
import { apiParams, AppCtx, useApp, useOpen } from "../ctx";
import { BuiltinNote, col, Controls, CutBanner, GraphCard, Head, Load, NameLink, PathCell, pathCol, Pick, Risks, Sel, StateTag, Tog } from "./common";
import { ActivityTab, UseLine } from "./Activity";
import { ChangeFeed } from "./Changes";
import { remember } from "./Home";
import { PagedTable } from "./paged";
import { AdminTable } from "./Rules";
import { changeOfPath, WhatIfButton } from "./Whatif";
import { byLevel, NOTE, ORDER, sameLabel, stepsOf, TITLE } from "./who";
import { doOf, usedHow } from "./verdict";

const STATES: [WhoState, string][] = [["active", "Active"], ["dormant", "Dormant"], ["disabled", "Disabled"], ["service", "Service"]];
const STATUS: Record<string, string> = { active: "Active", dormant: "Dormant", never: "Never logged in", disabled: "Disabled" };
const ini = (n: string) => { const w = n.match(/[A-Z]+|[0-9]+/g) ?? [n]; return w[0][0] + (w[1] ? (/\d/.test(w[1]) ? w[1].slice(-1) : w[1][0]) : ""); };
const tagWord = (t: string) => (t.includes("SEMANTIC_CATEGORY") ? "" : t.split("=").pop());
const off = (x: WhoPerson) => x.status !== "active";
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const ago = (x: WhoPerson) => x.login.split(" · ").pop();

export function ObjectPageView() {
  const c = useApp();
  const admin = c.params.preset === "admin";
  // a big object sends the first people matching the search (wq), plus the person picked (as, sel)
  const s = useApi<WhoPage>("who", { view: c.view, builtin: c.params.builtin, ...(admin ? { preset: "admin" } : { name: c.params.name ?? "" }),
    q: c.params.wq, st: c.params.st, as: c.params.as, sel: c.params.sel });
  const id = s.data?.object.id ?? c.params.name ?? "";
  const types = useApi<{ items: ListItem[] }>("list", { what: "types", view: c.view, builtin: c.params.builtin });
  const type = c.params.type || undefined; // narrows the Object search only
  return (
    <>
      <div className="ae-headrow">
        <div className="ae-h1 ae-h1-pick">
          {admin ? "Who holds an admin role" : <>Who has access to
            <Sel label="Type" value={c.params.type ?? ""} onPick={(v) => c.set({ type: v || null })}
              options={[["", "Any type"], ...(types.data?.items ?? []).map((i): [string, string] => [i.id, i.id])]} />
            <Pick label="Object" value={id} width={360} what="objects" params={{ type }}
              onPick={(v) => c.nav("object", { name: v, ...(type && { type }), ...(c.params.builtin && { builtin: c.params.builtin }), ...(c.params.as && { as: c.params.as }), ...(c.params.show && { show: c.params.show }) })} /></>}
        </div>
      </div>
      <Load s={s}>{(d) => <Who d={d} />}</Load>
    </>
  );
}

function Who({ d }: { d: WhoPage }) {
  const c = useApp();
  const csvOn = useCsv();
  const o = d.object, admin = o.preset === "admin";
  useEffect(() => { if (o.id) remember({ page: "object", id: o.id, label: o.id }); }, [o.id]);
  const [all, setAll] = useState(false);
  const sh = c.params.show, pp = c.params.part;
  const cols = !admin && (d.columns.length > 0 || o.sensitive);
  // old links: show=who is People by level; part=users|who (People) and sens|sees (Columns) without a show
  const show = sh === "who" || sh === "people" ? "people" : sh === "columns" && cols ? "columns"
    : (sh === "history" || sh === "activity") && !admin ? sh
    : !sh && !admin && (pp === "users" || pp === "who") ? "people" : !sh && cols && (pp === "sens" || pp === "sees") ? "columns" : "detail";
  const part = show === "people" ? (!admin && (pp === "who" || pp === "users") ? pp : "level") : show === "columns" ? (pp === "sees" ? "sees" : "sens") : "summary";
  const save = () => saveCsv("who.csv", { view: c.view, builtin: c.params.builtin, ...(admin ? { preset: "admin" } : { name: o.id }) }, `${o.id ?? "admin_roles"}_who.csv`);
  const tags = [
    <span key="type" className="ae-otag">{o.type.toLowerCase()}</span>,
    o.owners.length > 0 ? <span key="own" className="ae-otag">Owner {o.owners.join(", ")}</span>
      : o.owner_note && <span key="own" className="ae-otag ae-otag-warn">{o.owner_note[0].toUpperCase() + o.owner_note.slice(1)}</span>,
    o.columns > 0 && <span key="sens" className="ae-otag ae-sens-tag">Sensitive · {plural(o.columns, "column")}</span>,
    o.sensitive && !o.columns && <span key="sens" className="ae-otag ae-sens-tag">Sensitive</span>,
    ...o.tags.map((t) => <span key={`t${t}`} className="ae-otag">{t}</span>),
    o.masking.length > 0 && <span key="mask" className="ae-otag" title={o.masking.join(", ")}>{o.masking.length} masking polic{o.masking.length === 1 ? "y" : "ies"}</span>,
    ...o.row_policies.map((p) => <span key={`r${p}`} className="ae-otag">Row policy {p.split(".").pop()}</span>),
  ].filter(Boolean);
  const lvl2 = (tabs: { key: string; label: string; count?: number }[], first: string) => // counts only the who page knows: none that come later
    <Tabs nav={2} active={part} onChange={(k) => c.set({ show, part: k === first ? null : k })} tabs={tabs} />;
  return (
    <>
      <div className="ae-objhead">
        <div>
          {o.database && <div className="ae-muted ae-crumb">{[o.database, o.schema].filter(Boolean).join(" › ")} ›</div>}
          {!admin && <div className="ae-mono ae-objname">{o.name}</div>}
          <div className="ae-objtags">
            {tags.length > 3 ? <>{all ? tags : tags.slice(0, 3)}<button type="button" className="ae-otag" onClick={() => setAll(!all)}>{all ? "show less" : `+${tags.length - 3} more`}</button></> : tags}
          </div>
        </div>
        {csvOn && <button type="button" className="ae-btn" onClick={save}>Export CSV</button>}
      </div>
      <BuiltinNote b={d.builtin} />
      <Risks list={d.risks} />
      {d.app && <AppNote app={d.app} />}
      <Tabs nav active={show} onChange={(k) => c.set({ show: k === "detail" ? null : k, part: null })} tabs={[
        { key: "detail", label: admin ? "Admin holders table" : "Overview" },
        { key: "people", label: "People", count: d.counts.people },
        ...(cols ? [{ key: "columns", label: "Columns" }] : []),
        ...(admin ? [] : [{ key: "activity", label: "Activity" }, { key: "history", label: "History" }]),
      ]} />
      {show === "detail" && (admin ? <AdminDetail /> : <Detail id={o.id ?? ""} part="summary" />)}
      {show === "people" && <>
        {!admin && lvl2([{ key: "level", label: "By level", count: d.counts.people }, { key: "who", label: "By path" }, { key: "users", label: "Users × privileges" }], "level")}
        {part === "level" ? <><For d={d} /><List d={d} /><UsedNoGrant d={d} /></> : <Detail id={o.id ?? ""} part={part} />}
      </>}
      {show === "columns" && <>
        {lvl2([{ key: "sens", label: "Sensitivity" }, ...(d.by_role ? [{ key: "sees", label: "By role" }] : [])], "sens")}
        {part === "sens" && d.columns.length > 0 && <ColumnsCard d={d} />}
        <Detail id={o.id ?? ""} part={part} />
      </>}
      {show === "activity" && <ActivityTab what="object" name={o.id ?? ""} user={c.params.as} />}
      {show === "history" && <ChangeFeed subject={o.id ?? ""} />}
    </>
  );
}

/** A Streamlit app runs with its owner's rights: say whose data its viewers see, and who sees more than they may. */
function AppNote({ app }: { app: NonNullable<WhoPage["app"]> }) {
  const c = useApp();
  const sens = Object.entries(app.sensitive);
  const out = Object.entries(app.exposed);
  const viewers = new Set(Object.values(app.holders).flat()).size;
  return (
    <Banner tone={out.length ? "bad" : "info"} title={`Viewers see the data of its owner role ${app.owner.join(", ")}, not their own`}>
      <button type="button" className="ae-link" onClick={() => c.set({ show: "activity" })}>Who opened it →</button>
      <details><summary>Why</summary><ul>{[
      `${viewers === 1 ? "1 person" : `${viewers} people`} can open it, through ${Object.keys(app.holders).join(", ") || "no role"}.`,
      sens.length ? `The owner reads sensitive ${sens.map(([o, cs]) => `${o}${cs.length ? ` (${cs.join(", ")})` : ""}`).join(", ")}.` : "The owner reads no sensitive data.",
      ...(out.length ? [<>{out.length === 1 ? "1 person" : `${out.length} people`} can see it here but can't read it themselves:
        <NameList items={out.map(([u, os]) => ({ key: u, n: os.length === 1 ? os[0] : `${os.length} objects` }))} onOpen={(u) => c.nav("access", { user: u })} /></>] : []),
      "An app that queries with a caller's rights connection shows each viewer only their own data; the grants can't tell which one it uses.",
      ].map((l, i) => <li key={i}>{l}</li>)}</ul></details>
    </Banner>
  );
}

/** "Access for [person]": defaults to the signed-in user (the demo user on shared data). */
function For({ d }: { d: WhoPage }) {
  const c = useApp();
  const who = c.params.as ?? d.default_user ?? ""; // shared: empty until a person is picked
  const x = d.people.find((p) => p.name === who);
  const clear = x?.columns.filter((k) => k.state !== "masked").map((k) => k.column) ?? [];
  const masked = x?.columns.filter((k) => k.state === "masked").map((k) => k.column) ?? [];
  return (
    <section className="ae-forstrip" aria-label="Access for one person">
      <Pick label="Access for" value={who} width={200} what="users" onPick={(v) => c.set({ as: v })} />
      {!x ? <span className="ae-muted">{who ? `${who} has no access here.` : "Pick a person to see their access here."}</span> : <>
        <span className={`ae-lvl ae-lvl-${x.level}`}>{TITLE[x.level]}</span>
        {x.blocked && <span className="ae-blocked">blocked: {x.blocked}</span>}
        <span className="ae-privs">{x.privileges.join(" · ") || `through ${x.admin.join(", ")}`}</span>
        <span className="ae-muted">via</span><PathChips first={x.first} holder={x.holder} ways={x.ways} kinds={d.refs.kinds} />
        {x.columns.length > 0 && (
          <span className="ae-sens-word">
            {clear.length > 0 && `Sees ${clear.join(", ")} unmasked`}{clear.length > 0 && masked.length > 0 && " · "}{masked.length > 0 && `${masked.join(", ")} masked`}
          </span>
        )}
        <button type="button" className="ae-link" onClick={() => c.set({ show: "people", part: null, sel: x.name, by: null })}>How?</button>
      </>}
      {who && d.object.id && <UseLine name={d.object.id} user={who} />}
    </section>
  );
}

/** Used in the activity window though no grant reaches them: apart from the people and their counts. */
function UsedNoGrant({ d }: { d: WhoPage }) {
  const c = useApp();
  const u = d.used;
  if (!u?.rows.length) return null;
  const inside = d.object.type === "DATABASE" || d.object.type === "SCHEMA";
  type R = (typeof u.rows)[number];
  return (
    <Card title="Used it, no grant found" sub={`${plural(u.users, "user")} in ${u.days} days, not counted as having access${u.total > u.rows.length ? ` · first ${u.rows.length} of ${u.total} rows` : ""}`}>
      <DataTable csv="used_no_grant.csv" rows={u.rows} columns={[
        col("u", "User", (r: R) => r.user, { wrap: "nowrap", render: (r: R) => (
          <button type="button" className="ae-link ae-mono" title="Their use of it" onClick={() => c.set({ show: "activity", as: r.user, part: null })}>{r.user}</button>) }),
        col("h", "How", (r: R) => usedHow(r), { wrap: "wrap" }),
        col("q", "Queries", (r: R) => r.queries, { num: true }),
        ...(inside ? [col("o", "Objects", (r: R) => r.objects, { num: true })] : []),
        col("l", "Last", (r: R) => r.last, { wrap: "nowrap" })]} />
    </Card>
  );
}

function List({ d }: { d: WhoPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const n = d.counts;
  const roles = c.params.by === "roles";
  const same = c.params.same ? c.params.same === "1" : d.object.type === "WAREHOUSE";
  const [q, setQ] = useState(c.params.wq ?? "");
  useEffect(() => { // the server searches every person; a moment after the last key
    const t = setTimeout(() => { if (q !== (c.params.wq ?? "")) c.set({ wq: q || null }); }, 300);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const hit = (name: string) => !q || name.toLowerCase().includes(q.toLowerCase());
  const rows: WhoEntry[] = roles ? d.roles : d.people;
  const sel = rows.find((x) => x.name === c.params.sel) ?? rows[0];
  const pick = (name: string) => c.set({ sel: name });
  const lv = ORDER.filter((l) => n.levels[l]);
  return (
    <div className="ae-whogrid">
      <Card title="Who has access" sub={`${n.people} people · ${n.roles} roles`}
        right={<FilterChips label="Show" value={roles ? "roles" : "people"} onPick={(k) => c.set({ by: k === "roles" ? k : null, sel: null })}
          items={[{ key: "people", label: "People", count: n.people }, { key: "roles", label: "Roles", count: n.roles }]} />}>
        {n.people > 0 && <>
          <div className="ae-bar" role="img" aria-label={lv.map((l) => `${n.levels[l]} ${TITLE[l]}`).join(", ")}>
            {lv.map((l) => <span key={l} className={`ae-bar-lvl-${l}`} style={{ width: `${(100 * n.levels[l]) / n.people}%` }} />)}
            {n.blocked > 0 && <span className="ae-bar-blocked" style={{ width: `${(100 * n.blocked) / n.people}%` }} />}
          </div>
          <div className="ae-bar-legend">
            {lv.map((l) => <span key={l}><span className={`ae-dot2 ae-lvl-${l}`} />{TITLE[l]} {n.levels[l]}</span>)}
            {n.blocked > 0 && <span className="ae-blocked" title="The privilege is there, but not USAGE on the database or schema: Snowflake refuses it">Blocked {n.blocked}: no USAGE on the database or schema</span>}
          </div>
        </>}
        {!roles && n.people > 0 && <FilterChips label="People" value={d.st} onPick={(k) => c.set({ st: k || null, sel: null })}
          items={[{ key: "", label: "Everyone", count: n.people }, ...STATES.filter(([k]) => n.states[k]).map(([key, label]) => ({ key, label, count: n.states[key] ?? 0 }))]} />}
        <ListToolbar search={q} onSearch={setQ}>
          {!roles && <Toggle label="Group people with the same path" on={same} onPick={(v) => c.set({ same: v ? "1" : "0" })} />}
        </ListToolbar>
        {!rows.length ? <EmptyState title="Nobody">No user or role reaches this object (admin roles aside).</EmptyState>
          : !roles && same ? (
            <div className="ae-wholist">
              {d.groups.filter((g) => g.names.some(hit)).map((g) => {
                const x = d.people.find((p) => p.name === g.names[0]);
                if (!x) return null;
                return (
                  <button type="button" key={g.names.join()} className={`ae-whorow${sel && g.names.includes(sel.name) ? " on" : ""}`} onClick={() => pick(g.names[0])}>
                    <span className="ae-avatar ae-avatar-s" aria-hidden>{g.names.length > 1 ? g.names.length : ini(g.names[0])}</span>
                    <span className="ae-whoname"><span className="ae-mono">{sameLabel(g.names, g.route)}</span>
                      {g.names.length > 1 ? <span className="ae-muted"><NameList items={g.names} max={3} plain /></span> : <span className="ae-muted">{`${STATUS[x.status]} · last login ${ago(x)}`}</span>}</span>
                    <span className={`ae-lvl ae-lvl-${g.level}`}>{TITLE[g.level]}</span>
                    <span className="ae-privs">{g.blocked && <span className="ae-blocked">blocked: {g.blocked} · </span>}{g.privileges.join(" · ") || "All privileges"}</span>
                    <span />
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="ae-wholist">
              {byLevel(rows.filter((x) => hit(x.name))).map((g) => (
                <Fragment key={g.level}>
                  <div className="ae-whogroup"><span className={`ae-lvl ae-lvl-${g.level}`}>{TITLE[g.level]}</span><span className="ae-muted">{NOTE[g.level]}</span></div>
                  {g.rows.map((x) => {
                    const p = x as WhoPerson, r = x as WhoRole, dim = !roles && off(p);
                    return (
                      <button type="button" key={x.name} className={`ae-whorow${sel?.name === x.name ? " on" : ""}${dim ? " ae-whorow-off" : ""}`} onClick={() => pick(x.name)}>
                        <span className={`ae-avatar ae-avatar-s${dim ? " ae-avatar-off" : ""}`} aria-hidden>{ini(x.name)}</span>
                        <span className="ae-whoname"><span className="ae-mono">{x.name}</span>
                          <span className="ae-muted">{roles ? `${r.kind.replace("_", " ")} · ${plural(r.users, "user")}` : `${STATUS[p.status]}${p.service ? " · service" : ""} · last login ${ago(p)}`}</span></span>
                        <PathChips first={x.first} holder={x.holder} ways={1} kinds={d.refs.kinds} />
                        <span className="ae-privs">{x.blocked && <span className="ae-blocked">blocked: {x.blocked} · </span>}{x.privileges.join(" · ") || "All privileges"}</span>
                        <span className="ae-muted ae-whoways">{plural(x.ways, "path")}</span>
                      </button>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          )}
        {(d.shown.people > d.people.length || d.shown.roles > d.roles.length || d.shown.groups > d.groups.length) &&
          <p className="ae-muted">First {roles ? d.roles.length : same ? d.groups.length : d.people.length} of {roles ? d.shown.roles : same ? d.shown.groups : d.shown.people}, the most access first: search to find the rest.</p>}
      </Card>
      <aside className="ae-whoside">
        {sel && <How e={sel} d={d} role={roles} onOpen={o.open} />}
      </aside>
    </div>
  );
}

/** Each sensitive column: how many readers see it in the clear, and its masking policies. */
function ColumnsCard({ d }: { d: WhoPage }) {
  return (
    <Card title="Who sees each column in the clear">
      <ul className="ae-whocols">
        {d.columns.map((k) => (
          <li key={k.column}>
            <div><div className="ae-mono">{k.column}</div><div className="ae-muted">{k.tags.map(tagWord).filter(Boolean).join(", ") || (k.sensitive ? "sensitive" : "")}</div></div>
            <div className="ae-whocols-r">
              <MiniBar of={Math.max(1, k.clear.length + k.masked.length + k.unknown.length)} text={<span className={k.clear.length ? "ae-sens-word" : ""} title={k.clear.join(", ")}>{k.clear.length} of {k.clear.length + k.masked.length + k.unknown.length} see it</span>}
                parts={[{ key: "c", label: "See it in the clear", value: k.clear.length, cls: "high" }, { key: "m", label: "Masked", value: k.masked.length, cls: "keep" }, { key: "u", label: "Unknown", value: k.unknown.length, cls: "low" }]} />
              <div className="ae-muted">{k.policies.length ? `${k.policies.map((x) => x.split(".").pop()).join(", ")}${k.masked.length ? ` · masked for ${k.masked.length}` : ""}` : "No masking policy"}</div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function How({ e, d, role, onOpen }: { e: WhoEntry; d: WhoPage; role: boolean; onOpen: (id: string) => void }) {
  const c = useApp();
  const p = e as WhoPerson;
  const gone = !role && p.status === "disabled";
  const steps = stepsOf(e, d.refs.kinds, gone);
  const ch = changeOfPath(e.path, d.refs.kinds);
  const sum = gone ? "Disabled, but the grants are still there"
    : e.blocked ? `Blocked: ${e.blocked}, so Snowflake refuses the ${e.privileges.join(", ")}`
    : e.level === "admin" && !e.privileges.length ? "Through the roles granted to an admin role" : `${TITLE[e.level]}, ${plural(steps.length - 1, "step")} away`;
  return (
    <Card title={`How ${e.name} gets in`} sub={sum}>
      <ol className="ae-steps">
        {steps.map((s, i) => (
          <li key={i}>
            <span className={`ae-stepdot${i === 0 ? " first" : i === steps.length - 1 ? " last" : ""}`} aria-hidden />
            <div><button type="button" className="ae-link ae-mono" onClick={() => onOpen(e.path[i])}>{s.name}</button><div className="ae-muted">{s.kind}</div></div>
          </li>
        ))}
      </ol>
      {e.ways > 1 && <p className="ae-muted">{plural(e.ways, "way")} lead here, so removing one role may not remove the access.</p>}
      <div className="ae-how-links">
        {d.object.id && <button type="button" className="ae-btn ae-btn-s" onClick={() => c.nav("check", { [role ? "role" : "name"]: e.name, obj: d.object.id!, ...doOf(e.level) })}>Open in Can they?</button>}
        {role && <button type="button" className="ae-link" onClick={() => c.nav("access", { role: e.name })}>Open the role</button>}
        {ch && <WhatIfButton ch={[ch]} />}
      </div>
    </Card>
  );
}

/** One part of the object page (ObjectDetail) for the same object, inside this screen. */
function Detail({ id, part }: { id: string; part: string }) {
  const c = useApp();
  const { show: _s, as: _a, sel: _l, by: _b, same: _m, part: _p, ...rest } = c.params;
  return (
    <div className="ae-embed">
      <AppCtx.Provider value={{ ...c, params: { ...rest, name: id } }}><ObjectDetail part={part} /></AppCtx.Provider>
    </div>
  );
}

const unuser = (u: string) => u.replace(/ \(user\)$/, "");

/** One admin role in the banner: its users counted, the first 3 named; the paths open on demand. */
function AdminRoleLine({ g, refs }: { g: ObjectPage["admin_roles"][number]; refs: ObjectPage["refs"] }) {
  const rest = g.users - g.first.length;
  return (
    <span className="ae-adm-role">
      <span className="ae-pchip ae-pchip-admin">{g.role}</span>
      <span>{plural(g.users, "user")}</span>
      <span className="ae-adm-users">{g.first.map((u) => <NameLink key={u} id={u} refs={refs} label={unuser(u)} />)}</span>
      <details>
        <summary className="ae-link">{rest > 0 ? `+${rest} more · ` : ""}Show {plural(g.total, "path")}</summary>
        {g.paths.map((p, i) => <span key={i} className="ae-fd-path"><PathCell path={p} refs={refs} /><WhatIfButton ch={[{ op: "revoke_role_from_user", role: p[1], user: unuser(p[0]) }]} /></span>)}
        {g.total > g.paths.length && <p className="ae-muted">First {g.paths.length} of {g.total} paths.</p>}
      </details>
    </span>
  );
}

/** Admin preset: the Risks & fixes "Admin holders" table (admin roles and account privileges). */
function AdminDetail() {
  const c = useApp();
  const s = useApi<RulesPage>("rules", { view: c.view, builtin: c.params.builtin });
  return <Load s={s}>{(r) => <Card title="People with admin roles or account privileges" scroll><AdminTable admins={r.admins} refs={r.refs} /></Card>}</Load>;
}

type AdminRow = { admin: string[]; unknown: string[]; real: boolean; cells: Record<string, { has: boolean; admin: string | null }> };

/** Users × privileges, Admin column: the admin roles held; "all, via X" when nothing else shows what they give here. */
export const adminText = (r: AdminRow) =>
  !Object.values(r.cells).some((x) => x.has) && r.unknown.length ? `all, via ${r.unknown.join(", ")}` : r.admin.join(", ");

export const adminTitle = (r: AdminRow) =>
  adminText(r).startsWith("all") ? `${r.unknown.join(", ")}: no role link or grant of it is in the snapshot, so which privileges it gives here is not known; an admin role may hold every role`
    : Object.values(r.cells).some((x) => x.admin) ? `Admin role: cells marked "admin" come through ${r.admin.join(", ")} and the roles it holds`
    : `Holds ${r.admin.join(", ")}${r.real ? "" : "; no role it holds reaches this object"}`;

/** One part of the object page as a tab of screen 2: summary (Overview: counts, owner, graph of the paths in), who
 * (By path), users (Users × privileges), sees (By role), sens (Sensitivity). */
export function ObjectDetail({ part }: { part: string }) {
  const c = useApp();
  const name = c.params.name ?? "";
  const [tab, setTab] = useState("all");
  // no name: the server picks the first object of the type (as app.py)
  const s = useApi<ObjectPage>("object", { ...apiParams(c), name });
  const op = useOpen(s.data?.refs);
  return (
    <>
      <Head title="Object" sub="Who can reach a table, view or other object, and how." />
      {(part === "summary" || part === "users") && <Controls>
        <Tog label="Active users only" on={c.params.active === "1"} onPick={(v) => c.set({ active: v ? "1" : null })} />
        <Tog label="Users only" on={c.params.users === "1"} onPick={(v) => c.set({ users: v ? "1" : null })} />
        {s.data && <Sel label="Privilege" value={c.params.priv ?? ""} onPick={(v) => c.set({ priv: v })}
          options={[["", "Any"], ...s.data.object.privileges.map((p): [string, string] => [p, p])]} />}
      </Controls>}
      <Load s={s}>{(d) => {
        const o = d.object, k = d.kpis;
        return (
          <>
            {part === "summary" && <>  {/* the counts, owner, admin reach and paths diagram; the other parts are tables */}
              <Card>
                <KpiRow items={[
                  { label: "Users with access", value: k.people + k.disabled + k.service + k.admin, caption: `${k.people} people · ${k.disabled} disabled · ${k.service} service · ${k.admin} only through an admin role`, tone: k.admin ? "bad" : null },
                  { label: "Read / Write / Own", value: `${k.read} / ${k.write} / ${k.own}` },
                  { label: "Roles on the way", value: k.roles, caption: `${k.direct} direct holders` },
                  { label: "Longest chain", value: k.longest },
                ]} />
                {k.owners.length > 0 && <p>Owner: <Chips items={k.owners.map((r) => ({ id: r, kind: "technical" }))} /></p>}
                {k.owner_note && <p className="ae-muted">{k.owner_note}</p>}
                {k.deployers.length > 0 && <p>Deployed by: <Chips items={k.deployers.map((r) => ({ id: r, kind: "user" }))} /></p>}
              </Card>
              {d.admin_roles.length > 0 && <Banner tone="bad" title={`Admin roles reach this object: ${d.admin_users} user(s)`} lines={d.admin_roles.slice(0, 3).map((g) => <AdminRoleLine key={g.role} g={g} refs={d.refs} />)}>
                {d.admin_roles.length > 3 && <button type="button" className="ae-link" onClick={() => c.nav("object", { preset: "admin" })}>Every path: Who holds an admin role</button>}
              </Banner>}
              <CutBanner capped={d.capped} />
              <GraphCard g={d.graph} refs={d.refs} />
            </>}
            {part === "sens" && d.sensitivity && (
              <Card title="Sensitivity" sub={`${d.sensitivity.readers.people} people can read it (${d.sensitivity.readers.admin} admin, ${d.sensitivity.readers.service} service)`}>
                <Chips items={d.sensitivity.object_tags.map((t) => ({ id: t.label, title: t.origin, tone: t.sensitive ? "bad" : null }))} />
                {d.sensitivity.row_policies.map((p) => (
                  <p key={p.name}><strong>Row policy {p.name}</strong> on {p.args}: <code>{p.text}</code>{!p.from_text && <span className="ae-muted"> (condition unknown)</span>}</p>
                ))}
                {d.sensitivity.columns.length > 0 && (
                  <DataTable csv={`${o.name}_columns.csv`} rows={d.sensitivity.columns} maxHeight={320}
                    columns={[col("c", "Column", (r: any) => r.column),
                      col("t", "Tags", (r: any) => r.tags.map((t: any) => t.label).join(", "), { wrap: "wrap" }),
                      col("m", "Masking", (r: any) => (r.masking.length ? r.masking.join(", ") : "Not protected: no masking policy"), { wrap: "wrap",
                        render: (r: any) => (r.masking.length ? r.masking.join(", ") : <span className="ae-bad">Not protected: no masking policy</span>) }),
                      col("e", "Clear for", (r: any) => (r.unmasked_everyone ? "everyone" : r.clear_known ? r.clear_for.map((x: any) => x.role).join(", ") : "unknown"), { wrap: "wrap" })]} />
                )}
                {Object.entries(d.sensitivity.policy_text).map(([n, t]) => <details key={n}><summary>{n}</summary><pre className="ae-code">{t}</pre></details>)}
              </Card>
            )}
            {part === "users" && <Card title="Users" sub="Every user, with what they can do here" scroll
              right={c.view === "shared" && <button type="button" className="ae-btn" onClick={() => c.nav("review", { show: "grid", object: o.id, columns: "privileges" })}>Review people × privileges</button>}>
              <PagedTable path="object" at="m_offset" total={d.matrix.total} offset={d.matrix.offset} pick={(x: ObjectPage) => x.matrix.rows}
                csv={`${o.name}_users.csv`} rows={d.matrix.rows}
                columns={[
                  col("u", "User", (r: MatrixRow) => r.user, { render: (r: MatrixRow) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("t", "Type", (r: MatrixRow) => r.type),
                  col("s", "Status", (r: MatrixRow) => r.status, { render: (r: MatrixRow) => (r.flags.status ? <span className="ae-bad" title={r.flags.status}>{r.status}</span> : r.status) }),
                  col("adm", "Admin", (r: MatrixRow) => adminText(r), { render: (r: MatrixRow) => (r.admin.length ? <span className="ae-bad" title={adminTitle(r)}>{adminText(r)}</span> : null), wrap: "nowrap" }),
                  ...d.matrix.privs.map((p) => col(p, p, (r: MatrixRow) => (r.cells[p]?.has ? 1 : 0),
                    { render: (r: MatrixRow) => { const x = r.cells[p], why = r.flags[p];
                      return x?.has ? <span className={why ? "ae-bad" : undefined} title={why ? `${why}. ${x.title}` : x.title}>{x.owner ? "owner" : `D${x.depth ?? ""}`}{x.admin && " admin"}</span> : null; } })),
                  ...d.matrix.sensitive_cols.map((cn) => col(`c_${cn}`, cn, (r: MatrixRow) => r.seen[cn]?.state ?? "",
                    { render: (r: MatrixRow) => (r.seen[cn] ? StateTag(r.seen[cn]) : null) })),
                  ...(d.matrix.row_policy ? [col("rows", "Rows", (r: MatrixRow) => r.rows_state?.state ?? "", { render: (r: MatrixRow) => (r.rows_state ? StateTag(r.rows_state) : null) })] : []),
                  col("d", "Depth", (r: MatrixRow) => r.depth ?? "", { num: true }), col("n", "Paths", (r: MatrixRow) => r.paths, { num: true }),
                  pathCol<MatrixRow>(d.refs, "Shortest path"),
                ]} />
            </Card>}
            {part === "sees" && d.sees && (
              <Card title="What each role sees" sub="Columns clear or masked, rows all or filtered, per role that can read the object" scroll>
                <DataTable csv={`${o.name}_role_view.csv`} rows={d.sees.rows}
                  columns={[col("r", "Role", (r: any) => r.role, { render: (r: any) => <NameLink id={r.role} refs={d.refs} /> }),
                    ...(d.sees.row_policy ? [col("rows", "Rows", (r: any) => r.rows.state, { render: (r: any) => StateTag(r.rows) })] : []),
                    ...d.sees.cols.map((cn) => col(cn, cn, (r: any) => r.columns.find((x: any) => x.column === cn)?.state ?? "",
                      { render: (r: any) => { const x = r.columns.find((y: any) => y.column === cn); return x ? StateTag(x) : null; } }))]} />
              </Card>
            )}
            {part === "who" && (
              <Card title="By path" sub="Users and roles that come in through the same chain are one row" right={
                <FilterChips label="Show" value={tab} onPick={setTab} items={d.tabs.map((t) => ({ key: t.key, label: t.label, count: t.count }))} />}>
                <GroupedGrantees key={tab} params={{ ...apiParams(c), name: o.id, tab }} total={d.tabs.find((t) => t.key === tab)?.count ?? 0}
                  kinds={d.refs.kinds} onOpen={op.open} csv={`${o.name}_grantees_${tab}.csv`} />
              </Card>
            )}
          </>
        );
      }}</Load>
    </>
  );
}
