// Screen 6, review grid: people x objects (or x the privileges of one object), cell = ladder colour + word, hover =
// path. Keep / Revoke per row (saved in this browser), revokes to the change plan, Sign off downloads a CSV.
import { useState } from "react";
import { useApi } from "../api/client";
import type { GridPage } from "../api/types";
import { Card, EmptyState, FilterChips, LEVEL_WORD, Toggle } from "../components";
import { download } from "../components/table";
import { apiParams, useApp, useOpen } from "../ctx";
import { addTo, plan, saved, useSaved } from "./changeplan";
import { Load } from "./common";
import { gridRows, revokesOf, signoffCsv, type Decision } from "./signoff";

const decisions = saved<Record<string, Record<string, Decision>>>("ae-review", {}); // scope -> user -> decision
const SHOWN = 40;
const WORD: Record<string, string> = { ...LEVEL_WORD, read: "Read", change: "Change", own: "Own", use: "Use", names: "Names" };

export function ReviewGrid() {
  const c = useApp();
  const s = useApi<GridPage>("grid", apiParams(c));
  return <Load s={s}>{(d) => <Grid d={d} />}</Load>;
}

function Grid({ d }: { d: GridPage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const [all, setAll] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const people = c.params.people !== "0", stale = c.params.stale === "1", hide = c.params.hideusage !== "0";
  const key = d.scope === "object" ? `object:${d.object}` : d.scope === "db" ? `db:${d.db}` : d.scope;
  const store = useSaved(decisions);
  const dec = store[key] ?? {};
  const decide = (u: string, v: Decision) => {
    const cur = { ...dec };
    if (cur[u] === v) delete cur[u]; else cur[u] = v;
    decisions.set({ ...decisions.get(), [key]: cur });
  };
  const rows = gridRows(d.rows, people, stale);
  const shown = all ? rows : rows.slice(0, SHOWN);
  const done = rows.filter((r) => dec[r.user]).length, revokes = rows.filter((r) => dec[r.user] === "revoke");
  const scopes = [{ key: "sensitive", label: "Sensitive data", count: d.sensitive }, ...d.dbs.map((x) => ({ key: `db:${x}`, label: `Database ${x}` })), { key: "all", label: "Everything" }];
  const pick = (k: string) => c.set(k.startsWith("db:") ? { scope: "db", db: k.slice(3), columns: null, object: null } : { scope: k, db: null, columns: null, object: null });
  const isObj = d.scope === "object";
  const what = isObj ? `privileges on ${d.object}` : d.scope === "sensitive" ? `the ${d.columns.length} sensitive objects` : d.scope === "db" ? `database ${d.db}` : "the account's objects";
  const tpl = `minmax(200px, 220px) repeat(${Math.max(d.columns.length, 1)}, minmax(84px, 1fr)) 190px`;
  const sign = () => {
    const when = `${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`;
    download(`access_signoff_${key.replace(/[^A-Za-z0-9_]+/g, "_")}_${when.slice(0, 10)}.csv`, signoffCsv(d, rows, dec, reviewer.trim(), when));
  };
  return (
    <>
      <div className="ae-headrow">
        <p className="ae-answer">
          <b>{d.counts.people} people</b> {isObj ? "hold" : "can reach"} {what}.{d.counts.admin > 0 && <> {d.counts.admin} {d.counts.admin === 1 ? "is an admin" : "are admins"}</>}
          {d.counts.stale > 0 && <> and <span className="ae-warn-word">{d.counts.stale} {d.counts.stale === 1 ? "is" : "are"} dormant or disabled</span></>}. Mark each person Keep or Revoke, then sign off.
        </p>
        <div className="ae-row">
          <button type="button" className="ae-btn" onClick={() => c.nav("sensitive", { show: "catalog" })}>Sensitive objects catalog</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("compare", {})}>Compare two</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("flow", {})}>Data flow</button>
        </div>
      </div>
      <div className="ae-toolbar">
        {isObj ? <span className="ae-chip ae-chip-plain">{d.object} · privileges <button type="button" className="ae-link" onClick={() => pick("all")} aria-label="Back to objects">×</button></span>
          : <FilterChips label="Scope" value={d.scope === "db" ? `db:${d.db}` : d.scope} onPick={pick} items={scopes} />}
        <Toggle label="People only" on={people} onPick={(v) => c.set({ people: v ? null : "0" })} />
        <Toggle label="Only dormant / disabled" on={stale} onPick={(v) => c.set({ stale: v ? "1" : null })} />
        <Toggle label="Hide USAGE" on={hide} onPick={(v) => c.set({ hideusage: v ? null : "0" })} />
      </div>
      <Card title={isObj ? `Who holds each privilege on ${d.object.split(".").pop()}` : d.scope === "sensitive" ? "Who can reach each sensitive object" : "Who can reach each object"}
        sub={d.total > d.columns.length ? `First ${d.columns.length} of ${d.total} objects, most people first` : undefined}
        right={<span className="ae-bar-legend">{(["read", "change", "own", "admin"] as const).map((l) => <span key={l}><span className={`ae-dot2 ae-lvl-${l}`} />{WORD[l]}</span>)}<span className="ae-muted">Hover a cell for its path</span></span>}>
        {!rows.length || !d.columns.length ? <EmptyState title="Nobody here">Change the scope, or turn off Only dormant / disabled.</EmptyState> : (
          <div className="ae-grid-wrap">
            <div className="ae-rgrid" role="table" style={{ minWidth: 420 + d.columns.length * 90 }}>
              <div className="ae-rgrid-row ae-rgrid-h" role="row" style={{ gridTemplateColumns: tpl }}>
                <span>Person</span>
                {d.columns.map((x) => (
                  <span key={x.id} className="ae-rgrid-col" title={x.id}>
                    {isObj ? <b className="ae-mono">{x.name}</b> : <button type="button" className="ae-link ae-mono" onClick={() => o.open(x.id)}>{x.name}</button>}
                    <span className="ae-muted">{isObj ? x.note : x.ns}</span>
                    {x.note && !isObj && <span className="ae-sens-word">{x.note}</span>}
                  </span>
                ))}
                <span>Decision</span>
              </div>
              {shown.map((r) => {
                const v = dec[r.user];
                return (
                  <div key={r.user} role="row" className={`ae-rgrid-row${r.suggest ? " ae-rgrid-stale" : ""}`} style={{ gridTemplateColumns: tpl }}>
                    <span className="ae-rgrid-who">
                      <button type="button" className="ae-link ae-mono" onClick={() => c.nav("access", { user: r.user })}>{r.user}</button>
                      <span className={r.suggest ? "ae-warn-word" : "ae-muted"}>{r.type.includes("SERVICE") ? "Service" : "Person"} · {r.suggest ?? "active"} · {r.last_login}</span>
                    </span>
                    {d.columns.map((x) => {
                      const cl = r.cells[x.id];
                      return cl ? <span key={x.id} className={`ae-gcell ae-lvl-${cl.level}`} title={`${cl.path.join(" › ")}\n${cl.privileges.join(", ")}`}>{isObj && cl.level !== "admin" ? "Has" : WORD[cl.level] ?? cl.level}</span>
                        : <span key={x.id} className="ae-gcell ae-gcell-none" title="No access">·</span>;
                    })}
                    <span className="ae-rgrid-dec">
                      <span className="ae-row0" role="group" aria-label={`Decision for ${r.user}`}>
                        <button type="button" className={`ae-btn ae-dec${v === "keep" ? " ae-dec-keep" : ""}`} aria-pressed={v === "keep"} onClick={() => decide(r.user, "keep")}>Keep</button>
                        <button type="button" className={`ae-btn ae-dec${v === "revoke" ? " ae-dec-revoke" : ""}`} aria-pressed={v === "revoke"} onClick={() => decide(r.user, "revoke")}>Revoke</button>
                      </span>
                      {r.suggest && v !== "revoke" && <span className="ae-warn-word ae-small">Suggested: revoke ({r.suggest})</span>}
                    </span>
                  </div>
                );
              })}
            </div>
            {rows.length > SHOWN && <p className="ae-muted">Showing {shown.length} of {rows.length} people · <button type="button" className="ae-link" onClick={() => setAll(!all)}>{all ? "show fewer" : `show ${rows.length - SHOWN} more`}</button></p>}
          </div>
        )}
      </Card>
      <section className="ae-signbar">
        <span><b>{done}</b> of {rows.length} decided</span>
        <span><b>{revokes.length}</b> marked revoke</span>
        <span className="ae-signbar-act">
          <button type="button" className="ae-btn" disabled={!revokes.length} title="Adds the granted roles of each revoked person to the change plan (simulation only)"
            onClick={() => { plan.set(addTo(plan.get(), revokesOf(rows, dec))); c.nav("whatif", { show: "plan" }); }}>Test revokes in the change plan</button>
          <label className="ae-signbar-who"><span className="ae-sr">Reviewer</span>
            <input className="ae-input" placeholder="Reviewer name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
          <button type="button" className="ae-btn ae-btn-primary" disabled={!reviewer.trim()} title={reviewer.trim() ? "Downloads the sign-off as CSV" : "Type the reviewer name first"} onClick={sign}>Sign off review</button>
        </span>
      </section>
      <p className="ae-muted ae-small">Keep / Revoke are saved in this browser only. Sign off downloads a CSV (reviewer, decision, time); nothing is written to Snowflake and no revoke runs.</p>
    </>
  );
}
