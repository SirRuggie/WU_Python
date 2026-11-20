// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TicketBrowser from "./TicketBrowser";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/tickets");
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  api.mockReset();
  api.mockResolvedValue({ tickets: [], has_more: false });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const statusSelect = () =>
  [...document.querySelectorAll("dialog label")]
    .find((label) => label.textContent?.startsWith("Status"))!
    .querySelector("select")!;
const filtersButton = () =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
    button.textContent?.startsWith("Filters"),
  )!;
const openFilters = () => act(async () => filtersButton().click());

it("lists Open first because Open is the default status", async () => {
  await act(async () => root.render(<TicketBrowser />));
  expect(host.querySelector("details")).toBeNull();
  expect(host.querySelector("select")).toBeNull();
  await openFilters();
  const select = statusSelect();
  expect(select.value).toBe("open");
  expect([...select.options].map((option) => option.value)).toEqual([
    "open",
    "all",
    "approved",
    "denied",
    "closed",
  ]);
});

it("Clear filters returns to the default Open status", async () => {
  await act(async () => root.render(<TicketBrowser />));
  await openFilters();
  const select = statusSelect();
  await act(async () => {
    select.value = "closed";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(filtersButton().textContent).toBe("Filters · 1");
  expect(host.querySelector(".ticket-list-summary")?.textContent).toContain(
    "Closed tickets",
  );
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('dialog [aria-label="Close panel"]')!
      .click(),
  );
  const clear = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Clear filters",
  );
  expect(clear).toBeTruthy();
  await act(async () => clear!.click());
  expect(filtersButton().textContent).toBe("Filters");
  await openFilters();
  expect(statusSelect().value).toBe("open");
  expect(String(api.mock.calls.at(-1)?.[0])).toContain("status=open");
});

it("uses the singular for one ticket on the page", async () => {
  api.mockResolvedValue({
    tickets: [
      {
        id: "1",
        number: 1,
        name: "ticket-0001",
        user_id: "1",
        kind: "join",
        status: "open",
        created_at: null,
        flags: [],
      },
    ],
    has_more: false,
  });
  await act(async () => root.render(<TicketBrowser />));
  expect(host.querySelector(".ticket-list-summary")?.textContent).toContain(
    "Open tickets · 1 on this page",
  );
});

it.each(["all", "main", "fwa"])(
  "restores and changes the same type URL key (%s)",
  async (type) => {
    history.replaceState({}, "", `/tickets?type=${type}&status=closed`);
    await act(async () => root.render(<TicketBrowser />));
    const scope = host.querySelector('[aria-label="Ticket type"]')!;
    expect(scope.getAttribute("role")).toBe("group");
    const selected = scope.querySelector('[aria-pressed="true"]')!;
    expect(selected.textContent).toBe(
      type === "all" ? "All" : type === "main" ? "Main" : "FWA",
    );
    const next = type === "main" ? "fwa" : "main";
    await act(async () =>
      [...scope.querySelectorAll<HTMLButtonElement>("button")]
        .find(
          (button) => button.textContent === (next === "main" ? "Main" : "FWA"),
        )!
        .click(),
    );
    expect(new URLSearchParams(location.search).get("type")).toBe(next);
    expect(new URLSearchParams(location.search).get("status")).toBe("closed");
    expect(String(api.mock.calls.at(-1)?.[0])).toContain(`kind=${next}`);
    expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
      true,
    );
  },
);

it("counts the non-default status, applicant flag and both dates in Filters", async () => {
  history.replaceState({}, "", "/tickets?status=closed");
  await act(async () => root.render(<TicketBrowser />));
  await openFilters();
  const labels = [...document.querySelectorAll("dialog label")];
  await act(async () => {
    const flag = labels
      .find((label) => label.textContent?.startsWith("Applicant flag"))!
      .querySelector("select")!;
    flag.value = "blacklisted";
    flag.dispatchEvent(new Event("change", { bubbles: true }));
    for (const [label, value] of [
      ["From", "2026-11-01"],
      ["To", "2026-11-20"],
    ]) {
      const input = labels
        .find((node) => node.textContent?.trim() === label)!
        .querySelector("input")!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  expect(filtersButton().textContent).toBe("Filters · 4");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Dates use UTC.",
  );
});
