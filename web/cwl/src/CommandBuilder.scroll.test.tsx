// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import CommandBuilder, { type Command } from "./CommandBuilder";

it.each([false, true])(
  "jump-to-block respects reduced motion=%s",
  async (reduce) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const scroll = vi.fn();
    const originalScroll = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: reduce,
        addEventListener() {},
        removeEventListener() {},
      })),
    );
    vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
      fn(0);
      return 1;
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const value: Command = {
      command: "!fixture",
      enabled: true,
      text: "",
      title: "",
      description: "",
      image_url: "",
      color: "#f2b62a",
      blocks: [{ type: "text", text: "Fixture block" }],
    };
    try {
      await act(async () =>
        root.render(<CommandBuilder value={value} onChange={() => {}} />),
      );
      const select = [...host.querySelectorAll("select")].find((node) =>
        node.closest("label")?.textContent?.includes("Jump to block"),
      )!;
      await act(async () => {
        select.value = select.options[1].value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(scroll).toHaveBeenCalledWith({
        block: "start",
        behavior: reduce ? "auto" : "smooth",
      });
      expect(
        document.activeElement?.classList.contains("command-block-title"),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
      HTMLElement.prototype.scrollIntoView = originalScroll;
      vi.unstubAllGlobals();
    }
  },
);
