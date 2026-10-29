// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import App from "../App";
import { isTourReadOnly, setTourReadOnly } from "./session";
vi.mock("../DashboardHome", () => ({ default: () => <p>Home</p> }));
vi.mock("../TodoWorkspace", () => ({ default: () => <p>Tasks</p> }));
vi.mock("../MemberAssignments", () => ({ default: () => <p>Assignments</p> }));
afterEach(() => {
  setTourReadOnly(false);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it.each(["exit", "finish"])(
  "App tour %s releases the guard for a real signup request",
  async (ending) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    history.replaceState({}, "", "/signup");
    localStorage.clear();
    sessionStorage.clear();
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
      function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    );
    vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(
      () => {},
    );
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    } as unknown as MediaQueryList);
    const writes: string[] = [];
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).replace("/api/cwl", "");
      if (init?.method === "POST") writes.push(path);
      let data: object = {};
      if (path === "/auth/me")
        data = {
          user: { id: "1", username: "Member" },
          authenticated: true,
          csrf_token: "fixture",
          can_edit: false,
        };
      else if (path === "/seasons")
        data = {
          seasons: [
            { id: 1, label: "November", status: "draft", signup_open: true },
          ],
          member_season: { season_id: 1, revision: 0 },
        };
      else if (path.includes("accounts"))
        data = {
          accounts: [{ tag: "#P222222Y", name: "Fixture", town_hall: 18 }],
        };
      else if (path.includes("signups"))
        data =
          init?.method === "POST" ? { ok: true, count: 1 } : { signups: [] };
      return new Response(JSON.stringify(data), { status: 200 });
    });
    vi.stubGlobal("fetch", fetcher);
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const settle = async () => {
      for (let i = 0; i < 4; i++)
        await act(async () => {
          await new Promise((r) => setTimeout(r, 10));
        });
    };
    const click = async (selector: string) => {
      await act(async () => {
        const el = document.querySelector<HTMLButtonElement>(selector);
        expect(el).not.toBeNull();
        el!.click();
      });
      await settle();
    };
    try {
      await act(async () => root.render(<App />));
      await settle();
      await click(".tour-launcher");
      expect(isTourReadOnly()).toBe(true);
      if (ending === "finish") {
        for (let i = 0; i < 13; i++) await click(".tour-next");
      } else await click(".tour-close");
      expect(isTourReadOnly()).toBe(false);
      expect(writes).toEqual([]);
      await click('[data-tour-target="signup-pool"]');
      await click(".account-select input");
      await click(".submit-bar .primary");
      await click('[data-tour-target="signup-confirm"]');
      expect(writes).toEqual(["/seasons/1/signups"]);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
