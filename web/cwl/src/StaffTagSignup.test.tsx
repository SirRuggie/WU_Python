// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { api } from "./api";
import StaffTagSignup from "./StaffTagSignup";

vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
vi.mock("./useUnsavedWork", () => ({ default: () => {} }));
vi.mock("./MemberPicker", () => ({ default: () => null }));
vi.mock("./rosterUi/Menu", () => ({
  default: ({
    value,
    onValueChange,
  }: {
    value: string;
    onValueChange: (value: string) => void;
  }) => (
    <select
      aria-label="CWL type"
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
    >
      <option value="">Select</option>
      <option value="main">Main CWL</option>
    </select>
  ),
}));

it("marks only lookup Checking, preserves disabled duplicate guards and leaves saving Find player unmarked", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  let finishLookup!: (value: unknown) => void;
  let finishSave!: (value: unknown) => void;
  vi.mocked(api).mockImplementation((_path, method) =>
    method === "POST"
      ? new Promise((resolve) => {
          finishSave = resolve;
        })
      : new Promise((resolve) => {
          finishLookup = resolve;
        }),
  );
  const onSaved = vi.fn().mockResolvedValue(undefined);
  try {
    await act(async () =>
      root.render(
        <StaffTagSignup
          seasonId="1"
          onSaved={onSaved}
          onDirty={vi.fn()}
          onBusy={vi.fn()}
        />,
      ),
    );
    const find = host.querySelector<HTMLButtonElement>(
      ".staff-tag-lookup button",
    )!;
    expect(find.textContent).toBe("Find player");
    expect(find.disabled).toBe(true);
    expect(find.hasAttribute("aria-busy")).toBe(false);
    const input = host.querySelector<HTMLInputElement>("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "#PYY");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(find.disabled).toBe(false);
    find.focus();
    expect(document.activeElement).toBe(find);
    await act(async () => find.click());
    expect(find.textContent).toBe("Checking…");
    expect(find.getAttribute("aria-busy")).toBe("true");
    expect(find.disabled).toBe(true);
    await act(async () => {
      find.click();
      find.click();
    });
    expect(api).toHaveBeenCalledTimes(1);
    await act(async () =>
      finishLookup({
        account: { tag: "#PYY", name: "Fixture", town_hall: 16 },
        linked_user_id: null,
        signed_up_pool: null,
      }),
    );
    expect(find.textContent).toBe("Find player");
    expect(find.hasAttribute("aria-busy")).toBe(false);
    const select = host.querySelector<HTMLSelectElement>(
      'select[aria-label="CWL type"]',
    )!;
    await act(async () => {
      select.value = "main";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const save = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Add signup",
    )!;
    await act(async () => save.click());
    expect(save.textContent).toBe("Saving…");
    expect(save.classList.contains("is-primary")).toBe(true);
    expect(save.hasAttribute("aria-busy")).toBe(false);
    expect(find.disabled).toBe(true);
    expect(find.textContent).toBe("Find player");
    expect(find.hasAttribute("aria-busy")).toBe(false);
    await act(async () => {
      find.click();
      save.click();
    });
    expect(api).toHaveBeenCalledTimes(2);
    await act(async () => finishSave({}));
    expect(onSaved).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
