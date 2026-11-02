import React from "react";
import { createRoot } from "react-dom/client";
import ReturnReminderOverview from "../../src/ReturnReminderOverview";
import type { ReturnClan } from "../../src/returns/model";
import "../../src/style.css";
import "../../src/workflowControls.css";
import "../../src/accessibility.css";
const now = new Date();
const rows: ReturnClan[] = [
  ["AAA", "Running", "scheduled"],
  ["BBB", "Paused", "paused"],
  ["CCC", "Not started", "idle"],
  ["DDD", "No saved list", "not_saved"],
  ["EEE", "Window ended", "expired"],
].map(([id, label, state]) => ({
  id: "FWA#" + id,
  label: "Local clan " + id,
  clan_name: "Local clan " + id,
  clan_tag: "#" + id,
  return_section: "FWA",
  endpoint: "/fixture",
  description: "Fixture",
  group: "War",
  return_status: {
    state,
    label,
    players: state === "not_saved" ? 0 : 26,
    every_minutes: state === "not_saved" ? null : 60,
    last_sent_at:
      state === "scheduled"
        ? new Date(now.getTime() - 3600000).toISOString()
        : null,
    expires_at:
      state === "not_saved"
        ? null
        : new Date(
            now.getTime() + (state === "expired" ? -1 : 3) * 86400000,
          ).toISOString(),
    starts_at: ["scheduled", "paused", "expired"].includes(state)
      ? new Date(now.getTime() - 86400000).toISOString()
      : null,
  },
}));
rows.push({
  ...rows[0],
  id: "MAIN#FFF",
  return_section: "MAIN",
  clan_name: "Local Main clan",
  clan_tag: "#FFF",
  return_status: {
    ...rows[0].return_status!,
    state: "manual",
    label: "Manual sends",
  },
});
let nextError = 0;
const calls: { path: string; method: string }[] = [];
Object.assign(window, {
  returnFixture: {
    calls,
    failRefresh: (status = 500) => {
      nextError = status;
    },
  },
});
window.fetch = async (input, init) => {
  const path = String(input).replace("/api/cwl", ""),
    method = init?.method || "GET";
  calls.push({ path, method });
  const answer = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: {
        "Content-Type": "application/json",
        "X-Read-Retries-Exhausted": "1",
      },
    });
  if (path === "/manage/return-reminders" && nextError) {
    const status = nextError;
    nextError = 0;
    return answer({ error: "Local refresh failure" }, status);
  }
  if (path === "/manage/return-reminders") return answer({ documents: rows });
  if (path === "/manage/return-channels")
    return answer({
      fields: [
        { key: "fwa_channel_id", value: "123" },
        { key: "main_channel_id", value: "124" },
      ],
    });
  if (path === "/announcement-channels")
    return answer({
      channels: [
        { id: "123", name: "local-fwa-return" },
        { id: "124", name: "local-main-return" },
      ],
    });
  if (path.startsWith("/manage/return-bulk/") && method === "GET")
    return answer({
      revision: "fixture",
      fields: [
        {
          key: "clans",
          options: rows.map((row) => ({
            value: row.return_section + ":" + row.clan_tag,
            label: row.clan_name,
          })),
        },
      ],
    });
  if (path.startsWith("/manage/return-bulk/") && method === "POST")
    return answer({
      status: "done",
      message: "Local fixture saved. No message sent.",
    });
  return answer({ error: "Fixture endpoint unavailable" }, 404);
};
createRoot(document.getElementById("root")!).render(
  <div className="shell" style={{ display: "block" }}>
    <main style={{ maxWidth: 1200, margin: "auto", padding: 16 }}>
      <h1>Return reminders</h1>
      <p>
        Isolated sample data. All requests stay in this page; no Discord sends.
      </p>
      <ReturnReminderOverview
        onOpen={(section) =>
          window.alert(
            "Existing member-list details/clear confirmation preserved: " +
              section.label,
          )
        }
      />
    </main>
  </div>,
);
