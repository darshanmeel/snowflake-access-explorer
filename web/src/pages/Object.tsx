// Screen 2: who has access to a table (or any object), or to the admin roles (preset=admin). The old Object page
// (graph, by path / by user or role, users × privileges) is the default tab; the new list by level is next to it.
import { Fragment, useEffect, useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, MatrixRow, ObjectPage, RulesPage, WhoEntry, WhoPage, WhoPerson, WhoRole } from "../api/types";
import { Banner, Card, Chips, DataTable, EmptyState, FilterChips, GroupedGrantees, KpiRow, ListToolbar, MiniBar, PathChips, Tabs, Toggle, toCsv } from "../components";
import { download } from "../components/table";
import { apiParams, AppCtx, useApp, useOpen } from "../ctx";
import { col, Controls, GraphCard, Head, Load, NameLink, PathCell, pathCol, Pick, Sel, StateTag, Tog } from "./common";
import { ActivityTab, UseLine } from "./Activity";
import { ChangeFeed } from "./Changes";
import { remember } from "./Home";
import { AdminTable } from "./Rules";
import { changeOfPath, WhatIfButton } from "./Whatif";
import { byLevel, NOTE, ORDER, sameLabel, stepsOf, TITLE } from "./who";

const STATUS: Record<string, string> = { active: "Active", dormant: "Dormant", never: "Never logged in", disabled: "Disabled" };
const ini = (n: string) => { const w = n.match(/[A-Z]+|[0-9]+/g) ?? [n]; return w[0][0] + (w[1] ? (/\d/.test(w[1]) ? w[1].slice(-1) : w[1][0]) : ""); };
const tagWord = (t: string) => (t.includes("SEMANTIC_CATEGORY") ? "" : t.split("=").pop());
const off = (x: WhoPerson) => x.status !== "active";
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const ago = (x: WhoPerson) => x.login.split(" · ").pop();

export function ObjectPageView() {
  const c = useApp();
  const admin = c.params.preset === "admin";
  const s = useApi<WhoPage>("who", { view: c.view, ...(admin ? { preset: "admin" } : { name: c.params.name ?? "" }) });
  const id = s.data?.object.id ?? c.params.name ?? "";
  return (
    <>
      <div className="ae-headrow">
        <div className="ae-h1 ae-h1-pick">
          {admin ? "Who holds an admin role" : <>Who has access to <Pick label="Object" value={id} width={360} what="objects" onPick={(v) => c.nav("object", { name: v })} /></>}
        </div>
      </div>
      <Load s={s}>{(d) => <Who d={d} />}</Load>
    </>
  );
}

function Who({ d }: { d: WhoPage }) {
  const c = useApp();
  const o = d.object, admin = o.preset === "admin";
  useEffect(() => { if (o.id) remember({ page: "object", id: o.id, label: o.id }); }, [o.id]);
  const show = c.params.show === "who" || ((c.params.show === "history" || c.params.show === "activity") && !admin) ? c.params.show : "detail";
  const save = () => download(`${o.id ?? "admin_roles"}_who.csv`, toCsv(["User", "Status", "Last login", "Access", "Privileges", "Path", "Ways"],
    d.people.map((x) => [x.name, x.status, x.login, TITLE[x.level], x.privileges.join(" "), x.path.join(" > "), String(x.ways)])));
  return (
    <>
      <div className="ae-objhead">
        <div>
          {o.database && <div className="ae-muted ae-crumb">{[o.database, o.schema].filter(Boolean).join(" › ")} ›</div>}
          {!admin && <div className="ae-mono ae-objname">{o.name}</div>}
          <div className="ae-objtags">
            <span className="ae-otag">{o.type.toLowerCase()}</span>
            {o.columns > 0 && <span className="ae-otag ae-sens-tag">Sensitive · {plural(o.columns, "column")}</span>}
            {o.sensitive && !o.columns && <span className="ae-otag ae-sens-tag">Sensitive</span>}
            {o.tags.map((t) => <span key={t} className="ae-otag">{t}</span>)}
            {o.masking.length > 0 && <span className="ae-otag" title={o.masking.join(", ")}>{o.masking.length} masking polic{o.masking.length === 1 ? "y" : "ies"}</span>}
            {o.row_policies.map((p) => <span key={p} className="ae-otag">Row policy {p.split(".").pop()}</span>)}
            {o.owners.length > 0 ? <span className="ae-otag">Owner {o.owners.join(", ")}</span>
              : o.owner_note && <span className="ae-otag ae-otag-warn">{o.owner_note[0].toUpperCase() + o.owner_note.slice(1)}</span>}
          </div>
        </div>
        <button type="button" className="ae-btn" onClick={save}>Export CSV</button>
      </div>
      <For d={d} />
      <Tabs active={show} onChange={(k) => c.set({ show: k === "detail" ? null : k })} tabs={[
        { key: "detail", label: admin ? "Admin holders table" : "Diagram, paths & users" },
        { key: "who", label: "Who has access", count: d.counts.people },
        ...(admin ? [] : [{ key: "activity", label: "Activity" }, { key: "history", label: "History" }]),
      ]} />
      {show === "detail" && (admin ? <AdminDetail /> : <Detail id={o.id ?? ""} />)}
      {show === "who" && <List d={d} />}
      {show === "activity" && <ActivityTab what="object" name={o.id ?? ""} user={c.params.as} />}
      {show === "history" && <ChangeFeed subject={o.id ?? ""} />}
    </>
  );
}

