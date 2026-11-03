// Privileges split in tabs, each with its own small diagram and table.
import { useMemo, useState } from "react";
import type { Account, Graph as G, GraphNode, PrivClass, PrivRow, ReachRow, Refs, Tab, TabKey } from "../api/types";
import { Graph } from "./Graph";
import { DataTable, type Column } from "./DataTable";
import { Banner, Chips, Tabs } from "./parts";
import { PathText } from "./PathText";
import { tabGraph } from "./tabgraph";
import { byObject, TAB_LABEL, tabList, tabRoles, tabRows, type ObjRow } from "./tabs";
import type { ThemeName } from "./theme";

export interface PrivilegeTabsProps {
  rows: PrivRow[];
  roles?: ReachRow[];
  account?: Account | null;
  refs?: Refs | null;
  tabs?: Tab[]; // server counts; computed from the rows when left out
  graphs?: Partial<Record<TabKey, G>>; // server diagrams; built here when left out
  active?: TabKey;
  onTab?: (t: TabKey) => void;
  onNodeClick?: (n: GraphNode) => void;
  onOpen?: (id: string) => void; // a name clicked in a table or path
  theme?: ThemeName;
  max?: number;
  csvName?: string;
}

export function PrivilegeTabs(p: PrivilegeTabsProps) {
  const { rows, roles = [], account, refs, theme = "light" } = p;
  const tabs = p.tabs ?? tabList(rows, roles, account);
  const [own, setOwn] = useState<TabKey>(tabs[0]?.key ?? "all");
  const want = p.active ?? own;
  const active = tabs.some((t) => t.key === want) ? want : tabs[0]?.key ?? "all";
  const pick = (k: string) => { setOwn(k as TabKey); p.onTab?.(k as TabKey); };
  const graph = useMemo(
    () => p.graphs?.[active] ?? tabGraph({ tab: active, rows, roles, account, refs, max: p.max }),
    [p.graphs, active, rows, roles, account, refs, p.max],
  );
  const kinds = refs?.kinds ?? {};

  return (
    <div className="ae-privtabs">
      <Tabs tabs={tabs.map((t) => ({ ...t, tone: t.key === "account" ? "bad" as const : null }))} active={active} onChange={pick} />
      <div className="ae-privtab-body">
        {active === "account" && <AccountList account={account} rows={tabRows(rows, "account")} kinds={kinds} onOpen={p.onOpen} />}
        {graph.nodes.length > 1
          ? <Graph graph={graph} theme={theme} onNodeClick={p.onNodeClick} maxHeight={420} />
          : <p className="ae-muted">Nothing in {TAB_LABEL[active]}.</p>}
        {active === "granted" || active === "database_roles"
          ? <RoleTable rows={tabRoles(roles, active)} kinds={kinds} onOpen={p.onOpen} csv={`${p.csvName ?? "privileges"}_${active}.csv`} />
          : active !== "account" && (
            <PrivTable rows={tabRows(rows, active)} kinds={kinds} onOpen={p.onOpen} csv={`${p.csvName ?? "privileges"}_${active}.csv`} />
          )}
      </div>
    </div>
  );
}

/** Account tab: admin roles first, then account privileges, then the ones every user has via PUBLIC. All red. */
function AccountList({ account, rows, kinds, onOpen }: { account?: Account | null; rows: PrivRow[]; kinds: Record<string, string>; onOpen?: (id: string) => void }) {
  const admin = account?.admin ?? [];
  const privs = account ? account.privileges.filter((x) => !x.via_public) : rows.map((r) => ({ privilege: r.privilege, path: r.path.slice(0, -1), via_public: false }));
  const pub = account?.public ?? [];
  return (
    <div className="ae-account">
      {admin.length > 0 && (
        <Banner tone="bad" title={`Admin role${admin.length > 1 ? "s" : ""}: can change access itself`}
          lines={admin.map((a) => <><strong>{a.role}</strong> · <PathText path={a.path} kinds={kinds} onOpen={onOpen} /></>)} />
      )}
      {privs.length > 0 && (
        <Banner tone="bad" title="Account privileges"
          lines={privs.map((x) => <><strong>{x.privilege}</strong> · <PathText path={x.path} kinds={kinds} onOpen={onOpen} /></>)} />
      )}
      {pub.length > 0 && (
        <div className="ae-public">
          <div className="ae-muted">Via PUBLIC: every user has these</div>
          <Chips items={pub.map((x) => ({ id: x, kind: "admin", tone: "bad" }))} />
        </div>
      )}
    </div>
  );
}

