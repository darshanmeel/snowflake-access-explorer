// Tokens copied from ui.py TOKENS (keep both in step). "database" there is "database_role" here.
import type { CSSProperties } from "react";

export type ThemeName = "light" | "dark";
export interface KindStyle { bg: string; border: string; text: string; radius: string; dash: string }

const KINDS = ["user", "functional", "technical", "group", "database_role", "admin", "object"] as const;
const SHAPE: Record<string, [string, string]> = {
  user: ["999px", "solid"], functional: ["6px", "solid"], technical: ["6px", "solid"], group: ["6px", "dashed"],
  database_role: ["6px", "dashed"], admin: ["6px", "solid"], object: ["12px / 9px", "solid"],
};

const kinds = (rows: [string, string, string][]) =>
  Object.fromEntries(KINDS.map((k, i) => {
    const [bg, border, text] = rows[i];
    return [k, { bg, border, text, radius: SHAPE[k][0], dash: SHAPE[k][1] }];
  })) as Record<string, KindStyle>;

export const TOKENS = {
  light: {
    bg: "#E6F2F8", side: "#11567F", panel: "#FFFFFF", sunk: "#EDF5F9", line: "#CBDDE7", line_strong: "#B4CDDB", ink: "#0B1F2C", ink2: "#24404F", muted: "#4C6473", accent: "#11567F", accent_ink: "#0A3550", accent_soft: "#D3F0FB", edge: "#9AB0BD", warn_bg: "#FFF7EE", warn_ink: "#8A4305", warn_bd: "#F3D3AE", bad_bg: "#FDECEA", bad_ink: "#8E0A12", bad_bd: "#F4C2BC", ok_bg: "#E7F4EA", ok_ink: "#1E6B32", ok_bd: "#B8DEC2", low_bg: "#EFF4F7", low_ink: "#4C6473", low_bd: "#CBD8E0", e_read: "#1C97C9", e_write: "#0F6FA0", e_own: "#11567F", e_use: "#7F95A2", e_manage: "#072C44", lvl_names_bg: "#EFF4F7", lvl_names_ink: "#4C6473", lvl_read_bg: "#D3F0FB", lvl_read_ink: "#0E4A6E", lvl_change_bg: "#29B5E8", lvl_change_ink: "#04202F", lvl_own_bg: "#11567F", lvl_own_ink: "#FFFFFF", lvl_admin_bg: "#072C44", lvl_admin_ink: "#FFFFFF", sens_bg: "#FDEBD3", sens_ink: "#8A4305",
    kind: kinds([["#FFFFFF", "#24404F", "#0B1F2C"], ["#DDF2FB", "#11567F", "#0A3550"], ["#EEDDC8", "#8C5D34", "#4A2E14"], ["#FFEFDC", "#B8690F", "#5A3206"], ["#E6EBF2", "#56677F", "#24303F"], ["#FDECEA", "#B42318", "#8C271D"], ["#EDF3F7", "#4C6473", "#0B1F2C"]]),
  },
  dark: {
    bg: "#06151F", side: "#0A2E45", panel: "#0C2130", sunk: "#122B3C", line: "#21425A", line_strong: "#335A75", ink: "#E6F1F7", ink2: "#C5D8E3", muted: "#9DB6C5", accent: "#29B5E8", accent_ink: "#A6E2F7", accent_soft: "#114059", edge: "#56748A", warn_bg: "#2A2015", warn_ink: "#F7B267", warn_bd: "#5A3D1C", bad_bg: "#3A1A18", bad_ink: "#FF9B8F", bad_bd: "#6A2A24", ok_bg: "#16301E", ok_ink: "#8FD3A1", ok_bd: "#2D5235", low_bg: "#18303F", low_ink: "#9DB6C5", low_bd: "#335A75", e_read: "#4FB3DA", e_write: "#29B5E8", e_own: "#A6E2F7", e_use: "#7B93A3", e_manage: "#D5F1FB", lvl_names_bg: "#18303F", lvl_names_ink: "#9DB6C5", lvl_read_bg: "#114059", lvl_read_ink: "#A6E2F7", lvl_change_bg: "#1B6F98", lvl_change_ink: "#EAF8FE", lvl_own_bg: "#29B5E8", lvl_own_ink: "#04202F", lvl_admin_bg: "#A6E2F7", lvl_admin_ink: "#06263A", sens_bg: "#3A2612", sens_ink: "#F7B267",
    kind: kinds([["#0C2130", "#C5D8E3", "#E6F1F7"], ["#0F3A54", "#29B5E8", "#D5F1FB"], ["#35271A", "#C5926A", "#F1DCC5"], ["#352913", "#D7A443", "#F3DDAE"], ["#1D232C", "#93A6C0", "#DCE4EE"], ["#3A1B18", "#E27A6B", "#F6C3BA"], ["#18303F", "#7B93A3", "#E6F1F7"]]),
  },
};
export type Tokens = typeof TOKENS.light;

/** Style of a node kind; combined boxes borrow the style of what they hold. */
export function kindStyle(t: Tokens, kind: string): KindStyle {
  const base = { schema_group: "object", database_group: "object", type_group: "object", fold: "technical", lane_group: "technical" }[kind];
  return t.kind[base ?? kind] ?? t.kind.group;
}

// edge class -> colour token, width, dash, double line (as ui.EDGE; inherit_db and back added)
export const EDGE: Record<string, [keyof Tokens | "db", number, string, boolean]> = {
  inherit: ["edge", 1.5, "", false], back: ["edge", 1.5, "2 3", false], inherit_db: ["db", 1.6, "2 3", true],
  read: ["e_read", 1.8, "", false], write: ["e_write", 3, "", false], own: ["e_own", 4.5, "", true],
  use: ["e_use", 1.8, "5 4", false], manage: ["e_manage", 2.2, "8 3 2 3", false], admin: ["bad_ink", 2, "1 3", false],
};

export function edgeColor(t: Tokens, cls: string): string {
  const key = (EDGE[cls] ?? EDGE.inherit)[0];
  return key === "db" ? t.kind.database_role.border : (t[key] as string);
}

/** CSS variables (--ae-*) for a wrapper element; the shared CSS reads only these. */
export function themeVars(name: ThemeName): CSSProperties {
  const t = TOKENS[name];
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(t)) if (typeof v === "string") out[`--ae-${k}`] = v;
  for (const [k, s] of Object.entries(t.kind)) {
    out[`--ae-k-${k}-bg`] = s.bg;
    out[`--ae-k-${k}-bd`] = s.border;
    out[`--ae-k-${k}-ink`] = s.text;
  }
  return out as CSSProperties;
}

export const PCLASS: Record<string, string> = {
  read: "Read", write: "Write", own: "Own", use: "Use", manage: "Manage", admin: "Account",
  inherit: "Inherits", inherit_db: "Database role", back: "Also deeper",
};
export const KIND_LABEL: Record<string, string> = {
  user: "User", functional: "Functional", technical: "Technical", group: "Group / other", database_role: "Database role",
  admin: "Admin / account", object: "Object", schema_group: "Schema (combined)", database_group: "Database (combined)",
  type_group: "Object type (combined)", fold: "Folded roles (click opens)", lane_group: "Roles (combined)",
};
