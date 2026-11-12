import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { customerA, makeMe, mockFetch, page, renderApp } from "../test/utils";

const unauth = { status: 401, body: { error: { code: "not_authenticated", message: "Authentication credentials were not provided." } } };

describe("authentication flow", () => {
  it("redirects anonymous users to the login page", async () => {
    mockFetch({ "GET /api/v1/auth/me/": unauth, "GET /api/v1/auth/config/": { body: { local_login_enabled: true, oidc_enabled: false } } });
    renderApp("/customers");
    expect(await screen.findByRole("form", { name: "Local sign-in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("logs in and lands on the dashboard", async () => {
    let authed = false;
    const me = makeMe();
    mockFetch({
      "GET /api/v1/auth/me/": () => (authed ? { body: me } : unauth),
      "GET /api/v1/auth/config/": { body: { local_login_enabled: true, oidc_enabled: true } },
      "POST /api/v1/auth/login/": () => {
        authed = true;
        return { body: me };
      },
      "GET /api/v1/customers/": { body: page([customerA]) },
    });
    renderApp("/login");
    expect(await screen.findByRole("link", { name: /Microsoft Entra ID/ })).toHaveAttribute("href", "/api/v1/auth/oidc/login/");
    await userEvent.type(screen.getByLabelText("Email"), "eng@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("shows a generic error for bad credentials", async () => {
    mockFetch({
      "GET /api/v1/auth/me/": unauth,
      "GET /api/v1/auth/config/": { body: { local_login_enabled: true, oidc_enabled: false } },
      "POST /api/v1/auth/login/": { status: 400, body: { error: { code: "invalid_credentials", message: "Invalid email or password.", request_id: "r1" } } },
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "x@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });

  it("explains SSO failures from the callback", async () => {
    mockFetch({ "GET /api/v1/auth/me/": unauth, "GET /api/v1/auth/config/": { body: { local_login_enabled: false, oidc_enabled: true } } });
    renderApp("/login?error=account_not_provisioned");
    expect(await screen.findByText(/has not been provisioned/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Local sign-in" })).not.toBeInTheDocument();
  });
});

describe("application shell", () => {
  it("hides administration from non-super-admins and shows account status", async () => {
    mockFetch({ "GET /api/v1/auth/me/": { body: makeMe() }, "GET /api/v1/customers/": { body: page([customerA]) } });
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Administration" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /Customers/ })).toBeInTheDocument();
    expect(screen.getByText("Eng One")).toBeInTheDocument();
  });

  it("customer selector lists only server-authorised customers and ignores forged stored IDs", async () => {
    window.sessionStorage.setItem("okp.selectedCustomer", "bbbbbbbb-forged");
    const other = { ...customerA, id: "aaaaaaaa-0000-0000-0000-000000000002", code: "ZETA", name: "Zeta" };
    mockFetch({ "GET /api/v1/auth/me/": { body: makeMe() }, "GET /api/v1/customers/": { body: page([customerA, other]) } });
    renderApp("/");
    const select = await screen.findByLabelText("Customer");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    expect(select).toHaveValue("");
    await userEvent.selectOptions(select, customerA.id);
    expect(await screen.findByText("ACME — Acme Ltd", { selector: "p" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("okp.selectedCustomer")).toBe(customerA.id);
  });

  it("shows an honest empty state when the user has no grants", async () => {
    mockFetch({ "GET /api/v1/auth/me/": { body: makeMe({ memberships: [] }) }, "GET /api/v1/customers/": { body: page([]) } });
    renderApp("/");
    expect(await screen.findByText("You have no customer assignments.")).toBeInTheDocument();
  });

  it("future modules show no figures", async () => {
    mockFetch({ "GET /api/v1/auth/me/": { body: makeMe() }, "GET /api/v1/customers/": { body: page([customerA]) } });
    renderApp("/software");
    expect(await screen.findByText("This module is not implemented yet.")).toBeInTheDocument();
    expect(screen.queryByText(/\b\d+\s*(devices|assets|outdated)/i)).not.toBeInTheDocument();
  });
});

describe("customer detail", () => {
  it("shows only tabs permitted by the user's capabilities", async () => {
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([customerA]) },
      [`GET /api/v1/customers/${customerA.id}/`]: { body: customerA },
    });
    renderApp(`/customers/${customerA.id}`);
    const tablist = await screen.findByRole("tablist", { name: "Customer sections" });
    const tabs = within(tablist).getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Overview", "Reports"]);
  });

  it("renders a not-found error for a customer the server refuses", async () => {
    mockFetch({ "GET /api/v1/auth/me/": { body: makeMe() }, "GET /api/v1/customers/": { body: page([customerA]) } });
    renderApp("/customers/bbbbbbbb-0000-0000-0000-000000000009");
    expect(await screen.findByRole("alert")).toHaveTextContent("Not found. (ref req-test)");
  });

  it("customer admin sees members tab and can only grant delegable roles", async () => {
    const adminCustomer = { ...customerA, my_capabilities: ["customer.read", "customer.manage_members", "customer.audit.read", "customer.export"] };
    mockFetch({
      "GET /api/v1/auth/me/": { body: makeMe() },
      "GET /api/v1/customers/": { body: page([adminCustomer]) },
      [`GET /api/v1/customers/${customerA.id}/`]: { body: adminCustomer },
      [`GET /api/v1/customers/${customerA.id}/memberships/`]: { body: page([]) },
    });
    renderApp(`/customers/${customerA.id}`);
    await userEvent.click(await screen.findByRole("tab", { name: "Members" }));
    const roleSelect = await screen.findByLabelText("Role");
    expect(within(roleSelect).getAllByRole("option").map((o) => o.textContent)).toEqual(["engineer", "viewer"]);
  });
});
