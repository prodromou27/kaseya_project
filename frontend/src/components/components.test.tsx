import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";
import { DataTable } from "./DataTable";
import { ErrorState, QueryBoundary } from "./States";
import { Tabs } from "./Tabs";

type Row = { id: string; name: string };
const columns: ColumnDef<Row, unknown>[] = [{ header: "Name", accessorKey: "name" }];

describe("DataTable", () => {
  it("renders an accessible table with caption and column headers", () => {
    render(<DataTable caption="People" columns={columns} rows={[{ id: "1", name: "<b>x</b>" }]} total={1} />);
    const table = screen.getByRole("table", { name: "People" });
    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    // Source-controlled text is rendered as text, never HTML (SEC-02).
    expect(screen.getByText("<b>x</b>")).toBeInTheDocument();
  });

  it("shows the empty state instead of an empty table", () => {
    render(<DataTable caption="People" columns={columns} rows={[]} emptyTitle="Nobody here." />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("Nobody here.")).toBeInTheDocument();
  });

  it("paginates server-side", async () => {
    const onPageChange = vi.fn();
    render(<DataTable caption="People" columns={columns} rows={[{ id: "1", name: "a" }]} total={120} page={1} pageSize={50} onPageChange={onPageChange} />);
    expect(screen.getByText(/120 records · page 1 of 3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });
});

describe("States", () => {
  it("error state is announced and shows request reference", () => {
    render(<ErrorState error={new ApiError(500, "server_error", "Boom.", "req-9")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Boom. (ref req-9)");
  });

  it("QueryBoundary renders loading, error and empty states", () => {
    const base = { error: null, refetch: () => undefined };
    const { rerender } = render(<QueryBoundary query={{ ...base, isPending: true, isError: false, data: undefined }}>{() => "content"}</QueryBoundary>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    rerender(<QueryBoundary query={{ ...base, isPending: false, isError: true, data: undefined, error: new Error("x") }}>{() => "content"}</QueryBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(
      <QueryBoundary query={{ ...base, isPending: false, isError: false, data: [] as number[] }} isEmpty={(d) => d.length === 0}>
        {() => "content"}
      </QueryBoundary>,
    );
    expect(screen.getByText("Nothing to show yet.")).toBeInTheDocument();
  });
});

function TabsHarness() {
  const [active, setActive] = useState("a");
  return (
    <Tabs
      label="Sections"
      active={active}
      onChange={setActive}
      tabs={[
        { id: "a", label: "Alpha", content: "Panel A" },
        { id: "b", label: "Beta", content: "Panel B" },
      ]}
    />
  );
}

describe("Tabs", () => {
  it("supports keyboard navigation per WAI-ARIA", async () => {
    render(<TabsHarness />);
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha).toHaveAttribute("aria-selected", "true");
    alpha.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel B");
    await userEvent.keyboard("{Home}");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel A");
  });
});
