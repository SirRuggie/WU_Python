// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import CwlNextLink from "./CwlNextLink";
it("offers exactly one read-only destination and preserves disabled navigation", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host),
    next = vi.fn(),
    fetch = vi.spyOn(globalThis, "fetch");
  try {
    await act(async () =>
      root.render(
        <CwlNextLink
          label="Build roster"
          route={{ view: "roster", season: "" }}
          onNext={next}
        />,
      ),
    );
    expect(host.querySelectorAll("a")).toHaveLength(1);
    expect(host.textContent).toBe("Next: Build roster ›");
    expect(host.querySelector("a")!.getAttribute("href")).toBe("/cwl/roster");
    await act(async () =>
      (host.querySelector("a") as HTMLAnchorElement).click(),
    );
    expect(next).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
    await act(async () =>
      root.render(
        <CwlNextLink
          label="Build roster"
          route={{ view: "roster", season: "" }}
          onNext={next}
          disabled
        />,
      ),
    );
    (host.querySelector("a") as HTMLAnchorElement).click();
    expect(next).toHaveBeenCalledOnce();
  } finally {
    await act(async () => root.unmount());
    host.remove();
    fetch.mockRestore();
  }
});
