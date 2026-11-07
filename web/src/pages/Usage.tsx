// Screen 13, Granted vs used: what a person or role was granted next to what they used (ACCESS_HISTORY), weekly
// queries, last use and a suggestion. The unused grants go to the change plan (simulated on What if, never run).
import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, UsagePage, UsageRow } from "../api/types";
import { AccessPill, Card, CodeOutput, EmptyState, FilterChips, Tabs } from "../components";
import { useApp, useOpen } from "../ctx";
import type { Change } from "../components";
import { addTo, changeText, inPlan, plan, useSaved } from "./changeplan";
import { Load, Pick } from "./common";
import { bars, trimText, usageRows, type UsageFilter } from "./history";

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
/** The trim as CodeOutput revokes, with each object's type for the SQL. */
const revokes = (rows: UsageRow[]): Change[] => rows.flatMap((r) => r.changes.flatMap((ch) =>
  ch.op === "revoke_priv" ? [{ op: "revoke" as const, privilege: ch.privilege, object: r.object, objectType: r.type, to: ch.role }] : []));
const SUGGEST = { keep: "ae-sg-keep", trim: "ae-sg-trim", drop: "ae-sg-drop" } as const;

export function UsagePageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user);
  const s = useApi<UsagePage>("usage", { view: c.view, days: c.params.days, ...(role ? { role } : { user }) });
  const users = useApi<{ items: ListItem[] }>(mine ? null : "list", { what: "users", view: c.view });
  const roles = useApi<{ items: ListItem[] }>(mine ? null : "list", { what: "roles", view: c.view });
  const options = useMemo(() => [...(users.data?.items ?? []).map((i) => i.id), ...(roles.data?.items ?? []).map((i) => i.id)], [users.data, roles.data]);
  const pick = (v: string) => c.set(roles.data?.items.some((i) => i.id === v) && !users.data?.items.some((i) => i.id === v) ? { role: v, user: null } : { user: v, role: null });
  return (
    <>
      <div className="ae-headrow">
        {mine ? <h2 className="ae-h1">Granted vs used</h2> : (
          <div className="ae-h1 ae-h1-pick">Granted vs used for <Pick label="Person or role" value={role || user} options={options.length ? options : [role || user]} onPick={pick} width={260} /></div>
        )}
      </div>
      <Load s={s}>{(d) => <Body d={d} />}</Load>
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
  const [f, setF] = useState<UsageFilter>("all");
  const show = c.params.show === "trim" ? "trim" : "table";
  const rows = usageRows(d.rows, f);
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
        { key: "table", label: "Granted vs used", count: d.rows.length },
        { key: "trim", label: "Trim to what is used", count: n.changes },
      ]} />
      {show === "table" && (
        <Card>
          <FilterChips label="Show" value={f} onPick={(k) => setF(k as UsageFilter)} items={[
            { key: "all", label: "All", count: d.rows.length }, { key: "drop", label: "Not used", count: n.drop },
            { key: "trim", label: "Partly used", count: n.trim }, { key: "keep", label: "Keep", count: n.keep },
            { key: "sensitive", label: "Sensitive", count: d.rows.filter((r) => r.sensitive).length }]} />
          {!rows.length ? <EmptyState title="Nothing here">{d.rows.length ? "Change the filter." : "No tables or views reached."}</EmptyState> : (
            <div className="ae-olist" role="table">
              <div className="ae-urow ae-orow-h" role="row"><span>Object</span><span>Granted</span><span>Actually used</span><span>Queries per week</span><span>Last used</span><span>Suggestion</span></div>
              {rows.map((r) => <Row key={r.object} r={r} weeks={d.weeks} open={o.open} />)}
            </div>
          )}
          {n.changes > 0 && <Trim d={d} added={added} />}
          <p className="ae-muted ae-foot">Usage {d.source === "demo values" ? "values are demo values; in Snowflake they come" : "comes"} from SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
            (query metadata, Enterprise edition), refreshed with each snapshot. {w.kind === "user" ? "" : "For a role: used by any of its people, through any of their roles."}</p>
        </Card>
      )}
      {show === "trim" && (
        <Card title="Trim to what is used" sub="Revokes of the grants not used in this period, where they are granted: everyone else holding that role loses them too. Simulate before you change anything.">
          {!d.changes.length ? <EmptyState title="Nothing to trim">Every grant was used in the last {d.days} days{d.rows.some((r) => r.suggest === "trim") ? " (ownership is transferred, not revoked)" : ""}.</EmptyState> : <>
            <ul className="ae-plain">{d.changes.map((ch) => <li key={changeText(ch)} className="ae-mono">{changeText(ch)}</li>)}</ul>
            <div className="ae-actions">
              <button type="button" className="ae-btn ae-btn-primary" disabled={added} onClick={() => plan.set(addTo(plan.get(), d.changes))}>{added ? "In the change plan ✓" : "Add to change plan"}</button>
              <button type="button" className="ae-btn" onClick={() => c.nav("whatif", { show: "plan" })}>Open the change plan</button>
            </div>
            <CodeOutput changes={revokes(d.rows)} name="trim_unused" note={{ reason: `not used in the last ${d.days} days (ACCESS_HISTORY)` }} />
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
        <div className="ae-muted">{trimText(d.rows)}</div>
      </div>
      <div className="ae-actions">
        <button type="button" className="ae-btn ae-btn-primary" disabled={added} onClick={() => plan.set(addTo(plan.get(), d.changes))}>{added ? "In the change plan ✓" : "Add to change plan"}</button>
        <button type="button" className="ae-btn" onClick={() => c.set({ show: "trim" })}>See the revokes</button>
      </div>
    </div>
  );
}
