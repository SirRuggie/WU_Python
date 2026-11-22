// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TicketBrowser from "./TicketBrowser";
import { DashboardHistory } from "./dashboardHistory";
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

it.each(["all", "recruit", "account", "staff"])(
  "keeps %s type and status in the URL through read-only scope changes",
  async (type) => {
    history.replaceState({}, "", `/tickets?type=${type}&status=closed`);
    await act(async () => root.render(<TicketBrowser />));
    const scope = host.querySelector('[aria-label="Ticket type"]')!;
    const active = scope.querySelector('[aria-pressed="true"]');
    expect(active?.textContent).toBe(
      { all: "All", recruit: "Recruits", account: "Accounts", staff: "Staff" }[
        type
      ],
    );
    await act(async () =>
      [...scope.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.textContent === "Accounts")!
        .click(),
    );
    expect(new URLSearchParams(location.search).get("type")).toBe("account");
    expect(new URLSearchParams(location.search).get("status")).toBe("closed");
    expect(String(api.mock.calls.at(-1)?.[0])).toContain("type=account");
    expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
      true,
    );
  },
);

it("preserves a legacy Main kind link until a new scope is explicitly chosen", async () => {
  history.replaceState({}, "", "/tickets?kind=main");
  await act(async () => root.render(<TicketBrowser />));
  expect(String(api.mock.calls[0][0])).toContain("type=main");
  const scope = host.querySelector('[aria-label="Ticket type"]')!;
  expect(scope.querySelector('[aria-pressed="true"]')?.textContent).toBe(
    "Recruits",
  );
  await act(async () =>
    [...scope.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "All")!
      .click(),
  );
  expect(new URLSearchParams(location.search).has("kind")).toBe(false);
});

it("hides the type control when the actor has only Accounts", async () => {
  api.mockResolvedValue({
    tickets: [],
    has_more: false,
    allowed_types: ["account"],
  });
  await act(async () => root.render(<TicketBrowser />));
  expect(host.querySelector('[aria-label="Ticket type"]')).toBeNull();
  expect(filtersButton()).toBeTruthy();
});

it("uses a row-wide accessible read action and keeps flags beside the name", async () => {
  api.mockResolvedValue({
    tickets: [
      {
        id: "ticket_1",
        number: 1,
        name: "Casey",
        user_id: "123456789012345678",
        kind: "staff",
        status: "open",
        created_at: "2026-11-20T12:00:00Z",
        flags: [{ kind: "ghosted", label: "Ghosted", reason: "fixture" }],
      },
    ],
    has_more: false,
    allowed_types: ["staff"],
  });
  await act(async () => root.render(<TicketBrowser />));
  const read = host.querySelector("a.ticket-read")!;
  expect(read.getAttribute("aria-label")).toBe("Read Casey #1, Contact staff");
  expect(
    host.querySelector(".ticket-name-line .ticket-flags")?.textContent,
  ).toBe("Ghosted");
  expect(host.querySelector(".ticket-row small")?.textContent).toContain(
    "2026",
  );
});

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

const linkedTicket = {
  id: "ticket_123",
  number: 123,
  name: "Casey",
  user_id: "123456789012345678",
  kind: "staff",
  status: "open",
  created_at: "2026-11-20T12:00:00Z",
  flags: [],
};
const readerFixture = () => ({
  ticket: linkedTicket,
  messages: [],
  older: null,
  discord_url: "https://discord.com/channels/1/2",
  archived: false,
  checked_at: 1,
});
it("restores a direct read URL in a new tab using the existing authorized GET", async () => {
  history.replaceState(
    { wuDashboardIndex: 4 },
    "",
    "/tickets?type=staff&ticket=ticket_123",
  );
  api.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes("/messages")
        ? readerFixture()
        : {
            tickets: [linkedTicket],
            has_more: false,
            allowed_types: ["staff"],
          },
    ),
  );
  await act(async () => root.render(<TicketBrowser />));
  expect(host.querySelector("h1")?.textContent).toBe("#123 · Casey");
  expect(
    api.mock.calls.some((call) =>
      String(call[0]).startsWith("/manage/tickets/ticket_123/messages"),
    ),
  ).toBe(true);
  expect(
    api.mock.calls.some((call) =>
      String(call[0]).startsWith("/manage/tickets?"),
    ),
  ).toBe(false);
  const back = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.includes("Back to tickets"),
  )!;
  await act(async () => back.click());
  expect(new URLSearchParams(location.search).get("ticket")).toBeNull();
  expect(new URLSearchParams(location.search).get("type")).toBe("staff");
  expect(host.querySelector("h1")?.textContent).toBe("Tickets");
});
it("keeps real link semantics for modified clicks and restores list focus after Back", async () => {
  history.replaceState({ wuDashboardIndex: 4 }, "", "/tickets?type=staff");
  api.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes("/messages")
        ? readerFixture()
        : {
            tickets: [linkedTicket],
            has_more: false,
            allowed_types: ["staff"],
          },
    ),
  );
  await act(async () => root.render(<TicketBrowser />));
  const link = host.querySelector<HTMLAnchorElement>("a.ticket-read")!;
  expect(new URL(link.href).searchParams.get("ticket")).toBe("ticket_123");
  const modified = new MouseEvent("click", {
    bubbles: true,
    cancelable: true,
    button: 0,
    ctrlKey: true,
  });
  await act(async () => link.dispatchEvent(modified));
  expect(modified.defaultPrevented).toBe(false);
  await act(async () => link.click());
  expect(history.state.wuDashboardIndex).toBe(4);
  expect(history.state.wuTicketReader).toBe("ticket_123");
  expect(host.querySelector("h1")?.textContent).toBe("#123 · Casey");
  await act(async () => {
    history.replaceState({ wuDashboardIndex: 4 }, "", "/tickets?type=staff");
    window.dispatchEvent(
      new PopStateEvent("popstate", { state: history.state }),
    );
  });
  expect(host.querySelector("h1")?.textContent).toBe("Tickets");
  expect(document.activeElement?.getAttribute("aria-label")).toBe(
    "Read Casey #123, Contact staff",
  );
});

