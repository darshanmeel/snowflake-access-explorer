// Privileges split in tabs, each with its own small diagram and table.
import { useMemo, useState } from "react";
import { useApi } from "../api/client";
import type { Account, Graph as G, GraphNode, PrivClass, PrivRow, ReachRow, Refs, Tab, TabKey } from "../api/types";
import { Graph } from "./Graph";
import { DataTable, type Column, type DataTableProps } from "./DataTable";
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
  onOnly?: (id: string | null) => void; // a server diagram: Show only this / Whole graph (focus=)
  focus?: string | null; // its focused box (the page keeps it apart from its own graph's)
  onOpen?: (id: string) => void; // a name clicked in a table or path
  theme?: ThemeName;
  max?: number;
  csvName?: string;
  /** The User page params (the Role page's with of: "role"): privilege rows come a page at a time from GET privs and
   * each privilege tab's diagram from GET graph?of=user-tab (role-tab) (rows is then empty); the role and account tabs
   * still draw from roles and account. */
  server?: Record<string, string | undefined | null>;
  nav?: number; // Tabs nav: the tabs as side-menu items
}

export function PrivilegeTabs(p: PrivilegeTabsProps) {
  const { rows, roles = [], account, refs, theme = "light" } = p;
  const tabs = p.tabs ?? tabList(rows, roles, account);
  const [own, setOwn] = useState<TabKey>(tabs.some((t) => t.key === "all") ? "all" : tabs[0]?.key ?? "all"); // the full table first
  const want = p.active ?? own;
  const active = tabs.some((t) => t.key === want) ? want : tabs[0]?.key ?? "all";
  const pick = (k: string) => { setOwn(k as TabKey); p.onTab?.(k as TabKey); if (p.focus) p.onOnly?.(null); }; // a box of one tab is not in the next
  const local = !p.server || active === "account" || active === "granted" || active === "database_roles";
  const sg = useApi<G | null>(local ? null : "graph", { ...p.server, of: p.server?.of === "role" ? "role-tab" : "user-tab", tab: active, focus: p.focus });
  const graph = useMemo(
    () => (local ? p.graphs?.[active] ?? tabGraph({ tab: active, rows, roles, account, refs, max: p.max }) : sg.data),
    [local, sg.data, p.graphs, active, rows, roles, account, refs, p.max],
  );
  const kinds = refs?.kinds ?? {};

  return (
    <div className="ae-privtabs">
      <Tabs tabs={tabs.map((t) => ({ ...t, tone: t.key === "account" ? "bad" as const : null }))} active={active} onChange={pick} nav={p.nav} />
      <div className="ae-privtab-body">
        {active === "account" && <AccountList account={account} rows={tabRows(rows, "account")} kinds={kinds} onOpen={p.onOpen} />}
        {graph && graph.nodes.length > 1
          ? <Graph graph={graph} theme={theme} onNodeClick={p.onNodeClick} onOnly={local ? undefined : p.onOnly} maxHeight={420} />
          : !local && sg.error ? <p className="ae-muted" role="alert">{sg.error.message}</p>
          : !local && sg.loading ? <p className="ae-muted">Loading the diagram…</p>
          : <p className="ae-muted">Nothing in {TAB_LABEL[active]}.</p>}
        {active === "granted" || active === "database_roles"
          ? <RoleTable rows={tabRoles(roles, active)} kinds={kinds} onOpen={p.onOpen} csv={`${p.csvName ?? "privileges"}_${active}.csv`} />
          : active !== "account" && (
            <PrivTable rows={tabRows(rows, active)} kinds={kinds} onOpen={p.onOpen} csv={`${p.csvName ?? "privileges"}_${active}.csv`}
              server={p.server && { path: "privs", params: { ...p.server, tab: active, focus: undefined } }} />
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

function PrivTable({ rows, kinds, onOpen, csv, server }: {
  rows: PrivRow[]; kinds: Record<string, string>; onOpen?: (id: string) => void; csv: string; server?: DataTableProps<ObjRow>["server"];
}) {
  const objs = useMemo(() => (server ? [] : byObject(rows)), [rows, server]);
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
  return <DataTable columns={cols} rows={objs} csv={csv} sort={{ key: "depth" }} rowTone={(r) => (r.access === "admin" ? "bad" : null)} server={server} />;
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
