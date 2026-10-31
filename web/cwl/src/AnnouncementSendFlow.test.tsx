// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import ManageBridgeWorkspace from "./ManageBridgeWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DiscordMessagePreview", () => ({ default: () => null }));
vi.mock("./ChannelCombobox", () => ({ default: () => null }));
it.each(["send", "resend"])("%s opens progress, done and stopped instead of review", async (mode) => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  let sent = false;
  let status = "posting";
  const pool = { channel_id: "111111111111111111", title: "Roster", body: "Ready", media_url: null, buttons: [], role_ids: [], enabled: true, roster_url: null };
  api.mockImplementation(async (path: string, method?: string) => {
    if (path.endsWith("/send") && method === "POST") { sent = true; return {}; }
    if (path.includes("check-message")) return { deleted: true, message_id: "999999999999999999" };
    if (path.endsWith("manage-bridge")) return { cycle: "2026-11", generation: "g1", worker_ready: true, published_version: 2, pools: {
      main: { ...pool, delivery: sent || mode === "resend" ? { status: "sent" } : null,
        sequence: sent ? { sequence_id: "s1", status, announcement_confirmed: true, version: 2, channel_id: pool.channel_id, clans: [], message_url: "https://discord.com/channels/1/2/3" } : undefined },
      lazy: { ...pool, enabled: false, delivery: null },
    }};
    if (path.includes("channels")) return { channels: [{ id: pool.channel_id, name: "main-cwl", type: 0 }] };
    if (path.includes("roles")) return { roles: [] };
    return {};
  });
  const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
  async function click(label: string) {
    const button = [...document.querySelectorAll("button")].filter(b => b.textContent?.trim() === label).at(-1);
    expect(button, label).toBeTruthy(); await act(async () => button!.click());
  }
  try {
    await act(async () => root.render(<DashboardPermissions.Provider value={{owner:true,permissions:[]}}><ManageBridgeWorkspace seasonId="1" publicationVersion={2} /></DashboardPermissions.Provider>));
    for (const card of host.querySelectorAll(".announcement-pool-card")) {
      expect([...card.querySelectorAll("button")].filter(b => !b.closest("details")).map(b => b.textContent?.trim())).not.toEqual(expect.arrayContaining(["Preview", "Edit", "Clear", "Test full post"]));
      expect(card.querySelector("details")?.open).toBe(false);
      for (const button of card.querySelectorAll("button")) {
        if (["Preview", "Edit", "Clear", "Test full post"].includes(button.textContent?.trim() || "")) expect(button.closest("details:not([open])")).toBeTruthy();
      }
    }
    await click(mode === "send" ? "Review and send" : "Send again");
    await click(mode === "send" ? "Queue announcement" : "Send again — ping again");
    expect(document.querySelector("dialog")?.textContent).toContain("Posting");
    expect(document.querySelector("dialog")?.textContent).not.toContain("Review roster announcement");
    status = "complete"; await click("Refresh status");
    expect(document.querySelector("dialog")?.textContent).toContain("Done");
    status = "stopped"; await click("Refresh status");
    expect(document.querySelector("dialog")?.textContent).toContain("Posting stopped");
  } finally { await act(async () => root.unmount()); host.remove(); api.mockReset(); }
});
