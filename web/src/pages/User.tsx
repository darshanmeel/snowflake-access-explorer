import { useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, SensitiveReach, UserPage } from "../api/types";

type MR = UserPage["multi"]["rows"][number];
import { Fold, Rows, Banner, Card, DataTable, KpiRow, PrivilegeTabs, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { lean, Banners, col, Controls, CutBanner, DataViews, Findings, GraphCard, Head, Load, NameLink, pathCol, Pick, PickFirst, Sel, Tog, unread, Usage, ScopeChips, ScopePick } from "./common";

export function UserPage() {
  const c = useApp();
  const mine = c.view === "mine";
  const name = c.params.name ?? c.meta.default_user ?? "";
  const s = useApi<UserPage>(name ? "user" : null, { ...apiParams(c), name, lean: lean(c) });
  const o = useOpen(s.data?.refs);
  const pane = c.inside ? c.params.pane : undefined; // the Access page's Privileges tab ("privs") or Paths tab ("diagram")
  const [want, setPart] = useState(c.params.part ?? "diagram");
  const hu = s.data?.user;
  return (
    <>
      {!pane && <Head title={mine ? "My access" : "User"} sub={hu && `${hu.type.toLowerCase()} · ${hu.status} · default role ${hu.default_role ?? "none"} · secondary roles ${hu.secondary_roles} · default warehouse ${hu.default_warehouse ?? "none"} · last login ${hu.last_login_text || "never"}`} />}
      <Controls>
        {!mine && !pane && <Pick label="User" value={name} what="users" onPick={(v) => c.nav("user", { name: v })} />}
        <Sel label="Roles" value={c.params.roles ?? "all"} options={[["all", "All roles"], ["default", "Default role only"]]} onPick={(v) => c.set({ roles: v === "all" ? null : v })} />
        <Sel label="Max depth" value={c.params.depth ?? ""} options={[["", "No limit"], ["1", "1"], ["3", "3"], ["5", "5"], ["10", "10"]]} onPick={(v) => c.set({ depth: v })} />
        <Tog label="Data only" on={c.params.dataonly !== "0"} help="Hide USAGE on databases and schemas outside the Usage tab"
          onPick={(v) => c.set({ dataonly: v ? null : "0" })} />
        {!pane && <ScopePick />}
        {!pane && <Pick label="Only on object" value={c.params.on ?? ""} what="objects" onPick={(v) => c.set({ on: v })} />}
        {!pane && c.params.on && <button type="button" className="ae-chip ae-chip-plain" onClick={() => c.set({ on: null })}>any object ×</button>}
        {!pane && s.data && <Sel label="Only privilege" value={s.data.filters.priv} onPick={(v) => c.set({ priv: v })}
          options={[["", "Any privilege"], ...s.data.filters.privileges.map((o): [string, string] => [o, o])]} />}
      </Controls>
      <ScopeChips />
      {!name ? <PickFirst what="a user" /> : <Load s={s}>{(d) => {
        const u = d.user;
        const privs = <Card title="Privileges" sub="Counts are grants; one row per object.">
          <PrivilegeTabs rows={[]} roles={d.roles} account={d.account} server={{ ...apiParams(c), name }}
            refs={d.refs} tabs={d.tabs} theme={c.theme} nav={2} csvName={`${u.name}_privileges`} onNodeClick={o.node} onOpen={o.open}
            focus={c.params.tfocus} onOnly={(id) => c.set({ tfocus: id }, { push: true, stay: true })} />
        </Card>;
        if (pane === "privs") return <><Banners list={d.banners} />{privs}</>;
        const multi = d.multi.rows.length > 0 && (
          <Card title="Privileges reached more than one way" sub={`${d.multi.shown} of ${d.multi.total} paths`}>
            <DataTable csv={`${u.name}_multi_paths.csv`} rows={d.multi.rows}
              columns={[col("p", "Privilege", (r: MR) => r.privilege, { wrap: "nowrap" }), col("o", "Object", (r: MR) => r.object, { wrap: "nowrap" }),
                col("d", "Depth", (r: MR) => r.depth, { num: true }), pathCol<MR>(d.refs)]} />
          </Card>
        );
        if (pane === "diagram") return (
          <>
            <Banners list={d.banners} />
            <GraphCard leans g={d.graph} refs={d.refs} />
            <CutBanner capped={d.capped} />
            {multi && <Fold label={`Reached more than one way: ${d.multi.total} paths`}>{multi}</Fold>}
            <button type="button" className="ae-link" onClick={() => c.nav("see", { user: name })}>What they see →</button>
          </>
        );
        const parts = [
          { key: "diagram", label: "Diagram" },
          { key: "privs", label: "Privileges", count: d.kpis.privileges },
          ...(d.multi.rows.length ? [{ key: "multi", label: "Reached more than one way", count: d.multi.total }] : []),
          ...(d.can_read?.total ? [{ key: "sees", label: "All protected", count: d.can_read.total }] : []),
          ...(d.sensitive?.known && d.sensitive.rows.length ? [{ key: "sens", label: "Sensitive reach", count: d.sensitive.rows.length, tone: "warn" as const }] : []),
          { key: "usage", label: "Role usage", count: d.usage.roles.length },
        ];
        const part = parts.some((t) => t.key === want) ? want : parts[0].key;
        return (
          <>
            <Banners list={d.banners} />
            {u.disabled && <Banner tone="warn" title="Disabled user" lines={["This user cannot log in, but still holds the roles below."]} />}
            <Findings list={d.findings} total={d.findings_total} sev={d.findings_sev} grantee={d.user.name} of="user" refs={d.refs} />
            <Tabs nav active={part} onChange={(t) => { setPart(t); c.set({ otype: null, full: null }); }} tabs={parts} />
            {part === "diagram" && <><GraphCard leans g={d.graph} refs={d.refs} /><CutBanner capped={d.capped} /></>}
            <KpiRow items={[
              { label: "Privileges", value: d.kpis.privileges, caption: `${d.kpis.objects} objects` },
              { label: "Roles", value: d.kpis.roles, caption: `${d.kpis.roles_direct} direct` },
              { label: "Sensitive objects", value: d.kpis.sensitive_known && !unread(c.meta, "tags") ? d.kpis.sensitive ?? 0 : c.view === "mine" ? "unknown" : "not read", tone: d.kpis.sensitive ? "warn" : null },
              { label: "Admin roles", value: d.kpis.admin_roles, tone: d.kpis.admin_roles ? "bad" : null, caption: `${d.kpis.account_privs} account privileges` },
            ]} />
            {part === "privs" && privs}
            {part === "multi" && multi}
            {part === "sees" && <DataViews s={d.can_read} path="user" title="What they see when they read" />}
            {part === "sens" && d.sensitive && (
              <Card title="Sensitive reach" sub={`Reached through ${d.sensitive.roles.length} granted role(s)`}>
                <DataTable csv="sensitive_reach.csv" rows={d.sensitive.rows}
                  columns={[col("o", "Object", (r: SensitiveReach) => r.object, { wrap: "nowrap" }),
                    col("c", "Columns", (r: SensitiveReach) => r.cols.join(", "), { wrap: "wrap", render: (r: SensitiveReach) => <Rows items={r.cols} /> }),
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
