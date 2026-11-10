// Screen 0: start with a question. Search (people, roles, objects), "can X read Y" goes to Can they?, my access,
// account risks, data protection, recently viewed.
import { useEffect, useRef, useState } from "react";
import { get, useApi } from "../api/client";
import type { FindItem, HomePage, Page } from "../api/types";
import { Card, StackBar, type BarPart } from "../components";
import { useApp } from "../ctx";
import { Load } from "./common";

const RECENT = "ae-recent";

/** A search hit (top bar or Home): a person or role opens on Access, an object on Who has access. */
export function openFound(i: FindItem, nav: (p: Page, params: Record<string, string>) => void) {
  remember({ page: i.page, id: i.id, label: i.name });
  if (i.kind === "user") nav("access", { user: i.name });
  else if (i.kind === "object") nav("object", { name: i.id });
  else nav("access", { role: i.id });
}
type Recent = { page: Page; id: string; label: string };

export function recent(): Recent[] {
  try { return JSON.parse(localStorage.getItem(RECENT) ?? "[]"); } catch { return []; }
}

export function remember(r: Recent) {
  try { localStorage.setItem(RECENT, JSON.stringify([r, ...recent().filter((x) => x.id !== r.id)].slice(0, 8))); } catch { /* no storage */ }
}

/** "can ENGINEER_01 read SALES.CORE.TBL_CUSTOMER" -> who (a user, or a role such as F_MARKETING: Can they? takes a
 * name that is no user as the role), what, verb. */
export function parseQuestion(q: string): { who: string; what: string; priv: string } | null {
  const m = q.trim().match(/^can\s+(\S+)\s+(read|select|change|write|insert|update|delete|own)\s+(\S+?)\??$/i);
  if (!m) return null;
  const v = m[2].toLowerCase();
  const priv = v === "own" ? "OWNERSHIP" : v === "read" || v === "select" ? "SELECT" : v === "change" || v === "write" ? "INSERT" : v.toUpperCase();
  return { who: m[1].toUpperCase(), what: m[3].toUpperCase(), priv };
}

/** Screens whose name matches the search (2+ letters), so "graph" or "used" open them from Home. */
export function screensFor<T extends { key: string; label: string }>(q: string, pages: T[]): T[] {
  const t = q.trim().toLowerCase();
  return t.length < 2 ? [] : pages.filter((p) => p.key !== "home" && p.label.toLowerCase().includes(t));
}

type Who = { kind: string; id: string; name: string };
type Short = { page: Page; label: string; params: Record<string, string> };

const SHORT: [Page, string, ((w: Who) => Short | null)?][] = [
  ["check", "Can they read …?", (w) => (w.kind === "object" ? null : { page: "check", label: `Can ${w.name} read …?`, params: { [w.kind === "user" ? "name" : "role"]: w.kind === "user" ? w.name : w.id } })],
  ["graph", "Access graph", (w) => ({ page: "graph", label: `Graph of ${w.name}`, params: { [w.kind === "user" ? "user" : w.kind === "object" ? "table" : "role"]: w.kind === "user" ? w.name : w.id } })],
  ["compare", "Compare two people", (w) => (w.kind === "object" ? null : { page: "compare", label: `Compare ${w.name} with …`, params: { a: w.id } })],
  ["request", "Request access"], ["rules", "Risks & fixes"], ["whatif", "What if a role goes?"], ["sensitive", "Sensitive data"],
  ["flow", "Sensitive data flow"], ["usage", "Granted vs used"], ["changes", "What changed"]];

/** The shortcuts to the pages in the nav (My access has no flow or changes), filled in with who (the first search hit
 * or the default user) where the question is about someone. */
export const shortcuts = (keys: string[], who?: Who | null): Short[] =>
  SHORT.filter(([p]) => keys.includes(p)).map(([page, label, fill]) => (who && fill?.(who)) || { page, label, params: {} });

const GROUP: [string, string][] = [["user", "People"], ["role", "Roles"], ["warehouse", "Warehouses"], ["object", "Objects"]];
export const groupOf = (i: Pick<FindItem, "kind" | "type">) =>
  i.kind === "user" ? "user" : i.kind !== "object" ? "role" : i.type === "WAREHOUSE" ? "warehouse" : "object";

