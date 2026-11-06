// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import FilterChips from "./FilterChips";
import SectionTabs from "./SectionTabs";

let host: HTMLDivElement;
let root: Root;
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
const options = [
  { value: "one", label: "One", count: 2 },
  { value: "two", label: "Two", count: 0 },
];
const items = options.map(({ value, label }) => ({ id: value, label }));

it.each(["sections", "pills"])(
  "%s retain native focus/keyboard defaults, selection and disabled callbacks",
  (kind) => {
    const changed = vi.fn();
    function Fixture({ disabled = false }: { disabled?: boolean }) {
      const [value, setValue] = useState("one");
      const onChange = (next: string) => {
        changed(next);
        setValue(next);
      };
      return kind === "sections" ? (
        <SectionTabs
          label="Sections"
          items={items}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
      ) : (
        <FilterChips
          label="Statuses"
          options={options}
          value={value}
          onChange={onChange}
          disabled={disabled}
          variant="pill"
        />
      );
    }
    act(() => root.render(<Fixture />));
    const buttons = [...host.querySelectorAll("button")];
    expect(
      buttons.map((button) => button.getAttribute("aria-pressed")),
    ).toEqual(["true", "false"]);
    expect(buttons.map((button) => button.type)).toEqual(["button", "button"]);
    buttons[1].focus();
    expect(document.activeElement).toBe(buttons[1]);
    expect(buttons[1].tabIndex).toBe(0);
    // Native buttons own Enter/Space activation; no custom handler intercepts it.
    for (const key of ["Enter", " "]) {
      const event = new KeyboardEvent("keydown", {
        key,
        bubbles: true,
        cancelable: true,
      });
      expect(buttons[1].dispatchEvent(event)).toBe(true);
      expect(event.defaultPrevented).toBe(false);
    }
    act(() => buttons[1].click());
    expect(changed.mock.calls).toEqual([["two"]]);
    expect(
      buttons.map((button) => button.getAttribute("aria-pressed")),
    ).toEqual(["false", "true"]);
    act(() => root.render(<Fixture disabled />));
    expect(buttons.every((button) => button.disabled)).toBe(true);
    act(() => buttons[0].click());
    expect(changed.mock.calls).toEqual([["two"]]);
  },
);

it("preserves the exact default FilterChips DOM, including its trailing class space", () => {
  const props = { label: "Status", value: "one", options, onChange: () => {} };
  const baseline =
    '<div class="filter-chips " aria-label="Status"><button type="button" aria-pressed="true">One <small>2</small></button><button type="button" aria-pressed="false">Two <small>0</small></button></div>';
  expect(renderToStaticMarkup(<FilterChips {...props} />)).toBe(baseline);
  expect(
    renderToStaticMarkup(<FilterChips {...props} variant="default" />),
  ).toBe(baseline);
  expect(
    renderToStaticMarkup(<FilterChips {...props} className="custom" />),
  ).toBe(
    baseline.replace('class="filter-chips "', 'class="filter-chips custom"'),
  );
  expect(renderToStaticMarkup(<FilterChips {...props} disabled />)).toBe(
    baseline
      .replaceAll('aria-pressed="true"', 'aria-pressed="true" disabled=""')
      .replaceAll('aria-pressed="false"', 'aria-pressed="false" disabled=""'),
  );
});

it("gives SectionTabs the existing named group semantics and caller class", () => {
  act(() =>
    root.render(
      <SectionTabs
        label="Strike sections"
        className="strikes-tabs"
        items={items}
        value="one"
        onChange={() => {}}
      />,
    ),
  );
  expect(host.querySelector('[role="group"]')?.getAttribute("aria-label")).toBe(
    "Strike sections",
  );
  expect(host.firstElementChild?.className).toBe("section-tabs strikes-tabs");
  expect(host.querySelector('[role="tab"]')).toBeNull();
});
