import { createRoot } from "react-dom/client";
import ArrivalCheck from "../../src/ArrivalCheck";
import data from "./declaration-extras-data.json";
import "../../src/style.css";
const query = new URLSearchParams(location.search);
localStorage.setItem("wu-staff-cwl-pool", "lazy");
const now = new Date().toISOString();
const accounts = data.accounts.map((a) => ({
  ...a,
  current_clan_checked_at: now,
}));
let reads = 0;
Object.assign(window, { extraReads: () => reads });
window.fetch = async (input, options) => {
  const url = new URL(String(input), location.origin);
  if (
    url.origin !== location.origin ||
    !url.pathname.startsWith("/api/cwl/") ||
    (options?.method && options.method !== "GET")
  )
    throw new Error("Disconnected read-only fixture");
  let result: unknown;
  if (url.pathname.endsWith("/arrival-check"))
    result = {
      source: "published",
      version: 1,
      publication_available: true,
      publication_outdated: false,
      updating: false,
      accounts,
    };
  else if (url.pathname.endsWith("/roster"))
    result = { revision: 1, undo: null, clans: data.clans, accounts };
  else if (url.pathname.endsWith("/publication"))
    result = {
      published: { version: 1, published_at: now },
      last_publication: null,
    };
  else if (url.pathname.endsWith("/export-preview"))
    result = { rows: accounts, summary: { published_version: 1 } };
  else if (url.pathname.includes("/declaration-pings/"))
    result = {
      revision: 0,
      channel: null,
      can_send: true,
      channels: [],
      active: null,
      test_running: false,
      history: [],
      cooldown_until: 0,
      test_channel: { id: "", name: "", revision: 0 },
    };
  else if (url.pathname.endsWith("/declaration-extras")) {
    reads++;
    if (query.has("slow"))
      await new Promise((resolve) => setTimeout(resolve, 1500));
    result = {
      source: "published",
      basis: 1,
      clans: data.extra_clans
        .filter((_, i) => !query.has("omit") || i !== 0)
        .map((row, i) =>
          query.has("failure") && i === 0
            ? { ...row, status: "unavailable", count: null, extras: null }
            : query.has("empty")
              ? { ...row, status: "current", count: 0, extras: [] }
              : row,
        ),
    };
  } else
    return new Response(
      JSON.stringify({ error: "Fixture read is not connected" }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );
  return new Response(JSON.stringify(result), {
    headers: { "Content-Type": "application/json" },
  });
};
createRoot(document.getElementById("root")!).render(
  <main
    className="roster-ui"
    style={{ maxWidth: 1100, margin: "0 auto", padding: 16 }}
  >
    <h1>Declaration check</h1>
    <p>Isolated read-only fixture. No production connection.</p>
    <ArrivalCheck seasonId="1" />
  </main>,
);
