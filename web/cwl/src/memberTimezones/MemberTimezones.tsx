import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Directory, Member, RequestState } from "./types";
import MemberTimezoneEditor from "./MemberTimezoneEditor";
import Standardize from "./Standardize";
import "./MemberTimezones.css";

export default function MemberTimezones({
  onDirty,
}: {
  onDirty: (value: boolean) => void;
}) {
  const [data, setData] = useState<Directory | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState("All"),
    [editing, setEditing] = useState<Member | null>(null),
    [dirty, setDirty] = useState(false),
    [request, setRequest] = useState<RequestState | null>(null),
    [sending, setSending] = useState(false),
    [loaded, setLoaded] = useState("");
  const alive = useRef(true),
    generation = useRef(0),
    importId = useRef(crypto.randomUUID()),
    rowButton = useRef<HTMLButtonElement | null>(null);
  const denied = () => {
    generation.current++;
    setData(null);
    setEditing(null);
    setRequest(null);
    setDirty(false);
    onDirty(false);
    setError("Your access changed. Reload after access is restored.");
  };
  const fail = (e: unknown) => {
    if (!alive.current) return;
    if (e instanceof ApiError && [401, 403].includes(e.status)) denied();
    else
      setError(
        e instanceof Error ? e.message : "Member time zones are unavailable.",
      );
  };
  async function load() {
    const current = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const next = await api<Directory>("/manage/member-timezones");
      if (alive.current && current === generation.current) {
        setData(next);
        setLoaded(new Date().toLocaleTimeString());
      }
    } catch (e) {
      if (current === generation.current) fail(e);
    } finally {
      if (alive.current && current === generation.current) setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      generation.current++;
    };
  }, []);
  const busy =
    sending || (!!request && ["pending", "running"].includes(request.status));
  useEffect(() => {
    if (!request || !["pending", "running"].includes(request.status)) return;
    let cancelled = false,
      inflight = false;
    const path = request.status_url;
    const check = async () => {
      if (cancelled || inflight || document.visibilityState === "hidden")
        return;
      inflight = true;
      try {
        const result = await api<RequestState>(path);
        if (cancelled) return;
        setRequest((previous) =>
          previous ? { ...previous, ...result } : null,
        );
        if (!["pending", "running"].includes(result.status)) {
          if (result.status === "done") {
            setEditing(null);
            setDirty(false);
            onDirty(false);
            void load();
            rowButton.current?.focus();
          } else setError(result.message);
        }
      } catch (e) {
        if (!cancelled) fail(e);
      } finally {
        inflight = false;
      }
    };
    const timer = setInterval(() => void check(), 2000);
    void check();
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [request?.request_id, request?.status]);
  const close = () => {
    if (dirty && !window.confirm("Discard unsaved member profile changes?"))
      return;
    setEditing(null);
    setDirty(false);
    onDirty(false);
    rowButton.current?.focus();
  };
  async function importCurrent() {
    if (
      !window.confirm(
        "Import parsed nickname time zones? Existing saved profiles and all Discord nicknames stay unchanged.",
      )
    )
      return;
    setSending(true);
    setError("");
    try {
      setRequest(
        await api<RequestState>("/manage/member-timezones/import", "POST", {
          request_id: importId.current,
        }),
      );
    } catch (e) {
      fail(e);
    } finally {
      if (alive.current) setSending(false);
    }
  }
  const rows = (data?.members || [])
    .filter(
      (m) =>
        (status === "All" || m.status === status) &&
        `${m.name} ${m.nickname || ""} ${m.discord_id}`
          .normalize("NFKC")
          .toLocaleLowerCase()
          .includes(query.normalize("NFKC").toLocaleLowerCase()),
    )
    .sort((a, b) => {
      const az = a.profile?.utc_offset_minutes ?? a.parsed?.offsetMinutes,
        bz = b.profile?.utc_offset_minutes ?? b.parsed?.offsetMinutes;
      return (
        (az == null ? 1 : 0) - (bz == null ? 1 : 0) ||
        (az ?? 0) - (bz ?? 0) ||
        a.name.localeCompare(b.name) ||
        a.discord_id.localeCompare(b.discord_id)
      );
    });
  return (
    <main className="member-timezones">
      <h1>Member time zones</h1>
      <p>
        Requires Members & roles access. GMT labels use standard time and may
        differ from daylight saving time.
      </p>
      {error && <p role="alert">{error}</p>}
      <div className="mt-toolbar">
        <button
          disabled={loading || busy || !!editing}
          onClick={() => void load()}
        >
          Refresh members
        </button>
        {loaded && (
          <span>
            Loaded {loaded}
            {loading ? " · Refreshing…" : ""}
          </span>
        )}
      </div>
      {request && (
        <p role="status">
          {request.status}: {request.message}
          {request.result?.counts &&
            ` · ${Object.entries(request.result.counts)
              .map(([key, value]) => `${key}: ${value}`)
              .join(" · ")}`}
        </p>
      )}
      {!data ? (
        loading ? (
          <p role="status">Loading server members…</p>
        ) : (
          <p>Member data is unavailable. Use Refresh members to try again.</p>
        )
      ) : (
        <>
          {editing ? (
            <MemberTimezoneEditor
              key={editing.discord_id}
              member={editing}
              data={data}
              busy={busy}
              onDirty={(value) => {
                setDirty(value);
                onDirty(value);
              }}
              onDenied={denied}
              onClose={close}
              onQueue={(result) => {
                setRequest(result);
                setDirty(false);
                onDirty(false);
              }}
            />
          ) : (
            <>
              <div className="mt-toolbar">
                <label>
                  Search members
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Name, nickname or Discord ID"
                  />
                </label>
                <label>
                  Status
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    {[
                      "All",
                      "Saved",
                      "From nickname",
                      "Unknown",
                      "Missing",
                    ].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
              </div>
              <p>
                {rows.length} of {data.members.length} members · sorted west to
                east
              </p>
              {!rows.length && (
                <p>
                  {data.members.length
                    ? "No members match these filters."
                    : "No server members were returned."}
                </p>
              )}
              <ul className="mt-list">
                {rows.map((m) => (
                  <li key={m.discord_id}>
                    <div>
                      <strong>{m.name}</strong>
                      {m.bot && <span> · Bot</span>}
                      <p>{m.nickname || "No nickname"}</p>
                      <p>
                        {m.profile?.gmt_label ||
                          m.parsed?.label ||
                          "No time zone"}{" "}
                        {m.profile?.flag || ""} · {m.status}
                      </p>
                      {m.skip_reason && <p>{m.skip_reason}</p>}
                    </div>
                    <button
                      disabled={busy || m.bot}
                      onClick={(e) => {
                        rowButton.current = e.currentTarget;
                        setEditing(m);
                        setDirty(false);
                      }}
                    >
                      Edit {m.name}
                    </button>
                  </li>
                ))}
              </ul>
              <details>
                <summary>Import existing nicknames</summary>
                <p>
                  Fill profiles from recognized time zone labels. No nickname
                  changes; existing saved and imported choices are preserved.
                </p>
                <button disabled={busy} onClick={() => void importCurrent()}>
                  Import nickname time zones
                </button>
              </details>
              <Standardize disabled={busy} onDenied={denied} />
            </>
          )}
        </>
      )}
    </main>
  );
}
