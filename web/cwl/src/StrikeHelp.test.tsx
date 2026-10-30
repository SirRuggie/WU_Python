// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import StrikeHelp, { StrikeHelpText } from "./StrikeHelp";
import { strikeHelpText } from "./strikeHelp";

const expected = [
  "You get 1 strike if you miss both attacks in a war.",
  "Missing 1 attack gives no strike, but it breaks your streak.",
  "CWL never gives strikes.",
  "Play 2 wars in a row (use both attacks) → 1 strike is removed.",
  "Play 6 wars in a row → all your strikes are removed.",
  "A strike also goes away by itself after 60 days.",
  "Approved leave pauses strikes. Ask a leader before you go.",
  "At 4 strikes, leaders may replace you in the clan.",
];

it("keeps exact help wording in the shared rich and plain text renderers", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<StrikeHelpText />);
  expect(
    [...host.querySelectorAll("li")].map((item) => item.textContent),
  ).toEqual(expected);
  expect(strikeHelpText()).toBe(expected.join("\n"));
  expect(host.querySelector("strong")?.textContent).toBe("You get 1 strike");
});

it("substitutes the limit without changing the rest of the copy", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<StrikeHelpText limit={7} />);
  expect(
    [...host.querySelectorAll("li")].map((item) => item.textContent),
  ).toEqual([
    ...expected.slice(0, 7),
    "At 7 strikes, leaders may replace you in the clan.",
  ]);
  expect(strikeHelpText(7)).toContain("At 7 strikes");
  expect(strikeHelpText(NaN)).toContain("At 4 strikes");
});

it.each(["back", "close", "escape"])(
  "opens the shared panel and closes through %s",
  async (close) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
    };
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const back = vi.spyOn(history, "back").mockImplementation(() => {});
    try {
      await act(async () => root.render(<StrikeHelp />));
      await act(async () =>
        host.querySelector<HTMLButtonElement>("button")!.click(),
      );
      const dialog = document.querySelector<HTMLDialogElement>("dialog")!;
      expect(dialog.open).toBe(true);
      expect(dialog.textContent).toContain("How strikes work");
      expect(dialog.querySelectorAll("li")).toHaveLength(8);
      expect(document.activeElement).toBe(
        dialog.querySelector(".action-panel-close"),
      );
      await act(async () => {
        if (close === "back") {
          history.replaceState({}, "");
          window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
        } else if (close === "close")
          dialog.querySelector<HTMLButtonElement>("button")!.click();
        else
          dialog.dispatchEvent(
            new Event("cancel", { bubbles: false, cancelable: true }),
          );
      });
      expect(document.querySelector("dialog")).toBeNull();
      expect(host.querySelector("button")?.textContent).toBe(
        "How strikes work",
      );
    } finally {
      await act(async () => root.unmount());
      host.remove();
      back.mockRestore();
      history.replaceState({}, "");
    }
  },
);
