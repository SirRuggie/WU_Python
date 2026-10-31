// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import StrikeBulkMark from "./StrikeBulkMark";
import type { ActivityAccount } from "./strikeActivityView";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const row = {
  player_tag: "#PYY",
  player_name: "Fixture",
  current_clan_tag: "#PQQ",
  revision: 7,
} as ActivityAccount;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("submits groups once with displayed revisions and locks duplicate submits", async () => {
  let release: (value: unknown) => void = () => {};
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const saved = vi.fn(),
    busy = vi.fn();
  await act(async () =>
    root.render(<StrikeBulkMark rows={[row]} onSaved={saved} onBusy={busy} />),
  );
  const save = host.querySelector("button")!;
  await act(async () => {
    save.click();
    save.click();
  });
  expect(api).toHaveBeenCalledTimes(1);
  expect(api).toHaveBeenCalledWith(
    "/strikes/replacement-list/bulk",
    "POST",
    expect.objectContaining({
      clan_tag: "#PQQ",
      player_tags: ["#PYY"],
      revisions: { "#PYY": 7 },
    }),
  );
  expect(save.disabled).toBe(true);
  await act(async () => release({ added_count: 1, skipped_count: 0 }));
  expect(saved).toHaveBeenCalledOnce();
  expect(busy).toHaveBeenLastCalledWith(false);
});
it("conflict preserves draft and needs explicit refresh before any next write", async () => {
  vi.mocked(api).mockRejectedValue(new ApiError("Changed after one save", 409));
  const saved = vi.fn();
  await act(async () =>
    root.render(
      <StrikeBulkMark rows={[row]} onSaved={saved} onBusy={vi.fn()} />,
    ),
  );
  const note = host.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(note, "Keep this note");
    note.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector("button")!.click());
  expect(host.textContent).toContain("Changed after one save");
  expect(host.querySelector("input")!.value).toBe("Keep this note");
  await act(async () => host.querySelector("button")!.click());
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Refresh selected accounts")!
      .click(),
  );
  expect(saved).toHaveBeenCalledOnce();
});