export function HomePageView() {
  const c = useApp();
  const s = useApi<HomePage>("home", { view: c.view });
  const [q, setQ] = useState("");
  const [items, setItems] = useState<FindItem[]>([]);
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const f = (e: KeyboardEvent) => { if (e.key === "/" && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); box.current?.focus(); } };
    addEventListener("keydown", f);
    return () => removeEventListener("keydown", f);
  }, []);
  useEffect(() => {
    if (q.trim().length < 2 || parseQuestion(q)) { setItems([]); return; }
    const t = setTimeout(() => { get<{ items: FindItem[] }>("find", { q, view: c.view, limit: "24" }).then((r) => setItems(r.items), () => setItems([])); }, 160);
    return () => clearTimeout(t);
  }, [q, c.view]);
  const openItem = (i: FindItem) => openFound(i, c.nav);
  const ask = parseQuestion(q);
  const screens = ask ? [] : screensFor(q, c.meta.pages);
  const go = () => {
    if (ask) c.nav("check", { name: ask.who, obj: ask.what, priv: ask.priv });
    else if (items[0]) openItem(items[0]);
  };
  const rec = recent();
  const [rows, setRows] = useState(false);
  const first = items[0], me = c.meta.default_user;
  const who: Who | null = first ? { kind: first.kind, id: first.id, name: first.name } : me ? { kind: "user", id: me, name: me } : null;
  return (
    <div className="ae-home">
      <h2 className="ae-h1">Who can access what in Snowflake?</h2>
      <div className="ae-bigsearch">
        <label className="ae-sr" htmlFor="ae-home-q">Search</label>
        <input id="ae-home-q" ref={box} type="search" className="ae-input" value={q} autoComplete="off"
          placeholder="Find a person, role or table, or ask: can ENGINEER_01 read SALES.CORE.TBL_CUSTOMER"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") go(); if (e.key === "Escape") setQ(""); }} />
        {!q && <span className="ae-muted ae-kbd">Press / to search</span>}
      </div>
      {ask && (
        <button type="button" className="ae-askrow" onClick={go}>
          Can <b className="ae-mono">{ask.who}</b> {ask.priv === "SELECT" ? "read" : ask.priv.toLowerCase()} <b className="ae-mono">{ask.what}</b>? <span className="ae-muted">Enter to check</span>
        </button>
      )}
      {(items.length > 0 || screens.length > 0) && (
        <div className="ae-suggest">
          {screens.length > 0 && (
            <div>
              <h4>Screens</h4>
              {screens.map((p) => (
                <button type="button" key={p.key} className="ae-suggest-row" onClick={() => c.nav(p.key, {})}>
                  <span>{p.label}</span><span className="ae-muted">{p.group === "admin" ? "Admin" : p.group === "detail" ? "Detail" : "Answers"}</span>
                </button>
              ))}
            </div>
          )}
          {GROUP.map(([g, label]) => {
            const xs = items.filter((i) => groupOf(i) === g);
            return xs.length ? (
              <div key={g}>
                <h4>{label}</h4>
                {xs.slice(0, 8).map((i) => (
                  <button type="button" key={i.id} className="ae-suggest-row" onClick={() => openItem(i)}>
                    <span className="ae-mono">{i.name}</span><span className="ae-muted">{i.kind_label}{i.sensitive ? " · sensitive" : ""}{i.answer ? ` · ${i.answer}` : ""}</span>
                  </button>
                ))}
              </div>
            ) : null;
          })}
        </div>
      )}
      <div className="ae-shortcuts">
        <span className="ae-muted">Try:</span>
        {shortcuts(c.meta.pages.map((p) => p.key), who).map((x) => <button type="button" key={x.page} className="ae-link" onClick={() => c.nav(x.page, x.params)}>{x.label}</button>)}
      </div>
      <Load s={s}>{(d) => (
        <>
          <div className="ae-two">
            {d.me && (
              <Card title={c.view === "mine" ? "My access" : `Access of ${d.me.user}`} right={<button type="button" className="ae-btn" onClick={() => c.nav("access", c.view === "mine" ? {} : { user: d.me!.user })}>Open</button>}>
                <Ladder counts={d.me.counts} />
                <p className="ae-muted">Reads {d.me.counts.read} · changes {d.me.counts.change} · owns {d.me.counts.own} · runs {d.me.counts.runnable} · {d.me.counts.account} account powers</p>
              </Card>
            )}
            {d.risks && (
              <Card title="Account risks" right={<button type="button" className="ae-btn" onClick={() => c.nav("rules", {})}>Risks & fixes</button>}>
                <StackBar parts={sevParts(d.risks)} />
                <p className="ae-muted">{d.counts.users} users · {d.counts.roles} roles · {d.counts.objects} objects</p>
                {d.per_rule && <Areas perRule={d.per_rule} />}
              </Card>
            )}
          </div>
          {d.protection && (
            <section className="ae-prot">
              <h3>Data protection</h3>
              <div className="ae-tiles">
                <button type="button" className={`ae-tile${d.protection.unmasked ? " ae-tile-bad" : ""}`} onClick={() => c.nav("rules", { rule: "6" })}>
                  <span className="ae-tile-l">Sensitive columns not masked</span><span className="ae-tile-v">{d.protection.unmasked}</span>
                  <span className="ae-tile-c ae-mono">{d.protection.unmasked_names.join(", ")}</span>
                </button>
                <button type="button" className={`ae-tile${d.protection.dormant ? " ae-tile-warn" : ""}`} onClick={() => c.nav("rules", { rule: "7" })}>
                  <span className="ae-tile-l">Dormant or disabled people reading sensitive data</span><span className="ae-tile-v">{d.protection.dormant}</span>
                  <span className="ae-tile-c ae-mono">{d.protection.dormant_names.join(", ")}</span>
                </button>
                <button type="button" className="ae-tile" onClick={() => c.nav("sensitive", { show: "catalog" })}>
                  <span className="ae-tile-l">Tagged objects · masked columns</span><span className="ae-tile-v">{d.protection.tagged} · {d.protection.masked}</span>
                </button>
                <button type="button" className="ae-tile" onClick={() => c.nav("flow", {})}>
                  <span className="ae-tile-l">Where sensitive data flows</span><span className="ae-tile-v ae-tile-vs">Data flow →</span>
                  <span className="ae-tile-c">people → roles → sensitive objects</span>
                </button>
                <button type="button" className={`ae-tile${rows ? " on" : ""}`} aria-pressed={rows} onClick={() => setRows(!rows)} disabled={!d.protection.row_tables}>
                  <span className="ae-tile-l">Tables with row policies</span><span className="ae-tile-v">{d.protection.row_tables}</span>
                  <span className="ae-tile-c">{rows ? "hide the list" : "show the list"}</span>
                </button>
              </div>
              {rows && (
                <Card title="Tables with row policies" sub="Each row policy decides which rows a role sees. Open a table for who reads it.">
                  {d.protection.row_list.map((r) => (
                    <button type="button" key={r.object} className="ae-suggest-row" onClick={() => c.nav("object", { name: r.object })}>
                      <span className="ae-mono">{r.object}</span><span className="ae-muted">{r.policies.map((p) => p.split(".").pop()).join(", ")}</span>
                    </button>
                  ))}
                </Card>
              )}
            </section>
          )}
          {rec.length > 0 && (
            <div className="ae-shortcuts">
              <span className="ae-muted">Recently viewed:</span>
              {rec.map((r) => <button type="button" key={r.id} className="ae-pchip"
                onClick={() => (r.page === "user" ? c.nav("access", { user: r.label }) : r.page === "role" ? c.nav("access", { role: r.id }) : c.nav(r.page, { name: r.id }))}>{r.label}</button>)}
            </div>
          )}
        </>
      )}</Load>
    </div>
  );
}