const ACCESS: Partial<Record<PrivClass, string>> = { read: "Read", write: "Write", own: "Own", manage: "Manage", use: "Use", admin: "Admin" };

/** Access badge: Read / Write / Own (from the grants), the grants on hover. */
export const AccessTag = ({ cls, grants }: { cls: PrivClass; grants: string[] }) =>
  <span className={`ae-pclass ae-pclass-${cls}`} title={grants.join(", ")}>{ACCESS[cls] ?? cls}</span>;

function PrivTable({ rows, kinds, onOpen, csv }: { rows: PrivRow[]; kinds: Record<string, string>; onOpen?: (id: string) => void; csv: string }) {
  const objs = useMemo(() => byObject(rows), [rows]);
  const cols: Column<ObjRow>[] = [
    { key: "object", label: "Object", get: (r) => r.label, wrap: "truncate",
      render: (r) => <button className="ae-link" onClick={() => onOpen?.(r.object)} title={r.object}>
        {r.sensitive && <span className="ae-sens" title="Sensitive">●</span>}{r.label}</button> },
    { key: "type", label: "Type", get: (r) => r.type, wrap: "nowrap" },
    { key: "access", label: "Access", get: (r) => ACCESS[r.access] ?? r.access, wrap: "nowrap", render: (r) => <AccessTag cls={r.access} grants={r.grants} />,
      help: "Read when every grant only reads; any write grant makes it Write; OWNERSHIP is Own." },
    { key: "grants", label: "Grants", get: (r) => r.grants.join(", "), wrap: "wrap" },
    { key: "holder", label: "Grant holder", get: (r) => r.holder, wrap: "nowrap" },
    { key: "depth", label: "Depth", get: (r) => r.depth, num: true, render: (r) => `D${r.depth}` },
    { key: "count", label: "Paths", get: (r) => r.count, num: true, help: "Chains that give this access; over 1, one revoke may not remove it." },
    { key: "path", label: "Shortest path", get: (r) => r.path.join(" > "), wrap: "nowrap",
      render: (r) => <PathText path={r.path} more={r.more} cls={r.access} grants={r.grants} kinds={kinds} onOpen={onOpen} /> },
  ];
  return <DataTable columns={cols} rows={objs} csv={csv} sort={{ key: "depth" }} rowTone={(r) => (r.access === "admin" ? "bad" : null)} />;
}

function RoleTable({ rows, kinds, onOpen, csv }: { rows: ReachRow[]; kinds: Record<string, string>; onOpen?: (id: string) => void; csv: string }) {
  const cols: Column<ReachRow>[] = [
    { key: "role", label: "Role", get: (r) => r.role, wrap: "truncate",
      render: (r) => <button className={`ae-link ae-k-${r.admin ? "admin" : r.kind}`} onClick={() => onOpen?.(r.role)}>{r.role}</button> },
    { key: "kind", label: "Kind", get: (r) => r.kind.replace("_", " "), wrap: "nowrap" },
    { key: "depth", label: "Depth", get: (r) => r.depth, num: true, render: (r) => `D${r.depth}` },
    { key: "direct", label: "Direct", get: (r) => (r.direct ? "yes" : "") },
    { key: "count", label: "Paths", get: (r) => r.count, num: true },
    { key: "path", label: "Path", get: (r) => r.path, render: (r) => <PathText path={r.path} kinds={kinds} onOpen={onOpen} /> },
  ];
  return <DataTable columns={cols} rows={rows} csv={csv} sort={{ key: "depth" }} rowTone={(r) => (r.admin ? "bad" : null)} />;
}
