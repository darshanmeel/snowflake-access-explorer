// Screen 16, where sensitive data flows: people -> the role they were granted -> sensitive object. Box height and
// line width = people. A click follows one box (sel= in the URL; the server answers its links and people in follow);
// the default is the dormant or disabled people.
import { useApi } from "../api/client";
import type { FlowNode, FlowPage } from "../api/types";
import { Banner, Card, DataTable, StackBar, Tabs } from "../components";
import { apiParams, useApp } from "../ctx";
import { col, Head, Load } from "./common";
import { linkKey } from "./signoff";

const W = 200, COLX = [0, 380, 760], TOP = 28, GAP = 12, MIN = 44;
const TONE: Record<string, string> = { active: "var(--ae-accent)", risky: "var(--ae-warn_ink)", admin: "var(--ae-lvl_admin_bg)", service: "var(--ae-line_strong)" };
const plural = (n: number, w: string, m = `${w}s`) => `${n} ${n === 1 ? w : m}`;

export function FlowPageView() {
  const c = useApp();
  const s = useApi<FlowPage>("flow", apiParams(c));
  return (
    <>
      <button type="button" className="ae-link ae-crumb" onClick={() => c.nav("review", { show: "grid" })}>← Review & sign-off</button>
      <Head title="Where sensitive data flows" sub="People → the role they were granted → the sensitive object. Line width = people. Click a box to follow it." />
      <Load s={s}>{(d) => d.state !== "ok"
        ? <Banner tone="info" title="Nothing to show" lines={[d.state === "mine" ? "The flow needs the shared snapshot: it is about everyone." : "No object carries a sensitive tag."]} />
        : <Flow d={d} />}</Load>
    </>
  );
}

function sub(n: FlowNode, col: number): string {
  if (col === 0) return plural(n.count, "person", "people");
  if (col === 1) return n.kind === "admin" ? "inherit everything" : plural(n.count, "person", "people");
  if (n.unmasked?.length) return `${n.unmasked.join(", ")} unmasked`;
  if (n.masked?.length) return `${n.masked.join(", ")} masked`;
  return n.row_policies?.length ? `${n.ns} · rows by ${n.row_policies.map((p) => p.split(".").pop()).join(", ")}` : `${n.ns} · whole object`;
}

/** Tables first: on a big account the drawing has thousands of boxes and lines, so it opens only on a click. */
function Flow({ d }: { d: FlowPage }) {
  const c = useApp();
  const show = c.params.show === "graph" ? "graph" : "table";
  return (
    <>
      <Tabs nav active={show} onChange={(k) => c.set({ show: k === "table" ? null : k })} tabs={[
        { key: "table", label: "Tables" }, { key: "graph", label: "Graph" }]} />
      {show === "table" ? <Tables d={d} /> : <Body d={d} />}
    </>
  );
}

type Obj = FlowNode & { roles: number };
type Role = FlowNode & { objects: number };

function Tables({ d }: { d: FlowPage }) {
  const c = useApp();
  const out = new Map<string, number>(), into = new Map<string, number>();
  d.links.forEach((l) => { out.set(l.source, (out.get(l.source) ?? 0) + 1); into.set(l.target, (into.get(l.target) ?? 0) + 1); });
  const objs: Obj[] = d.objects.map((n) => ({ ...n, roles: into.get(n.id) ?? 0 }));
  const roles: Role[] = d.roles.map((n) => ({ ...n, objects: out.get(n.id) ?? 0 }));
  const LABEL: Record<string, string> = { active: "Active people", risky: "Dormant or disabled", admin: "Admin", service: "Service" };
  return (
    <>
      <Card title="People who reach sensitive data" sub="Each person once, in their main group">
        <StackBar parts={d.groups.map((g) => ({ key: g.id, label: LABEL[g.id] ?? g.label, value: g.count, cls: g.id === "risky" ? "medium" : g.id === "admin" ? "high" : "low" }))} />
      </Card>
      <Card title="Sensitive objects" sub="People who can read each one, the roles they come through, and what is masked">
        <DataTable csv="sensitive_objects.csv" rows={objs} rowTone={(r) => (r.unmasked?.length ? "bad" : null)} onRowClick={(r) => c.nav("object", { name: r.id, show: "who" })}
          columns={[col("o", "Object", (r: Obj) => r.id, { wrap: "wrap" }), col("p", "People", (r: Obj) => r.count, { num: true }),
            col("r", "Through roles", (r: Obj) => r.roles, { num: true }),
            col("u", "Unmasked columns", (r: Obj) => (r.unmasked ?? []).join(", ")), col("m", "Masked columns", (r: Obj) => (r.masked ?? []).join(", ")),
            col("w", "Rows", (r: Obj) => (r.row_policies?.length ? `by ${r.row_policies.map((x) => x.split(".").pop()).join(", ")}` : "whole object"))]} />
      </Card>
      <Card title="Roles that lead there" sub="The role people were granted, the people holding it and the sensitive objects it reaches">
        <DataTable csv="sensitive_roles.csv" rows={roles} onRowClick={(r) => r.kind !== "admin" && r.kind !== "fold" && c.nav("access", { role: r.id })}
          columns={[col("r", "Role", (r: Role) => r.label, { wrap: "wrap" }), col("k", "Kind", (r: Role) => r.kind ?? ""),
            col("p", "People", (r: Role) => r.count, { num: true }), col("o", "Sensitive objects", (r: Role) => r.objects, { num: true })]} />
      </Card>
    </>
  );
}

