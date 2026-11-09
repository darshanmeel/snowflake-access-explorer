// Streamlit entry (npm run build:st -> dist-st/), used by st_react.app(): the whole app in one component. Links inside
// Snowsight's iframe would leave the app, so the page's query string goes back to Python, which sets st.query_params.
import { createRoot } from "react-dom/client";
import { ApiFail, setTransport } from "../api/client";
import "../app.css";
import { App } from "../App";
import { onRender, ready, setHeight, setValue } from "./protocol";

export type Args = { component?: string; answers?: Record<string, Answer>; query?: string };
type Answer = { status: number; body: any };
type Req = { id: string; method: string; url: string; body?: unknown };

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

const root = createRoot(document.getElementById("root")!);
let started = false;
const draw = (args: Args) => {
  if (args.component !== "app") return;
  if (!started) { started = true; startApp(args.query); root.render(<App onUrl={(q) => { if (q !== at) { at = q; flush(); } }} />); }
  answer(args.answers);
};

onRender((args) => { draw(args as Args); requestAnimationFrame(() => setHeight()); });
new ResizeObserver(() => setHeight()).observe(document.body);
ready();
