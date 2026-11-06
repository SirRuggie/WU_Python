// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AccountCard from "./AccountCard";

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

it("preserves the exact article, native button attributes and caller child order", () => {
  const select = (
    <label className="select">
      <input type="checkbox" aria-label="Select Name" />
    </label>
  );
  const name = <strong className="name">Name</strong>;
  const weight = <span className="weight">100</span>;
  const rows = (
    <>
      <span id="meta">TH18 · #P2Y</span>
      <span className="status">Existing status</span>
    </>
  );
  const after = (
    <>
      <span className="sr-only">Description</span>
      <button className="menu">Actions</button>
    </>
  );
  act(() =>
    root.render(
      <article className="legacy-card">
        {select}
        <button
          type="button"
          className="body"
          aria-describedby="meta"
          aria-label="Details for Name"
        >
          <span className="top">
            {name}
            {weight}
          </span>
          {rows}
        </button>
        {after}
      </article>,
    ),
  );
  const before = host.innerHTML;
  act(() =>
    root.render(
      <AccountCard
        variant="structural"
        className="legacy-card"
        beforeBody={select}
        body={{
          type: "button",
          className: "body",
          "aria-describedby": "meta",
          "aria-label": "Details for Name",
        }}
        top={{ element: "span", className: "top", name, aside: weight }}
        rows={rows}
        afterBody={after}
      />,
    ),
  );
  expect(host.innerHTML).toBe(before);
  const described = host
    .querySelector("button.body")!
    .getAttribute("aria-describedby")!
    .split(/\s+/);
  expect(described.every((id) => host.querySelector(`[id="${id}"]`))).toBe(
    true,
  );
  expect(
    [...host.querySelector("article")!.children].map((node) => node.tagName),
  ).toEqual(["LABEL", "BUTTON", "SPAN", "BUTTON"]);
});

it("preserves a no-body declaration shape without nesting its name button and DM link", () => {
  const name = <button className="staff">Name</button>;
  const aside = (
    <a href="https://discord.com/users/123" className="dm">
      DM
    </a>
  );
  const rows = (
    <>
      <span className="meta">TH18 · #P2Y</span>
      <span className="status">Existing status</span>
    </>
  );
  act(() =>
    root.render(
      <article className="declaration">
        <div className="top">
          {name}
          {aside}
        </div>
        {rows}
      </article>,
    ),
  );
  const before = host.innerHTML;
  act(() =>
    root.render(
      <AccountCard
        variant="structural"
        className="declaration"
        top={{ element: "div", className: "top", name, aside }}
        rows={rows}
      />,
    ),
  );
  expect(host.innerHTML).toBe(before);
  expect(host.querySelector("article > button")).toBeNull();
  expect(host.querySelector("button button, button a")).toBeNull();
});

it("passes native selection and body handlers unchanged and honors disabled", () => {
  const toggle = vi.fn(),
    details = vi.fn();
  const render = (disabled: boolean, selecting = false) =>
    act(() =>
      root.render(
        <AccountCard
          variant="structural"
          className="legacy-card"
          beforeBody={
            <input
              type="checkbox"
              aria-label="Select Name"
              disabled={disabled}
              onChange={toggle}
            />
          }
          body={{
            type: "button",
            className: "body",
            disabled,
            onClick: selecting ? toggle : details,
          }}
          top={{
            element: "span",
            className: "top",
            name: <strong>Name</strong>,
          }}
          rows={<span>Existing status</span>}
        />,
      ),
    );
  render(false);
  act(() => {
    host.querySelector<HTMLInputElement>("input")!.click();
    host.querySelector<HTMLButtonElement>("button.body")!.click();
  });
  expect(toggle).toHaveBeenCalledTimes(1);
  expect(details).toHaveBeenCalledTimes(1);
  render(false, true);
  act(() => host.querySelector<HTMLButtonElement>("button.body")!.click());
  expect(toggle).toHaveBeenCalledTimes(2);
  render(true, true);
  act(() => {
    host.querySelector<HTMLInputElement>("input")!.click();
    host.querySelector<HTMLButtonElement>("button.body")!.click();
  });
  expect(toggle).toHaveBeenCalledTimes(2);
  expect(details).toHaveBeenCalledTimes(1);
});
