// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Switch from "./Switch";

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("is a native checkbox switch that reports the next state", () => {
  const onChange = vi.fn();
  act(() =>
    root.render(
      <Switch checked={false} onChange={onChange} aria-label="Updates" />,
    ),
  );
  const input = host.querySelector<HTMLInputElement>("input")!;
  expect(input.type).toBe("checkbox");
  expect(input.getAttribute("role")).toBe("switch");
  expect(input.getAttribute("aria-label")).toBe("Updates");
  expect(host.textContent).toBe("Off");
  act(() => input.click());
  expect(onChange).toHaveBeenCalledWith(true);
});

it("shows a visible label before the state text and marks a problem", () => {
  act(() =>
    root.render(
      <Switch checked problem label="Reminders" onChange={() => {}} />,
    ),
  );
  expect(host.querySelector("label")!.textContent).toBe("RemindersOn");
  expect(host.querySelector("input")!.hasAttribute("aria-label")).toBe(false);
  expect(host.querySelector("label")!.classList).toContain("is-problem");
});

it("does not report changes while disabled", () => {
  const onChange = vi.fn();
  act(() =>
    root.render(
      <Switch checked disabled onChange={onChange} label="Reminders" />,
    ),
  );
  act(() => host.querySelector("input")!.click());
  expect(onChange).not.toHaveBeenCalled();
});
