// Can they? (screens 3 and 12): a sentence question, the verdict Yes / Partly / No with the privileges held, then tabs.
// "Answer & diagram" (the old page: banner, combined diagram, paths, ownership, where to cut, ways to remove, what they
// see) is the default; Routes & where to cut (one lane per route, cut points with side effects), Nearest ways in (No)
// and Rows & columns (grant, rows, columns; Partly) follow. The subject is a person (name=) or a role (role=).
import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { CheckPage, ListItem, Path, Refs } from "../api/types";
import { Banner, Card, CodeOutput, DataTable, EmptyState, KpiRow, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { cutChanges, cutLabel, cutWhatIf, needOf, nearestNote, nearestTitle, pickSubject, sideEffects, subjectIn, subjectLink, verdictLine } from "./verdict";
import { col, GraphCard, Load, NameLink, PathCell, pathCol, Pick, Sel, StateTag } from "./common";
import { changeOfPath, WhatIfButton, whatIf } from "./Whatif";

export function CheckPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const asked = subjectIn(c.params);
  const name = asked.name ?? c.meta.default_user;
  const users = useApi<{ items: ListItem[] }>(mine ? null : "list", { what: "users", view: c.view });
  const roles = useApi<{ items: ListItem[] }>(mine ? null : "list", { what: "roles", view: c.view });
  const objs = useApi<{ items: ListItem[] }>("list", { what: "objects", view: c.view });
  const s = useApi<CheckPage>("check", { ...apiParams(c), ...(asked.role ? { role: name } : { name }) });
  const us = useMemo(() => users.data?.items.map((i) => i.id) ?? [], [users.data]);
  const rs = useMemo(() => roles.data?.items.map((i) => i.id) ?? [], [roles.data]);
  return (
    <>
      <h2 className="ae-h1">Can they?</h2>
      <div className="ae-ask" role="group" aria-label="Question">
        <span className="ae-ask-w">Can</span>
        {mine ? <span className="ae-mono ae-ask-w">{s.data?.user ?? "you"}</span>
          : <Pick label="Person or role" value={name} options={us.length || rs.length ? [...us, ...rs] : [name]} onPick={(v) => c.set({ ...pickSubject(v, us, rs), obj: null })} />}
        {s.data && <Sel label="Privilege" value={s.data.priv} onPick={(v) => c.set({ priv: v, do: null })}
          options={s.data.privileges.map((p): [string, string] => [p, p === "*" ? "do anything to" : p])} />}
        <Pick label="Object" value={c.params.obj ?? s.data?.object ?? ""} width={340} options={objs.data?.items.map((i) => i.id) ?? []} onPick={(v) => c.set({ obj: v, priv: null })} />
        <span className="ae-ask-w">?</span>
      </div>
      <Load s={s}>{(d) => <Body d={d} />}</Load>
    </>
  );
}

const MARK = { yes: "✓", partly: "½", no: "✕" } as const;
const WORD = { yes: "Yes", partly: "Partly", no: "No" } as const;

