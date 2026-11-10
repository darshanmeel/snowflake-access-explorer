// Screen 4: Access graph. Start from a table, a role or a person; columns by step, line colour by what the line ends
// up granting, same-path people stacked, built-ins folded; a click on a box traces everything through it.
import { useMemo } from "react";
import { useApi } from "../api/client";
import type { Graph as G, GraphNode, ListItem, MapPage } from "../api/types";
import { Card, EmptyState, Graph, LEVEL_WORD, Tabs, Toggle } from "../components";
import { apiParams, useApp } from "../ctx";
import { GraphCard, Load, Pick } from "./common";
import { riskIds, startOf } from "./screens";
import { WhatIfButton } from "./Whatif";

const MODES = [["object", "Table", "table"], ["role", "Role", "role"], ["user", "Person", "user"]] as const;
const KIND_WORD: Record<string, string> = {
  user: "Person", functional: "Functional role", technical: "Technical role", group: "Group role", database_role: "Database role",
  admin: "Admin role", object: "Object", fold: "Folded group",
};

export function GraphPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const mode = c.params.table ? "object" : c.params.role ? "role" : "user";
  const name = c.params.table ?? c.params.role ?? c.params.user ?? "";
  const s = useApi<MapPage>("map", { ...apiParams(c), show: null, sel: null, risky: null }); // a click or a tab: no new request
  const what = mode === "object" ? "objects" : mode === "role" ? "roles" : "users";
  const objs = useApi<{ items: ListItem[] }>(mode === "object" || mine ? null : "list", { what: "objects", type: "TABLE", view: c.view, limit: "1" });
  const roles = useApi<{ items: ListItem[] }>(mode === "role" ? null : "list", { what: "roles", view: c.view, limit: "1" });
  const shown = s.data?.name ?? name;
  const first = (m: string) => (m === "object" ? objs.data?.items[0]?.id : m === "role" ? roles.data?.items[0]?.id : c.meta.default_user);
  const pick = (m: string) => {
    if (m === mode) return;
    const id = first(m);
    if (id) c.set(startOf(m === "user" ? "user" : m === "object" ? "object" : "functional", id));
  };
  const tab = c.params.show === "trace" ? "trace" : "diagram";
  return (
    <>
      <div className="ae-headrow">
        <div>
          <h2 className="ae-h1">Access graph</h2>
          {s.data && <p className="ae-muted ae-graph-sub">{s.data.graph.header}</p>}
        </div>
        <div className="ae-seg2" role="group" aria-label="Start from">
          {MODES.map(([m, label]) => (
            <button key={m} type="button" aria-pressed={m === mode} className={m === mode ? "on" : ""} onClick={() => pick(m)}>
              {label}{m === mode && <span className="ae-mono ae-seg2-n">{shown.split(".").pop()}</span>}
            </button>
          ))}
        </div>
      </div>
      {!(mine && mode === "user") && (
        <div className="ae-controls">
          <Pick label={MODES.find((x) => x[0] === mode)![1]} value={shown} what={what} params={mode === "object" ? { type: "TABLE" } : undefined}
            onPick={(v) => c.set(startOf(mode === "user" ? "user" : mode, v))} width={300} />
        </div>
      )}
      <Tabs active={tab} onChange={(k) => c.set({ show: k === "diagram" ? null : k })} tabs={[
        { key: "diagram", label: "Role hierarchy, by depth" },
        { key: "trace", label: "Trace graph" },
      ]} />
      {tab === "diagram" && <OldDiagram mode={mode} name={shown} />}
      {tab === "trace" && <Load s={s}>{(d) => <Trace d={d} />}</Load>}
    </>
  );
}

/** The diagram the person, role or object page draws (kept: the default tab). */
function OldDiagram({ mode, name }: { mode: string; name: string }) {
  const c = useApp();
  const g = useApi<G>(name ? "graph" : null, { of: mode, name, view: c.view, ...(c.params.builtin ? { builtin: c.params.builtin } : {}) });
  return <Load s={g}>{(x) => (x ? <GraphCard g={x} /> : <EmptyState title="Nothing to draw" />)}</Load>;
}

