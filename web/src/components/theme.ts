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
    bg: "#F6F7F9", side: "#FFFFFF", panel: "#FFFFFF", sunk: "#F3F5F8", line: "#E3E6EB", line_strong: "#C9D2DE", ink: "#14171C", ink2: "#333A45", muted: "#5B6472", accent: "#1D5FD1", accent_ink: "#123F91", accent_soft: "#E4ECFB", edge: "#A3ADBB", warn_bg: "#FFF7EE", warn_ink: "#8A4305", warn_bd: "#F3D3AE", bad_bg: "#FDECEA", bad_ink: "#B42318", bad_bd: "#F4C2BC", ok_bg: "#E7F4EA", ok_ink: "#1E6B32", ok_bd: "#B8DEC2", low_bg: "#F3F5F8", low_ink: "#5B6472", low_bd: "#D5DBE3", e_read: "#7FA6E8", e_write: "#3E78D9", e_own: "#1D5FD1", e_use: "#8792A2", e_manage: "#0E2F6B", lvl_names_bg: "#F3F5F8", lvl_names_ink: "#5B6472", lvl_read_bg: "#DCE8FB", lvl_read_ink: "#1A4FA8", lvl_change_bg: "#8FB3EE", lvl_change_ink: "#0B2A5E", lvl_own_bg: "#1D5FD1", lvl_own_ink: "#FFFFFF", lvl_admin_bg: "#0E2F6B", lvl_admin_ink: "#FFFFFF", sens_bg: "#FDEBD3", sens_ink: "#8A4305",
    kind: kinds([["#FFFFFF", "#333A45", "#14171C"], ["#DFE9F6", "#30476B", "#1D2C44"], ["#EEDDC8", "#8C5D34", "#4A2E14"], ["#FAEBCB", "#B07A1E", "#553806"], ["#E6EBF2", "#56677F", "#24303F"], ["#FDECEA", "#B42318", "#8C271D"], ["#EEF1F5", "#5B6472", "#14171C"]]),
  },
  dark: {
    bg: "#0F1216", side: "#171B21", panel: "#171B21", sunk: "#1C2129", line: "#2A303A", line_strong: "#3A4250", ink: "#E8EBF0", ink2: "#C9CED6", muted: "#A3ABB8", accent: "#6E9CF0", accent_ink: "#A9C4F0", accent_soft: "#1C2C47", edge: "#5A6577", warn_bg: "#2A2015", warn_ink: "#F7B267", warn_bd: "#5A3D1C", bad_bg: "#3A1A18", bad_ink: "#FF9B8F", bad_bd: "#6A2A24", ok_bg: "#16301E", ok_ink: "#8FD3A1", ok_bd: "#2D5235", low_bg: "#222833", low_ink: "#A3ABB8", low_bd: "#3A4250", e_read: "#6F8FC4", e_write: "#6E9CF0", e_own: "#A9C4F0", e_use: "#7D8796", e_manage: "#C9D9F5", lvl_names_bg: "#222833", lvl_names_ink: "#A3ABB8", lvl_read_bg: "#1C2C47", lvl_read_ink: "#A9C4F0", lvl_change_bg: "#2E4F8C", lvl_change_ink: "#E4ECFB", lvl_own_bg: "#4C82E6", lvl_own_ink: "#0B1220", lvl_admin_bg: "#A9C4F0", lvl_admin_ink: "#0B1B3A", sens_bg: "#3A2612", sens_ink: "#F7B267",
    kind: kinds([["#171B21", "#C9CED6", "#E8EBF0"], ["#1C2A3F", "#7EA3D6", "#D5E3F6"], ["#35271A", "#C5926A", "#F1DCC5"], ["#352913", "#D7A443", "#F3DDAE"], ["#1D232C", "#93A6C0", "#DCE4EE"], ["#3A1B18", "#E27A6B", "#F6C3BA"], ["#222833", "#8792A2", "#E8EBF0"]]),
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
