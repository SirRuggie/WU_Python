// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import MemberFilters from "./MemberFilters";
import type { MemberFilters as Filters } from "./model";

it("keeps status and actions visible while Filters counts roles, bots and selected only and Sort stays independent", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  let value: Filters = {
    query: "",
    status: "all",
    roles: ["99"],
    bots: false,
    selectedOnly: false,
  };
  function Harness() {
    const [filters, setFilters] = useState(value);
    const [sort, setSort] = useState<"name" | "time_zone">("name");
    value = filters;
    return (
      <MemberFilters
        value={filters}
        onChange={setFilters}
        sort={sort}
        onSort={setSort}
        roles={[{ id: "99", name: "Local role" }]}
        counts={{ all: 4, needs_flag: 1, no_time_zone: 2, check_name: 0 }}
        actions={<button>Existing action</button>}
      />
    );
  }
  try {
    await act(async () => root.render(<Harness />));
    const filters = () =>
      [...host.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
        button.textContent?.startsWith("Filters"),
      )!;
    expect(filters().textContent).toBe("Filters · 1");
    expect(host.querySelector("details")).toBeNull();
    expect(host.textContent).toContain("Existing action");
    expect(
      host.querySelector('[aria-label="Member status"]')?.textContent,
    ).toContain("All 4");
    await act(async () => filters().click());
    expect(document.querySelector("dialog")?.textContent).toContain(
      "Filter members",
    );
    const selected = [...document.querySelectorAll("dialog label")]
      .find((label) => label.textContent === "Selected people")!
      .querySelector<HTMLInputElement>("input")!;
    await act(async () => selected.click());
    expect(value).toEqual({
      query: "",
      status: "all",
      roles: ["99"],
      bots: false,
      selectedOnly: true,
    });
    expect(filters().textContent).toBe("Filters · 2");
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('dialog [aria-label="Close panel"]')!
        .click(),
    );
    await act(async () =>
      host
        .querySelector<HTMLButtonElement>('[aria-label="Sort: Name"]')!
        .click(),
    );
    const zone = [
      ...document.querySelectorAll<HTMLButtonElement>("dialog button"),
    ].find((button) => button.textContent === "Time zone")!;
    await act(async () => zone.click());
    expect(host.querySelector('[aria-label="Sort: Time zone"]')).toBeTruthy();
    expect(value.roles).toEqual(["99"]);
    expect(value.selectedOnly).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