function Trace({ d }: { d: MapPage }) {
  const c = useApp();
  const sel = c.params.sel && d.detail[c.params.sel] ? c.params.sel : null;
  const risky = c.params.risky === "1";
  const hi = useMemo(() => (risky ? riskIds(d.risky, d.risky_nodes) : undefined), [risky, d]);
  const node = d.graph.nodes.find((n) => n.id === sel) ?? null;
  return (
    <>
      <div className="ae-toolbar">
        <Toggle label="Group people with the same path" on={c.params.same !== "0"} onPick={(v) => c.set({ same: v ? null : "0", sel: null })} />
        <Toggle label="Show admin bypass" on={c.params.admin !== "0"} onPick={(v) => c.set({ admin: v ? null : "0", sel: null })} />
        <Toggle label="Fold Snowflake built-ins" on={c.params.builtin !== "1"} onPick={(v) => c.set({ builtin: v ? null : "1", sel: null })} />
        <Toggle label="Highlight risky paths (to admin, via PUBLIC, read role that writes)" on={risky} onPick={(v) => c.set({ risky: v ? "1" : null })} />
      </div>
      <div className="ae-gmap">
        <Card title="Click a box to trace everything through it" right={sel && <button type="button" className="ae-btn" onClick={() => c.set({ sel: null })}>Clear trace</button>}>
          {d.graph.nodes.length > 1 ? (
            <Graph graph={d.graph} theme={c.theme} focus={sel} hi={hi} flow maxHeight={760} minZoom={0.6}
              onNodeClick={(n) => c.set({ sel: n.id === sel ? null : n.id })} />
          ) : <EmptyState title="Nobody reaches it">No role or person has a grant on it.</EmptyState>}
        </Card>
        <div className="ae-whoside">
          <Card title={node ? node.label : "Details"}>
            {node ? <Detail d={d} n={node} /> : <p className="ae-muted">Click any box in the graph to see who comes through it and what it leads to.</p>}
          </Card>
          <Card title="How to read it">
            <ul className="ae-gkey">
              {([["read", "Carries read access"], ["write", "Carries write access"], ["own", "Carries ownership"],
                ["admin", "Admin bypass or account privilege: no grant needed"], ["use", "Lets them use or run something"],
                ["inherit", "Holds the role, leads to nothing on the ladder"]] as const).map(([k, t]) => (
                <li key={k}><span className={`ae-gline ae-gline-${k}`} aria-hidden />{t}</li>
              ))}
              {risky && <li><span className="ae-gline ae-gline-risk" aria-hidden />Risky: {Object.values(d.why).join(", ")}</li>}
            </ul>
            <p className="ae-muted">Thicker line, more people flow through it. People with exactly the same lines are stacked into one box.</p>
          </Card>
        </div>
      </div>
    </>
  );
}

function Detail({ d, n }: { d: MapPage; n: GraphNode }) {
  const c = useApp();
  const x = d.detail[n.id];
  const stack = n.marks.includes("stack");
  const fold = n.kind === "fold" || n.group != null;
  const fake = n.id === "Every object (admin)" || n.id === "ACCOUNT"; // drawn boxes, not roles or objects
  const droppable = !fake && n.id !== "PUBLIC" && !c.meta.admin_roles.includes(n.id) && n.kind !== "user" && n.kind !== "object";
  const open = () => (n.kind === "user" ? c.nav("access", { user: n.name }) : n.kind === "object" ? c.nav("object", { name: n.id }) : c.nav("access", { role: n.id }));
  const chips = (xs: string[], kind: string, more: number) => (
    <div className="ae-gchips">
      {xs.map((v) => <button type="button" key={v} className={`ae-chip ae-chip-${kind}`} onClick={() => c.set(startOf(kind, v))} title={`${v}: make it the start`}>{d.refs.labels[v] ?? v.split(".").pop()}</button>)}
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
