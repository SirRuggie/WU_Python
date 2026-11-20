// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import TicketBrowser from "./TicketBrowser";
import TicketConversation from "./TicketConversation";
import { formatDateTime } from "./format";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
const at = "2026-01-02T00:30:00Z";
const ticket = {
  id: "utc-boundary",
  number: 1,
  name: "Sample",
  user_id: "123",
  kind: "join",
  status: "open",
  created_at: at,
  flags: [],
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  const original = Intl.DateTimeFormat.prototype.resolvedOptions;
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(
    function (this: Intl.DateTimeFormat) {
      return { ...original.call(this), timeZone: "Pacific/Honolulu" };
    },
  );
  api.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
function expectUtc(text: string | null) {
  const utc = formatDateTime(at, { timeZone: "UTC" });
  const local = formatDateTime(at);
  expect(local).not.toBe(utc);
  expect(text).toContain(utc);
  expect(text).not.toContain(local);
}
it("keeps the UTC-labelled ticket list on January 2 for a January 1 viewer", async () => {
  api.mockResolvedValue({ tickets: [ticket], has_more: false });
  await act(async () => root.render(<TicketBrowser />));
  expectUtc(host.textContent);
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.open = false;
  });
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.startsWith("Filters"))!
      .click(),
  );
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Dates use UTC.",
  );
  expectUtc(host.textContent);
});
it("keeps both opened and message dates in UTC for a non-UTC viewer", async () => {
  api.mockResolvedValue({
    ticket,
    messages: [
      {
        id: "message",
        author: "Sample",
        at,
        edited: false,
        text: "Fixture only",
        attachments: [],
        bot: false,
      },
    ],
    older: null,
    discord_url: "https://discord.com/channels/1/2",
    archived: false,
    checked_at: 1,
  });
  await act(async () =>
    root.render(<TicketConversation ticket={ticket} onBack={() => {}} />),
  );
  expectUtc(
    [...host.querySelectorAll("small")].find((node) =>
      node.textContent?.startsWith("Opened "),
    )?.textContent ?? null,
  );
  expectUtc(
    host.querySelector(".ticket-message header small")?.textContent ?? null,
  );
});
