// Screen 4: Access graph. Start from a table, a role or a person; columns by step, line colour by what the line ends
// up granting, same-path people stacked, built-ins folded; a click on a box traces everything through it, Show only
// this draws just those lines (focus=), and database or schema, object type and access filters narrow it on the server.
import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { Graph as G, GraphNode, ListItem, MapNode, MapPage } from "../api/types";
import { Fold, Card, EmptyState, Graph, LEVEL_WORD, Tabs, Toggle } from "../components";
import { apiParams, useApp } from "../ctx";
import { lean, GraphCard, Load, Pick, PickFirst, ScopePick, Sel } from "./common";
import { riskIds, startOf } from "./screens";
import { WhatIfButton } from "./Whatif";

const MODES = [["object", "Table", "object"], ["role", "Role", "role"], ["user", "Person", "person"]] as const;
const KIND_WORD: Record<string, string> = {
  user: "Person", functional: "Functional role", technical: "Technical role", group: "Group role", database_role: "Database role",
  admin: "Admin role", object: "Object", fold: "Folded group", database_group: "Objects of a database", schema_group: "Objects of a schema",
  type_group: "Objects of one type", lane_group: "Roles of one step",
};

export function GraphPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const mode = c.params.table ? "object" : c.params.role ? "role" : "user";
  const name = c.params.table ?? c.params.role ?? c.params.user ?? "";
  const tab = c.params.show === "trace" ? "trace" : "diagram";
  // only the Trace tab draws the access graph; a click or the risky toggle: no new request
  const none = !mine && !name;  // shared: nobody picked yet
  const s = useApi<MapPage>(tab === "trace" && !none ? "map" : null, { ...apiParams(c), show: null, sel: null, risky: null });
  const what = mode === "object" ? "objects" : mode === "role" ? "roles" : "users";
  const objs = useApi<{ items: ListItem[] }>(mode === "object" || mine ? null : "list", { what: "objects", type: "TABLE", view: c.view, limit: "1" });
  const roles = useApi<{ items: ListItem[] }>(mode === "role" ? null : "list", { what: "roles", view: c.view, limit: "1" });
  const shown = s.data?.name ?? (name || (mode === "user" ? c.meta.default_user ?? "" : ""));
  const first = (m: string) => (m === "object" ? objs.data?.items[0]?.id : m === "role" ? roles.data?.items[0]?.id : c.meta.default_user);
  const pick = (m: string) => {
    if (m === mode) return;
    const id = first(m);
    if (id) c.set(startOf(m === "user" ? "user" : m === "object" ? "object" : "functional", id));
    else if (m === "user") c.set({ table: null, role: null, user: null });  // no default person: pick one
  };
  return (
    <>
      <h2 className="ae-sr">Access graph</h2>
      <Tabs nav active={mode} onChange={pick} tabs={[...MODES].reverse().map(([m, , word]) => ({ key: m, label: `From ${word === "person" ? "a person" : word === "role" ? "a role" : "an object"}` }))} />
      <div className="ae-h1 ae-h1-pick">What leads {mode === "object" ? "to" : "from"}
        {!(mine && mode === "user") &&
          <Pick label={MODES.find((x) => x[0] === mode)![1]} value={shown} what={what} params={mode === "object" ? { type: "TABLE" } : undefined}
            onPick={(v) => c.set(startOf(mode === "user" ? "user" : mode, v))} width={300} />}
        ?
      </div>
      {!none && <Tabs nav={2} active={tab} onChange={(k) => c.set({ show: k === "diagram" ? null : k, focus: null, sel: null })} tabs={[
        { key: "diagram", label: "Hierarchy" },
        { key: "trace", label: "Trace" },
      ]} />}
      {!none && <Difference tab={tab} mode={mode} />}
      {mode !== "object" && !none && <Fold label="Filter" on={!!(c.params.schema || c.params.otype || c.params.access)}><div className="ae-controls"><Filters trace={tab === "trace"} /></div></Fold>}
      {none ? <PickFirst what={mode === "user" ? "a person" : mode === "role" ? "a role" : "a table"} /> : <>
        {tab === "diagram" && <OldDiagram mode={mode} name={shown} />}
        {tab === "trace" && <Load s={s}>{(d) => <><p className="ae-answer">{d.graph.header.replace(/\.$/, "")}{mode !== "object" && !c.params.schema && !c.params.otype && !c.params.access && <span className="ae-muted"> (nothing left out)</span>}</p><Trace d={d} /></>}</Load>}
      </>}
    </>
  );
}

