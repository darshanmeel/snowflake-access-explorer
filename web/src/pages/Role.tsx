import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { HeldRow, HoldCell, ListItem, RolePage } from "../api/types";
import { Banner, Card, DataTable, EmptyState, FilterChips, Fold, Graph, KpiRow, NameList, PrivilegeTabs, StatusDot, Tabs, pathGraph, type TabItem } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Banners, col, Controls, DataViews, GraphCard, Head, Load, NameLink, pathCol, Pick, Risks, ScopePick, Sel, Tog } from "./common";
import { PagedTable } from "./paged";
import { changeOfPath, WhatIfButton } from "./Whatif";

type RW = RolePage["readonly_writes"][number];
const CELL: Record<HoldCell, string> = { direct: "direct", inherited: "inherited", owner: "owner", lacks: "lacks" };

/** What the role holds, one object type at a time (a picker with its count). */
function Holds({ d }: { d: RolePage }) {
  const c = useApp();
  const t = d.holds.types.find((x) => x.type === c.params.htype) ?? d.holds.types[0];
  if (!t) return null;
  type HR = (typeof t.rows)[number];
  return (
    <>
      <Controls>
        <Sel label="Type" value={t.type} onPick={(k) => c.set({ htype: k, h_offset: null })} options={d.holds.types.map((x): [string, string] => [x.type, `${x.type.toLowerCase()} (${x.count})`])} />
        <Sel label="Show who lacks" value={d.filters.lacks} onPick={(v) => c.set({ lacks: v })}
          options={[["", "(any)"], ...d.filters.gaps.map((x): [string, string] => [x, x])]} />
      </Controls>
      <PagedTable key={t.type} path="role" at="h_offset" total={t.count} offset={t.offset} csv={`${d.role.name}_${t.type}.csv`} rows={t.rows}
        pick={(x: RolePage) => x.holds.types.find((y) => y.type === t.type)?.rows ?? []}
        columns={[col("o", "Object", (r: HR) => r.object, { wrap: "nowrap" }),
          ...t.privs.map((p) => col(p, p, (r: HR) => CELL[r.cells[p]] ?? "",
            { wrap: "nowrap", render: (r: HR) => <span className={`ae-cell ae-cell-${r.cells[p]}`}>{r.cells[p] === "lacks" ? "—" : r.cells[p] ?? ""}</span> }))]} />
    </>
  );
}

function revokeText(r: HeldRow) {
  if (r.loses_it) return r.loses.length ? `loses ${r.loses.length} privilege(s)` : "loses access";
  if (r.direct) return `keeps it: ${r.count - 1} other path${r.count === 2 ? "" : "s"}`;
  return r.only_via.length ? `only via ${r.only_via.join(", ")}` : "keeps it other ways";
}

/** Who gets the role: a graph from the holders to the role (Users / Roles / All chips; the first of each kind on a big
 * account), the table under it a page at a time from GET held. */
