import { describe, expect, it } from "vitest";
import { redirect } from "../App";
import { parseQuestion } from "../pages/Home";
import { sqlOf, terraformOf, ticketOf, type Change } from "./codegen";

const role: Change = { op: "grant", role: "F_HR", to: "FIN_09", toUser: true };
const priv: Change = { op: "revoke", privilege: "INSERT", objectType: "TABLE", object: "SHARED.LOGGING.TBL_LOGGING", to: "T_SHARED_LOGGING_READ" };
const note = { reason: "payroll close", approver: "HR_OWNER", expiry: "2026-12-31" };

describe("code output", () => {
  it("writes SQL with comments and an undo line", () => {
    const s = sqlOf([role, priv], note);
    expect(s).toContain("-- Reason: payroll close");
    expect(s).toContain("GRANT ROLE F_HR TO USER FIN_09;");
    expect(s).toContain("-- undo: REVOKE ROLE F_HR FROM USER FIN_09;");
    expect(s).toContain("REVOKE INSERT ON TABLE SHARED.LOGGING.TBL_LOGGING FROM ROLE T_SHARED_LOGGING_READ;");
  });
  it("quotes names that need it and handles database roles and account privileges", () => {
    expect(sqlOf([{ op: "grant", role: "HR.SC_R_PEOPLE", to: "F_HR" }])).toContain("GRANT DATABASE ROLE HR.SC_R_PEOPLE TO ROLE F_HR;");
    expect(sqlOf([{ op: "revoke", privilege: "EXECUTE TASK", objectType: "ACCOUNT", object: "ACCOUNT", to: "my role" }])).toContain('ON ACCOUNT FROM ROLE "my role";');
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
  it("writes valid text for ownership, future grants and account objects", () => {
    const own: Change = { op: "revoke", privilege: "OWNERSHIP", objectType: "TABLE", object: "SALES.RAW.TBL_ORDER_RAW", to: "T_SALES_RAW_OWNER" };
    expect(sqlOf([own])).toContain("GRANT OWNERSHIP ON TABLE SALES.RAW.TBL_ORDER_RAW TO ROLE <new owner role> COPY CURRENT GRANTS;");
    expect(sqlOf([own])).not.toContain("REVOKE OWNERSHIP");
    const fut: Change = { op: "revoke", privilege: "SELECT", objectType: "FUTURE TABLE", object: "SALES.CORE.<TABLE>", to: "T_SALES_CORE_READ" };
    expect(sqlOf([fut])).toContain("REVOKE SELECT ON FUTURE TABLES IN SCHEMA SALES.CORE FROM ROLE T_SALES_CORE_READ;");
    expect(sqlOf([{ ...fut, object: "SALES.<TABLE>" }])).toContain("ON FUTURE TABLES IN DATABASE SALES FROM");
    const grant = (objectType: string, object: string) => terraformOf([{ op: "grant", privilege: "USAGE", objectType, object, to: "F_X" }]);
    expect(grant("WAREHOUSE", "WH_SALES_XS")).toContain('on_account_object {\n    object_type = "WAREHOUSE"\n    object_name = "WH_SALES_XS"');
    expect(grant("DATABASE", "SALES")).toContain('object_type = "DATABASE"');
    expect(grant("DATABASE", "SALES")).not.toContain("on_database");
    expect(grant("SCHEMA", "SALES.CORE")).toContain('on_schema {\n    schema_name = "SALES.CORE"');
    expect(grant("FUTURE TABLE", "SALES.CORE.<TABLE>")).toContain('object_type_plural = "TABLES"\n      in_schema   = "SALES.CORE"');
    const db = terraformOf([{ op: "grant", privilege: "USAGE", objectType: "DATABASE", object: "HR", to: "HR.SC_R" }]);
    expect(db).toContain('resource "snowflake_grant_privileges_to_database_role"');
    expect(db).toContain('on_database = "HR"');
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