/** "Access for [person]": defaults to the signed-in user (the demo user on shared data). */
function For({ d }: { d: WhoPage }) {
  const c = useApp();
  const who = c.params.as ?? d.default_user ?? "";
  const x = d.people.find((p) => p.name === who);
  const clear = x?.columns.filter((k) => k.state !== "masked").map((k) => k.column) ?? [];
  const masked = x?.columns.filter((k) => k.state === "masked").map((k) => k.column) ?? [];
  return (
    <section className="ae-forstrip" aria-label="Access for one person">
      <Pick label="Access for" value={who} width={200} what="users" onPick={(v) => c.set({ as: v })} />
      {!x ? <span className="ae-muted">{who ? `${who} has no access here.` : ""}</span> : <>
        <span className={`ae-lvl ae-lvl-${x.level}`}>{TITLE[x.level]}</span>
        <span className="ae-privs">{x.privileges.join(" · ") || `through ${x.admin.join(", ")}`}</span>
        <span className="ae-muted">via</span><PathChips first={x.first} holder={x.holder} ways={x.ways} kinds={d.refs.kinds} />
        {x.columns.length > 0 && (
          <span className="ae-sens-word">
            {clear.length > 0 && `Sees ${clear.join(", ")} unmasked`}{clear.length > 0 && masked.length > 0 && " · "}{masked.length > 0 && `${masked.join(", ")} masked`}
          </span>
        )}
        <button type="button" className="ae-link" onClick={() => c.set({ show: "who", sel: x.name, by: null })}>How?</button>
      </>}
      {who && d.object.id && <UseLine name={d.object.id} user={who} />}
    </section>
  );
}

