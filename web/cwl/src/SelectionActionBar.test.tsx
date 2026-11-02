// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import MemberBulkBar from "./members/MemberBulkBar";
import { membersText as text } from "./members/strings";
it("shared extraction preserves Members labels, partial page selection and desktop action callbacks", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onShow = vi.fn(),
    onAdd = vi.fn(),
    onRemove = vi.fn(),
    onFix = vi.fn(),
    onClear = vi.fn(),
    onSelectPage = vi.fn(),
    onSelectMatching = vi.fn();
  try {
    await act(async () =>
      root.render(
        <MemberBulkBar
          pageSelected={false}
          pagePartial={true}
          onSelectPage={onSelectPage}
          matchingCount={40}
          onSelectMatching={onSelectMatching}
          count={5}
          hidden={2}
          canRoles={true}
          canProfiles={true}
          busy={false}
          onShow={onShow}
          onAdd={onAdd}
          onRemove={onRemove}
          onFix={onFix}
          onClear={onClear}
        />,
      ),
    );
    expect(
      host.querySelector('[role="region"]')?.getAttribute("aria-label"),
    ).toBe(text.selectionLabel);
    expect(host.querySelector("input")?.indeterminate).toBe(true);
    expect(host.querySelector("input")?.getAttribute("aria-label")).toBe(
      text.selectPage,
    );
    for (const [label, callback] of [
      [text.addRole, onAdd],
      [text.removeRole, onRemove],
      [text.fixNames, onFix],
      [text.selectNone, onClear],
      [text.selectMatching(40), onSelectMatching],
    ] as const) {
      const button = [...host.querySelectorAll("button")].find(
        (button) => button.textContent === label,
      )!;
      await act(async () => button.click());
      expect(callback).toHaveBeenCalledOnce();
    }
    expect(host.querySelector("button")?.getAttribute("aria-label")).toBe(
      text.selected(5, 2),
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
