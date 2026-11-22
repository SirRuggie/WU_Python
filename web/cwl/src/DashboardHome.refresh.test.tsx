// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { Session } from "./api";
import DashboardHome from "./DashboardHome";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));

it("offers one Try again and hides the duplicate header Refresh on failure", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockRejectedValue(new Error("offline"));
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardHome
          session={{ user: { id: "1" }, can_edit: false } as unknown as Session}
          seasonId=""
          seasons={[]}
          onNavigate={vi.fn()}
          onStart={vi.fn()}
        />,
      ),
    );
    const buttons = [...host.querySelectorAll("button")].filter(
      (item) => item.textContent === "Try again",
    );
    expect(buttons).toHaveLength(1);
    expect(host.querySelector('button[aria-label="Refresh"]')).toBeNull();
    expect(buttons[0].getAttribute("aria-label")).toBe("Try again: dashboard");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it.each([false, true])(
  "My accounts keeps saved data and only offers signup controls when open (%s)",
  async (open) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    localStorage.clear();
    sessionStorage.clear();
    const season = {
      id: 1,
      label: "December 2026",
      status: "draft",
      signup_open: open,
    };
    const accounts = [
      {
        tag: "#OPEN",
        name: "Unsigned fixture",
        town_hall: 18,
        current_clan_name: "Fixture clan",
        current_clan_tag: "#CLAN",
        verified: true,
        lazy_eligible: true,
        lazy_ineligible_reason: null,
        family_clan_status: "approved",
      },
      {
        tag: "#SAVED",
        name: "Saved fixture",
        town_hall: 17,
        current_clan_name: "Fixture clan",
        current_clan_tag: "#CLAN",
        verified: true,
        lazy_eligible: true,
        lazy_ineligible_reason: null,
        family_clan_status: "approved",
      },
    ];
    api.mockReset().mockImplementation(async (path: string) =>
      path.startsWith("/linked-accounts")
        ? { accounts, updating: false, total: 2, link_instruction: "" }
        : path.endsWith("/signups")
          ? {
              signups: [
                {
                  tag: "#SAVED",
                  user_id: "1",
                  pool: "main",
                  prefer_crystal_1_or_lower: false,
                },
              ],
            }
          : path.endsWith("/my-assignments")
            ? {
                accounts: [
                  {
                    tag: "#SAVED",
                    player_name: "Saved fixture",
                    town_hall: 17,
                    pool: "main",
                    assigned_clan_tag: "#CLAN",
                    assigned_clan_name: "Saved clan",
                  },
                ],
                published: { version: 1 },
                visibility: "current",
                draft_changed: false,
              }
            : path === "/seasons"
              ? { seasons: [season] }
              : {},
    );
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardHome
            session={
              {
                authenticated: true,
                user: { id: "1", username: "Fixture" },
                can_edit: false,
                csrf_token: "fixture",
              } as Session
            }
            seasonId="1"
            seasons={[season]}
            onNavigate={vi.fn()}
            onStart={vi.fn()}
          />,
        ),
      );
      for (let i = 0; i < 3; i++)
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 0));
        });
      expect(host.textContent).toContain("Unsigned fixture");
      expect(host.textContent).toContain("Saved fixture");
      expect(host.textContent).toContain("Saved clan");
      const check = host.querySelector<HTMLInputElement>(
        ".hub-account input[type=checkbox]",
      );
      if (open) {
        expect(check).toBeTruthy();
        expect(host.textContent).toContain("Select accounts not signed up");
        await act(async () => check!.click());
        expect(host.textContent).toContain("Main CWL →");
        expect(host.textContent).toContain("Lazy CWL →");
      } else {
        expect(check).toBeNull();
        expect(host.querySelector(".signup-closed-line")?.textContent).toBe(
          "Signups are closed.",
        );
        expect(host.textContent).not.toContain("Select accounts not signed up");
        expect(host.querySelector(".hub-selected-bar")).toBeNull();
        expect(host.querySelector(".hub-selection")).toBeNull();
      }
      expect(api.mock.calls.every((call) => !call[1])).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
