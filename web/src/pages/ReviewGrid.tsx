// Screen 6, review grid: people x objects (or x the privileges of one object), cell = ladder colour + word, hover =
// path. Keep / Revoke per row (saved in this browser), revokes to the change plan, Sign off downloads a CSV.
import { useEffect, useState } from "react";
import { useApi } from "../api/client";
import type { GridPage } from "../api/types";
import { Card, EmptyState, FilterChips, LEVEL_WORD, ListToolbar, Toggle, useCsv } from "../components";
import { download } from "../components/table";
import { apiParams, useApp, useOpen } from "../ctx";
import { addTo, plan, saved, useSaved } from "./changeplan";
import { Load, Sel } from "./common";
import { gridRows, revokesOf, signoffCsv, type Decision } from "./signoff";

const decisions = saved<Record<string, Record<string, Decision>>>("ae-review", {}); // scope -> user -> decision
const SHOWN = 40;
const DB_CHIPS = 6;
const WORD: Record<string, string> = { ...LEVEL_WORD, read: "Read", change: "Change", own: "Own", use: "Use", names: "Names" };

/** Keep / Revoke for one person or a group: icon buttons, the word in the label and on hover. */
function Dec({ who, v, pick, hint }: { who: string; v?: Decision; pick: (v: Decision) => void; hint?: string | null }) {
  return (
    <span className="ae-rgrid-dec">
      <span className="ae-row0" role="group" aria-label={`Decision for ${who}`}>
        <button type="button" className={`ae-btn ae-dec${v === "keep" ? " ae-dec-keep" : ""}`} aria-pressed={v === "keep"} aria-label={`Keep ${who}`} title="Keep" onClick={() => pick("keep")}>✓</button>
        <button type="button" className={`ae-btn ae-dec${v === "revoke" ? " ae-dec-revoke" : ""}`} aria-pressed={v === "revoke"} aria-label={`Revoke ${who}`} title="Revoke" onClick={() => pick("revoke")}>✕</button>
      </span>
      {hint && <span className="ae-warn-word ae-small">{hint}</span>}
    </span>
  );
}

