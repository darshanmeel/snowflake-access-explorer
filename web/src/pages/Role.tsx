import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { HeldRow, HoldCell, ListItem, RolePage } from "../api/types";
import { Banner, Card, DataTable, Graph, KpiRow, PrivilegeTabs, StatusDot, Tabs, pathGraph } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Banners, col, Controls, DataViews, Findings, GraphCard, Head, Load, NameLink, pathCol, Pick, Sel, Tog } from "./common";
import { changeOfPath, WhatIfButton } from "./Whatif";

type RW = RolePage["readonly_writes"][number];
const CELL: Record<HoldCell, string> = { direct: "direct", inherited: "inherited", owner: "owner", lacks: "lacks" };

/** What the role holds, one tab per object type with its count. */
function Holds({ d }: { d: RolePage }) {
  const [tab, setTab] = useState(d.holds.types[0]?.type ?? "");
  const t = d.holds.types.find((x) => x.type === tab) ?? d.holds.types[0];
  if (!t) return null;
  type HR = (typeof t.rows)[number];
  return (
    <>
      <Tabs active={t.type} onChange={setTab} tabs={d.holds.types.map((x) => ({ key: x.type, label: x.type.toLowerCase(), count: x.rows.length }))} />
      <DataTable key={t.type} csv={`${d.role.name}_${t.type}.csv`} rows={t.rows}
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

/** Who gets the role: a graph from the holders to the role (Users / Roles / All), the table under it. */
function HeldBy({ d }: { d: RolePage }) {
  const c = useApp();
  const o = useOpen(d.refs);
  const users = d.held_by.rows.filter((r) => r.kind === "user");
  const [tab, setTab] = useState(users.length ? "users" : "all");
  const rows = tab === "users" ? users : tab === "roles" ? d.held_by.rows.filter((r) => r.kind !== "user") : d.held_by.rows;
  const g = useMemo(() => pathGraph(rows.map((r) => ({ path: r.path, cls: "inherit" as const })),
    { kinds: d.refs.kinds, objectLabel: "This role", title: "Held by" }), [rows, d.refs.kinds]);
  return (
    <>
      <Tabs active={tab} onChange={setTab} tabs={[
        { key: "users", label: "Users", count: users.length },
        { key: "roles", label: "Roles", count: d.held_by.rows.length - users.length },
        { key: "all", label: "All", count: d.held_by.rows.length },
      ]} />
      {d.usage.holders > 0 && (
        <p className="ae-muted">{d.usage.used} of {d.usage.holders} users who hold it used it in the query history
          {d.usage.unused.length > 0 && <> · not used by {d.usage.unused.slice(0, 8).join(", ")}{d.usage.unused.length > 8 ? ` +${d.usage.unused.length - 8}` : ""}</>}</p>
      )}
      {rows.length > 0 && <Graph graph={g} theme={c.theme} onNodeClick={o.node} maxHeight={420} />}
      <DataTable csv={`${d.role.name}_held_by_${tab}.csv`} rows={rows} rowTone={(r: HeldRow) => (r.kind === "admin" ? "bad" : r.loses_it ? "warn" : null)}
        columns={[
          col("g", "Grantee", (r: HeldRow) => r.grantee, { wrap: "nowrap", render: (r: HeldRow) => <NameLink id={r.id} refs={d.refs} label={r.grantee} /> }),
          col("k", "Kind", (r: HeldRow) => r.kind_label, { wrap: "nowrap" }),
          col("s", "Status", (r: HeldRow) => r.status ?? "", { wrap: "nowrap", render: (r: HeldRow) => r.status && <><StatusDot s={r.status} /> {r.status}</> }),
          col("d", "Depth", (r: HeldRow) => r.depth, { num: true }), col("n", "Paths", (r: HeldRow) => r.count, { num: true }),
          col("l", "If revoked", revokeText, { wrap: "nowrap", help: "Direct holder: what removing its own grant does. Others: the roles every path goes through." }),
          pathCol<HeldRow>(d.refs),
          col("act", "", () => "", { wrap: "nowrap", render: (r: HeldRow) => {
            const ch = r.direct ? (r.kind === "user" ? { op: "revoke_role_from_user" as const, role: d.role.name, user: r.id.replace(/ \(user\)$/, "") }
              : { op: "revoke_role_from_role" as const, role: d.role.name, grantee: r.id }) : changeOfPath(r.path, d.refs.kinds);
            return ch && <WhatIfButton ch={[ch]} label="What if?" />;
          } }),
        ]} />
    </>
  );
}

export function RolePageView() {
  const c = useApp();
  const name = c.params.name ?? "";
  const s = useApi<RolePage>(name ? "role" : null, { ...apiParams(c), name });
  const o = useOpen(s.data?.refs);
  const [part, setPart] = useState(c.params.part ?? "privs");
  return (
    <>
      <Head title="Role" sub="Who holds this role, what it holds, and what it can reach." right={name && <WhatIfButton ch={[{ op: "drop_role", role: name }]} label="What if dropped?" />} />
      <Controls>
        <Pick label="Role" value={name} what="roles" onPick={(v) => c.nav("role", { name: v })} />
        <Sel label="Max depth" value={c.params.depth ?? ""} options={[["", "No limit"], ["1", "1"], ["3", "3"], ["5", "5"], ["10", "10"]]} onPick={(v) => c.set({ depth: v })} />
        <Tog label="Users only" on={c.params.users === "1"} onPick={(v) => c.set({ users: v ? "1" : null })} help="Hide roles that no user holds" />
        <Tog label="Sensitive only" on={c.params.sensitive === "1"} onPick={(v) => c.set({ sensitive: v ? "1" : null })} />
      </Controls>
      {!name && <p className="ae-muted">Pick a role above, or search in the top bar.</p>}
      {name && <Load s={s}>{(d) => (
        <>
          <Banners list={d.banners} />
          <KpiRow items={[
            { label: "Kind", value: d.role.kind.replace("_", " "), caption: d.role.owner.length ? `owner ${d.role.owner.join(", ")}` : undefined, tone: d.role.admin ? "bad" : null },
            { label: "Effective privileges", value: d.kpis.effective, caption: `${d.kpis.privileges} direct, ${d.kpis.future} future` },
            { label: "Held by roles", value: d.kpis.above, caption: `${d.kpis.above_direct} direct` },
            { label: "Users", value: d.kpis.users, caption: `${d.kpis.users_direct} direct` },
            { label: "Farthest user", value: d.kpis.farthest },
            { label: "Sensitive objects", value: d.kpis.sensitive, tone: d.kpis.sensitive ? "warn" : null },
          ]} />
          {d.scope_kpis && <KpiRow items={[
            { label: "Direct in scope", value: d.scope_kpis.direct }, { label: "Effective in scope", value: d.scope_kpis.effective },
            { label: "Objects", value: d.scope_kpis.objects }, { label: "Holders", value: d.scope_kpis.holders }, { label: "Sensitive", value: d.scope_kpis.sensitive },
          ]} />}
          <Findings list={d.findings} total={d.findings_total} refs={d.refs} />
          {d.readonly_writes.length > 0 && (
            <Card title="Read-only role that can write" sub="Named like a reader, yet holds a write privilege">
              <DataTable csv={`${d.role.name}_readonly_writes.csv`} rows={d.readonly_writes} rowTone={() => "bad"}
                columns={[col("o", "Object", (r: RW) => r.object, { wrap: "wrap" }), col("p", "Privileges", (r: RW) => r.privileges.join(", ")),
                  col("h", "Holder", (r: RW) => r.holder, { render: (r: RW) => <NameLink id={r.holder} refs={d.refs} /> }),
                  col("i", "How", (r: RW) => (r.inherited ? "inherited" : "direct") + (r.how ? ` · ${r.how}` : "")),
                  col("n", "Read-only objects", (r: RW) => `${r.read_only} of ${r.objects}`)]} />
            </Card>
          )}
          <GraphCard g={d.graph} refs={d.refs} />
          <Tabs active={part} onChange={setPart} tabs={[
            { key: "privs", label: "Privileges", count: d.privileges.length },
            { key: "held", label: "Held by", count: d.held_by.rows.length },
            ...(d.holds.types.length ? [{ key: "holds", label: "What it holds", count: d.holds.count }] : []),
            ...(d.can_read?.length ? [{ key: "sees", label: "What it sees", count: d.can_read.length }] : []),
          ]} />
          {part === "privs" && <Card title="Effective privileges and roles held" sub="Split by what they allow">
            <PrivilegeTabs rows={d.privileges} roles={d.roles} account={d.account} refs={d.refs} tabs={d.tabs} theme={c.theme}
              csvName={`${d.role.name}_privileges`} onNodeClick={o.node} onOpen={o.open} />
          </Card>}
          {part === "held" && <Card title="Held by" sub="Every user and role that gets this role, through which chain, and what a revoke would take away">
            <HeldBy d={d} />
            {d.filters.cuts.length > 0 && (
              <Controls><Sel label="If revoked from" value={d.filters.cut} onPick={(v) => c.set({ cut: v })}
                options={[["", "(pick a grantee)"], ...d.filters.cuts.map((x): [string, string] => [x, x])]} /></Controls>
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
              <Controls><Sel label="Show who lacks" value={d.filters.lacks} onPick={(v) => c.set({ lacks: v })}
                options={[["", "(any)"], ...d.filters.gaps.map((x): [string, string] => [x, x])]} /></Controls>
              <Holds d={d} />
              {d.holds.other.length > 0 && (
                <details><summary>Account and other privileges ({d.holds.other.length})</summary><DataTable csv={`${d.role.name}_other.csv`} rows={d.holds.other}
                  columns={[col("p", "Privilege", (r: RolePage["holds"]["other"][number]) => r.privilege), col("t", "On", (r: RolePage["holds"]["other"][number]) => r.type),
                    col("o", "Object", (r: RolePage["holds"]["other"][number]) => r.object, { wrap: "wrap" })]} /></details>
              )}
            </Card>
          )}
          {part === "sees" && <DataViews views={d.can_read} />}
        </>
      )}</Load>}
    </>
  );
}
