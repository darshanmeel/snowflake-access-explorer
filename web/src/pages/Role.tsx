import { useApi } from "../api/client";
import type { HeldRow, HoldCell, ListItem, RolePage } from "../api/types";
import { Banner, Card, DataTable, KpiRow, PrivilegeTabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Banners, col, Controls, DataViews, Findings, GraphCard, Head, Load, NameLink, pathCol, Pick, Sel, Tog } from "./common";

type RW = RolePage["readonly_writes"][number];
const CELL: Record<HoldCell, string> = { direct: "direct", inherited: "inherited", owner: "owner", lacks: "lacks" };

export function RolePageView() {
  const c = useApp();
  const name = c.params.name ?? "";
  const roles = useApi<{ items: ListItem[] }>("list", { what: "roles", view: c.view });
  const s = useApi<RolePage>(name ? "role" : null, { ...apiParams(c), name });
  const o = useOpen(s.data?.refs);
  const names = roles.data?.items.map((i) => i.id) ?? [];
  return (
    <>
      <Head title="Role" sub="Who holds this role, what it holds, and what it can reach." />
      <Controls>
        <Pick label="Role" value={name} options={names} onPick={(v) => c.nav("role", { name: v })} />
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
          <Card title="Effective privileges and roles held" sub="Split by what they allow">
            <PrivilegeTabs rows={d.privileges} roles={d.roles} account={d.account} refs={d.refs} tabs={d.tabs} theme={c.theme}
              csvName={`${d.role.name}_privileges`} onNodeClick={o.node} onOpen={o.open} />
          </Card>
          <Card title="Held by" sub="Every user and role that gets this role, and what they would lose if the link to it were cut">
            <DataTable csv={`${d.role.name}_held_by.csv`} rows={d.held_by.rows} rowTone={(r: HeldRow) => (r.kind === "admin" ? "bad" : null)}
              columns={[
                col("g", "Grantee", (r: HeldRow) => r.grantee, { render: (r: HeldRow) => <NameLink id={r.id} refs={d.refs} label={r.grantee} /> }),
                col("k", "Kind", (r: HeldRow) => r.kind_label), col("s", "Status", (r: HeldRow) => r.status ?? ""),
                col("d", "Depth", (r: HeldRow) => r.depth, { num: true }), col("n", "Paths", (r: HeldRow) => r.count, { num: true }),
                col("v", "Only via", (r: HeldRow) => r.only_via.join(", "), { wrap: "wrap" }),
                col("l", "If revoked", (r: HeldRow) => (r.loses_it ? `loses ${r.loses.length} privilege(s)` : "keeps it other ways"), { help: "What the grantee loses if the link to this role is removed" }),
                pathCol<HeldRow>(d.refs),
              ]} />
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
          </Card>
          {d.holds.types.length > 0 && (
            <Card title="What it holds" sub={`${d.holds.count} privileges on ${d.holds.objects} objects. Green: has it, red: lacks it.`}>
              <Controls><Sel label="Show who lacks" value={d.filters.lacks} onPick={(v) => c.set({ lacks: v })}
                options={[["", "(any)"], ...d.filters.gaps.map((x): [string, string] => [x, x])]} /></Controls>
              {d.holds.types.map((t) => (
                <div key={t.type} className="ae-hold">
                  <h4>{t.type}</h4>
                  <DataTable csv={`${d.role.name}_${t.type}.csv`} rows={t.rows}
                    columns={[col("o", "Object", (r: (typeof t.rows)[number]) => r.object, { wrap: "wrap" }),
                      ...t.privs.map((p) => col(p, p, (r: (typeof t.rows)[number]) => CELL[r.cells[p]] ?? "",
                        { render: (r: (typeof t.rows)[number]) => <span className={`ae-cell ae-cell-${r.cells[p]}`}>{r.cells[p] === "lacks" ? "—" : r.cells[p] ?? ""}</span> }))]} />
                </div>
              ))}
              {d.holds.other.length > 0 && (
                <DataTable csv={`${d.role.name}_other.csv`} rows={d.holds.other}
                  columns={[col("p", "Privilege", (r: RolePage["holds"]["other"][number]) => r.privilege), col("t", "On", (r: RolePage["holds"]["other"][number]) => r.type),
                    col("o", "Object", (r: RolePage["holds"]["other"][number]) => r.object, { wrap: "wrap" })]} />
              )}
            </Card>
          )}
          <DataViews views={d.can_read} />
        </>
      )}</Load>}
    </>
  );
}