/** What the two tabs answer, the open one marked, and who shows the difference best. */
function Difference({ tab, mode }: { tab: string; mode: string }) {
  const c = useApp();
  const row = (k: string, name: string, q: string, how: string) => (
    <div className={tab === k ? "on" : ""}><b>{name}</b><span>{q}</span><span className="ae-muted">{how}</span></div>);
  const go = (p: Record<string, string>) => c.set({ user: null, role: null, table: null, focus: null, sel: null, ...p });
  return (
    <div className="ae-gdiff" aria-label="Hierarchy or Trace">
      {row("diagram", "Hierarchy", "How deep is it?", "Roles in lanes by depth, one line per grant.")}
      {row("trace", "Trace", "Who passes through a box?", `${mode === "user" ? "The same paths" : "People too"}, lines thicker with more people, admin bypass and risky paths drawn.`)}
      <p className="ae-muted">Most different for a role many people hold or a person with an admin role{c.meta.mode === "fake" && <>: try{" "}
        <button type="button" className="ae-link ae-mono" onClick={() => go({ role: "GRP_EMEA_ALL" })}>GRP_EMEA_ALL</button> (14 people) or{" "}
        <button type="button" className="ae-link ae-mono" onClick={() => go({ user: "OPS_01" })}>OPS_01</button> (admin), then switch the tab</>}.</p>
    </div>
  );
}

/** The diagram the person, role or object page draws (kept: the default tab). */
function OldDiagram({ mode, name }: { mode: string; name: string }) {
  const c = useApp();
  const g = useApi<G>("graph", { of: mode, name: name || null, view: c.view, builtin: c.params.builtin, focus: c.params.focus, lean: lean(c),
    ...(mode !== "object" ? { schema: c.params.schema, otype: c.params.otype } : {}) });
  const said = (x: G) => {
    const roles = x.nodes.filter((n) => !["user", "object", "fold", "schema_group", "database_group", "type_group", "lane_group"].includes(n.kind) && n.id !== name).length;
    const people = x.nodes.filter((n) => n.kind === "user" && n.name !== name).length, objs = x.header.match(/([\d,]+) objects?/)?.[1] ?? String(x.nodes.filter((n) => n.kind === "object").length);
    const w = (n: number | string, one: string, many = `${one}s`) => `${n} ${String(n) === "1" ? one : many}`;
    const short = mode === "object" ? name.split(".").pop() : name; // a login can be an email: only objects are shortened
    return mode === "object" ? `${w(people, "person", "people")} come in to ${short} through ${w(roles, "role")}` : mode === "role" ? `${short} opens ${w(objs, "object")}${people ? ` for ${w(people, "person", "people")}` : ""}` : `${short} reaches ${w(objs, "object")} through ${w(roles, "role")}`;
  };
  return <Load s={g}>{(x) => (x ? <><p className="ae-answer">{x.focus ? `What passes through ${x.focus.label}` : said(x)}</p><GraphCard leans={mode !== "object"} g={x} title={mode === "object" ? "Every way in" : mode === "role" ? "Who holds it, what it opens" : "Person to roles to objects"} /></> : <EmptyState title="Nothing to draw" />)}</Load>;
}

function Trace({ d }: { d: MapPage }) {
  const c = useApp();
  const [picked, setPicked] = useState<GraphNode | null>(null); // a box drawn from an opened box: not in d.graph.nodes
  const node = d.graph.nodes.find((n) => n.id === c.params.sel) ?? (picked && picked.id === c.params.sel ? picked : null);
  const more = useApi<{ detail: Record<string, MapNode> }>(node && !d.detail[node.id] ? "map" : null,
    { ...apiParams(c), show: null, sel: null, risky: null, node: node?.id }); // its detail comes when it is picked
  const x = node ? d.detail[node.id] ?? more.data?.detail[node.id] ?? null : null;
  const sel = node && x ? node.id : null;
  const risky = c.params.risky === "1";
  const filtered = !!(c.params.schema || c.params.otype || c.params.access);
  const hi = useMemo(() => (risky ? riskIds(d.risky, d.risky_nodes) : undefined), [risky, d]);
  return (
    <>
      <div className="ae-toolbar">
        <Toggle label={<span title="Group people with the same path">Group same path</span>} on={c.params.same !== "0"} onPick={(v) => c.set({ same: v ? null : "0", sel: null })} />
        <Toggle label={<span title="Show admin bypass">Admin bypass</span>} on={c.params.admin !== "0"} onPick={(v) => c.set({ admin: v ? null : "0", sel: null })} />
        <Toggle label={<span title="Fold Snowflake built-ins">Fold built-ins</span>} on={c.params.builtin !== "1"} onPick={(v) => c.set({ builtin: v ? null : "1", sel: null })} />
        <Toggle label={<span title="Highlight risky paths (to admin, via PUBLIC, read role that writes)">Risky paths</span>} on={risky} onPick={(v) => c.set({ risky: v ? "1" : null })} />
      </div>
      {!node && <p className="ae-muted">Click any box in the graph to see who comes through it and what it leads to.</p>}
      <div className={node ? "ae-gmap" : undefined}>
        <Card title="Click a box to trace everything through it" right={sel && <button type="button" className="ae-btn" onClick={() => c.set({ sel: null })}>Clear trace</button>}>
          {d.graph.nodes.length > 1 ? (
            <Graph graph={d.graph} theme={c.theme} focus={sel} hi={hi} flow maxHeight={760} minZoom={0.6}
              onPick={(n) => { setPicked(n); c.set({ sel: n.id }, { stay: true }); }}
              onOnly={(id) => c.set({ focus: id, sel: id }, { push: true, stay: true })} />
          ) : filtered ? <EmptyState title="Nothing matches the filters">Change the database, type or access above.</EmptyState>
            : <EmptyState title="Nobody reaches it">No role or person has a grant on it.</EmptyState>}
          <div className="ae-bar-legend" title="Thicker = more people">
            {([["read", "Read"], ["write", "Write"], ["own", "Own"], ["admin", "Admin bypass"], ["use", "Use"], ["inherit", "Holds the role only"]] as const).map(([k, t]) => (
              <span key={k}><span className={`ae-gline ae-gline-${k}`} aria-hidden />{t}</span>
            ))}
            {risky && <span title={Object.values(d.why).join(", ")}><span className="ae-gline ae-gline-risk" aria-hidden />Risky</span>}
          </div>
        </Card>
        {node && <div className="ae-whoside">
          <Card title={node.label}>
            {x ? <Detail d={d} n={node} x={x} />
              : more.error ? <p className="ae-muted" role="alert">{more.error.message}</p>
              : <p className="ae-muted">Loading…</p>}
          </Card>
        </div>}
      </div>
    </>
  );
}

