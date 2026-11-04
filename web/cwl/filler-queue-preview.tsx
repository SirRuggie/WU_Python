import "./src/tokens.css";
import { createRoot } from "react-dom/client";
import { useState } from "react";
import ArrivalCheck from "./src/ArrivalCheck";
import StaffDetailsHost from "./src/StaffDetailsHost";
import { DashboardPermissions } from "./src/DashboardPermissions";
import { api, setCsrfToken } from "./src/api";
import "./src/style.css";
localStorage.setItem("wu-staff-cwl-pool", "lazy");
function Preview() {
  const [loaded, setLoaded] = useState(false),
    [open, setOpen] = useState(true),
    [dirty, setDirty] = useState(false),
    [working, setWorking] = useState(false),
    [error, setError] = useState("");
  async function login() {
    try {
      await api("/dev/login", "POST");
      const me = await api<{ csrf_token: string }>("/auth/me");
      setCsrfToken(me.csrf_token);
      setLoaded(true);
    } catch {
      setError("Could not open local sample session");
    }
  }
  async function fail(status: number, afterCommit = false) {
    await api("/fixture145/controls", "POST", {
      status,
      after: 2,
      afterCommit,
    });
  }
  return (
    <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
      <main
        className="roster-ui"
        style={{ maxWidth: 1100, margin: "0 auto", padding: 16 }}
      >
        <h1>Background filler saves</h1>
        <p>
          Owned sample SQLite and real existing mark endpoint. No production,
          Discord or provider access.
        </p>
        {!loaded ? (
          <button onClick={() => void login()}>Open local test session</button>
        ) : (
          <>
            <p role="status">
              Page guard: {working ? "working" : "idle"} ·{" "}
              {dirty ? "unsaved work" : "clean"}
            </p>
            <details>
              <summary>Local fixture controls</summary>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {[409, 401, 403, 504].map((status) => (
                  <button key={status} onClick={() => void fail(status)}>
                    Fail second save: {status}
                  </button>
                ))}
                <button onClick={() => void fail(0, true)}>
                  Lose second acknowledgement after commit
                </button>
                <button onClick={() => void fail(-1)}>
                  Clear simulated failure
                </button>
                <button
                  onClick={() => {
                    if (
                      (working || dirty) &&
                      !confirm("Leave sample page while saves are working?")
                    )
                      return;
                    setOpen(false);
                  }}
                >
                  Leave sample page
                </button>
                <button onClick={() => setOpen(true)}>
                  Reopen sample page
                </button>
              </div>
            </details>
            {open ? (
              <>
                <ArrivalCheck
                  seasonId="1"
                  onDirty={setDirty}
                  onWorking={setWorking}
                />
                <StaffDetailsHost />
              </>
            ) : (
              <p>Sample page closed. Unsent ticks are discarded.</p>
            )}
          </>
        )}
        {error && <p role="alert">{error}</p>}
      </main>
    </DashboardPermissions.Provider>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
