import { useState } from "react";
import { useApi } from "../api/client";
import type { ListItem, MatrixRow, ObjectPage } from "../api/types";
import { Banner, Card, Chips, DataTable, GroupedGrantees, KpiRow, Tabs } from "../components";
import { apiParams, useApp, useOpen } from "../ctx";
import { col, Controls, GraphCard, Head, Load, NameLink, PathCell, pathCol, Pick, Sel, StateTag, Tog } from "./common";
import { WhatIfButton } from "./Whatif";

export function ObjectPageView() {
  const c = useApp();
  const name = c.params.name ?? "";
  const [tab, setTab] = useState("all");
  const [part, setPart] = useState("who");
  const list = useApi<{ items: ListItem[] }>("list", { what: "objects", view: c.view, type: c.params.type });
  const types = useApi<{ items: ListItem[] }>("list", { what: "types", view: c.view });
  // no name: the server picks the first object of the type (as app.py)
  const s = useApi<ObjectPage>("object", { ...apiParams(c), name });
  const op = useOpen(s.data?.refs);
  return (
    <>
      <Head title="Object" sub="Who can reach a table, view or other object, and how." />
      <Controls>
        <Sel label="Type" value={c.params.type ?? ""} onPick={(v) => c.nav("object", v ? { type: v } : {})}
          options={[["", "Any type"], ...(types.data?.items ?? []).map((i): [string, string] => [i.id, i.id])]} />
        <Pick label="Object" value={name || s.data?.object.id || ""} width={360} options={list.data?.items.map((i) => i.id) ?? []}
          onPick={(v) => c.nav("object", c.params.type ? { name: v, type: c.params.type } : { name: v })} />
        <Tog label="Active users only" on={c.params.active === "1"} onPick={(v) => c.set({ active: v ? "1" : null })} />
        <Tog label="Users only" on={c.params.users === "1"} onPick={(v) => c.set({ users: v ? "1" : null })} />
        {s.data && <Sel label="Privilege" value={c.params.priv ?? ""} onPick={(v) => c.set({ priv: v })}
          options={[["", "Any"], ...s.data.object.privileges.map((p): [string, string] => [p, p])]} />}
      </Controls>
      <Load s={s}>{(d) => {
        const o = d.object, k = d.kpis;
        const gs = tab === "all" ? d.grantees : d.grantees.filter((g) => g.tabs.includes(tab as never));
        return (
          <>
            <Card title={o.id} sub={`${o.type.toLowerCase()}${o.sensitive ? " · sensitive" : ""}`}>
              <KpiRow items={[
                { label: "People", value: k.people, caption: `${k.disabled} disabled · ${k.service} service` },
                { label: "Admin", value: k.admin, tone: k.admin ? "bad" : null },
                { label: "Read / Write / Own", value: `${k.read} / ${k.write} / ${k.own}` },
                { label: "Roles on the way", value: k.roles, caption: `${k.direct} direct holders` },
                { label: "Longest chain", value: k.longest },
              ]} />
              {k.owners.length > 0 && <p>Owner: <Chips items={k.owners.map((r) => ({ id: r, kind: "technical" }))} /></p>}
              {k.deployers.length > 0 && <p>Deployed by: <Chips items={k.deployers.map((r) => ({ id: r, kind: "user" }))} /></p>}
              {k.owner_note && <p className="ae-muted">{k.owner_note}</p>}
            </Card>
            {d.admin_paths.length > 0 && <Banner tone="bad" title={`Admin roles reach this object: ${new Set(d.admin_paths.map((p) => p[0])).size} user(s)`} lines={d.admin_paths.map((p, i) => <span key={i} className="ae-fd-path"><PathCell path={p} refs={d.refs} /><WhatIfButton ch={[{ op: "revoke_role_from_user", role: p[1], user: p[0].replace(/ \(user\)$/, "") }]} /></span>)}>
              <p className="ae-muted">An admin role inherits every role, so these users reach this object without a path drawn below.</p>
            </Banner>}
            <GraphCard g={d.graph} refs={d.refs} />
            <Tabs active={part} onChange={setPart} tabs={[
              { key: "who", label: "Who has access", count: d.grantees.length },
              { key: "users", label: "Users × privileges", count: d.matrix.rows.length },
              ...(d.sees ? [{ key: "sees", label: "What each role sees", count: d.sees.rows.length }] : []),
              ...(d.sensitivity ? [{ key: "sens", label: "Sensitivity", count: d.sensitivity.columns.length, tone: o.sensitive ? "warn" as const : null }] : []),
            ]} />
            {part === "sens" && d.sensitivity && (
              <Card title="Sensitivity" sub={`${d.sensitivity.readers.people} people can read it (${d.sensitivity.readers.admin} admin, ${d.sensitivity.readers.service} service)`}>
                <Chips items={d.sensitivity.object_tags.map((t) => ({ id: t.label, title: t.origin, tone: t.sensitive ? "bad" : null }))} />
                {d.sensitivity.row_policies.map((p) => (
                  <p key={p.name}><strong>Row policy {p.name}</strong> on {p.args}: <code>{p.text}</code>{!p.from_text && <span className="ae-muted"> (condition unknown)</span>}</p>
                ))}
                {d.sensitivity.columns.length > 0 && (
                  <DataTable csv={`${o.name}_columns.csv`} rows={d.sensitivity.columns} maxHeight={320}
                    columns={[col("c", "Column", (r: any) => r.column),
                      col("t", "Tags", (r: any) => r.tags.map((t: any) => t.label).join(", "), { wrap: "wrap" }),
                      col("m", "Masking", (r: any) => (r.masking.length ? r.masking.join(", ") : "Not protected: no masking policy"), { wrap: "wrap",
                        render: (r: any) => (r.masking.length ? r.masking.join(", ") : <span className="ae-bad">Not protected: no masking policy</span>) }),
                      col("e", "Clear for", (r: any) => (r.unmasked_everyone ? "everyone" : r.clear_known ? r.clear_for.map((x: any) => x.role).join(", ") : "unknown"), { wrap: "wrap" })]} />
                )}
                {Object.entries(d.sensitivity.policy_text).map(([n, t]) => <details key={n}><summary>{n}</summary><pre className="ae-code">{t}</pre></details>)}
              </Card>
            )}
            {part === "users" && <Card title="Users" sub="Every user, with what they can do here" scroll>
              <DataTable csv={`${o.name}_users.csv`} rows={d.matrix.rows} rowTone={(r: MatrixRow) => (r.admin.length ? "bad" : null)}
                columns={[
                  col("u", "User", (r: MatrixRow) => r.user, { render: (r: MatrixRow) => <NameLink id={r.user} refs={d.refs} /> }),
                  col("t", "Type", (r: MatrixRow) => r.type), col("s", "Status", (r: MatrixRow) => r.status),
                  ...d.matrix.privs.map((p) => col(p, p, (r: MatrixRow) => (r.cells[p]?.has ? 1 : 0),
                    { render: (r: MatrixRow) => (r.cells[p]?.has ? <span title={r.cells[p].title}>{r.cells[p].owner ? "owner" : `D${r.cells[p].depth ?? ""}`}</span> : null) })),
                  ...d.matrix.sensitive_cols.map((cn) => col(`c_${cn}`, cn, (r: MatrixRow) => r.seen[cn]?.state ?? "",
                    { render: (r: MatrixRow) => (r.seen[cn] ? StateTag(r.seen[cn]) : null) })),
                  ...(d.matrix.row_policy ? [col("rows", "Rows", (r: MatrixRow) => r.rows_state?.state ?? "", { render: (r: MatrixRow) => (r.rows_state ? StateTag(r.rows_state) : null) })] : []),
                  col("d", "Depth", (r: MatrixRow) => r.depth ?? "", { num: true }), col("n", "Paths", (r: MatrixRow) => r.paths, { num: true }),
                  pathCol<MatrixRow>(d.refs, "Shortest path"),
                ]} />
            </Card>}
            {part === "sees" && d.sees && (
              <Card title="What each role sees" sub="Columns clear or masked, rows all or filtered, per role that can read the object" scroll>
                <DataTable csv={`${o.name}_role_view.csv`} rows={d.sees.rows}
                  columns={[col("r", "Role", (r: any) => r.role, { render: (r: any) => <NameLink id={r.role} refs={d.refs} /> }),
                    ...(d.sees.row_policy ? [col("rows", "Rows", (r: any) => r.rows.state, { render: (r: any) => StateTag(r.rows) })] : []),
                    ...d.sees.cols.map((cn) => col(cn, cn, (r: any) => r.columns.find((x: any) => x.column === cn)?.state ?? "",
                      { render: (r: any) => { const x = r.columns.find((y: any) => y.column === cn); return x ? StateTag(x) : null; } }))]} />
              </Card>
            )}
            {part === "who" && (
              <Card title="Who has access" sub="Users that come in through the same chain are one row" right={
                <div className="seg">{d.tabs.map((t) => <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label} {t.count}</button>)}</div>}>
                <GroupedGrantees key={tab} rows={gs} kinds={d.refs.kinds} onOpen={op.open} csv={`${o.name}_grantees_${tab}.csv`} />
              </Card>
            )}
          </>
        );
      }}</Load>
    </>
  );
}
