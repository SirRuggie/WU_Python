// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TicketBrowser from "./TicketBrowser";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
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
  [...host.querySelectorAll("label")]
    .find((label) => label.textContent?.startsWith("Status"))!
    .querySelector("select")!;

it("lists Open first because Open is the default status", async () => {
  await act(async () => root.render(<TicketBrowser />));
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
  const select = statusSelect();
  await act(async () => {
    select.value = "closed";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const clear = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Clear filters",
  );
  expect(clear).toBeTruthy();
  await act(async () => clear!.click());
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
  expect(host.textContent).toContain("1 ticket on this page");
  expect(host.textContent).not.toContain("1 tickets");
});