it("preserves a direct reader URL during the shell's same-view auth rewrite", () => {
  history.replaceState(
    { wuDashboardIndex: 4 },
    "",
    "/tickets?type=staff&ticket=ticket_123",
  );
  const controller = new DashboardHistory(history);
  controller.write({ view: "tickets", season: "" }, false);
  expect(new URLSearchParams(location.search).get("ticket")).toBe("ticket_123");
  controller.write({ view: "roster", season: "1" }, true);
  expect(new URLSearchParams(location.search).has("ticket")).toBe(false);
});

it("shows a permanent access denial without search, Filters or retry", async () => {
  const { ApiError } = await import("./api");
  api.mockRejectedValue(new ApiError("Ticket access is not permitted.", 403));
  await act(async () => root.render(<TicketBrowser />));
  expect(host.textContent).toContain("You do not have access to tickets.");
  expect(host.querySelector('input[type="search"]')).toBeNull();
  expect(host.querySelector(".ticket-toolbar")).toBeNull();
  expect(host.textContent).not.toContain("Try again");
});

it("keeps retry available for a temporary ticket load failure", async () => {
  const { ApiError } = await import("./api");
  api.mockRejectedValue(new ApiError("Temporary failure", 503));
  await act(async () => root.render(<TicketBrowser />));
  expect(host.textContent).toContain("Temporary failure");
  expect(host.textContent).toContain("Try again");
  expect(host.querySelector('input[type="search"]')).not.toBeNull();
});

it("recovers a forbidden saved type to one authorized All read", async () => {
  const { ApiError } = await import("./api");
  history.replaceState({}, "", "/tickets?type=staff");
  api.mockRejectedValueOnce(
    new ApiError("You do not have access to this ticket type.", 403),
  );
  api.mockResolvedValue({
    tickets: [],
    has_more: false,
    allowed_types: ["main", "fwa", "account"],
  });
  await act(async () => root.render(<TicketBrowser />));
  const reads = api.mock.calls.map(([path]) => String(path));
  expect(reads).toHaveLength(2);
  expect(reads[0]).toContain("type=staff");
  expect(reads[1]).toContain("type=all");
  expect(new URLSearchParams(window.location.search).get("type")).toBeNull();
  expect(host.querySelector('input[type="search"]')).not.toBeNull();
  expect(host.textContent).toContain("Recruits");
  expect(host.textContent).toContain("Accounts");
  expect(host.textContent).not.toContain("You do not have access to tickets.");
});

it("stops after the All recovery also receives a permanent denial", async () => {
  const { ApiError } = await import("./api");
  history.replaceState({}, "", "/tickets?type=staff");
  api.mockRejectedValue(new ApiError("Ticket access is not permitted.", 403));
  await act(async () => root.render(<TicketBrowser />));
  expect(api.mock.calls).toHaveLength(2);
  expect(host.textContent).toContain("You do not have access to tickets.");
  expect(host.querySelector(".ticket-toolbar")).toBeNull();
  expect(host.textContent).not.toContain("Try again");
});

it("shows account clan without inferring a clan for historical rows", async () => {
  api.mockResolvedValue({
    tickets: ["main", "fwa", null].map((clan, index) => ({
      id: String(index + 1),
      number: index + 1,
      name: "Account owner",
      user_id: "50",
      kind: "account",
      account_clan: clan,
      status: "open",
      created_at: null,
      flags: [],
    })),
    has_more: false,
  });
  await act(async () => root.render(<TicketBrowser />));
  const rows = [...host.querySelectorAll<HTMLElement>(".ticket-row")];
  expect(rows).toHaveLength(3);
  expect(rows[0].textContent).toContain("Add account · Main");
  expect(rows[1].textContent).toContain("Add account · FWA");
  expect(rows[2].textContent).toContain("Add account");
  expect(rows[2].textContent).not.toMatch(/Main|FWA/);
  expect(
    rows[0].querySelector(".ticket-read")?.getAttribute("aria-label"),
  ).toContain("Add account · Main");
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
});
