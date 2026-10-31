// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CopyReminders from "./CopyReminders";
import { api } from "../api";
vi.mock("../api", () => ({ api: vi.fn() }));
const settings = {
  enabled: true,
  channel_id: "123456789012345678",
  minutes: [30],
  war_started: true,
  audience: "remaining" as const,
};
const source = { settings, revision: "source-v1", history: [] };
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const onBusy = vi.fn();
beforeEach(() => {
  vi.mocked(api).mockReset();
  onBusy.mockReset();
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = false;
    },
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockResolvedValue({
    clans: [
      {
        name: "Alpha",
        tag: "#P2Y",
        type: "CWL",
        revision: "alpha-v1",
        settings,
      },
      {
        name: "Beta",
        tag: "#P8Y",
        type: "FWA",
        revision: "beta-v1",
        settings: { ...settings, channel_id: "", enabled: false },
      },
    ],
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
async function render(revision = source.revision) {
  await act(async () =>
    root.render(
      <CopyReminders
        base="/source"
        source={{ ...source, revision }}
        disabled={false}
        onBusy={onBusy}
      />,
    ),
  );
}
async function open() {
  await render();
  await act(async () => {
    const details = host.querySelector("details")!;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
}
async function click(text: string) {
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find((b) => b.textContent === text)!
      .click(),
  );
}
async function choose(name: string) {
  await act(async () =>
    [...host.querySelectorAll("label")]
      .find((l) => l.textContent?.includes(name))!
      .querySelector<HTMLInputElement>("input")!
      .click(),
  );
}
it("loads targets only when opened", async () => {
  await render();
  expect(api).not.toHaveBeenCalled();
  await open();
  expect(api).toHaveBeenCalledWith("/source/copy");
});
it("previews targets and requires confirmation before sending their own revisions, without channel fields", async () => {
  await open();
  await choose("Alpha");
  await choose("Beta");
  await click("Review copy");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Copy to 2 clans?",
  );
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Beta · Needs a channel · Off",
  );
  expect(vi.mocked(api).mock.calls).toHaveLength(1);
  vi.mocked(api).mockResolvedValue({
    results: [
      { tag: "#P2Y", ok: true, message: "Copied" },
      { tag: "#P8Y", ok: false, message: "Settings changed" },
    ],
  });
  await click("Copy settings");
  expect(api).toHaveBeenLastCalledWith("/source/copy", "POST", {
    revision: "source-v1",
    fields: ["minutes"],
    targets: [
      { tag: "#P2Y", revision: "alpha-v1" },
      { tag: "#P8Y", revision: "beta-v1" },
    ],
  });
  expect(host.textContent).toContain("Alpha: Copied");
  expect(host.textContent).toContain("Beta: Settings changed");
});
it("source revision change invalidates an open confirmation", async () => {
  await open();
  await choose("Alpha");
  await click("Review copy");
  await render("source-v2");
  expect(document.querySelector("dialog")).toBeNull();
  expect(vi.mocked(api).mock.calls).toHaveLength(1);
});
