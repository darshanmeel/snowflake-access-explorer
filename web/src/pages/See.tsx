// Screen 7: What they see + role usage. The old tables (What they see, Sensitive data they can see, Role usage) stay
// the default tab; "Column by column" has the sentence, one card per object and the role usage bars.
import { useMemo } from "react";
import { useApi } from "../api/client";
import type { ListItem, SeeCard, SeePage, SensitiveReach } from "../api/types";
import { Card, DataTable, EmptyState, FilterChips, IdentityCard, Tabs } from "../components";
import { useApp, useOpen } from "../ctx";
import { col, DataViews, Load, NameLink, pathCol, Pick, StateTag, Usage } from "./common";
import { seeSentence } from "./screens";

/** What the picker of screens 7 and 9 searches: people and roles (My access: the roles of your slice). */
export const subjects = (mine: boolean) => (mine ? "roles" : "users,roles");

export function SeePageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = mine ? "" : c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user);
  const s = useApi<SeePage>("see", { view: c.view, ...(role ? { role } : { user }) });
  const id = role || user;
  return (
    <>
      <div className="ae-headrow">
        {mine ? <h2 className="ae-h1">What I see</h2> : (
          <div className="ae-h1 ae-h1-pick">What <Pick label="Person or role" value={id} what={subjects(mine)} width={260}
            onPick={(v, i) => c.set(i.kind !== "user" ? { role: v, user: null } : { user: v, role: null })} /> sees</div>
        )}
      </div>
      <Load s={s}>{(d) => <Body d={d} />}</Load>
    </>
  );
}

function Body({ d }: { d: SeePage }) {
  const c = useApp();
  const w = d.who, user = w.kind === "user";
  const tab = c.params.show === "cards" ? "cards" : "detail";
  const sub: Record<string, string> = user ? { user: w.name } : { role: w.name };
  return (
    <>
      <IdentityCard name={w.name} tag={c.view === "mine" ? "You" : "Viewing"}
        line={user ? `${w.type === "SERVICE" ? "Service user" : "Person"} · ${w.status ?? ""}${w.default_role ? ` · default role ${w.default_role}` : ""}${w.secondary_all ? " · secondary roles ALL" : ""}` : w.type}
        roles={user ? w.roles.map((r) => ({ id: r, note: r === w.default_role ? "default" : "" })) : undefined} />
      <div className="ae-actions">
        <button type="button" className="ae-btn" onClick={() => c.nav("access", sub)}>Access</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("graph", sub)}>Show as graph</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("compare", { a: w.id })}>Compare with…</button>
      </div>
      <Tabs active={tab} onChange={(k) => c.set({ show: k === "detail" ? null : k })} tabs={[
        { key: "detail", label: "What they see · tables" },
        { key: "cards", label: "Column by column", count: d.cards.length },
      ]} />
      {tab === "detail" && <Old d={d} />}
      {tab === "cards" && <Cards d={d} />}
    </>
  );
}

/** The old User / Role tabs: What they see, Sensitive data they can see, Role usage. */
function Old({ d }: { d: SeePage }) {
  const c = useApp();
  const user = d.who.kind === "user";
  const part = c.params.part ?? "sees";
  return (
    <>
      <Tabs active={part} onChange={(k) => c.set({ part: k === "sees" ? null : k })} tabs={[
        { key: "sees", label: user ? "What they see" : "What it sees", count: d.can_read?.length ?? 0 },
        ...(user && d.sensitive?.known ? [{ key: "sens", label: "Sensitive data they can see", count: d.sensitive.rows.length, tone: "warn" as const }] : []),
        { key: "usage", label: "Role usage", count: d.usage?.roles.length ?? d.role_usage?.holders ?? 0 },
      ]} />
      {part === "sees" && (d.can_read?.length ? <DataViews views={d.can_read} title={user ? "What they see when they read" : "What it sees"} />
        : <EmptyState title={d.known ? "No protected object" : "Not known here"}>{d.known ? "Nothing they read has a tag, a masking policy or a row policy." : "Policies need the shared snapshot."}</EmptyState>)}
      {part === "sens" && d.sensitive && (
        <Card title="Sensitive data they can see" sub={`Reached through ${d.sensitive.roles.length} granted role(s)`}>
          <DataTable csv="sensitive_reach.csv" rows={d.sensitive.rows}
            columns={[col("o", "Object", (r: SensitiveReach) => r.object, { wrap: "nowrap" }),
              col("c", "Columns", (r: SensitiveReach) => r.cols.join(", "), { wrap: "wrap" }),
              col("r", "Granted role", (r: SensitiveReach) => r.role, { wrap: "nowrap", render: (r: SensitiveReach) => <NameLink id={r.role} refs={d.refs} /> }),
              col("t", "Sees", (r: SensitiveReach) => r.text, { wrap: "wrap" }),
              pathCol<SensitiveReach>(d.refs)]} />
        </Card>
      )}
      {part === "usage" && (d.usage ? <Usage u={d.usage} refs={d.refs} /> : <RoleUse d={d} />)}
    </>
  );
}

