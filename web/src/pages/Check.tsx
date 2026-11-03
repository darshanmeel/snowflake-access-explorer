import { useApi } from "../api/client";
import type { CheckPage, ListItem } from "../api/types";
import { Banner, Card, DataTable, KpiRow } from "../components";
import { apiParams, useApp } from "../ctx";
import { col, Controls, GraphCard, Head, Load, NameLink, PathCell, pathCol, Pick, Sel, StateTag, Usage } from "./common";
import { changeOfPath, WhatIfButton } from "./Whatif";

export function CheckPageView() {
  const c = useApp();
  const mine = c.view === "mine";
  const name = c.params.name ?? c.meta.default_user;
  const users = useApi<{ items: ListItem[] }>(mine ? null : "list", { what: "users", view: c.view });
  const objs = useApi<{ items: ListItem[] }>("list", { what: "objects", view: c.view });
  const s = useApi<CheckPage>("check", { ...apiParams(c), name });
  return (
    <>
      <Head title="Can they?" sub="Ask: can this user do this to that object, and through what path." />
      <Controls>
        {!mine && <Pick label="User" value={name} options={users.data?.items.map((i) => i.id) ?? [name]} onPick={(v) => c.set({ name: v, obj: null })} />}
        <Pick label="Object" value={c.params.obj ?? s.data?.object ?? ""} width={360} options={objs.data?.items.map((i) => i.id) ?? []} onPick={(v) => c.set({ obj: v, priv: null })} />
        {s.data && <Sel label="Privilege" value={s.data.priv} onPick={(v) => c.set({ priv: v })} options={s.data.privileges.map((p): [string, string] => [p, p])} />}
      </Controls>
      <Load s={s}>{(d) => {
        const a = d.answer;
        return (
          <>
            <Banner tone={a.yes ? (a.tone === "warn" ? "warn" : a.tone === "low" ? "info" : "bad") : "info"} title={a.title} lines={[a.text]} />
            <KpiRow items={a.stats.map(([label, value]) => ({ label, value }))} />
            {d.status !== "active" && <Banner tone="warn" title={`User is ${d.status}`} lines={d.dormant_days ? [`No login for ${d.dormant_days} days.`] : []} />}
            {d.admin_paths.length > 0 && (
              <Banner tone="bad" title="Admin roles give this user everything" lines={d.admin_paths.map((p) => p.join(" > "))} />
            )}
            <GraphCard g={d.graph} refs={d.refs} />
            {d.paths.length > 0 && (
              <Card title="Paths" sub={`${d.paths.length} way(s) to ${d.priv} on ${d.object}`}>
                <DataTable csv="check_paths.csv" rows={d.paths}
                  columns={[col("d", "Depth", (r: CheckPage["paths"][number]) => r.depth, { num: true }),
                    col("h", "Held by", (r: CheckPage["paths"][number]) => r.holder, { render: (r: CheckPage["paths"][number]) => <NameLink id={r.holder} refs={d.refs} /> }),
                    col("w", "How", (r: CheckPage["paths"][number]) => r.how, { wrap: "wrap" }), pathCol<CheckPage["paths"][number]>(d.refs),
                    col("w", "", () => "", { render: (r: CheckPage["paths"][number]) => { const ch = changeOfPath(r.path, d.refs.kinds); return ch && <WhatIfButton ch={[ch]} />; } })]} />
              </Card>
            )}
            {d.owner.length > 0 && (
              <Card title="Through ownership" sub="The owner of an object can do everything on it">
                {d.owner.map((p, i) => <div key={i}><PathCell path={p} refs={d.refs} /></div>)}
              </Card>
            )}
            {d.choke.length > 0 && (
              <Card title="Where to cut" sub="Every path goes through one of these. Remove the link and the access is gone.">
                {d.choke.map((r) => <div key={r} className="ae-fd-path"><NameLink id={r} refs={d.refs} /><WhatIfButton ch={[{ op: "drop_role", role: r }]} label="What if dropped?" /></div>)}
              </Card>
            )}
            {!a.yes && d.closest && (
              <Card title="Closest the user gets" sub="The nearest chain that stops short">
                <PathCell path={d.closest} refs={d.refs} />
              </Card>
            )}
            {!a.yes && d.ask.length > 0 && (
              <Card title="Roles to ask for" sub="Roles that would give this access">
                <DataTable csv="check_ask.csv" rows={d.ask}
                  columns={[col("r", "Role", (r: CheckPage["ask"][number]) => r.role, { render: (r: CheckPage["ask"][number]) => <NameLink id={r.role} refs={d.refs} /> }),
                    col("n", "Privileges", (r: CheckPage["ask"][number]) => r.privileges, { num: true }), pathCol<CheckPage["ask"][number]>(d.refs)]} />
              </Card>
            )}
            {d.options.length > 0 && (
              <Card title="Ways to remove this access" sub="Text to copy into your infrastructure as code. This app never runs it.">
                {d.options.map((x, i) => (
                  <div key={i} className="ae-option">
                    <p><strong>Option {i + 1}</strong> · {x.affects} privilege(s) lost · {x.users.length} user(s) affected</p>
                    <pre className="ae-code">{x.iac}</pre><pre className="ae-code">{x.sql}</pre>
                  </div>
                ))}
              </Card>
            )}
            {d.read && (
              <Card title="What they see" sub={d.read.summary}>
                {d.use_role && <p>Use role <NameLink id={d.use_role} refs={d.refs} />{d.warehouse ? ` with warehouse ${d.warehouse}` : ""}.</p>}
                {d.read.role_only && <p className="ae-muted">{d.read.role_only}</p>}
                {d.read.rows && <p>Rows: {StateTag(d.read.rows)} <span className="ae-muted">{d.read.rows.reason}</span></p>}
                {d.read.columns.length > 0 && (
                  <DataTable csv="check_columns.csv" rows={d.read.columns}
                    columns={[col("c", "Column", (r: any) => r.column), col("s", "State", (r: any) => r.state, { render: (r: any) => StateTag(r) }),
                      col("r", "Why", (r: any) => r.reason, { wrap: "wrap" })]} />
                )}
              </Card>
            )}
            <Usage u={d.usage} />
          </>
        );
      }}</Load>
    </>
  );
}
