import { createRoot } from "react-dom/client";
import CwlPoolRoles from "../../src/CwlPoolRoles";
import { DashboardPermissions } from "../../src/DashboardPermissions";
import "../../src/style.css";
const mode = new URLSearchParams(location.search).get("state") || "blank";
const role = "333333333333333333";
const roles = [
  {
    id: role,
    name: "CWL participants with a deliberately long role name & <plain text>",
  },
];
let pools = ["main", "lazy"].map((pool) => ({
  pool,
  role_id: mode === "blank" ? null : role,
  revision: 1,
  member_basis: "fixture-" + pool,
  member_count: 91,
  progress:
    mode === "pending"
      ? { done: 21, pending: 70 }
      : mode === "failure"
        ? { failed: 1, done: 90 }
        : {},
  failure:
    mode === "failure" ? "Bot permission missing. Will check again." : null,
  scanning: mode === "scan",
}));
const methods: string[] = [];
Object.assign(window, { fixtureMethods: methods });
window.fetch = async (input, options) => {
  const url = String(input),
    method = options?.method || "GET";
  methods.push(method + " " + url);
  if (!url.startsWith("/api/cwl/pool-roles"))
    throw new Error("Fixture forbids external/API access");
  if (method === "POST") {
    const body = JSON.parse(String(options?.body));
    pools = pools.map((row) =>
      row.pool === body.pool
        ? {
            ...row,
            role_id: body.role_id,
            revision: row.revision + 1,
            progress: { pending: 91 },
            failure: null,
          }
        : row,
    );
  }
  return Response.json({
    pools,
    ...(url.includes("choices=1")
      ? mode === "outage"
        ? {
            roles: [],
            roles_error:
              "Role choices unavailable. Refresh or turn off a saved role.",
          }
        : { roles }
      : {}),
  });
};
createRoot(document.getElementById("root")!).render(
  <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
    <main style={{ maxWidth: 1000, margin: "auto", padding: 16 }}>
      <h1>Seasons · isolated role settings</h1>
      <p>Disconnected sample data. No real role or Discord request.</p>
      <CwlPoolRoles />
    </main>
  </DashboardPermissions.Provider>,
);