function HeldBy({ d }: { d: RolePage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const h = d.held_by;
  const [tab, setTab] = useState(h.users ? "users" : "all");
  const rows = tab === "users" ? h.rows.filter((r) => r.kind === "user") : tab === "roles" ? h.rows.filter((r) => r.kind !== "user") : h.rows;
  const n = tab === "users" ? h.users : tab === "roles" ? h.roles : h.total;
  const g = useMemo(() => pathGraph(rows.map((r) => ({ path: r.path, cls: "inherit" as const })),
    { kinds: d.refs.kinds, objectLabel: "This role", title: "Held by" }), [rows, d.refs.kinds]);
  return (
    <>
      <FilterChips label="Show" value={tab} onPick={setTab} items={[
        { key: "users", label: "Users", count: h.users },
        { key: "roles", label: "Roles", count: h.roles },
        { key: "all", label: "All", count: h.total },
      ]} />
      {d.usage.holders > 0 && (
        <div className="ae-muted"><p>{d.usage.used} of {d.usage.holders} users who hold it used it in the query history</p>
          {d.usage.unused.length > 0 && <Fold label={`Not used by ${(d.usage.holders - d.usage.used).toLocaleString("en-US")}`}><NameList items={d.usage.unused} total={d.usage.holders - d.usage.used} onOpen={(u) => c.nav("access", { user: u })} /></Fold>}</div>
      )}
      <DataTable csv={`${d.role.name}_held_by_${tab}.csv`} rows={[]} server={{ path: "held", params: { ...apiParams(c), name: d.role.name, tab } }} rowTone={(r: HeldRow) => (r.kind === "admin" ? "bad" : r.loses_it ? "warn" : null)}
        columns={[
          col("g", "Grantee", (r: HeldRow) => r.grantee, { wrap: "nowrap", render: (r: HeldRow) => <NameLink id={r.id} refs={d.refs} label={r.grantee} /> }),
          col("k", "Kind", (r: HeldRow) => r.kind_label, { wrap: "nowrap" }),
          col("s", "Status", (r: HeldRow) => r.status ?? "", { wrap: "nowrap", render: (r: HeldRow) => r.status && <><StatusDot s={r.status} /> {r.status}</> }),
          col("h", "Holds it", (r: HeldRow) => (r.direct ? "directly" : `through ${r.depth - 1 || 1} ${r.depth > 2 ? "roles" : "role"}`), { wrap: "wrap" }),
          col("l", "If revoked", revokeText, { wrap: "nowrap", help: "Direct holder: what removing its own grant does. Others: the roles every path goes through." }),
          pathCol<HeldRow>(d.refs),
          col("act", "", () => "", { wrap: "nowrap", render: (r: HeldRow) => {
            const ch = r.direct ? (r.kind === "user" ? { op: "revoke_role_from_user" as const, role: d.role.name, user: r.id.replace(/ \(user\)$/, "") }
              : { op: "revoke_role_from_role" as const, role: d.role.name, grantee: r.id }) : changeOfPath(r.path, d.refs.kinds);
            return ch && <WhatIfButton ch={[ch]} label="What if?" />;
          } }),
        ]} />
      {rows.length > 0 && <Fold label="As a graph"><Graph graph={g} theme={c.theme} onNodeClick={o.node} maxHeight={420} />
        {n > rows.length && <p className="ae-muted">First {rows.length} of {n}.</p>}</Fold>}
    </>
  );
}

/** A role's tabs after its diagram: on the Role page, and as the Access page's own tabs for a role (counts once loaded). */
export const roleTabs = (d?: RolePage | null): TabItem[] => [
  { key: "privs", label: "Privileges", count: d?.tabs.find((t) => t.key === "all")?.count ?? null },
  { key: "held", label: "Held by", count: d?.held_by.total ?? null },
  ...(d?.holds.types.length ? [{ key: "holds", label: "What it holds", count: d.holds.count }] : []),
  ...(d?.can_read?.total ? [{ key: "sees", label: "All protected", count: d.can_read.total }] : []),
  ...(d?.readonly_writes.length ? [{ key: "rw", label: "Read-only writes", count: d.readonly_writes.length, tone: "bad" as const }] : []),
];

export function RolePageView() {
  const c = useApp();
  const name = c.params.name ?? "";
  const s = useApi<RolePage>(name ? "role" : null, { ...apiParams(c), name });
  const o = useOpen(s.data?.refs);
  const pane = c.inside ? c.params.pane : undefined; // the Access page's tab this one part fills (diagram, privs, held, ...)
  const [want, setPart] = useState(c.params.part ?? "diagram");
  const ro = s.data?.role;
  return (
    <>
      {!pane && <Head title="Role" sub={ro && <span className={ro.admin ? "ae-bad" : undefined}>{ro.kind.replace("_", " ")}{ro.owner.length ? ` · owner ${ro.owner.join(", ")}` : ""}</span>} right={name && <WhatIfButton ch={[{ op: "drop_role", role: name }]} label="What if dropped?" />} />}
      <Controls>
        {!pane && <Pick label="Role" value={name} what="roles" onPick={(v) => c.nav("role", { name: v })} />}
        <Sel label="Max depth" value={c.params.depth ?? ""} options={[["", "No limit"], ["1", "1"], ["3", "3"], ["5", "5"], ["10", "10"]]} onPick={(v) => c.set({ depth: v })} />
        <ScopePick />
        <Tog label="Users only" on={c.params.users === "1"} onPick={(v) => c.set({ users: v ? "1" : null })} help="Hide roles that no user holds" />
        <Tog label="Sensitive only" on={c.params.sensitive === "1"} onPick={(v) => c.set({ sensitive: v ? "1" : null })} />
      </Controls>
      {!name && <p className="ae-muted">Pick a role above, or search in the top bar.</p>}
      {name && <Load s={s}>{(d) => {
        const tabs = [{ key: "diagram", label: "Diagram" }, ...roleTabs(d)];
        const part = pane ?? (tabs.some((t) => t.key === want) ? want : "diagram");
        return (
        <>
          {!pane && <Risks list={d.risks} />}{/* inside: the Access page's Overview has the strip */}
          <Banners list={d.banners} />
          {part === "diagram" && !pane && <KpiRow items={d.scope_kpis ? [
            { label: "Effective privileges", value: d.scope_kpis.effective, caption: `in scope · ${d.scope_kpis.objects} objects, ${d.scope_kpis.direct} direct` },
            { label: "Users", value: d.scope_kpis.holders, caption: "in scope" },
            { label: "Sensitive objects", value: d.scope_kpis.sensitive, caption: "in scope", tone: d.scope_kpis.sensitive ? "warn" : null },
          ] : [
            { label: "Effective privileges", value: d.kpis.effective, caption: `${d.kpis.privileges} direct, ${d.kpis.future} future` },
            { label: "Users", value: d.kpis.users, caption: `${d.kpis.users_direct} direct · ${d.kpis.above} held by roles · farthest ${d.kpis.farthest}` },
            { label: "Sensitive objects", value: d.kpis.sensitive, tone: d.kpis.sensitive ? "warn" : null },
          ]} />}
          {!pane && <Tabs nav active={part} onChange={setPart} tabs={tabs} />}
          {!tabs.some((t) => t.key === part) && <EmptyState title="Nothing here">Clear the filters above, or open another tab.</EmptyState>}
          {part === "diagram" && <GraphCard g={d.graph} refs={d.refs} />}
          {part === "rw" && d.readonly_writes.length > 0 && (
            <Card title="Read-only role that can write" sub="Named like a reader, yet holds a write privilege">
              <DataTable csv={`${d.role.name}_readonly_writes.csv`} rows={d.readonly_writes} rowTone={() => "bad"}
                columns={[col("o", "Object", (r: RW) => r.object, { wrap: "wrap" }), col("p", "Privileges", (r: RW) => r.privileges.join(", ")),
                  col("h", "Holder", (r: RW) => r.holder, { render: (r: RW) => <NameLink id={r.holder} refs={d.refs} /> }),
                  col("i", "How", (r: RW) => (r.inherited ? "inherited" : "direct") + (r.how ? ` · ${r.how}` : "")),
                  col("n", "Read-only objects", (r: RW) => `${r.read_only} of ${r.objects}`)]} />
            </Card>
          )}
          {part === "privs" && <Card title="Effective privileges and roles held" sub="Split by what they allow">
            <PrivilegeTabs rows={[]} roles={d.roles} account={d.account} refs={d.refs} tabs={d.tabs} theme={c.theme}
              server={{ ...apiParams(c), name: d.role.name, of: "role" }} nav={2}
              csvName={`${d.role.name}_privileges`} onNodeClick={o.node} onOpen={o.open}
              focus={c.params.tfocus} onOnly={(id) => c.set({ tfocus: id }, { push: true, stay: true })} />
          </Card>}
          {part === "held" && <Card title="Taking it away">
            <HeldBy d={d} />
            {d.filters.cuts_total > 0 && (
              <Controls><Pick label="If revoked from" value={d.filters.cut} what="direct_holders" params={{ role: d.role.name }} onPick={(v) => c.set({ cut: v })} />
                {d.filters.cut ? <button type="button" className="ae-link" onClick={() => c.set({ cut: null })}>Clear</button>
                  : <span className="ae-muted">{d.filters.cuts_total} direct {d.filters.cuts_total === 1 ? "holder" : "holders"}: type to search</span>}</Controls>
            )}
            {d.held_by.revoke && (
              <Banner tone="warn" title={`Revoking from ${d.held_by.revoke.grantee} loses ${d.held_by.revoke.lost} privileges for ${d.held_by.revoke.users} users`}>
                <p className="ae-muted">Text to copy into your infrastructure as code. This app never runs it.</p>
                <pre className="ae-code">{d.held_by.revoke.iac}</pre><pre className="ae-code">{d.held_by.revoke.sql}</pre>
              </Banner>
            )}
          </Card>}
          {part === "holds" && d.holds.types.length > 0 && (
            <Card title="What it holds" sub={`${d.holds.count} privileges on ${d.holds.objects} objects. Green: has it, red: lacks it.`}>
              <Holds d={d} />
              {d.holds.other_total > 0 && (
                <details><summary>Account and other privileges ({d.holds.other_total})</summary><PagedTable path="role" at="o_offset" total={d.holds.other_total}
                  offset={d.holds.other_offset} pick={(x: RolePage) => x.holds.other} csv={`${d.role.name}_other.csv`} rows={d.holds.other}
                  columns={[col("p", "Privilege", (r: RolePage["holds"]["other"][number]) => r.privilege), col("t", "On", (r: RolePage["holds"]["other"][number]) => r.type),
                    col("o", "Object", (r: RolePage["holds"]["other"][number]) => r.object, { wrap: "wrap" })]} /></details>
              )}
            </Card>
          )}
          {part === "sees" && <DataViews s={d.can_read} path="role" />}
        </>
        );
      }}</Load>}
    </>
  );
}
