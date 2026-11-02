import { createRoot } from "react-dom/client";
import ReminderWorkspace from "../../src/ReminderWorkspace";
import type { Campaign } from "../../src/reminderCampaign";
import initial from "./signup-reminders-data.json";
import "../../src/style.css";
import "../../src/contrast.css";
import "../../src/workflowControls.css";
import "../../src/accessibility.css";
const query = new URLSearchParams(location.search);
let campaign = structuredClone(initial) as Campaign;
if (query.has("different")) {
  campaign.messages["reminder:3"].variants.lazy.destination_channel_id =
    "channel-special";
  campaign.messages["reminder:4"].variants.main.role_ids = ["role-special"];
  campaign.messages["reminder:5"].variants.lazy.enabled = false;
}
if (query.has("paused")) campaign.paused = true;
let fail = 0;
let revision = 1;
const calls: { path: string; method: string; body: unknown }[] = [];
Object.assign(window, {
  reminderFixture: {
    calls,
    failRefresh: (status: number) => {
      fail = status;
    },
  },
});
function state() {
  return {
    cycle: "2026-11",
    generation: String(revision),
    worker_ready: !query.has("offline"),
    schedule_synced: !query.has("pending") && !query.has("off"),
    activated: !query.has("off"),
    campaign,
    signup_open: true,
    schedule: Object.keys(campaign.messages).flatMap((message_id, index) =>
      ["main", "lazy"].map((variant) => ({
        id: `${message_id}:${variant}`,
        message_id,
        variant,
        run_at: `2030-11-${String(22 + Math.min(index, 6)).padStart(2, "0")}T06:00:00Z`,
        status: "scheduled",
      })),
    ),
    history: [],
  };
}
window.fetch = async (input, options) => {
  const url = new URL(String(input), location.origin);
  const method = options?.method || "GET";
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/cwl/"))
    throw Error("Disconnected reminder fixture");
  const body = options?.body ? JSON.parse(String(options.body)) : null;
  calls.push({ path: url.pathname, method, body });
  if (url.pathname.endsWith("announcement-channels"))
    return Response.json({
      channels: [
        { id: "channel-main", name: "Main announcements" },
        { id: "channel-lazy", name: "Lazy announcements" },
        { id: "channel-special", name: "Different destination" },
      ],
    });
  if (url.pathname.endsWith("announcement-roles"))
    return Response.json({
      roles: [
        { id: "role-main", name: "Main members" },
        { id: "role-lazy", name: "Lazy members" },
        { id: "role-special", name: "Different notify" },
      ],
    });
  if (!url.pathname.includes("manage-reminders"))
    throw Error("Unexpected fixture path");
  if (fail && method === "GET") {
    const status = fail;
    fail = 0;
    return Response.json(
      { error: "Injected fixture refresh failure" },
      { status },
    );
  }
  if (method === "POST" && url.pathname.endsWith("/pause")) {
    campaign.paused = body.paused;
    revision++;
  } else if (method === "PATCH") {
    campaign = { ...campaign, ...body.patch };
    revision++;
  }
  return Response.json(state());
};
createRoot(document.getElementById("root")!).render(
  <div className="shell">
    <aside className="sidebar">
      <div className="brand-wrap">Local review</div>
    </aside>
    <div className="workspace">
      <header className="topbar">Signup reminders</header>
      <main>
        <h1>Signup reminders</h1>
        <ReminderWorkspace seasonId="42" archived={false} onDirty={() => {}} />
      </main>
    </div>
  </div>,
);
