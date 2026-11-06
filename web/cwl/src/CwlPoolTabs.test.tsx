// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CwlPoolTabs, { useCwlPool } from "./CwlPoolTabs";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("keeps Main/Lazy labels, named group, controlled selection and disabled callbacks", () => {
  const changed = vi.fn();
  const render = (value: "main" | "lazy", disabled = false) =>
    act(() =>
      root.render(
        <CwlPoolTabs value={value} onChange={changed} disabled={disabled} />,
      ),
    );
  render("main");
  const group = host.querySelector('[role="group"]')!;
  expect(group.getAttribute("aria-label")).toBe("CWL group");
  const buttons = [...group.querySelectorAll("button")];
  expect(buttons.map((b) => b.textContent)).toEqual(["Main CWL", "Lazy CWL"]);
  expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual([
    "true",
    "false",
  ]);
  act(() => buttons[1].click());
  expect(changed.mock.calls).toEqual([["lazy"]]);
  // The caller remains the state owner; no optimistic selection is invented.
  expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
  render("lazy", true);
  expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual([
    "false",
    "true",
  ]);
  expect(buttons.every((b) => b.disabled)).toBe(true);
  act(() => buttons[0].click());
  expect(changed.mock.calls).toEqual([["lazy"]]);
});

it.each(["main", "lazy"] as const)(
  "retains the persisted %s pool and updates its existing storage key",
  (saved) => {
    localStorage.setItem("wu-staff-cwl-pool", saved);
    function Fixture() {
      const [value, change] = useCwlPool();
      return <CwlPoolTabs value={value} onChange={change} />;
    }
    act(() => root.render(<Fixture />));
    const buttons = [...host.querySelectorAll("button")];
    expect(buttons[saved === "main" ? 0 : 1].getAttribute("aria-pressed")).toBe(
      "true",
    );
    act(() => buttons[saved === "main" ? 1 : 0].click());
    expect(localStorage.getItem("wu-staff-cwl-pool")).toBe(
      saved === "main" ? "lazy" : "main",
    );
  },
);

it("keeps pool selection usable when browser storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  function Fixture() {
    const [value, change] = useCwlPool();
    return <CwlPoolTabs value={value} onChange={change} />;
  }
  act(() => root.render(<Fixture />));
  const buttons = [...host.querySelectorAll("button")];
  expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
  act(() => buttons[1].click());
  expect(buttons[1].getAttribute("aria-pressed")).toBe("true");
});