/** Read only / read + change / owns: the access ladder as one bar (Home, and the Access screen where it filters). */
export const ladderParts = (counts: { read: number; change: number; own: number }): BarPart[] => [
  { key: "read", label: "Read only", value: counts.read - counts.change, cls: "lvl-read" },
  { key: "change", label: "Read + change", value: counts.change - counts.own, cls: "lvl-change" },
  { key: "own", label: "Owns", value: counts.own, cls: "lvl-own" }];

function Ladder({ counts }: { counts: { read: number; change: number; own: number } }) {
  return <StackBar parts={ladderParts(counts)} />;
}

export const sevParts = (n: Record<string, number>): BarPart[] => [
  { key: "High", label: "High", value: (n.High ?? 0) + (n.Critical ?? 0), cls: "high" },
  { key: "Medium", label: "Medium", value: n.Medium ?? 0, cls: "medium" }, { key: "Low", label: "Low", value: n.Low ?? 0, cls: "low" }];

/** Findings per rule area: per severity, from the findings per rule and each rule's area and severity. */
export function areaCounts(rules: { num: string; area: string; severity: string }[], perRule: Record<string, number>) {
  const out = new Map<string, Record<string, number>>();
  for (const r of rules) {
    const m = out.get(r.area) ?? { Critical: 0, High: 0, Medium: 0, Low: 0 };
    m[r.severity] = (m[r.severity] ?? 0) + (perRule[r.num] ?? 0);
    out.set(r.area, m);
  }
  return [...out].map(([area, n]) => ({ area, n, total: Object.values(n).reduce((a, b) => a + b, 0) }));
}

/** One small bar per rule area, longest first; a click opens that area on the Rules list. */
function Areas({ perRule }: { perRule: Record<string, number> }) {
  const c = useApp();
  const rows = areaCounts(c.meta.rules, perRule).filter((r) => r.total).sort((x, y) => y.total - x.total);
  const max = Math.max(1, ...rows.map((r) => r.total));
  if (!rows.length) return null;
  return (
    <div className="ae-areas" aria-label="Findings by area">
      <div className="ae-muted ae-areas-h">Findings by area</div>
      {rows.map((r) => (
        <button type="button" key={r.area} className="ae-area" onClick={() => c.nav("rules", { show: "list", area: r.area })} title={`Open ${r.area} on the Rules list`}>
          <span className="ae-area-name">{r.area}</span>
          <span className="ae-area-track" style={{ width: `${(100 * r.total) / max}%` }}>
            {sevParts(r.n).map((p) => p.value > 0 && <span key={p.key} className={`ae-bar-${p.cls}`} style={{ flex: p.value }} />)}
          </span>
          <b className="ae-area-n">{r.total}</b>
        </button>
      ))}
    </div>
  );
}
