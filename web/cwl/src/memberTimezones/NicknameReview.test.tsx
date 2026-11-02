// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import NicknameReview from "./NicknameReview";
import type { Change } from "./types";

it("reveals hidden selected members without changing the parent filters or selection", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  const root = createRoot(host);
  const ids = ["111111111111111111", "222222222222222222"];
  const selected = new Set(ids),
    visibleIds = new Set([ids[0]]);
  const rows: Change[] = ids.map((discord_id, index) => ({
    discord_id,
    name: `Fixture ${index + 1}`,
    old_nickname: "Old",
    new_nickname: "New",
    revision: 1,
    category: "will_change",
  }));
  const onSelect = vi.fn(),
    onConfirm = vi.fn();
  try {
    await act(async () =>
      root.render(
        <NicknameReview
          rows={rows}
          members={[]}
          selected={selected}
          visibleIds={visibleIds}
          onSelect={onSelect}
          onConfirm={onConfirm}
          disabled={false}
        />,
      ),
    );
    expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(1);
    const hidden = Array.from(host.querySelectorAll("button")).find(
      (button) => button.textContent === "1 hidden",
    );
    expect(hidden).toBeDefined();
    await act(async () => hidden!.click());
    expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(
      Array.from(host.querySelectorAll("button")).some(
        (button) => button.textContent === "Rename 2",
      ),
    ).toBe(true);
    expect(visibleIds).toEqual(new Set([ids[0]]));
    expect(selected).toEqual(new Set(ids));
    expect(onSelect).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
  }
});
