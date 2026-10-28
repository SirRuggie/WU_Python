// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import AnnouncementMonth from "./AnnouncementMonth";
import { announcementMonth, announcementMonthLabel } from "./announcementMonth";
it("derives a month only from a complete month label", () => {
  expect(announcementMonth("November 2026")).toBe("2026-11");
  expect(announcementMonth("Special season")).toBe("");
  expect(announcementMonth("November 2026 extra")).toBe("");
  expect(announcementMonthLabel("2026-11")).toBe("November 2026");
});
it("prefills without binding; Change reveals the picker and Load is explicit", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div"),
    root = createRoot(host),
    load = vi.fn();
  try {
    await act(async () =>
      root.render(
        <AnnouncementMonth
          value="2026-11"
          linked={null}
          disabled={false}
          onChange={() => {}}
          onLoad={load}
        />,
      ),
    );
    expect(load).not.toHaveBeenCalled();
    expect(host.querySelector("input")).toBeNull();
    const buttons = [...host.querySelectorAll("button")];
    await act(async () =>
      buttons.find((b) => b.textContent === "Change")!.click(),
    );
    expect(host.querySelector("input")?.type).toBe("month");
    await act(async () =>
      buttons.find((b) => b.textContent === "Load November 2026")!.click(),
    );
    expect(load).toHaveBeenCalledOnce();
    await act(async () =>
      root.render(
        <AnnouncementMonth
          value=""
          linked={null}
          disabled={false}
          onChange={() => {}}
          onLoad={load}
        />,
      ),
    );
    expect(host.querySelector("input")).not.toBeNull();
    expect(host.textContent).not.toContain("CWL month:");
  } finally {
    await act(async () => root.unmount());
  }
});
