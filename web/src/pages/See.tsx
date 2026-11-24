// Screen 7: What they see + role usage. "Column by column" (the sentence, one card per object) first; the old tables
// (All protected, Sensitive reach, Role usage) are the other side-menu items.
import { useMemo } from "react";
import { useApi } from "../api/client";
import type { ListItem, SeeCard, SeePage, SensitiveReach } from "../api/types";
import { Rows, Card, DataTable, EmptyState, FilterChips, IdentityCard, NameList, Pager, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { col, DataViews, Load, NameLink, pathCol, Pick, PickFirst, Risks, StateTag, unread, Usage } from "./common";
import { PAGE } from "./paged";
import { seeSentence } from "./screens";

/** What the picker of screens 7 and 9 searches: people and roles (My access: the roles of your slice). */
export const subjects = (mine: boolean) => (mine ? "roles" : "users,roles");

export function SeePageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const role = mine ? "" : c.params.role ?? "";
  const user = c.params.user ?? (role ? "" : c.meta.default_user ?? "");
  const s = useApi<SeePage>(role || user ? "see" : null, { ...apiParams(c), ...(role ? { role } : { user }) });  // its tables page (v_offset, c_offset)
  const id = role || user;
  return (
    <>
      <div className="ae-headrow">
        {mine ? <h2 className="ae-h1">What I see</h2> : (
          <div className="ae-h1 ae-h1-pick">What <Pick label="Person or role" value={id} user={!role} what={subjects(mine)} width={260}
            onPick={(v, i) => c.set(i.kind !== "user" ? { role: v, user: null } : { user: v, role: null })} /> sees</div>
        )}
      </div>
      {role || user ? <Load s={s}>{(d) => <Body d={d} />}</Load> : <PickFirst />}
    </>
  );
}

const SHOWS = ["sees", "sens", "usage", "cards"];

function Body({ d }: { d: SeePage }) {
  const c = useApp();
  const w = d.who, user = w.kind === "user";
  const sub: Record<string, string> = user ? { user: w.name } : { role: w.name };
  const tagsOff = unread(c.meta, "tags");
  const { show, part } = c.params;  // part: old links and redirect() output
  const tab = SHOWS.includes(show ?? "") ? show! : SHOWS.slice(0, 3).includes(part ?? "") ? part! : "cards";
  return (
    <>
      <IdentityCard name={w.name} tag={c.view === "mine" ? "You" : "Viewing"}
        line={user ? `${w.type === "SERVICE" ? "Service user" : "Person"} · ${w.status ?? ""}${w.default_role ? ` · default role ${w.default_role}` : ""}${w.secondary_all ? " · secondary roles ALL" : ""}` : w.type}
        roles={user ? w.roles.map((r) => ({ id: r, note: r === w.default_role ? "default" : "" })) : undefined} />
      <div className="ae-actions">
        <button type="button" className="ae-btn" onClick={() => c.nav("access", sub)}>Access</button>
        <button type="button" className="ae-btn" onClick={() => c.nav("graph", sub)}>Show as graph</button>
      </div>
      <Tabs nav active={tab} onChange={(k) => c.set({ show: k === "cards" ? null : k, part: null })} tabs={[
        { key: "cards", label: "Column by column", count: d.counts?.objects ?? 0 },
        { key: "sees", label: "All protected", count: d.can_read?.total ?? 0 },
        ...(user && d.sensitive?.known ? [{ key: "sens", label: "Sensitive reach", count: d.sensitive.rows.length, tone: "warn" as const }]
          : user && tagsOff ? [{ key: "sens", label: "Sensitive reach", tone: "warn" as const }] : []),
        { key: "usage", label: "Role usage", count: d.usage?.roles.length ?? d.role_usage?.holders ?? 0 },
      ]} />
      {tab === "cards" && <Cards d={d} />}
      {tab === "sees" && (d.can_read?.total ? <DataViews s={d.can_read} path="see" title={user ? "What they see when they read" : "What it sees"} />
        : tagsOff ? <EmptyState title="Not read: sensitivity unknown">{tagsOff.title}. {tagsOff.meaning} {tagsOff.fix ? `Fix: ${tagsOff.fix}` : ""}</EmptyState>
        : <EmptyState title={d.known ? "No protected object" : "Not known here"}>{d.known ? "Nothing they read has a tag, a masking policy or a row policy." : "Policies need the shared snapshot."}</EmptyState>)}
      {tab === "sens" && !d.sensitive && tagsOff && <EmptyState title="Not read: sensitivity unknown">{tagsOff.title}. {tagsOff.meaning}</EmptyState>}
      {tab === "sens" && d.sensitive && (
        <Card title="Sensitive reach" sub={`Reached through ${d.sensitive.roles.length} granted role(s)`}>
          <DataTable csv="sensitive_reach.csv" rows={d.sensitive.rows}
            columns={[col("o", "Object", (r: SensitiveReach) => r.object, { wrap: "nowrap" }),
              col("c", "Columns", (r: SensitiveReach) => r.cols.join(", "), { wrap: "wrap", render: (r: SensitiveReach) => <Rows items={r.cols} /> }),
              col("r", "Granted role", (r: SensitiveReach) => r.role, { wrap: "nowrap", render: (r: SensitiveReach) => <NameLink id={r.role} refs={d.refs} /> }),
              col("t", "Sees", (r: SensitiveReach) => r.text, { wrap: "wrap" }),
              pathCol<SensitiveReach>(d.refs)]} />
        </Card>
      )}
      {tab === "usage" && (d.usage ? <Usage u={d.usage} refs={d.refs} /> : <RoleUse d={d} />)}
      <Risks list={d.risks} quiet />
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
      <p>{u.used} of {u.holders} holders used it{u.unused.length > 0 && " · not used by:"}</p>
      <NameList items={u.unused} max={3} />
    </Card>
  );
}