function List({ d }: { d: WhoPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const n = d.counts;
  const roles = c.params.by === "roles";
  const same = c.params.same ? c.params.same === "1" : d.object.type === "WAREHOUSE";
  const [q, setQ] = useState("");
  const hit = (name: string) => !q || name.toLowerCase().includes(q.toLowerCase());
  const rows: WhoEntry[] = roles ? d.roles : d.people;
  const sel = rows.find((x) => x.name === c.params.sel) ?? rows[0];
  const pick = (name: string) => c.set({ sel: name });
  const lv = ORDER.filter((l) => n.levels[l]);
  return (
    <div className="ae-whogrid">
      <Card title="Who has access" sub={`${n.people} ${n.people === 1 ? "person" : "people"} · ${plural(n.roles, "role")} in between · grouped by the most each can do`}
        right={<FilterChips label="Show" value={roles ? "roles" : "people"} onPick={(k) => c.set({ by: k === "roles" ? k : null, sel: null })}
          items={[{ key: "people", label: "People", count: n.people }, { key: "roles", label: "Roles", count: n.roles }]} />}>
        {n.people > 0 && <>
          <div className="ae-bar" role="img" aria-label={lv.map((l) => `${n.levels[l]} ${TITLE[l]}`).join(", ")}>
            {lv.map((l) => <span key={l} className={`ae-bar-lvl-${l}`} style={{ width: `${(100 * n.levels[l]) / n.people}%` }} />)}
          </div>
          <div className="ae-bar-legend">
            {lv.map((l) => <span key={l}><span className={`ae-dot2 ae-lvl-${l}`} />{TITLE[l]} {n.levels[l]}</span>)}
            {n.disabled > 0 && <span className="ae-warn-word">{plural(n.disabled, "disabled user")} still hold{n.disabled === 1 ? "s" : ""} access</span>}
            {n.dormant > 0 && <span className="ae-muted">{n.dormant} dormant or never logged in</span>}
          </div>
        </>}
        <ListToolbar search={q} onSearch={setQ}>
          {!roles && <Toggle label="Group people with the same path" on={same} onPick={(v) => c.set({ same: v ? "1" : "0" })} />}
        </ListToolbar>
        {!rows.length ? <EmptyState title="Nobody">No user or role reaches this object (admin roles aside).</EmptyState>
          : !roles && same ? (
            <div className="ae-wholist">
              {d.groups.filter((g) => g.names.some(hit)).map((g) => {
                const x = d.people.find((p) => p.name === g.names[0])!;
                return (
                  <button type="button" key={g.names.join()} className={`ae-whorow${sel && g.names.includes(sel.name) ? " on" : ""}`} onClick={() => pick(g.names[0])}>
                    <span className="ae-avatar ae-avatar-s" aria-hidden>{g.names.length > 1 ? g.names.length : ini(g.names[0])}</span>
                    <span className="ae-whoname"><span className="ae-mono">{sameLabel(g.names, g.route)}</span>
                      <span className="ae-muted">{g.names.length > 1 ? g.names.slice(0, 6).join(", ") + (g.names.length > 6 ? ` and ${g.names.length - 6} more` : "") : `${STATUS[x.status]} · last login ${ago(x)}`}</span></span>
                    <span className={`ae-lvl ae-lvl-${g.level}`}>{TITLE[g.level]}</span>
                    <span className="ae-privs">{g.privileges.join(" · ") || "All privileges"}</span>
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
                        <span className="ae-privs">{x.privileges.join(" · ") || "All privileges"}</span>
                        <span className="ae-muted ae-whoways">{plural(x.ways, "path")}</span>
                      </button>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          )}
      </Card>
      <aside className="ae-whoside">
        {sel && <How e={sel} d={d} role={roles} onOpen={o.open} />}
        {d.columns.length > 0 && (
          <Card title="Sensitive columns" sub="Who sees each one unmasked">
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
        )}
      </aside>
    </div>
  );
}

function How({ e, d, role, onOpen }: { e: WhoEntry; d: WhoPage; role: boolean; onOpen: (id: string) => void }) {
  const c = useApp();
  const p = e as WhoPerson;
  const gone = !role && p.status === "disabled";
  const steps = stepsOf(e, d.refs.kinds, gone);
  const ch = changeOfPath(e.path, d.refs.kinds);
  const sum = gone ? "Disabled, but the grants are still there"
    : e.level === "admin" && !e.privileges.length ? "An admin role inherits everything" : `${TITLE[e.level]}, ${plural(steps.length - 1, "step")} away`;
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
      {e.ways > 1 && <p className="ae-muted">{plural(e.ways - 1, "other way")} lead{e.ways === 2 ? "s" : ""} here too, so removing one role may not remove the access.</p>}
      <div className="ae-how-links">
        {!role && d.object.id && <button type="button" className="ae-link" onClick={() => c.nav("check", { name: e.name, obj: d.object.id! })}>All paths (Can they?)</button>}
        {role && d.object.id && <button type="button" className="ae-link" onClick={() => c.nav("check", { role: e.name, obj: d.object.id! })}>All paths (Can they?)</button>}
        {role && <button type="button" className="ae-link" onClick={() => c.nav("access", { role: e.name })}>Open the role</button>}
        {ch && <WhatIfButton ch={[ch]} />}
      </div>
    </Card>
  );
}

/** The old Object page for the same object, inside this screen. */
function Detail({ id }: { id: string }) {
  const c = useApp();
  const { show: _s, as: _a, sel: _l, by: _b, same: _m, ...rest } = c.params;
  return (
    <div className="ae-embed">
      <AppCtx.Provider value={{ ...c, params: { ...rest, name: id } }}><ObjectDetail /></AppCtx.Provider>
    </div>
  );
}

/** Admin preset: the Rule checks "Admin holders" table (admin roles and account privileges). */
function AdminDetail() {
  const c = useApp();
  const s = useApi<RulesPage>("rules", { view: c.view });
  return <Load s={s}>{(r) => <Card title="People with admin roles or account privileges" scroll><AdminTable admins={r.admins} refs={r.refs} /></Card>}</Load>;
}

/** The old Object page: graph of the paths in, who has access by path or by user / role, users × privileges, what
 * each role sees, sensitivity. The default tab of screen 2. */
export function ObjectDetail() {
  const c = useApp();
  const name = c.params.name ?? "";
  const [tab, setTab] = useState("all");
  const [part, setPart] = useState(c.params.part ?? "who");
  const types = useApi<{ items: ListItem[] }>("list", { what: "types", view: c.view });
  // no name: the server picks the first object of the type (as app.py)
  const s = useApi<ObjectPage>("object", { ...apiParams(c), name });
  const op = useOpen(s.data?.refs);
  return (
    <>
      <Head title="Object" sub="Who can reach a table, view or other object, and how." />
      <Controls>
        <Sel label="Type" value={c.params.type ?? ""} onPick={(v) => c.nav("object", v ? { type: v } : {})}
          options={[["", "Any type"], ...(types.data?.items ?? []).map((i): [string, string] => [i.id, i.id])]} />
        <Pick label="Object" value={name || s.data?.object.id || ""} width={360} what="objects" params={{ type: c.params.type }}
          onPick={(v) => c.nav("object", c.params.type ? { name: v, type: c.params.type } : { name: v })} />
        <Tog label="Active users only" on={c.params.active === "1"} onPick={(v) => c.set({ active: v ? "1" : null })} />
        <Tog label="Users only" on={c.params.users === "1"} onPick={(v) => c.set({ users: v ? "1" : null })} />
        {s.data && <Sel label="Privilege" value={c.params.priv ?? ""} onPick={(v) => c.set({ priv: v })}
          options={[["", "Any"], ...s.data.object.privileges.map((p): [string, string] => [p, p])]} />}
      </Controls>
      <Load s={s}>{(d) => {
        const o = d.object, k = d.kpis;
        const gs = tab === "all" ? d.grantees : d.grantees.filter((g) => g.tabs.includes(tab as never));
        return (
          <>
            <Card title={o.id} sub={`${o.type.toLowerCase()}${o.sensitive ? " · sensitive" : ""}`}>
              <KpiRow items={[
                { label: "People", value: k.people, caption: `${k.disabled} disabled · ${k.service} service` },
                { label: "Admin", value: k.admin, tone: k.admin ? "bad" : null },
                { label: "Read / Write / Own", value: `${k.read} / ${k.write} / ${k.own}` },
                { label: "Roles on the way", value: k.roles, caption: `${k.direct} direct holders` },
                { label: "Longest chain", value: k.longest },
              ]} />
              {k.owners.length > 0 && <p>Owner: <Chips items={k.owners.map((r) => ({ id: r, kind: "technical" }))} /></p>}
              {k.deployers.length > 0 && <p>Deployed by: <Chips items={k.deployers.map((r) => ({ id: r, kind: "user" }))} /></p>}
              {k.owner_note && <p className="ae-muted">{k.owner_note}</p>}
            </Card>
            {d.admin_paths.length > 0 && <Banner tone="bad" title={`Admin roles reach this object: ${new Set(d.admin_paths.map((p) => p[0])).size} user(s)`} lines={d.admin_paths.map((p, i) => <span key={i} className="ae-fd-path"><PathCell path={p} refs={d.refs} /><WhatIfButton ch={[{ op: "revoke_role_from_user", role: p[1], user: p[0].replace(/ \(user\)$/, "") }]} /></span>)}>
              <p className="ae-muted">An admin role inherits every role, so these users reach this object without a path drawn below.</p>
            </Banner>}
            <GraphCard g={d.graph} refs={d.refs} />
            <Tabs active={part} onChange={setPart} tabs={[
              { key: "who", label: "Who has access", count: d.grantees.length },
              { key: "users", label: "Users × privileges", count: d.matrix.rows.length },
              ...(d.sees ? [{ key: "sees", label: "What each role sees", count: d.sees.rows.length }] : []),
              ...(d.sensitivity ? [{ key: "sens", label: "Sensitivity", count: d.sensitivity.columns.length, tone: o.sensitive ? "warn" as const : null }] : []),
            ]} />
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
              <DataTable csv={`${o.name}_users.csv`} rows={d.matrix.rows} rowTone={(r: MatrixRow) => (r.admin.length ? "bad" : null)}
                columns={[
                  col("u", "User", (r: MatrixRow) => r.user, { render: (r: MatrixRow) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("t", "Type", (r: MatrixRow) => r.type), col("s", "Status", (r: MatrixRow) => r.status),
                  ...d.matrix.privs.map((p) => col(p, p, (r: MatrixRow) => (r.cells[p]?.has ? 1 : 0),
                    { render: (r: MatrixRow) => (r.cells[p]?.has ? <span title={r.cells[p].title}>{r.cells[p].owner ? "owner" : `D${r.cells[p].depth ?? ""}`}</span> : null) })),
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
              <Card title="Who has access" sub="Users that come in through the same chain are one row" right={
                <div className="seg">{d.tabs.map((t) => <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label} {t.count}</button>)}</div>}>
                <GroupedGrantees key={tab} rows={gs} kinds={d.refs.kinds} onOpen={op.open} csv={`${o.name}_grantees_${tab}.csv`} />
              </Card>
            )}
          </>
        );
      }}</Load>
    </>
  );
}
