// Streamlit entry (npm run build:st -> dist-st/). Python (st_react.py) sends {component, props, theme}; a click comes
// back as the component value and Python sets st.query_params and reruns: links inside Snowsight's iframe would leave
// the app. Fallback (st_react.MODE = "html"): the bundle is inlined into st.components.v1.html with the args in
// window.__AE_ARGS__, drawn once and display-only (no way back to Python there).
import { createRoot } from "react-dom/client";
import { ApiFail, setTransport } from "../api/client";
import "../app.css";
import { App } from "../App";
import type { GraphNode } from "../api/types";
import { Chips, DataTable, Graph, PrivilegeTabs, Root, type ChipItem, type Column } from "../components";
import { onRender, ready, setHeight, setValue } from "./protocol";

export type Args = { component?: string; props?: any; theme?: "light" | "dark"; answers?: Record<string, Answer>; query?: string };
type Answer = { status: number; body: any };
type Req = { id: string; method: string; url: string; body?: unknown };
type Click = { id: string; name?: string; kind?: string | null; action?: unknown; row?: unknown };

declare global { interface Window { __AE_ARGS__?: Args } }

const inline = window.__AE_ARGS__;
// nonce: the same click twice must still reach Python as a new value (st_react drops a nonce it has seen)
const click = (v: Click) => { if (!inline) setValue({ ...v, nonce: Date.now() + Math.random() }); };
const kindOf = (props: any, id: string) => props.refs?.kinds?.[id] ?? null;

// The whole app ("app"): every API call becomes a request in the component value; Python answers it with server.py
// (st_react.app) and sends the answer back in the next render's args. The full list of open requests is sent each
// time, so a value Streamlit coalesced is never lost; ids carry a per-load prefix so a reloaded frame never gets an
// old answer.
const boot = Math.random().toString(36).slice(2, 8);
let seq = 0, timer = 0, at = "";
const open = new Map<string, { req: Req; ok: (v: unknown) => void; fail: (e: unknown) => void }>();
const flush = () => {
  clearTimeout(timer);
  timer = window.setTimeout(() => setValue({ requests: [...open.values()].map((o) => o.req), url: at, nonce: Date.now() + Math.random() }));
};
const answer = (answers: Record<string, Answer> = {}) => {
  for (const [id, o] of open) {
    const a = answers[id];
    if (!a) continue;
    open.delete(id);
    if (a.status < 300) o.ok(a.body);
    else o.fail(new ApiFail(a.status, String(a.body?.detail ?? a.status), a.body?.message ?? `Request failed (${a.status})`));
  }
};
const startApp = (query = "") => {
  if (query) history.replaceState(null, "", `?${query}`);
  document.body.classList.add("st-embed");
  setTransport((method, url, body) => new Promise((ok, fail) => {
    const id = `${boot}-${++seq}`;
    open.set(id, { req: { id, method, url, body }, ok, fail });
    flush();
  }));
};

export function View({ component, props = {}, theme = "light" }: Args) {
  const node = (n: GraphNode) => click({ id: n.id, name: n.name, kind: n.kind, action: n.action });
  const open = (id: string) => click({ id, kind: kindOf(props, id), action: null });
  switch (component) {
    case "app":
      return <App onUrl={(q) => { if (q !== at) { at = q; flush(); } }} />;
    case "graph":
      return <Graph {...props} theme={theme} onNodeClick={node} />;
    case "privileges":
      return <PrivilegeTabs {...props} theme={theme} onNodeClick={node} onOpen={open} />;
    case "table": {
      const link: string | null = props.link ?? null; // column whose value names a user/role/object
      const cols: Column<Record<string, any>>[] = (props.columns ?? []).map((c: any) => ({ ...c, get: (r: any) => r[c.key] }));
      return (
        <DataTable {...props} columns={cols}
          onRowClick={link ? (r: Record<string, any>) => click({ id: String(r[link]), kind: r._kind ?? kindOf(props, String(r[link])), action: null, row: r }) : undefined} />
      );
    }
    case "chips":
      return <Chips items={props.items ?? []} max={props.max}
        onClick={(c: ChipItem) => click({ id: c.id, kind: c.kind ?? null, action: null })} />;
    default:
      return <div>Unknown component: {String(component)}</div>;
  }
}

const root = createRoot(document.getElementById("root")!);
let started = false;
const draw = (args: Args, base?: string) => {
  if (args.component === "app") {
    if (!started) { started = true; startApp(args.query); root.render(<View {...args} />); }
    answer(args.answers);
    return;
  }
  const t = args.theme ?? (base === "dark" ? "dark" : "light");
  root.render(<Root theme={t}><View {...args} theme={t} /></Root>);
};

if (inline) {
  draw(inline);
} else {
  onRender((args, theme) => { draw(args as Args, theme?.base); requestAnimationFrame(() => setHeight()); });
  new ResizeObserver(() => setHeight()).observe(document.body);
  ready();
}