export function ReviewGrid() {
  const c = useApp();
  const [q, setQ] = useState(""), [asked, setAsked] = useState("");
  useEffect(() => { const t = setTimeout(() => setAsked(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  const s = useApi<GridPage>("grid", { ...apiParams(c), q: asked || null }); // the server filters and caps the people
  return <Load s={s}>{(d) => <Grid d={d} q={q} setQ={setQ} />}</Load>;
}

function Grid({ d, q, setQ }: { d: GridPage; q: string; setQ: (q: string) => void }) {
  const c = useApp();
  const csvOn = useCsv();
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
  const decideAll = (us: string[], v: Decision) => { // one decision for a group: all set, or all cleared when they had it
    const cur = { ...dec }, had = us.every((u) => cur[u] === v);
    for (const u of us) { if (had) delete cur[u]; else cur[u] = v; }
    decisions.set({ ...decisions.get(), [key]: cur });
  };
  const rows = gridRows(d.rows, people, stale, q);
  // people whose every cell is Admin are one row with one decision: their cells say nothing person by person
  const isAdm = (r: (typeof rows)[number]) => d.columns.length > 0 && d.columns.every((x) => r.cells[x.id]?.level === "admin");
  const admins = rows.filter(isAdm).map((r) => r.user);
  const rest = admins.length > 1 ? rows.filter((r) => !isAdm(r)) : rows;
  const shown = all ? rest : rest.slice(0, SHOWN);
  const sleepy = rows.filter((r) => r.suggest).map((r) => r.user);
  const partial = d.total > d.columns.length || d.matched > d.rows.length;
  const done = rows.filter((r) => dec[r.user]).length, revokes = rows.filter((r) => dec[r.user] === "revoke");
  const many = d.dbs.length > DB_CHIPS; // a big account: the databases in a picker, not a wall of chips above the grid
  const scopes = [{ key: "sensitive", label: "Sensitive data", count: d.sensitive }, ...(many ? [] : d.dbs.map((x) => ({ key: `db:${x}`, label: `Database ${x}` }))), { key: "all", label: "Everything" }];
  const pick = (k: string) => c.set(k.startsWith("db:") ? { scope: "db", db: k.slice(3), columns: null, object: null } : { scope: k, db: null, columns: null, object: null });
  const isObj = d.scope === "object";
  const what = isObj ? `privileges on ${d.object}` : d.scope === "sensitive" ? `the ${d.total} sensitive objects` : d.scope === "db" ? `database ${d.db}` : "the account's objects";
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
          {(d.total > d.columns.length || d.matched > d.rows.length) && <span className="ae-warn-word"> Partial: the grid draws {d.columns.length} of {d.total} objects and lists {d.rows.length} of {d.matched} people; pick a database or search for the rest.</span>}
        </p>
        <div className="ae-row">
          <button type="button" className="ae-btn" onClick={() => c.nav("sensitive", { show: "catalog" })}>Sensitive objects catalog</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("compare", {})}>Compare two</button>
          <button type="button" className="ae-btn" onClick={() => c.nav("flow", {})}>Data flow</button>
        </div>
      </div>
      <ListToolbar search={q} onSearch={setQ}
        onCsv={() => download(`access_review_${key.replace(/[^A-Za-z0-9_]+/g, "_")}.csv`, signoffCsv(d, rows, dec, reviewer.trim(), "not signed"))}>
        {isObj ? <span className="ae-chip ae-chip-plain">{d.object} · privileges <button type="button" className="ae-link" onClick={() => pick("all")} aria-label="Back to objects">×</button></span>
          : <><FilterChips label="Scope" value={d.scope === "db" ? `db:${d.db}` : d.scope} onPick={pick} items={scopes} />
            {many && <Sel label="Database" value={d.scope === "db" ? d.db : ""} onPick={(v) => pick(v ? `db:${v}` : "sensitive")}
              options={[["", "One database…"], ...d.dbs.map((x): [string, string] => [x, x])]} />}</>}
        <Toggle label="People only" on={people} onPick={(v) => c.set({ people: v ? null : "0" })} />
        <Toggle label="Only dormant / disabled" on={stale} onPick={(v) => c.set({ stale: v ? "1" : null })} />
        <Toggle label="Hide USAGE" on={hide} onPick={(v) => c.set({ hideusage: v ? null : "0" })} />
      </ListToolbar>
      <Card title={isObj ? `Who holds each privilege on ${d.object.split(".").pop()}` : d.scope === "sensitive" ? "Who can reach each sensitive object" : "Who can reach each object"}
        sub={[d.total > d.columns.length && `First ${d.columns.length} of ${d.total} objects, most people first`,
          d.matched > d.rows.length && `first ${d.rows.length} of ${d.matched} people, admins and the highest access first: search or filter for the others`]
          .filter(Boolean).join("; ").replace(/^./, (x) => x.toUpperCase()) || undefined}
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
              {admins.length > 1 && (
                <div role="row" className="ae-rgrid-row ae-rgrid-group" style={{ gridTemplateColumns: tpl }}>
                  <span className="ae-rgrid-who"><b>Admin holders · {admins.length} people</b>
                    <span className="ae-muted ae-small" title={admins.join(", ")}>{admins[0]}{admins.length > 1 ? ` +${admins.length - 1}` : ""}</span></span>
                  <span className="ae-gcell ae-lvl-admin" style={{ gridColumn: `span ${d.columns.length}` }}>Admin on every object: an admin role inherits every role</span>
                  <Dec who={`the ${admins.length} admin holders`} v={admins.every((u) => dec[u] === "keep") ? "keep" : admins.every((u) => dec[u] === "revoke") ? "revoke" : undefined}
                    pick={(v) => decideAll(admins, v)} />
                </div>
              )}
              {shown.map((r) => {
                const v = dec[r.user];
                return (
                  <div key={r.user} role="row" className={`ae-rgrid-row${r.suggest ? " ae-rgrid-stale" : ""}`} style={{ gridTemplateColumns: tpl }}>
                    <span className="ae-rgrid-who">
                      <button type="button" className="ae-link ae-mono" onClick={() => c.nav("access", { user: r.user })}>{r.user}</button>
                      <span className={r.suggest ? "ae-warn-word" : "ae-muted"}>{r.type.includes("SERVICE") ? "Service" : "Person"} · {r.suggest ?? "active"} · {r.last_login}</span>
                      {(r.beyond ?? 0) > 0 && <span className="ae-muted ae-small">+{r.beyond} objects not drawn</span>}
                    </span>
                    {d.columns.map((x) => {
                      const cl = r.cells[x.id];
                      return cl ? <span key={x.id} className={`ae-gcell ae-lvl-${cl.level}`} title={`${cl.path.join(" › ")}\n${cl.privileges.join(", ")}`}>{isObj && cl.level !== "admin" ? "Has" : WORD[cl.level] ?? cl.level}</span>
                        : <span key={x.id} className="ae-gcell ae-gcell-none" title="No access">·</span>;
                    })}
                    <Dec who={r.user} v={v} pick={(x) => decide(r.user, x)} hint={r.suggest && v !== "revoke" ? `Suggested: revoke (${r.suggest})` : null} />
                  </div>
                );
              })}
            </div>
            {rest.length > SHOWN && <p className="ae-muted">Showing {shown.length} of {rest.length} people · <button type="button" className="ae-link" onClick={() => setAll(!all)}>{all ? "show fewer" : `show ${rest.length - SHOWN} more`}</button></p>}
          </div>
        )}
      </Card>
      {partial && <p className="ae-signwarn" role="note">Not the whole review: {d.rows.length < d.matched ? `${d.rows.length.toLocaleString()} of ${d.matched.toLocaleString()} people listed` : ""}{d.rows.length < d.matched && d.columns.length < d.total ? ", " : ""}{d.columns.length < d.total ? `${d.columns.length} of ${d.total.toLocaleString()} objects drawn` : ""}. A sign-off here covers only these: pick a database or search for the rest.</p>}
      <section className="ae-signbar">
        <span className="ae-signbar-prog">
          <span><b>{done}</b> of {d.matched.toLocaleString()} decided · <b>{revokes.length}</b> marked revoke</span>
          <span className="ae-signbar-track" role="img" aria-label={`${done} of ${d.matched} people decided`}><span style={{ width: `${(100 * done) / Math.max(1, d.matched)}%` }} /></span>
        </span>
        {sleepy.length > 0 && <button type="button" className="ae-btn" onClick={() => decideAll(sleepy, "revoke")}
          title="Marks every dormant or disabled person listed here Revoke; a second click clears it">{sleepy.every((u) => dec[u] === "revoke") ? "Clear" : "Revoke"} all {sleepy.length} dormant / disabled</button>}
        <span className="ae-signbar-act">
          <button type="button" className="ae-btn" disabled={!revokes.length} title="Adds the granted roles of each revoked person to the change plan (simulation only)"
            onClick={() => { plan.set(addTo(plan.get(), revokesOf(rows, dec))); c.nav("whatif", { show: "plan" }); }}>Test revokes in the change plan</button>
          {csvOn && <>
            <label className="ae-signbar-who"><span className="ae-sr">Reviewer</span>
              <input className="ae-input" placeholder="Reviewer name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
            <button type="button" className="ae-btn ae-btn-primary" disabled={!reviewer.trim()} title={reviewer.trim() ? "Downloads the sign-off as CSV" : "Type the reviewer name first"} onClick={sign}>Sign off review</button>
          </>}
        </span>
      </section>
      <p className="ae-muted ae-small">Keep / Revoke are saved in this browser only.{csvOn ? " Sign off downloads a CSV (reviewer, decision, time);" : " CSV export is off here, so there is no sign-off file;"} nothing is written to Snowflake and no revoke runs.</p>
    </>
  );
}
