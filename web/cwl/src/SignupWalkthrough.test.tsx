// @vitest-environment happy-dom
import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import SignupWalkthrough from "./SignupWalkthrough";
import MemberSeasonLine from "./MemberSeasonLine";
import type { Season } from "./api";
it("shows art and a large title only on the current step, with compact inactive captions", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div"),
    root = createRoot(host),
    navigate = vi.fn();
  try {
    for (const stage of [1, 2, 3] as const) {
      await act(async () =>
        root.render(
          <SignupWalkthrough
            stage={stage}
            pool="lazy"
            selectedCount={2}
            busy={false}
            canReview
            headingRef={createRef()}
            onNavigate={navigate}
          />,
        ),
      );
      expect(host.querySelectorAll(".walkthrough-instruction")).toHaveLength(1);
      expect(
        host.querySelector(".current .walkthrough-instruction")?.textContent,
      ).toBe(
        [
          "Choose Main or Lazy CWL. You can choose a different option for each account.",
          "Select the accounts you want to sign up for Lazy CWL.",
          "Check your accounts. Select Sign up below to finish.",
        ][stage - 1],
      );
      if (stage === 2)
        expect(
          host.querySelector(".walkthrough-summary")?.textContent,
        ).toContain("You’re signing up for Lazy CWL");
      expect(host.querySelectorAll("img")).toHaveLength(1);
      const image = host.querySelector("img")!;
      expect(image.getAttribute("src")).toBe(
        `/assets/tour/${["U04", "U23", "U19"][stage - 1]}.webp`,
      );
      expect(image.getAttribute("loading")).toBe("lazy");
      expect(host.querySelector(".current [aria-current=step]")).not.toBeNull();
      expect(
        host.querySelectorAll("li:not(.current) .walkthrough-summary"),
      ).toHaveLength(0);
      expect(
        host.querySelector("li:not(.current) .walkthrough-step")?.textContent,
      ).toContain(" · ");
    }
    await act(async () =>
      host.querySelector<HTMLButtonElement>("button")!.click(),
    );
    expect(navigate).toHaveBeenCalledWith(1);
  } finally {
    await act(async () => root.unmount());
  }
});
it("shows one member season line with local close time, no internal Draft chip", async () => {
  const host = document.createElement("div"),
    root = createRoot(host);
  const season = {
    label: "November 2026",
    status: "draft",
    signup_open: true,
    signup_deadline: "2026-10-30T21:00:00Z",
  } as Season;
  try {
    await act(async () => root.render(<MemberSeasonLine season={season} />));
    expect(host.textContent).toBe(
      `November 2026 · Open · closes ${new Date(season.signup_deadline!).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`,
    );
    expect(host.textContent?.toLowerCase()).not.toContain("draft");
    await act(async () =>
      root.render(
        <MemberSeasonLine season={{ ...season, signup_deadline: null }} />,
      ),
    );
    expect(host.textContent).toBe("November 2026 · Open");
    await act(async () =>
      root.render(
        <MemberSeasonLine
          season={{ ...season, status: "archived", signup_deadline: null }}
        />,
      ),
    );
    expect(host.textContent).toBe("November 2026 · Open");
    await act(async () =>
      root.render(
        <MemberSeasonLine season={{ ...season, signup_open: false }} />,
      ),
    );
    expect(host.textContent).toBe("November 2026 · Signups closed");
  } finally {
    await act(async () => root.unmount());
  }
});
