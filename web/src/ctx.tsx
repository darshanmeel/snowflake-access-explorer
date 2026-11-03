// App context: URL state, navigation, theme, meta. Pages read it, never touch window.location.
import { createContext, useContext } from "react";
import type { GraphNode, Meta, NodeAction, NodeKind, Page, Refs } from "./api/types";
import type { ThemeName } from "./components";

export type Params = Record<string, string>;

export interface Ctx {
  page: Page;
  params: Params; // URL params without page and data: the API params
  view: "shared" | "mine";
  meta: Meta;
  theme: ThemeName;
  nav: (page: Page, params?: Params) => void; // another page (keeps data=)
  set: (patch: Record<string, string | null | undefined>) => void; // same page, merge params
}

export const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);

/** API params of the page: the URL params plus view. */
export const apiParams = (c: Ctx) => ({ ...c.params, view: c.view });

const base = (id: string) => id.replace(/ \(user\)$/, "");

/** Page that shows `id`, from the kind the server sent in refs. */
export function openTarget(id: string, refs?: Refs | null): { page: Page; params: Params } {
  const k: NodeKind | undefined = refs?.kinds[id];
  if (k === "user") return { page: "user", params: { name: base(id) } };
  if (k === "object" || (!k && refs?.types[id])) return { page: "object", params: { name: id } };
  if (!k && /\(user\)$/.test(id)) return { page: "user", params: { name: base(id) } };
  return { page: "role", params: { name: id } };
}

/** Handlers for graph and table clicks, shared by every page. */
export function useOpen(refs?: Refs | null) {
  const c = useApp();
  const open = (id: string) => { const t = openTarget(id, refs); c.nav(t.page, t.params); };
  const action = (a: NodeAction | null) => {
    if (!a) return;
    if (a.kind === "page") c.nav(a.page, a.params);
    else if (a.kind === "drill") c.set({ schema: a.schema, otype: null });
    else if (a.kind === "otype") c.set({ otype: a.otype });
    else if (a.kind === "full") c.set({ full: "1" });
  };
  const node = (n: GraphNode) => action(n.action);
  return { open, action, node };
}
