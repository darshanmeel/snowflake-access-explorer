import { useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, SensitiveReach, UserPage } from "../api/types";

type MR = UserPage["multi"]["rows"][number];
import { Banner, Card, DataTable, KpiRow, PrivilegeTabs, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { Banners, col, Controls, CutBanner, DataViews, Findings, GraphCard, Head, Load, NameLink, pathCol, Pick, PickFirst, Sel, Tog, unread, Usage, ScopeChips } from "./common";

export function UserPage() {
  const c = useApp();
  const mine = c.view === "mine";
  const name = c.params.name ?? c.meta.default_user ?? "";
  const s = useApi<UserPage>(name ? "user" : null, { ...apiParams(c), name });
  const o = useOpen(s.data?.refs);
  const [part, setPart] = useState(c.params.part ?? "privs");
  return (
    <>
      <Head title={mine ? "My access" : "User"} sub="What this user can reach, and through which roles." />
      <Controls>
        {!mine && <Pick label="User" value={name} what="users" onPick={(v) => c.nav("user", { name: v })} />}
        <Sel label="Roles" value={c.params.roles ?? "all"} options={[["all", "All roles"], ["default", "Default role only"]]} onPick={(v) => c.set({ roles: v === "all" ? null : v })} />
        <Sel label="Max depth" value={c.params.depth ?? ""} options={[["", "No limit"], ["1", "1"], ["3", "3"], ["5", "5"], ["10", "10"]]} onPick={(v) => c.set({ depth: v })} />
        <Tog label="Data only" on={c.params.dataonly !== "0"} help="Hide USAGE on databases and schemas outside the Usage tab"
          onPick={(v) => c.set({ dataonly: v ? null : "0" })} />
        <Pick label="Only on object" value={c.params.on ?? ""} what="objects" onPick={(v) => c.set({ on: v })} />
        {c.params.on && <button type="button" className="ae-chip ae-chip-plain" onClick={() => c.set({ on: null })}>any object ×</button>}
        {s.data && <Sel label="Only privilege" value={s.data.filters.priv} onPick={(v) => c.set({ priv: v })}
          options={[["", "Any privilege"], ...s.data.filters.privileges.map((o): [string, string] => [o, o])]} />}
      </Controls>
      <ScopeChips />
      {!name ? <PickFirst what="a user" /> : <Load s={s}>{(d) => {
        const u = d.user;
        return (
          <>
            <Banners list={d.banners} />
            {u.disabled && <Banner tone="warn" title="Disabled user" lines={["This user cannot log in, but still holds the roles below."]} />}
            <Card title={u.name} sub={`${u.type.toLowerCase()} · ${u.status}${u.login_mark && u.status !== "never" && u.status !== "dormant" ? ` · ${u.login_mark}` : ""}`}>
              <KpiRow items={[
                { label: "Default role", value: u.default_role ?? "none" },
                { label: "Secondary roles", value: u.secondary_roles },
                { label: "Default warehouse", value: u.default_warehouse ?? "none" },
                { label: "Last login", value: u.last_login_text || "never", tone: u.login_mark ? "warn" : null },
              ]} />
            </Card>
            <KpiRow items={[
              { label: "Privileges", value: d.kpis.privileges, caption: `${d.kpis.objects} objects` },
              { label: "Paths", value: d.kpis.paths, caption: `${d.kpis.multi} reached more than one way` },
              { label: "Roles", value: d.kpis.roles, caption: `${d.kpis.roles_direct} direct` },
              { label: "Deepest chain", value: d.kpis.deepest },
              { label: "Sensitive objects", value: d.kpis.sensitive_known && !unread(c.meta, "tags") ? d.kpis.sensitive ?? 0 : c.view === "mine" ? "unknown" : "not read", tone: d.kpis.sensitive ? "warn" : null },
              { label: "Admin roles", value: d.kpis.admin_roles, tone: d.kpis.admin_roles ? "bad" : null },
              { label: "Account privileges", value: d.kpis.account_privs, tone: d.kpis.account_privs ? "bad" : null },
            ]} />
            <Findings list={d.findings} total={d.findings_total} sev={d.findings_sev} grantee={d.user.name} of="user" refs={d.refs} />
            <GraphCard g={d.graph} refs={d.refs} />
            <CutBanner capped={d.capped} />
            <Tabs nav={c.inside ? 2 : 1} active={part} onChange={(t) => { setPart(t); c.set({ schema: null, otype: null, full: null }); }} tabs={[
              { key: "privs", label: "Privileges", count: d.kpis.privileges },
              ...(d.multi.rows.length ? [{ key: "multi", label: "Reached more than one way", count: d.multi.total }] : []),
              ...(d.can_read?.total ? [{ key: "sees", label: "What they see", count: d.can_read.total }] : []),
              ...(d.sensitive?.known && d.sensitive.rows.length ? [{ key: "sens", label: "Sensitive data they can see", count: d.sensitive.rows.length, tone: "warn" as const }] : []),
              { key: "usage", label: "Role usage", count: d.usage.roles.length },
            ]} />
            {part === "privs" && <Card title="Privileges" sub="One row per object: Read, Write or Own from the grants. Each tab has its own diagram.">
              <PrivilegeTabs rows={[]} roles={d.roles} account={d.account} server={{ ...apiParams(c), name }}
                refs={d.refs} tabs={d.tabs} theme={c.theme} csvName={`${u.name}_privileges`} onNodeClick={o.node} onOpen={o.open} />
            </Card>}
            {part === "multi" && (
              <Card title="Privileges reached more than one way" sub={`${d.multi.shown} of ${d.multi.total} paths`}>
                <DataTable csv={`${u.name}_multi_paths.csv`} rows={d.multi.rows}
                  columns={[col("p", "Privilege", (r: MR) => r.privilege, { wrap: "nowrap" }), col("o", "Object", (r: MR) => r.object, { wrap: "nowrap" }),
                    col("d", "Depth", (r: MR) => r.depth, { num: true }), pathCol<MR>(d.refs)]} />
              </Card>
            )}
            {part === "sees" && <DataViews s={d.can_read} path="user" title="What they see when they read" />}
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
            {part === "usage" && <Usage u={d.usage} refs={d.refs} />}
          </>
        );
      }}</Load>}
    </>
  );
}
