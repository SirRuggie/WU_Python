// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterImageCarousel from "./RosterImageCarousel";
it("keeps previous/current/next slides eager and does not load farther slides", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const clans = ["A", "B", "C", "D", "E"].map((name) => ({
    tag: "#" + name,
    name,
    pool: "main",
    count: 20,
    pages: 2,
  }));
  const props = {
    clans,
    version: 1,
    path: "/seasons/1/roster-images",
    disabled: false,
    onSelect: vi.fn(),
    onReady: vi.fn(),
  };
  try {
    await act(async () =>
      root.render(<RosterImageCarousel {...props} selected="#C" />),
    );
    for (const name of ["B", "C", "D"]) {
      const images = host.querySelectorAll(
        `article[aria-label="${name} roster"] img`,
      );
      expect(images).toHaveLength(2);
      for (const image of images)
        expect(image.getAttribute("loading")).toBe("eager");
    }
    for (const name of ["A", "E"])
      expect(
        host.querySelectorAll(`article[aria-label="${name} roster"] img`),
      ).toHaveLength(0);
    await act(async () =>
      root.render(<RosterImageCarousel {...props} selected="#D" />),
    );
    expect(
      host.querySelectorAll('article[aria-label="B roster"] img'),
    ).toHaveLength(0);
    for (const image of host.querySelectorAll(
      'article[aria-label="E roster"] img',
    ))
      expect(image.getAttribute("loading")).toBe("eager");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