function Body({ d }: { d: FlowPage }) {
  const c = useApp();
  const f = d.follow!, sel = f.sel, lit = f.lit && new Set(f.lit);
  const cols = [d.groups, d.roles, d.objects];
  const most = Math.max(...cols.map((xs) => xs.reduce((s, n) => s + n.count, 0)));
  const unit = Math.max(2, Math.min(9, 520 / Math.max(most, 1)));
  const pos = new Map<string, { x: number; y: number; h: number; col: number; n: FlowNode }>();
  const ys = cols.map((xs, i) => xs.reduce((y, n) => { const h = Math.max(MIN, n.count * unit); pos.set(n.id, { x: COLX[i], y, h, col: i, n }); return y + h + GAP; }, TOP));
  const gh = Math.max(...ys) + 8, gw = COLX[2] + W;
  const picked = sel ? pos.get(sel) : undefined;
  const open = (n: FlowNode, col: number) => (col === 2 ? c.nav("object", { name: n.id, show: "who" }) : c.nav("access", { role: n.id }));
  return (
    <Card>
      <div className="ae-flow-head">
        <b>{f.headline}</b>
        <button type="button" className="ae-btn" disabled={!sel} onClick={() => c.set({ sel: "none" })}>Show everyone</button>
      </div>
      <div className="ae-flow-wrap">
        <div className="ae-flow" style={{ width: gw, height: gh }}>
          {["People", "Through role", "Sensitive object"].map((t, i) => <span key={t} className="ae-flow-col" style={{ left: COLX[i] }}>{t}</span>)}
          <svg width={gw} height={gh} viewBox={`0 0 ${gw} ${gh}`} aria-hidden className="ae-flow-svg">
            {d.links.map((l) => {
              const a = pos.get(l.source), b = pos.get(l.target);
              if (!a || !b) return null;
              const k = linkKey(l.source, l.target), n = sel ? f.width[k] ?? 0 : l.count;
              const x1 = a.x + W, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, mx = (x1 + x2) / 2;
              const tone = TONE[a.col === 0 ? l.source : f.tone[k] ?? "active"] ?? TONE.active;
              return <path key={k} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} fill="none" stroke={tone}
                strokeWidth={Math.max(2, Math.min(n || l.count, 40) * Math.min(3, unit * 0.6))} opacity={n ? 0.5 : 0.07}><title>{`${l.source} → ${l.target}: ${plural(n || l.count, "person", "people")}`}</title></path>;
            })}
          </svg>
          {[...pos.values()].map(({ x, y, h, col, n }) => {
            const kind = col === 0 ? `ae-fn-${n.id}` : col === 1 ? (n.kind === "admin" ? "ae-fn-admin" : "ae-fn-role") : "ae-fn-obj";
            const dim = lit && !lit.has(n.id);
            return (
              <button key={n.id} type="button" aria-pressed={sel === n.id} className={`ae-fnode ${kind}${sel === n.id ? " on" : ""}${dim ? " dim" : ""}`}
                style={{ left: x, top: y, width: W, height: h }} title={`${n.id}\n${plural(n.count, "person", "people")}`} onClick={() => c.set({ sel: sel === n.id ? "none" : n.id })}>
                <span className="ae-fnode-l">{n.label}</span>
                <span className={`ae-fnode-s${col === 2 && n.unmasked?.length ? " bad" : ""}`}>{sub(n, col)}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="ae-bar-legend ae-flow-legend">
        {([["active", "Active people"], ["risky", "Dormant or disabled"], ["admin", "Admin"], ["service", "Service"]] as const).map(([k, l]) => (
          <span key={k}><span className="ae-flow-key" style={{ background: TONE[k] }} />{l}</span>))}
        <span className="ae-bad">Red text = columns with no masking</span>
      </div>
      {picked && (
        <div className="ae-flow-detail">
          <div><b className="ae-mono">{picked.n.label}</b> <span className="ae-muted">{plural(f.count, "person", "people")}{f.users.length < f.count ? ` (first ${f.users.length} shown)` : ""}</span></div>
          <div className="ae-objtags0">{f.users.map((u) => <button type="button" key={u} className="ae-pchip" onClick={() => c.nav("access", { user: u })}>{u}</button>)}</div>
          <div className="ae-row0">
            {(picked.col === 2 || (picked.col === 1 && picked.n.kind !== "admin" && picked.n.kind !== "fold")) &&
              <button type="button" className="ae-btn" onClick={() => open(picked.n, picked.col)}>{picked.col === 2 ? "Who has access" : "Open the role"}</button>}
            <button type="button" className="ae-btn" onClick={() => c.nav("review", { show: "grid", ...(picked.n.id === "risky" ? { stale: "1" } : {}) })}>Review these people</button>
          </div>
        </div>
      )}
    </Card>
  );
}