function Cards({ d }: { d: SeePage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const only = c.params.all !== "1";
  const cards = d.cards;  // one page of the filter (all=1: every protected object), c_offset / limit
  const size = Number(c.params.limit) || PAGE;
  const n = d.counts;
  const s = n && seeSentence(n);
  const user = d.who.kind === "user";
  const tagsOff = unread(c.meta, "tags");
  return (
    <>
      <div className="ae-headrow">
        {s ? <p className="ae-answer">When <span className="ae-mono">{d.who.name}</span> {user ? "queries, they see" : "is the role in use, it sees"} <b>{s.rows}</b> and{" "}
          <b className={n.clear ? "ae-sens-word" : undefined}>{s.cols}</b>. {s.fix}</p> : <p className="ae-muted">Policies are not known here: they need the shared snapshot.</p>}
        <FilterChips label="Show" value={only ? "sens" : "all"} onPick={(k) => c.set({ all: k === "all" ? "1" : null, c_offset: null })}
          items={[{ key: "sens", label: "Only sensitive", count: n?.sensitive ?? 0 }, { key: "all", label: "All protected objects", count: n?.objects ?? 0 }]} />
      </div>
      <div className="ae-seecards">
        {!cards.length && (tagsOff && only ? <EmptyState title="Not read: sensitivity unknown">{tagsOff.title}: which objects are sensitive is not known.</EmptyState>
          : <EmptyState title="Nothing here">No {only ? "sensitive" : "protected"} object they can read.</EmptyState>)}
        {cards.map((x) => <SeeObj key={x.object} x={x} open={o.open} rule={() => c.nav("rules", { rule: "6" })} />)}
        {d.cards_total > size && <Pager at={Math.floor(d.cards_offset / size)} size={size} total={d.cards_total} sizes={[25, 50, 100, 250]}
          onPage={(k) => c.set({ c_offset: k ? String(k * size) : null })} onSize={(k) => c.set({ limit: k === PAGE ? null : String(k), c_offset: null })} />}
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
