// Screen 16, where sensitive data flows: people -> the role they were granted -> sensitive object. Box height and
// line width = people. A click follows one box (sel= in the URL); the default is the dormant or disabled people.
import { useApi } from "../api/client";
import type { FlowNode, FlowPage } from "../api/types";
import { Banner, Card } from "../components";
import { apiParams, useApp } from "../ctx";
import { Head, Load } from "./common";
import { follow, linkKey } from "./signoff";

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
        : <Body d={d} />}</Load>
    </>
  );
}

function sub(n: FlowNode, col: number): string {
  if (col === 0) return n.users.length <= 3 ? n.users.join(", ") : plural(n.users.length, "person", "people");
  if (col === 1) return n.kind === "admin" ? "inherit everything" : plural(n.users.length, "person", "people");
  if (n.unmasked?.length) return `${n.unmasked.join(", ")} unmasked`;
  if (n.masked?.length) return `${n.masked.join(", ")} masked`;
  return n.row_policies?.length ? `${n.ns} · rows by ${n.row_policies.map((p) => p.split(".").pop()).join(", ")}` : `${n.ns} · whole object`;
}

function Body({ d }: { d: FlowPage }) {
  const c = useApp();
  const all = [...d.groups, ...d.roles, ...d.objects];
  const raw = c.params.sel === "none" ? null : c.params.sel ?? d.select;
  const sel = raw && all.some((n) => n.id === raw) ? raw : null;
  const f = follow(d, sel);
  const cols = [d.groups, d.roles, d.objects];
  const most = Math.max(...cols.map((xs) => xs.reduce((s, n) => s + n.users.length, 0)));
  const unit = Math.max(2, Math.min(9, 520 / Math.max(most, 1)));
  const pos = new Map<string, { x: number; y: number; h: number; col: number; n: FlowNode }>();
  const ys = cols.map((xs, i) => xs.reduce((y, n) => { const h = Math.max(MIN, n.users.length * unit); pos.set(n.id, { x: COLX[i], y, h, col: i, n }); return y + h + GAP; }, TOP));
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
              const k = linkKey(l.source, l.target), n = sel ? f.width.get(k) ?? 0 : l.users.length;
              const x1 = a.x + W, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, mx = (x1 + x2) / 2;
              const tone = TONE[a.col === 0 ? l.source : f.tone.get(k) ?? "active"] ?? TONE.active;
              return <path key={k} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} fill="none" stroke={tone}
                strokeWidth={Math.max(2, Math.min(n || l.users.length, 40) * Math.min(3, unit * 0.6))} opacity={n ? 0.5 : 0.07}><title>{`${l.source} → ${l.target}: ${plural(n || l.users.length, "person", "people")}`}</title></path>;
            })}
          </svg>
          {[...pos.values()].map(({ x, y, h, col, n }) => {
            const kind = col === 0 ? `ae-fn-${n.id}` : col === 1 ? (n.kind === "admin" ? "ae-fn-admin" : "ae-fn-role") : "ae-fn-obj";
            const dim = f.lit && !f.lit.has(n.id);
            return (
              <button key={n.id} type="button" aria-pressed={sel === n.id} className={`ae-fnode ${kind}${sel === n.id ? " on" : ""}${dim ? " dim" : ""}`}
                style={{ left: x, top: y, width: W, height: h }} title={`${n.id}\n${n.users.join(", ")}`} onClick={() => c.set({ sel: sel === n.id ? "none" : n.id })}>
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
          <div><b className="ae-mono">{picked.n.label}</b> <span className="ae-muted">{plural(picked.n.users.length, "person", "people")}</span></div>
          <div className="ae-objtags0">{picked.n.users.map((u) => <button type="button" key={u} className="ae-pchip" onClick={() => c.nav("access", { user: u })}>{u}</button>)}</div>
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
