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
it.each([
  ["neutral", "", "is-unassigned"],
  ["good", "is-assigned", "is-in-clan"],
  ["bad", "compare-account-missing", "is-elsewhere"],
] as const)(
  "uses the held reference classes for %s and keeps the article and dialog slots",
  (tone, surface, text) => {
    act(() =>
      root.render(
        <AccountCard
          thLevel={18}
          name="Local account"
          meta={["TH 18", "#P2Y", "Local Alpha"]}
          status={{ tone, content: "Existing status" }}
          className="participation-row"
        >
          <dialog>Existing dialog</dialog>
        </AccountCard>,
      ),
    );
    expect(host.firstElementChild?.tagName).toBe("ARTICLE");
    expect(
      host.firstElementChild?.classList.contains("participation-row"),
    ).toBe(true);
    const frame = host.querySelector(".roster-ui .player-card")!;
    expect(frame).not.toBeNull();
    if (surface) expect(frame.classList.contains(surface)).toBe(true);
    expect(
      host.querySelector(`.account-card-status .${text}`)?.textContent,
    ).toBe("Existing status");
    expect(host.querySelector(".account-card-meta")?.textContent).toBe(
      "TH 18 · #P2Y · Local Alpha",
    );
    expect(host.querySelector("dialog")?.closest(".roster-ui")).toBeNull();
    expect(host.querySelector("dialog")?.closest("article")).toBe(
      host.firstElementChild,
    );
    expect(host.querySelectorAll("button")).toHaveLength(0);
    expect(host.querySelector(".account-card-flags")).toBeNull();
  },
);
it("preserves caller nodes/handlers, one values instance and an optional left selection", () => {
  const name = vi.fn(),
    action = vi.fn(),
    select = vi.fn();
  act(() =>
    root.render(
      <AccountCard
        select={
          <input
            type="checkbox"
            aria-label="Select account"
            onChange={select}
          />
        }
        thLevel={null}
        name={<button onClick={name}>Local account</button>}
        values={<span data-values>3 Attacks · 6 Stars</span>}
        action={<button onClick={action}>Details</button>}
        meta={["TH —", "#P2Y", "Unplaced"]}
        status={{ tone: "neutral", content: "CWL in progress" }}
        flags={[]}
      />,
    ),
  );
  expect(host.querySelectorAll("[data-values]")).toHaveLength(1);
  expect(host.querySelector("button button")).toBeNull();
  expect(host.querySelector(".account-card-meta")?.textContent).toBe(
    "TH — · #P2Y · Unplaced",
  );
  act(() => {
    host.querySelector<HTMLButtonElement>(".account-card-name button")!.click();
    host
      .querySelector<HTMLButtonElement>(".account-card-action button")!
      .click();
    host.querySelector<HTMLInputElement>(".account-card-select input")!.click();
  });
  expect(name).toHaveBeenCalledTimes(1);
  expect(action).toHaveBeenCalledTimes(1);
  expect(select).toHaveBeenCalledTimes(1);
});
it("omits empty flags and joins real parts without losing a zero value", () => {
  const render = (flags: React.ReactNode[]) =>
    act(() =>
      root.render(
        <AccountCard
          thLevel={18}
          name="Local account"
          meta={["TH 18", null, false, 0, "#P2Y"]}
          status={{ tone: "neutral", content: "CWL in progress" }}
          flags={flags}
        />,
      ),
    );
  render([null, false, ""]);
  expect(host.querySelector(".account-card-flags")).toBeNull();
  expect(host.querySelector(".account-card-meta")?.textContent).toBe(
    "TH 18 · 0 · #P2Y",
  );
  render(["Staff correction"]);
  expect(host.querySelector(".account-card-flags")?.textContent).toBe(
    "Staff correction",
  );
});
it("marks the player name as auto direction and exposes the full name", () => {
  act(() =>
    root.render(
      <AccountCard thLevel={18} name="مرحبا Warrior" meta={["TH 18"]} />,
    ),
  );
  const name = host.querySelector(".player-card-name-text");
  expect(name?.getAttribute("dir")).toBe("auto");
  expect(name?.getAttribute("title")).toBe("مرحبا Warrior");
});
