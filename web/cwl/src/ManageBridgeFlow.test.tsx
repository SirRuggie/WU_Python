// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi } from "vitest";
import ManageBridgeWorkspace from "./ManageBridgeWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./ChannelCombobox", () => ({ default: () => null }));
vi.mock("./DiscordMessagePreview", () => ({ default: () => null }));
it.each(["sent", "pending"])(
  "Declaration cue requires confirmed delivery (%s), not just queue acceptance",
  async (status) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const pool = {
      channel_id: "123",
      title: "Roster",
      body: "Read this",
      media_url: null,
      buttons: [],
      role_ids: [],
      enabled: true,
      delivery: null,
      roster_url: null,
    };
    api.mockImplementation(async (path: string) =>
      path.includes("manage-bridge")
        ? {
            cycle: "2026-11",
            generation: "r1",
            worker_ready: true,
            published_version: 2,
            pools: { main: { ...pool, delivery: { status } }, lazy: pool },
          }
        : path.includes("roles")
          ? { roles: [] }
          : { channels: [] },
    );
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const next = vi.fn();
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            <ManageBridgeWorkspace
              seasonId="1"
              publicationVersion={2}
              onDeclaration={next}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      const button = [...host.querySelectorAll("button")].find(
        (b) => b.textContent === "Next: Declaration readiness check ›",
      );
      expect(!!button).toBe(status === "sent");
      if (button) {
        await act(async () => button.click());
        expect(next).toHaveBeenCalledOnce();
      }
      expect(api.mock.calls.every((c) => !c[1])).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
