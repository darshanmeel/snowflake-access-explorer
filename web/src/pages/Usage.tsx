// Screen 13, Granted vs used: what a person or role was granted next to what they used (ACCESS_HISTORY), weekly
// queries, last use and a suggestion. The unused grants go to the change plan (simulated on What if, never run).
import { get, useApi } from "../api/client";
import type { ListItem, UsagePage, UsageRow } from "../api/types";
import { AccessPill, Card, CodeOutput, EmptyState, FilterChips, ListToolbar, Pager, Tabs } from "../components";
import { download } from "../components/table";
import { apiParams, useApp, useOpen } from "../ctx";
import { addTo, changeText, inPlan, plan, planTexts, useSaved } from "./changeplan";
import { Load, Pick, PickFirst } from "./common";
import { bars, usageCsv, type UsageFilter } from "./history";
import { PAGE } from "./paged";

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
/** The trim's SQL as the server writes it (What if's text), with the reason. */
const trimTexts = (d: UsagePage) => {
  const t = planTexts(d.changes, d.sql);
  const why = `not used in the last ${d.days} days (ACCESS_HISTORY)`;
  return { sql: `-- Reason: ${why}\n${t.sql}`, tf: `# Reason: ${why}\n${t.tf}`, ticket: t.ticket.replace("Reason: (fill in)", `Reason: ${why}`) };
};
const SUGGEST = { keep: "ae-sg-keep", trim: "ae-sg-trim", drop: "ae-sg-drop" } as const;

export function UsagePageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user ?? "");
  const s = useApi<UsagePage>(role || user ? "usage" : null, { view: c.view, days: c.params.days, f: c.params.f, q: c.params.q,
    u_offset: c.params.u_offset, limit: c.params.limit, ...(role ? { role } : { user }) });
  const pick = (v: string, i: ListItem) => c.set(i.kind !== "user" ? { role: v, user: null } : { user: v, role: null });
  return (
    <>
      <div className="ae-headrow">
        {mine ? <h2 className="ae-h1">Granted vs used</h2> : (
          <div className="ae-h1 ae-h1-pick">Granted vs used for <Pick label="Person or role" value={role || user} user={!role} what="users,roles" onPick={pick} width={260} /></div>
        )}
      </div>
      {role || user ? <Load s={s}>{(d) => <Body d={d} />}</Load> : <PickFirst />}
    </>
  );
}

function Body({ d }: { d: UsagePage }) {
  const c = useApp();
  const w = d.who, user = w.kind === "user";
  const back: Record<string, string> = user ? { user: w.name } : { role: w.name };
  const period = (
    <FilterChips label="Period" value={String(d.days)} onPick={(k) => c.set({ days: k === "90" ? null : k })}
      items={d.periods.map((p) => ({ key: String(p), label: `${p} days` }))} />
  );
  return (
    <>
      <div className="ae-actions">
        <button type="button" className="ae-btn" onClick={() => c.nav("access", back)}>Access</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("see", back)}>What they see</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("access", { ...back, show: "history" })}>History</button>
      </div>
      {!d.available ? (
        <Card title="No usage to compare with">
          <EmptyState title="Granted vs used needs ACCESS_HISTORY">{d.reason}</EmptyState>
          <p className="ae-note">{d.enable}</p>
        </Card>
      ) : <Used d={d} period={period} />}
    </>
  );
}