function Detail({ d, n, x }: { d: MapPage; n: GraphNode; x: MapNode }) {
  const c = useApp();
  const stack = n.marks.includes("stack");
  const fold = n.kind === "fold" || n.group != null;
  const fake = n.id === "Through admin roles" || n.id === "ACCOUNT"; // drawn boxes, not roles or objects
  const droppable = !fake && n.id !== "PUBLIC" && !c.meta.admin_roles.includes(n.id) && n.kind !== "user" && n.kind !== "object";
  const open = () => (n.kind === "user" ? c.nav("access", { user: n.name }) : n.kind === "object" ? c.nav("object", { name: n.id }) : c.nav("access", { role: n.id }));
  const chips = (xs: string[], kind: string, more: number) => (
    <div className="ae-gchips">
      {xs.map((v) => <button type="button" key={v} className={`ae-chip ae-chip-${kind}`} onClick={() => c.set(startOf(kind, v))} title={`${v}: make it the start`}>{d.refs.labels[v] ?? (kind === "user" ? v : v.split(".").pop())}</button>)}
      {more > xs.length && <span className="ae-muted">+{more - xs.length} more</span>}
    </div>
  );
  return (
    <div className="ae-gdetail">
      <div className="ae-muted">{stack ? "People with the same path" : KIND_WORD[n.kind] ?? n.kind}{n.sub && !stack ? ` · ${n.sub}` : ""}</div>
      {x.level && <div>Leads to: <span className={`ae-lvl ae-lvl-${x.level}`}>{LEVEL_WORD[x.level] ?? x.level}</span></div>}
      {x.risk && <p className="ae-bad">Risky: {d.why[x.risk]}</p>}
      {stack && x.members && <><h4>The {x.members.length} people</h4>{chips(x.members, "user", x.members.length)}</>}
      {!stack && <><h4>People who come through here · {x.people_count}</h4>{x.people_count ? chips(x.people, "user", x.people_count) : <p className="ae-muted">Nobody drawn here.</p>}</>}
      <h4>What it leads to · {x.leads_count}</h4>
      {x.leads_count ? chips(x.leads.filter((o) => d.refs.kinds[o] === "object"), "object", x.leads_count) : <p className="ae-muted">Nothing further.</p>}
      <div className="ae-row">
        {!stack && !fold && !fake && <button type="button" className="ae-btn" onClick={open}>Open its page</button>}
        {!stack && !fold && droppable && <WhatIfButton ch={[{ op: "drop_role", role: n.id }]} label="What if removed?" />}
        {!stack && !fold && n.id !== d.id && !fake &&
          <button type="button" className="ae-btn" onClick={() => c.set(startOf(n.kind, n.id))}>Make it the start</button>}
        {n.kind === "fold" && <button type="button" className="ae-btn" onClick={() => c.set({ builtin: "1", sel: null })}>Unfold the built-ins</button>}
      </div>
    </div>
  );
}

const ACCESS: [string, string][] = [["", "Any"], ["read", "Read"], ["write", "Write"], ["own", "Own"]];

/** Above the access graph: a database or schema, an object type and, on the Trace graph, the step a line carries
 * (the line colours). The server narrows the graph (schema=, otype=, access=); they stay in the URL. */
function Filters({ trace }: { trace: boolean }) {
  const c = useApp();
  const types = useApi<{ items: ListItem[] }>("list", { what: "types", view: c.view });
  return (
    <>
      <ScopePick />
      <Sel label="Object type" value={c.params.otype ?? ""} onPick={(v) => c.set({ otype: v || null, focus: null, sel: null })}
        options={[["", "Every type"], ...(types.data?.items ?? []).map((t): [string, string] => [t.id, t.id.toLowerCase()])]} />
      {trace && <Sel label="Access" value={c.params.access ?? ""} onPick={(v) => c.set({ access: v || null, focus: null, sel: null })} options={ACCESS} />}
    </>
  );
}
