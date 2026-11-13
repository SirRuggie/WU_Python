// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./useDiscordIdentities", () => ({
  default: () => ({ members: {}, loading: false }),
}));
import ParticipationWorkspace from "./ParticipationWorkspace";

const row = (tag: string, name: string) => ({
  tag,
  player_name: name,
  town_hall: 16,
  pool: "main",
  assigned_clan_tag: "#2YQ",
  assigned_clan_name: "Family",
  attacks: 4,
  stars: 9,
  notes: "",
  revision: 1,
  updated_by: null,
  updated_at: null,
  in_latest_publication: true,
  source_status: "complete",
  source_complete: true,
});
const participation = {
  publication_version: 1,
  accounts: [row("#P1", "Alpha"), row("#P2", "Bravo")],
  sync: {
    cycle: "2026-11",
    cycle_source: "settings",
    enabled: true,
    status: "complete",
    warning: null,
    last_checked_at: "2026-11-01T12:00:00Z",
    last_success_at: "2026-11-01T12:00:00Z",
    updated_at: "2026-11-01T12:00:00Z",
  },
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
const named = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.trim() === name,
  )!;
const details = (name: string) =>
  host.querySelector<HTMLButtonElement>(
    `button[aria-label="Details for ${name}"]`,
  )!;
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
  api
    .mockReset()
    .mockImplementation(async (_route: string, method?: string) =>
      method === "PATCH"
        ? { account: { ...row("#P1", "Alpha"), notes: "Late", revision: 2 } }
        : participation,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
      />,
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("the open Details sheet saves staff notes; the list and other records stay locked", async () => {
  await act(async () => details("Alpha").click());
  const notes = host.querySelector<HTMLTextAreaElement>(
    'textarea[name="notes"]',
  )!;
  expect(notes.disabled).toBe(false);
  // The list-level controls and the other records stay locked meanwhile.
  // Check Clash now lives in the capture menu, which disables as a whole.
  expect(
    host.querySelector<HTMLButtonElement>(
      ".participation-capture .roster-action-trigger",
    )!.disabled,
  ).toBe(true);
  expect(details("Bravo").disabled).toBe(true);
  expect(
    host.querySelector<HTMLButtonElement>(
      ".cwl-page-header .roster-menu-trigger",
    )?.disabled,
  ).toBe(true);
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!;
    setter.call(notes, "Late");
    notes.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => named("Save").click());
  expect(writes()).toHaveLength(1);
  expect(writes()[0][1]).toBe("PATCH");
  expect(writes()[0][2]).toMatchObject({ notes: "Late", revision: 1 });
  expect(host.querySelector("dialog")?.open).toBe(false);
});