function Body({ d }: { d: CheckPage }) {
  const c = useApp();
  const show = c.params.show ?? "answer";
  const tabs = [
    { key: "answer", label: "Answer & diagram" },
    ...(d.lanes_total ? [{ key: "routes", label: "Routes & where to cut", count: d.lanes_total }] : []),
    ...(d.verdict === "no" ? [{ key: "nearest", label: "Nearest ways in", count: d.nearest.length }] : []),
    ...(d.layers ? [{ key: "layers", label: "Rows & columns", tone: d.verdict === "partly" ? ("warn" as const) : null }] : []),
  ];
  const at = tabs.some((t) => t.key === show) ? show : "answer";
  return (
    <>
      <section className={`ae-verdict ae-verdict-${d.verdict}`} aria-label="Answer">
        <div className="ae-verdict-head">
          <span className="ae-verdict-mark" aria-hidden>{MARK[d.verdict]}</span>
          <div>
            <div className="ae-verdict-word">{WORD[d.verdict]}{d.answer.tone === "warn" && <span className="ae-warn-word"> · user is {d.status}</span>}
              {!d.subject.user && <span className="ae-muted"> · role {d.user}, held by {d.subject.people} {d.subject.people === 1 ? "person" : "people"}</span>}</div>
            <div className="ae-verdict-line">{verdictLine(d)}</div>
          </div>
        </div>
        <ul className="ae-privrow" aria-label={`Privileges on ${d.object}`}>
          {d.held.map((p) => (
            <li key={p.privilege} className={p.held ? "on" : ""}>
              <span aria-hidden>{p.held ? "✓" : "✕"}</span>{p.privilege}<span className="ae-sr">{p.held ? " held" : " not held"}</span>
            </li>
          ))}
        </ul>
      </section>
      <Tabs active={at} onChange={(k) => c.set({ show: k === "answer" ? null : k })} tabs={tabs} />
      {at === "answer" && <Answer d={d} />}
      {at === "routes" && <Routes d={d} />}
      {at === "nearest" && <NearestWays d={d} />}
      {at === "layers" && <Layers d={d} />}
    </>
  );
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

function Routes({ d }: { d: CheckPage }) {
  const c = useApp();
  const [sel, setSel] = useState(0);
  const cut = d.cuts[sel];
  return (
    <>
      <Card title="How the access gets there" sub={`One lane per route, read left to right${d.lanes_total > d.lanes.length ? ` · first ${d.lanes.length} of ${d.lanes_total}` : ""}`}>
        <div className="ae-routes">
          {d.lanes.map((l, i) => <Lane key={i} path={l.path} grant={l.privileges.join(", ")} refs={d.refs} cut={d.cut} user={d.subject.user} />)}
        </div>
        <div className="ae-route-legend">
          <span><span className="ae-route-key cut" />In every route: a place to cut</span>
          <span><span className="ae-route-key" />Only in this route</span>
        </div>
      </Card>
      <div className="ae-two">
        <Card title="Where to cut" sub={d.cuts.length ? "Removing one of these links removes this access. The side effects differ."
          : d.view === "mine" ? "Not worked out in My access: it needs everyone's grants." : "No single link is on every route: each route needs its own cut (see Answer & diagram)."}>
          <ul className="ae-cuts">
            {d.cuts.map((x, i) => (
              <li key={i} className={i === sel ? "on" : ""}>
                <button type="button" className="ae-cut-main" aria-pressed={i === sel} onClick={() => setSel(i)}>
                  <b>{cutLabel(x.edges)}</b>
                  <span className="ae-muted">{x.people.length > 1
                    ? `Ends this access for ${x.people.length} people: ${x.people.slice(0, 4).join(", ")}${x.people.length > 4 ? " …" : ""}.`
                    : x.people.length ? `Ends this access only for ${x.people[0]}.` : `Ends it for ${d.user} only: no one holds it.`}{x.lost > 0 ? ` ${d.user} also loses ${x.lost} other privilege${x.lost === 1 ? "" : "s"}.` : ""}</span>
                </button>
                <span className="ae-cut-side">
                  {sideEffects(x.people.length, x.lost).map((b) => <span key={b.text} className={`ae-sfx ae-sfx-${b.tone}`}>{b.text}</span>)}
                  <button type="button" className="ae-btn ae-btn-s" title="Simulate it on the What if page: nothing changes in Snowflake" onClick={() => whatIf(c, cutWhatIf(x.edges))}>Simulate</button>
                </span>
              </li>
            ))}
          </ul>
          {cut && <CodeOutput changes={cutChanges(cut.edges, d.type)} name={`revoke_${d.user.toLowerCase()}`} />}
        </Card>
        <Card title="What they see">
          {d.read ? (
            <ul className="ae-items">
              <li><span>Rows</span>{d.read.rows ? StateTag(d.read.rows) : <b>All rows</b>}</li>
              {d.read.columns.map((x) => <li key={x.column}><span className="ae-mono">{x.column}</span>{StateTag(x)}</li>)}
            </ul>
          ) : <p className="ae-muted">Not a read of a table or view.</p>}
          {d.use_role && (
            <>
              <div className="ae-muted ae-mt">To use it</div>
              <pre className="ae-code">{`USE ROLE ${d.use_role};${d.warehouse ? `\nUSE WAREHOUSE ${d.warehouse};` : ""}`}</pre>
            </>
          )}
        </Card>
      </div>
    </>
  );
}

function NearestWays({ d }: { d: CheckPage }) {
  const c = useApp();
  if (d.view === "mine") return <EmptyState title="Not worked out in My access">The nearest ways in need everyone's grants: open the shared snapshot.</EmptyState>;
  if (!d.nearest.length) return <EmptyState title="No way in to suggest">No role that can be suggested reaches {d.ask_priv} on {d.object} (admin and build roles are never suggested).</EmptyState>;
  return (
    <Card title="Nearest ways in" sub={`For ${d.ask_priv}. The dashed red link is what is missing. Fewest missing links first, then the fewest people who would get it too.`}>
      <div className="ae-near">
        {d.nearest.map((n, i) => (
          <div key={i} className={`ae-near-row${n.broad || n.rule1 ? " warn" : ""}`}>
            <Lane path={n.path} grant={d.ask_priv} refs={d.refs} missing={n.missing} user={d.subject.user} />
            <div className="ae-near-foot">
              <div>
                <b>{nearestTitle(n)}</b> · <span className="ae-muted">{nearestNote(n, d.approver)}</span>
                {n.broad && <div className="ae-warn-word">Too broad: {n.broad}. Not recommended.</div>}
              </div>
              <div className="ae-row">
                <button type="button" className={`ae-btn${i === 0 && !n.broad ? " ae-btn-primary" : ""}`}
                  onClick={() => c.nav("request", { ...subjectLink(d.subject, "request"), obj: d.object, need: needOf(d.ask_priv), role: n.role,
                    ...(n.to_user || !d.subject.user ? {} : { to: n.to }) })}>
                  {n.broad ? "Request anyway" : `Request ${n.cost > 1 ? "a new role" : n.role}`}
                </button>
                <button type="button" className="ae-btn" title="Everything this role gives: the effect of granting it" onClick={() => c.nav("access", { role: n.role })}>What it brings</button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Layers({ d }: { d: CheckPage }) {
  return (
    <Card title="Three layers, checked in order" sub="The grant lets the query run; a row access policy decides the rows; masking policies decide the columns.">
      <div className="ae-layers">
        {(d.layers ?? []).map((l, i) => (
          <div key={l.step} className={`ae-layer ${l.ok ? "ok" : l.result === "Not reached" ? "skip" : "bad"}`}>
            <div className="ae-muted">{i + 1} · {l.step}</div>
            <b>{l.result}</b>
            <div className="ae-layer-why">{l.reason}</div>
          </div>
        ))}
      </div>
      {d.read?.role_only && <p className="ae-note">With only {d.use_role} as primary role: {d.read.role_only}</p>}
    </Card>
  );
}

/** The old Can they? page, kept as the default tab. */
function Answer({ d }: { d: CheckPage }) {
  const a = d.answer;
  return (
    <>
      <Banner tone={a.yes ? (a.tone === "warn" ? "warn" : a.tone === "low" ? "info" : "bad") : "info"} title={a.title} lines={[a.text]} />
      <KpiRow items={a.stats.map(([label, value]) => ({ label, value }))} />
      {d.status && d.status !== "active" && <Banner tone="warn" title={`User is ${d.status}`} lines={d.dormant_days ? [`No login for ${d.dormant_days} days.`] : []} />}
      {d.admin_paths.length > 0 && (
        <Banner tone="bad" title={`Admin roles give this ${d.subject.user ? "user" : "role"} everything`} lines={d.admin_paths.map((p, i) => <PathCell key={i} path={p} refs={d.refs} />)} />
      )}
      <GraphCard g={d.graph} refs={d.refs} />
      {d.paths.length > 0 && (
        <Card title="Paths" sub={`${d.paths.length} way(s) to ${d.priv === "*" ? "any privilege" : d.priv} on ${d.object}`}>
          <DataTable csv="check_paths.csv" rows={d.paths}
            columns={[...(d.priv === "*" ? [col("p", "Privilege", (r: CheckPage["paths"][number]) => r.privilege, { wrap: "nowrap" })] : []),
              col("d", "Depth", (r: CheckPage["paths"][number]) => r.depth, { num: true }),
              col("h", "Held by", (r: CheckPage["paths"][number]) => r.holder, { render: (r: CheckPage["paths"][number]) => <NameLink id={r.holder} refs={d.refs} /> }),
              col("w", "How", (r: CheckPage["paths"][number]) => r.how, { wrap: "wrap" }), pathCol<CheckPage["paths"][number]>(d.refs),
              col("w", "", () => "", { render: (r: CheckPage["paths"][number]) => { const ch = changeOfPath(r.path, d.refs.kinds); return ch && <WhatIfButton ch={[ch]} />; } })]} />
        </Card>
      )}
      {d.owner.length > 0 && (
        <Card title="Through ownership" sub="The owner of an object can do everything on it">
          {d.owner.map((p, i) => <div key={i}><PathCell path={p} refs={d.refs} /></div>)}
        </Card>
      )}
      {d.choke.length > 0 && (
        <Card title="Where to cut" sub="Every path goes through one of these. Remove the link and the access is gone.">
          {d.choke.map((r) => <div key={r} className="ae-fd-path"><NameLink id={r} refs={d.refs} /><WhatIfButton ch={[{ op: "drop_role", role: r }]} label="What if dropped?" /></div>)}
        </Card>
      )}
      {!a.yes && d.closest && (
        <Card title={`Closest the ${d.subject.user ? "user" : "role"} gets`} sub="The nearest chain that stops short">
          <PathCell path={d.closest} refs={d.refs} />
        </Card>
      )}
      {!a.yes && d.ask.length > 0 && (
        <Card title="Roles to ask for" sub="Roles that would give this access">
          <DataTable csv="check_ask.csv" rows={d.ask}
            columns={[col("r", "Role", (r: CheckPage["ask"][number]) => r.role, { render: (r: CheckPage["ask"][number]) => <NameLink id={r.role} refs={d.refs} /> }),
              col("n", "Privileges", (r: CheckPage["ask"][number]) => r.privileges, { num: true }), pathCol<CheckPage["ask"][number]>(d.refs)]} />
        </Card>
      )}
      {d.options.length > 0 && (
        <Card title="Ways to remove this access" sub="Text to copy into your infrastructure as code. This app never runs it.">
          {d.options.map((x, i) => (
            <div key={i} className="ae-option">
              <p><strong>Option {i + 1}</strong> · {x.affects} privilege(s) lost · {x.users.length} user(s) affected</p>
              <pre className="ae-code">{x.iac}</pre><pre className="ae-code">{x.sql}</pre>
            </div>
          ))}
        </Card>
      )}
      {d.read && (
        <Card title="What they see" sub={d.read.summary}>
          {d.use_role && <p>Use role <NameLink id={d.use_role} refs={d.refs} />{d.warehouse ? ` with warehouse ${d.warehouse}` : ""}.</p>}
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
