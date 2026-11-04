import "./src/tokens.css";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, setCsrfToken, type Session, type Pool } from "./src/api";
import AnnouncementPostUpdate from "./src/AnnouncementPostUpdate";
import DiscordPreview, { type PreviewPart } from "./src/DiscordMessagePreview";
import type { PostCopy } from "./src/announcementPostUpdate";
import "./src/style.css";
import "./src/announcementWorkspace.css";
import "./src/workflowControls.css";
import "./src/accessibility.css";
type State = {
  season_id: string;
  cycle: string;
  generation: string;
  pools: Record<
    Pool,
    { copy: PostCopy; live: PreviewPart[]; future: PostCopy }
  >;
  flags: Record<string, boolean>;
  edits: number;
};
function Preview() {
  useEffect(() => {
    const rewrite = () =>
      document
        .querySelectorAll<HTMLAnchorElement>(
          'a[href^="https://discord.com/channels/"]',
        )
        .forEach((link) => {
          const id = link.href.split("/").at(-1);
          link.href =
            "/api/cwl/fixture/post-view?message_id=" +
            encodeURIComponent(id || "400");
        });
    const observer = new MutationObserver(rewrite);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["href"],
    });
    rewrite();
    return () => observer.disconnect();
  }, []);

  const [state, setState] = useState<State | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = async () => {
    try {
      setState(await api<State>("/fixture/post-update-state"));
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  };
  const login = async () => {
    setBusy(true);
    try {
      await api("/dev/login", "POST");
      const me = await api<Session>("/auth/me");
      setCsrfToken(me.csrf_token);
      await load();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };
  const control = async (action: string) => {
    try {
      await api("/fixture/post-update-controls", "POST", { action });
      await load();
    } catch (reason) {
      setError(String(reason));
    }
  };
  return (
    <main style={{ maxWidth: 1200, margin: "auto", padding: 16 }}>
      <h1>Roster post editor</h1>
      <p>
        Local test session. Posts, saved copies and artwork are samples. Nothing
        reaches Discord or production.
      </p>
      {!state ? (
        <button type="button" disabled={busy} onClick={() => void login()}>
          Open local test session
        </button>
      ) : (
        <>
          <p role="status">
            Confirmed fake post edits: {state.edits}. Updates save real isolated
            fixture state.
          </p>
          <details>
            <summary>Local fixture controls</summary>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                paddingBlock: 12,
              }}
            >
              {[
                "Change fake post",
                "Toggle deleted post",
                "Toggle bot access",
                "Toggle worker pause",
                "Toggle slow edit",
                "Toggle saved-copy race",
              ].map((label) => (
                <button
                  type="button"
                  key={label}
                  onClick={() => void control(label)}
                >
                  {label}
                </button>
              ))}
              <button type="button" onClick={() => void load()}>
                Refresh fixture state
              </button>
            </div>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(state.flags, null, 2)}
            </pre>
          </details>
          {(["main", "lazy"] as const).map((pool) => (
            <section
              key={pool}
              aria-label={`${pool === "main" ? "Main" : "Lazy"} roster`}
              style={{
                border: "1px solid #505050",
                padding: 16,
                borderRadius: 12,
                marginBlock: 16,
              }}
            >
              <h2>{pool === "main" ? "Main" : "Lazy"} roster post</h2>
              <AnnouncementPostUpdate
                seasonId={state.season_id}
                cycle={state.cycle}
                pool={pool}
                generation={state.generation}
                copy={state.pools[pool].copy}
                allowed={true}
                onUpdated={() => void load()}
              />
              <details>
                <summary>Current fake post and saved copy</summary>
                <DiscordPreview
                  label="Current fake post"
                  parts={state.pools[pool].live}
                />
                <p>Current month saved body: {state.pools[pool].copy.body}</p>
                <p>Next month saved body: {state.pools[pool].future.body}</p>
              </details>
            </section>
          ))}
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