function Used({ d, period }: { d: UsagePage; period: React.ReactNode }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const n = d.counts!, w = d.who;
  const f = d.f as UsageFilter, q = c.params.q ?? "", size = Number(c.params.limit) || PAGE;
  const show = c.params.show === "trim" ? "trim" : "table";
  const rows = d.rows;  // one page; the server filters (f), searches (q) and pages (u_offset, limit)
  const csv = async () => download(`${w.name}_granted_vs_used.csv`, usageCsv((await get<UsagePage>("usage", { ...apiParams(c), limit: "0", u_offset: "" })).rows));
  const list = useSaved(plan);
  const added = inPlan(list, d.changes);
  return (
    <>
      <div className="ae-usehead">
        <p className="ae-answer">
          In the last {d.days} days {w.kind === "user" ? "" : "people holding "}<span className="ae-mono">{w.name}</span> <b>used {n.used} of {n.objects}</b> tables and views they can reach
          {n.write_unused > 0 && <>, and <b>never used write access</b> on {plural(n.write_unused, "object")}</>}.
          {n.changes > 0 ? <> <span className="ae-ok-word">{plural(n.changes, "grant")} could go</span> without changing their work.</> : " Every grant is in use."}
        </p>
        {period}
      </div>
      <Tabs active={show} onChange={(k) => c.set({ show: k === "table" ? null : k })} tabs={[
        { key: "table", label: "Granted vs used", count: n.objects },
        { key: "trim", label: "Trim to what is used", count: n.changes },
      ]} />
      {show === "table" && (
        <Card>
          <ListToolbar search={q} onSearch={(v) => c.set({ q: v || null, u_offset: null })} onCsv={csv}>
            <FilterChips label="Show" value={f} onPick={(k) => c.set({ f: k === "all" ? null : k, u_offset: null })} items={[
              { key: "all", label: "All", count: n.objects }, { key: "drop", label: "Not used", count: n.drop },
              { key: "trim", label: "Partly used", count: n.trim }, { key: "keep", label: "Keep", count: n.keep },
              { key: "sensitive", label: "Sensitive", count: n.sensitive }]} />
          </ListToolbar>
          {!rows.length ? <EmptyState title="Nothing here">{n.objects ? "Change the filter or clear the search." : "No tables or views reached."}</EmptyState> : (
            <div className="ae-olist" role="table">
              <div className="ae-urow ae-orow-h" role="row"><span>Object</span><span>Granted</span><span>Actually used</span><span>Queries per week</span><span>Last used</span><span>Suggestion</span></div>
              {rows.map((r) => <Row key={r.object} r={r} weeks={d.weeks} open={o.open} />)}
            </div>
          )}
          {d.rows_total > size && <Pager at={Math.floor(d.offset / size)} size={size} total={d.rows_total} sizes={[25, 50, 100, 250]}
            onPage={(k) => c.set({ u_offset: k ? String(k * size) : null })} onSize={(k) => c.set({ limit: k === PAGE ? null : String(k), u_offset: null })} />}
          {n.changes > 0 && <Trim d={d} added={added} />}
          <p className="ae-muted ae-foot">Usage {d.source === "demo values" ? "values are demo values; in Snowflake they come" : "comes"} from SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
            (query metadata, Enterprise edition), refreshed with each snapshot. {w.kind === "user" ? "" : "For a role: used by any of its people, through any of their roles."}</p>
        </Card>
      )}
      {show === "trim" && (
        <Card title="Trim to what is used" sub="Revokes of the grants not used in this period, where they are granted: everyone else holding that role loses them too. Simulate before you change anything.">
          {d.changes_capped ? <EmptyState title={`${plural(n.changes, "revoke")}: too many to list here`}>The CSV of Granted vs used has every unused privilege, object by object.</EmptyState>
            : !d.changes.length ? <EmptyState title="Nothing to trim">Every grant was used in the last {d.days} days{n.trim ? " (ownership is transferred, not revoked)" : ""}.</EmptyState> : <>
            <ul className="ae-plain">{d.changes.map((ch) => <li key={changeText(ch)} className="ae-mono">{changeText(ch)}</li>)}</ul>
            <div className="ae-actions">
              <button type="button" className="ae-btn ae-btn-primary" disabled={added} onClick={() => plan.set(addTo(plan.get(), d.changes))}>{added ? "In the change plan ✓" : "Add to change plan"}</button>
              <button type="button" className="ae-btn" onClick={() => c.nav("whatif", { show: "plan" })}>Open the change plan</button>
            </div>
            <CodeOutput changes={[]} name="trim_unused" texts={trimTexts(d)} />
          </>}
        </Card>
      )}
    </>
  );
}

function Row({ r, weeks, open }: { r: UsageRow; weeks: string[]; open: (id: string) => void }) {
  const hs = bars(r.weeks);
  const ns = [r.database, r.schema].filter(Boolean).join(".");
  return (
    <div className="ae-urow" role="row">
      <span className="ae-ocell">
        <button type="button" className="ae-link ae-mono ae-oname" onClick={() => open(r.object)}>{r.object.split(".").pop()}</button>
        <span className="ae-muted ae-osub">{r.type.toLowerCase()}{ns ? ` · ${ns}` : ""}{r.sensitive && <span className="ae-sens-word"> · sensitive</span>}</span>
      </span>
      <AccessPill level={r.level} />
      {r.used ? <AccessPill level={r.used} /> : <span className="ae-lvl ae-lvl-none">Not used</span>}
      <span className="ae-bars" role="img" aria-label={r.used ? `Queries per week over ${weeks.length} weeks: ${r.weeks.join(", ")}` : `No queries in ${weeks.length} weeks`}>
        {hs.map((h, i) => <span key={weeks[i] ?? i} className={r.weeks[i] ? "on" : ""} style={{ height: h }} title={`Week of ${weeks[i]}: ${r.weeks[i]} quer${r.weeks[i] === 1 ? "y" : "ies"}`} />)}
      </span>
      <span className="ae-muted">{r.last ? r.last.slice(0, 10) : "never"}</span>
      <span><span className={`ae-sg ${SUGGEST[r.suggest]}`} title={r.unused.length ? `Not used: ${r.unused.join(", ")}` : undefined}>{r.text}</span></span>
    </div>
  );
}

function Trim({ d, added }: { d: UsagePage; added: boolean }) {
  const c = useApp();
  return (
    <div className="ae-trim">
      <div>
        <div className="ae-trim-t">Trim to what is used: {plural(d.counts!.changes, "grant")}</div>
        <div className="ae-muted">{d.trim_text}</div>
      </div>
      <div className="ae-actions">
        {!d.changes_capped && <button type="button" className="ae-btn ae-btn-primary" disabled={added} onClick={() => plan.set(addTo(plan.get(), d.changes))}>{added ? "In the change plan ✓" : "Add to change plan"}</button>}
        <button type="button" className="ae-btn" onClick={() => c.set({ show: "trim" })}>See the revokes</button>
      </div>
    </div>
  );
}
