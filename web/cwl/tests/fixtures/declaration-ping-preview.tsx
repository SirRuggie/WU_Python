import React from "react";
import { createRoot } from "react-dom/client";
import DeclarationPingPanel from "../../src/DeclarationPingPanel";
import DiscordPreview, { type PreviewPart } from "../../src/DiscordPreview";
import fixtures from "./declaration-ping-data.json";
import "../../src/style.css";

const query = new URLSearchParams(location.search);
const count = (
  [26, 65, 125].includes(Number(query.get("count")))
    ? Number(query.get("count"))
    : 125
) as 26 | 65 | 125;
const pool = query.get("pool") === "main" ? "main" : "lazy";
const review = fixtures[String(count) as "26" | "65" | "125"];
const state = {
  revision: 1,
  channel: { id: "234567890123456789", name: "lazy-cwl-declaration" },
  can_send: query.get("readonly") !== "1",
  channels: [
    {
      id: "234567890123456789",
      name: "lazy-cwl-declaration",
      type: 0,
      can_send: true,
    },
    {
      id: "345678901234567890",
      name: "main-cwl-declaration",
      type: 5,
      can_send: true,
    },
  ],
  active: null,
  test_running: false,
  history: [],
  cooldown_until: 0,
  test_channel: { id: "456789012345678901", name: "shared-test", revision: 1 },
};
window.fetch = async (input, options) => {
  const path = String(input);
  if (!path.startsWith("/api/cwl/"))
    throw new Error("Fixture blocks non-dashboard requests");
  if (path.endsWith("/send") || path.endsWith("/close-interrupted"))
    return new Response(
      JSON.stringify({ error: "Fixture only: no delivery is connected" }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    );
  const body = options?.body ? JSON.parse(String(options.body)) : {};
  const result = path.endsWith("/preview")
    ? {
        ...review,
        mode: body.mode,
        channel:
          body.mode === "test"
            ? { id: state.test_channel.id, name: state.test_channel.name }
            : state.channel,
      }
    : state;
  return new Response(JSON.stringify(result), {
    headers: { "Content-Type": "application/json" },
  });
};
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <main style={{ maxWidth: 1100, margin: "0 auto", padding: 16 }}>
      <h1>Declaration check</h1>
      <p>
        Isolated {count}-account {pool} fixture. Send paths are disconnected.
      </p>
      {query.get("post") === "1" ? (
        review.previews.map((parts, i) => (
          <DiscordPreview
            key={i}
            parts={parts as PreviewPart[]}
            label={`Chunk ${i + 1} of ${review.chunks}`}
          />
        ))
      ) : (
        <DeclarationPingPanel seasonId="1" pool={pool} missing={count} />
      )}
    </main>
  </React.StrictMode>,
);
