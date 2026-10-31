// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import AddClan from "./AddClan";
import { api } from "../api";
vi.mock("../api", () => ({ api: vi.fn() }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const onOpen = vi.fn();
const clan = {
  tag: "#P0LYQ",
  name: "Example",
  revision: "one",
  type: "",
  logo: "",
};
const found = {
  state: "found",
  tag: clan.tag,
  name: clan.name,
  members: 42,
  removal_id: null,
  reminder_revision: null,
};
beforeEach(async () => {
  vi.mocked(api).mockReset();
  onOpen.mockReset();
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
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(<AddClan disabled={false} onBusy={() => {}} onOpen={onOpen} />),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
async function click(text: string) {
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find((b) => b.textContent === text)!
      .click(),
  );
}
async function lookup(result: unknown) {
  vi.mocked(api).mockResolvedValueOnce(result);
  await act(async () => {
    const input = host.querySelector("input")!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, clan.tag);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
}
it("looks up first, then opens the added clan", async () => {
  await lookup(found);
  expect(host.textContent).toContain("Found: Example · 42 members");
  expect(vi.mocked(api).mock.calls.every((c) => c[1] !== "POST")).toBe(true);
  vi.mocked(api).mockResolvedValueOnce({ clan, warning: "" });
  await click("Add");
  expect(api).toHaveBeenLastCalledWith("/manage/clans", "POST", {
    tag: clan.tag,
  });
  expect(onOpen).toHaveBeenCalledWith(clan, "");
});
it("opens existing clans without submitting a write", async () => {
  await lookup({ state: "existing", clan });
  expect(host.textContent).toContain("Already in the family");
  await click("Open");
  expect(api).toHaveBeenCalledTimes(1);
  expect(onOpen).toHaveBeenCalledWith(clan, "");
});
it("confirms start fresh and sends the reviewed removal and reminder revision", async () => {
  await lookup({
    ...found,
    state: "removed",
    removal_id: "old",
    reminder_revision: "version-eight",
  });
  await click("Start fresh");
  expect(api).toHaveBeenCalledTimes(1);
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Delivery history is kept",
  );
  vi.mocked(api).mockResolvedValueOnce({
    clan,
    warning: "Review War reminders.",
  });
  await act(async () =>
    document.querySelector<HTMLButtonElement>("dialog .primary")!.click(),
  );
  expect(api).toHaveBeenLastCalledWith("/manage/clans", "POST", {
    tag: clan.tag,
    mode: "fresh",
    removal_id: "old",
    reminder_revision: "version-eight",
  });
  expect(onOpen).toHaveBeenCalledWith(clan, "Review War reminders.");
});
it("invalidates the lookup when the entered tag changes", async () => {
  await lookup(found);
  await act(async () => {
    const input = host.querySelector("input")!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "#OTHER");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).not.toContain("Found:");
});

it("restores the reviewed snapshot only after confirmation", async () => {
  await lookup({
    ...found,
    state: "removed",
    removal_id: "old",
    reminder_revision: "version-eight",
  });
  await click("Restore old settings");
  expect(api).toHaveBeenCalledTimes(1);
  await click("Cancel");
  expect(api).toHaveBeenCalledTimes(1);
  await click("Restore old settings");
  vi.mocked(api).mockResolvedValueOnce({ clan, message: "Clan restored." });
  await act(async () =>
    document.querySelector<HTMLButtonElement>("dialog .primary")!.click(),
  );
  expect(api).toHaveBeenLastCalledWith(
    "/manage/clan-history/old/restore",
    "POST",
    { confirm_tag: clan.tag },
  );
  expect(onOpen).toHaveBeenCalledWith(clan, "Clan restored.");
});

it("asks about dirty settings before writing and cancels without adding", async () => {
  const beforeAdd = vi.fn().mockResolvedValue(false);
  await act(async () =>
    root.render(
      <AddClan
        disabled={false}
        onBusy={() => {}}
        onOpen={onOpen}
        beforeAdd={beforeAdd}
      />,
    ),
  );
  await lookup(found);
  await click("Add");
  expect(beforeAdd).toHaveBeenCalledOnce();
  expect(api).toHaveBeenCalledTimes(1);
  expect(onOpen).not.toHaveBeenCalled();
  beforeAdd.mockResolvedValue(true);
  vi.mocked(api).mockResolvedValueOnce({ clan, warning: "" });
  await click("Add");
  expect(api).toHaveBeenLastCalledWith("/manage/clans", "POST", {
    tag: clan.tag,
  });
  expect(onOpen).toHaveBeenCalledOnce();
});
