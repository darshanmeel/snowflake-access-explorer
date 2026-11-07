// Screen 0: start with a question. Search (people, roles, objects), "can X read Y" goes to Can they?, my access,
// account risks, data protection, recently viewed.
import { useEffect, useRef, useState } from "react";
import { get, useApi } from "../api/client";
import type { FindItem, HomePage, Page } from "../api/types";
import { Card } from "../components";
import { useApp } from "../ctx";
import { Load } from "./common";

const RECENT = "ae-recent";
type Recent = { page: Page; id: string; label: string };

export function recent(): Recent[] {
  try { return JSON.parse(localStorage.getItem(RECENT) ?? "[]"); } catch { return []; }
}

export function remember(r: Recent) {
  try { localStorage.setItem(RECENT, JSON.stringify([r, ...recent().filter((x) => x.id !== r.id)].slice(0, 8))); } catch { /* no storage */ }
}

/** "can ENGINEER_01 read SALES.CORE.TBL_CUSTOMER" -> who, what, verb. */
export function parseQuestion(q: string): { who: string; what: string; priv: string } | null {
  const m = q.trim().match(/^can\s+(\S+)\s+(read|select|change|write|insert|update|delete|own)\s+(\S+?)\??$/i);
  if (!m) return null;
  const v = m[2].toLowerCase();
  const priv = v === "own" ? "OWNERSHIP" : v === "read" || v === "select" ? "SELECT" : v === "change" || v === "write" ? "INSERT" : v.toUpperCase();
  return { who: m[1].toUpperCase(), what: m[3].toUpperCase(), priv };
}

const GROUP: [string, string][] = [["user", "People"], ["role", "Roles"], ["object", "Objects"]];
const groupOf = (i: FindItem) => (i.kind === "user" ? "user" : i.kind === "object" ? "object" : "role");

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
  const openItem = (i: FindItem) => {
    remember({ page: i.page, id: i.id, label: i.name });
    if (i.kind === "user") c.nav("access", { user: i.name });
    else if (i.kind === "object") c.nav("object", { name: i.id });
    else c.nav("access", { role: i.id });
  };
  const ask = parseQuestion(q);
  const go = () => {
    if (ask) c.nav("check", { name: ask.who, obj: ask.what, priv: ask.priv });
    else if (items[0]) openItem(items[0]);
  };
  const rec = recent();
  return (
    <div className="ae-home">
      <h2 className="ae-h1">Who can access what in Snowflake?</h2>
      <div className="ae-bigsearch">
        <label className="ae-sr" htmlFor="ae-home-q">Search</label>
        <input id="ae-home-q" ref={box} type="search" className="ae-input" value={q} autoComplete="off"
          placeholder="Find a person, role or table, or ask: can ENGINEER_01 read SALES.CORE.TBL_CUSTOMER"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") go(); if (e.key === "Escape") setQ(""); }} />
        <span className="ae-muted ae-kbd">Press / to search</span>
      </div>
      {ask && (
        <button type="button" className="ae-askrow" onClick={go}>
          Can <b className="ae-mono">{ask.who}</b> {ask.priv === "SELECT" ? "read" : ask.priv.toLowerCase()} <b className="ae-mono">{ask.what}</b>? <span className="ae-muted">Enter to check</span>
        </button>
      )}
      {items.length > 0 && (
        <div className="ae-suggest">
          {GROUP.map(([g, label]) => {
            const xs = items.filter((i) => groupOf(i) === g);
            return xs.length ? (
              <div key={g}>
                <h4>{label}</h4>
                {xs.slice(0, 8).map((i) => (
                  <button type="button" key={i.id} className="ae-suggest-row" onClick={() => openItem(i)}>
                    <span className="ae-mono">{i.name}</span><span className="ae-muted">{i.kind_label}{i.sensitive ? " · sensitive" : ""}</span>
                  </button>
                ))}
              </div>
            ) : null;
          })}
        </div>
      )}
      <div className="ae-shortcuts">
        <span className="ae-muted">Try:</span>
        <button type="button" className="ae-link" onClick={() => c.nav("check", {})}>Can they read …?</button>
        <button type="button" className="ae-link" onClick={() => c.nav("rules", {})}>Risks & fixes</button>
        <button type="button" className="ae-link" onClick={() => c.nav("whatif", {})}>What if a role goes?</button>
        <button type="button" className="ae-link" onClick={() => c.nav("sensitive", {})}>Sensitive data</button>
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
                <Bar parts={[["High", d.risks.High + d.risks.Critical, "high"], ["Medium", d.risks.Medium, "medium"], ["Low", d.risks.Low, "low"]]} />
                <p className="ae-muted">{d.counts.users} users · {d.counts.roles} roles · {d.counts.objects} objects</p>
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
                <button type="button" className="ae-tile" onClick={() => c.nav("sensitive", {})}>
                  <span className="ae-tile-l">Tagged objects · masked columns</span><span className="ae-tile-v">{d.protection.tagged} · {d.protection.masked}</span>
                </button>
                <button type="button" className="ae-tile" onClick={() => c.nav("flow", {})}>
                  <span className="ae-tile-l">Where sensitive data flows</span><span className="ae-tile-v ae-tile-vs">Data flow →</span>
                  <span className="ae-tile-c">people → roles → sensitive objects</span>
                </button>
                <button type="button" className="ae-tile" onClick={() => c.nav("sensitive", {})}>
                  <span className="ae-tile-l">Tables with row policies</span><span className="ae-tile-v">{d.protection.row_tables}</span>
                </button>
              </div>
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

function Ladder({ counts }: { counts: { read: number; change: number; own: number } }) {
  const ro = counts.read - counts.change, ch = counts.change - counts.own;
  return <Bar parts={[["Read only", ro, "lvl-read"], ["Read + change", ch, "lvl-change"], ["Owns", counts.own, "lvl-own"]]} />;
}

function Bar({ parts }: { parts: [string, number, string][] }) {
  const total = parts.reduce((s, p) => s + p[1], 0) || 1;
  return (
    <div>
      <div className="ae-bar" aria-hidden>{parts.map(([l, v, k]) => v > 0 && <span key={l} className={`ae-bar-${k}`} style={{ width: `${(100 * v) / total}%` }} />)}</div>
      <div className="ae-bar-legend">{parts.map(([l, v, k]) => <span key={l}><span className={`ae-dot2 ae-bar-${k}`} />{l} <b>{v}</b></span>)}</div>
    </div>
  );
}