function RoleUse({ d }: { d: SeePage }) {
  const u = d.role_usage;
  if (!u) return null;
  const pct = u.holders ? Math.round((100 * u.used) / u.holders) : 0;
  return (
    <Card title="Role usage" sub="Users holding the role who used it in the query history">
      <div className="ae-gbar"><span style={{ width: `${pct}%` }} /></div>
      <p>{u.used} of {u.holders} holders used it{u.unused.length > 0 && <> · not used by {u.unused.slice(0, 12).join(", ")}{u.unused.length > 12 ? ` +${u.unused.length - 12}` : ""}</>}</p>
    </Card>
  );
}

function Cards({ d }: { d: SeePage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const only = c.params.all !== "1";
  const cards = d.cards.filter((x) => !only || x.sensitive);
  const n = d.counts;
  const s = n && seeSentence(n);
  const user = d.who.kind === "user";
  return (
    <>
      <div className="ae-headrow">
        {s ? <p className="ae-answer">When <span className="ae-mono">{d.who.name}</span> {user ? "queries, they see" : "is the role in use, it sees"} <b>{s.rows}</b> and{" "}
          <b className={n.clear ? "ae-sens-word" : undefined}>{s.cols}</b>. {s.fix}</p> : <p className="ae-muted">Policies are not known here: they need the shared snapshot.</p>}
        <FilterChips label="Show" value={only ? "sens" : "all"} onPick={(k) => c.set({ all: k === "all" ? "1" : null })}
          items={[{ key: "sens", label: "Only sensitive", count: d.cards.filter((x) => x.sensitive).length }, { key: "all", label: "All protected objects", count: d.cards.length }]} />
      </div>
      <div className="ae-whogrid">
        <div className="ae-seecards">
          {!cards.length && <EmptyState title="Nothing here">No {only ? "sensitive" : "protected"} object they can read.</EmptyState>}
          {cards.map((x) => <SeeObj key={x.object} x={x} open={o.open} rule={() => c.nav("rules", { rule: "6" })} />)}
        </div>
        <aside className="ae-whoside">
          {d.usage ? <UseBars d={d} /> : <RoleUse d={d} />}
        </aside>
      </div>
    </>
  );
}

const ROWS: Record<string, string> = { all: "all", filtered: "filtered", none: "none", unknown: "unknown" };

function SeeObj({ x, open, rule }: { x: SeeCard; open: (id: string) => void; rule: () => void }) {
  return (
    <section className="ae-card ae-seecard">
      <div className="ae-seecard-head">
        <div><button type="button" className="ae-link ae-mono" onClick={() => open(x.object)}>{x.object}</button> <span className="ae-muted">{x.type.toLowerCase()}</span></div>
        <span className="ae-chip ae-chip-plain" title={x.rows.reason}>Rows: {ROWS[x.rows.state]}{x.rows.policy ? ` · ${x.rows.policy.split(".").pop()}` : " · no row policy"}</span>
      </div>
      {x.columns.map((col) => (
        <div key={col.column} className="ae-seecol">
          <span className="ae-mono">{col.column}</span>
          <StateTag state={col.state} reason={col.reason} />
          <span>{col.reason}</span>
          {col.fix ? <button type="button" className="ae-link" onClick={rule}>Add masking →</button> : <span />}
        </div>
      ))}
      {!x.columns.length && <p className="ae-muted">No tagged or masked column: the object itself is tagged.</p>}
    </section>
  );
}

function UseBars({ d }: { d: SeePage }) {
  const o = useOpen(d.refs);
  const u = d.usage!;
  const max = Math.max(1, ...u.roles.map((r) => r.queries));
  const unused = u.roles.filter((r) => r.status === "unused");
  return (
    <Card title="Role usage" sub={u.source}>
      {!u.readable ? <p className="ae-muted">Query history is not readable with this role.</p> : (
        <div className="ae-gbars">
          {u.roles.map((r) => (
            <div key={r.role}>
              <div className="ae-gbars-h"><button type="button" className="ae-link ae-mono" onClick={() => o.open(r.role)}>{r.role}</button>
                <span><b>{r.queries}</b> queries{r.last_used ? ` · last ${r.last_used.slice(0, 10)}` : ""}</span></div>
              <div className="ae-gbar"><span style={{ width: `${(100 * r.queries) / max}%` }} className={r.status === "secondary" ? "ae-gbar-2" : undefined} /></div>
              <div className="ae-muted">{r.default ? "Used as default role" : r.status === "secondary" ? "Used as secondary role" : r.status === "unused" ? `Not used in ${u.days} days` : "Used"}</div>
            </div>
          ))}
        </div>
      )}
      {u.readable && <p className={unused.length ? "ae-note" : "ae-note ae-gok"}>{unused.length
        ? `${unused.map((r) => r.role).join(", ")} not used in ${u.days} days: a candidate to revoke (see What if).`
        : `Every granted role was used in the last ${u.days} days.`}</p>}
      {u.warehouses.length > 0 && <p className="ae-muted">Warehouses: {u.warehouses.map((w) => `${w.name} · ${w.queries} queries`).join(" · ")}</p>}
    </Card>
  );
}
