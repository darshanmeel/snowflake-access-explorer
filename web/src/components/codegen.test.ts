import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import { parseQuestion } from "../pages/Home";
import { sqlOf, terraformOf, ticketOf, type Change } from "./codegen";

const role: Change = { op: "grant", role: "F_HR", to: "FIN_09", toUser: true };
const priv: Change = { op: "revoke", privilege: "INSERT", objectType: "TABLE", object: "SHARED.LOGGING.TBL_LOGGING", to: "T_SHARED_LOGGING_READ" };
const note = { reason: "payroll close", approver: "HR_OWNER", expiry: "2026-12-31" };

describe("code output", () => {
  it("writes the server's SQL under the note, never its own", () => {
    const s = sqlOf([{ ...role, sql: "GRANT ROLE F_HR TO USER FIN_09;" }, priv], note);
    expect(s).toContain("-- Reason: payroll close");
    expect(s).toContain("GRANT ROLE F_HR TO USER FIN_09;");
    expect(s).not.toContain("INSERT"); // no sql from the server: nothing written for it
  });
  it("writes Terraform resources of the Snowflake provider", () => {
    const t = terraformOf([role, { op: "grant", privilege: "SELECT", objectType: "VIEW", object: "SALES.MART.VW_CUSTOMER", to: "F_ANALYST" }], note);
    expect(t).toContain('resource "snowflake_grant_account_role" "f_hr_to_fin_09"');
    expect(t).toContain('  user_name        = "FIN_09"');
    expect(t).toContain('resource "snowflake_grant_privileges_to_account_role"');
    expect(t).toContain('    object_type = "VIEW"');
    expect(t).toContain("# Expires: 2026-12-31");
    expect(terraformOf([priv])).toContain("delete the resource");
  });
  it("writes valid Terraform for future grants, account objects and database roles", () => {
    const grant = (objectType: string, object: string) => terraformOf([{ op: "grant", privilege: "USAGE", objectType, object, to: "F_X" }]);
    expect(grant("WAREHOUSE", "WH_SALES_XS")).toContain('on_account_object {\n    object_type = "WAREHOUSE"\n    object_name = "WH_SALES_XS"');
    expect(grant("DATABASE", "SALES")).toContain('object_type = "DATABASE"');
    expect(grant("DATABASE", "SALES")).not.toContain("on_database");
    expect(grant("SCHEMA", "SALES.CORE")).toContain('on_schema {\n    schema_name = "SALES.CORE"');
    expect(grant("FUTURE TABLE", "SALES.CORE.<TABLE>")).toContain('object_type_plural = "TABLES"\n      in_schema   = "SALES.CORE"');
    const db = terraformOf([{ op: "grant", privilege: "USAGE", objectType: "DATABASE", object: "HR", to: "HR.SC_R", toDb: true }]);
    expect(db).toContain('resource "snowflake_grant_privileges_to_database_role"');
    expect(db).toContain('on_database = "HR"');
    // the kind comes from the server, not from a dot: an account role named F.SPECIAL stays an account role
    expect(terraformOf([{ op: "grant", role: "F.SPECIAL", to: "F_X" }])).toContain('resource "snowflake_grant_account_role"');
    expect(terraformOf([{ op: "grant", role: "HR.R", to: "F_X", roleDb: true }])).toContain('resource "snowflake_grant_database_role"');
  });
  it("writes ticket text", () => {
    const t = ticketOf([role, priv], note);
    expect(t).toContain("1. Grant role F_HR to user FIN_09");
    expect(t).toContain("2. Revoke INSERT on table SHARED.LOGGING.TBL_LOGGING from role T_SHARED_LOGGING_READ");
    expect(t).toContain("Approver: HR_OWNER");
  });
});

describe("home and links", () => {
  it("reads a typed question", () => {
    expect(parseQuestion("can engineer_01 read sales.core.tbl_customer?")).toEqual({ who: "ENGINEER_01", what: "SALES.CORE.TBL_CUSTOMER", priv: "SELECT" });
    expect(parseQuestion("Can FIN_09 change HR.PEOPLE.TBL_EMPLOYEE")?.priv).toBe("INSERT");
    expect(parseQuestion("ENGINEER_01")).toBeNull();
  });
  it("sends old and empty links to a screen", () => {
    expect(redirect(null, {}).page).toBe("home");
    expect(redirect("nope", {}).page).toBe("home");
    expect(redirect("user", { name: "X" })).toEqual({ page: "user", params: { name: "X" } });
    expect(redirect("access", { name: "X" })).toEqual({ page: "access", params: { user: "X" } });
    expect(redirect("rules", { tab: "admins" })).toEqual({ page: "object", params: { preset: "admin" } });
    expect(redirect("admins", {})).toEqual({ page: "object", params: { preset: "admin" } });
    expect(redirect("who", { name: "DB.S.T" })).toEqual({ page: "object", params: { name: "DB.S.T" } });
    expect(redirect("object", { name: "DB.S.T" })).toEqual({ page: "object", params: { name: "DB.S.T" } });
    expect(redirect("rules", { rule: "6" })).toEqual({ page: "rules", params: { rule: "6" } });
  });
});
