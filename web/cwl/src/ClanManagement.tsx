import { useCallback, useEffect, useState, useRef } from "react";
import { api, apiUpload } from "./api";
import ReminderOverview from "./clanManagement/ReminderOverview";
import ClanDirectory from "./clanManagement/ClanDirectory";
import ClanSettingsNavigation from "./clanManagement/ClanSettingsNavigation";
import ClanFields from "./clanManagement/ClanFields";
import type { Clan } from "./clanManagement/types";
import type { AnnouncementChannel } from "./announcements";
import "./ClanManagement.css";
import ClanHistory from "./ClanHistory";
import WarReminders from "./WarReminders";
type Directory = { clans: Clan[]; types: string[]; town_halls: string[] };
type Choice = { id: string; name: string };
const path = (tag: string) => "/manage/clans/" + encodeURIComponent(tag);
const sections = [
  "Details",
  "Roles",
  "Channels",
  "Artwork",
  "War reminders",
] as const;
export default function ClanManagement({
  onDirty,
}: {
  onDirty: (value: boolean) => void;
}) {
  const [view, setView] = useState<"overview" | "clans" | "history">(
    "overview",
  );
  const [overviewReturnTag, setOverviewReturnTag] = useState<string | null>(
    null,
  );
  const [channelsReady, setChannelsReady] = useState(false);
  const editGeneration = useRef(0),
    loadGeneration = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const running = useRef(false);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [directoryError, setDirectoryError] = useState("");
  const [choicesError, setChoicesError] = useState("");
  const [reminderBusy, setReminderBusy] = useState(false);
  const reminderActivityChanged = useCallback((value: boolean) => {
    ++editGeneration.current;
    setReminderBusy(value);
  }, []);
  const reminderChanged = useCallback((value: boolean) => {
    ++editGeneration.current;
    setReminderDirty(value);
  }, []);
  const [data, setData] = useState<Directory>({
      clans: [],
      types: [],
      town_halls: [],
    }),
    [saved, setSaved] = useState<Clan | null>(null),
    [draft, setDraft] = useState<Clan | null>(null),
    [section, setSection] = useState<(typeof sections)[number]>("Details"),
    [query, setQuery] = useState(""),
    [newTag, setNewTag] = useState(""),
    [adding, setAdding] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [roles, setRoles] = useState<Choice[]>([]),
    [channels, setChannels] = useState<AnnouncementChannel[]>([]),
    [memberQuery, setMemberQuery] = useState(""),
    [members, setMembers] = useState<Choice[]>([]),
    [memberError, setMemberError] = useState(""),
    [statusUrl, setStatusUrl] = useState("");
  const [showDirectory, setShowDirectory] = useState(false),
    [clanType, setClanType] = useState(""),
    [reminderDirty, setReminderDirty] = useState(false);
  const clanDirty = !!draft && JSON.stringify(draft) !== JSON.stringify(saved);
  const dirty = clanDirty || reminderDirty;
  async function load(refresh = false) {
    const edit = editGeneration.current,
      turn = ++loadGeneration.current;
    try {
      const result = await api<Directory>("/manage/clans");
      if (turn !== loadGeneration.current || edit !== editGeneration.current)
        return;
      setData(result);
      setDirectoryError("");
      if (refresh && saved) {
        const current = result.clans.find((c) => c.tag === saved.tag) || null;
        setSaved(current);
        setDraft(current);
      }
    } catch (e) {
      if (turn === loadGeneration.current)
        setDirectoryError(
          e instanceof Error ? e.message : "Could not load clans.",
        );
    } finally {
      if (turn === loadGeneration.current) setDirectoryLoading(false);
    }
  }

  async function loadChoices() {
    setChoicesError("");
    try {
      const result = await api<{
        roles: Choice[];
        channels: AnnouncementChannel[];
      }>("/manage/clan-choices");
      setRoles(result.roles);
      setChannels(result.channels);
      setChannelsReady(true);
    } catch (e) {
      setChoicesError(
        e instanceof Error ? e.message : "Could not load roles and channels.",
      );
    }
  }
  useEffect(() => {
    void load();
    void loadChoices();
    return () => {
      ++loadGeneration.current;
    };
  }, []);
  useEffect(() => {
    onDirty(dirty || busy || reminderBusy);
    const guard = (e: BeforeUnloadEvent) => {
      if (dirty || busy || reminderBusy) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => {
      onDirty(false);
      window.removeEventListener("beforeunload", guard);
    };
  }, [dirty, busy, reminderBusy, onDirty]);
  useEffect(() => {
    if (view !== "clans" || dirty || busy || reminderBusy || statusUrl) return;
    const timer = setInterval(() => {
      if (!document.hidden) void load(true);
    }, 30000);
    return () => clearInterval(timer);
  }, [view, dirty, busy, reminderBusy, statusUrl, saved?.tag]);
  useEffect(() => {
    if (!draft || section !== "Roles") return;
    let active = true;
    const timer = setTimeout(() => {
      api<{ members: Choice[] }>(
        "/manage/clan-members?q=" +
          encodeURIComponent(memberQuery) +
          "&selected=" +
          encodeURIComponent(draft.leader_id || ""),
      )
        .then((r) => {
          if (active) {
            setMembers(r.members);
            setMemberError("");
          }
        })
        .catch((e) => {
          if (active) setMemberError(e.message);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [memberQuery, section, draft?.tag, draft?.leader_id]);
  useEffect(() => {
    if (!statusUrl) return;
    let active = true;
    const timer = setInterval(() => {
      api<{ status: string; message: string }>(statusUrl)
        .then((result) => {
          if (!active) return;
          if (["done", "failed", "uncertain"].includes(result.status)) {
            setStatusUrl("");
            setNotice(result.message);
            void load(true);
          }
        })
        .catch((e) => {
          if (active) {
            setError(e.message);
            setStatusUrl("");
          }
        });
    }, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [statusUrl]);
  function select(row: Clan | null) {
    if (disabled) return;
    if (row?.tag === saved?.tag) {
      setShowDirectory(false);
      requestAnimationFrame(() => headingRef.current?.focus());
      return;
    }
    if (dirty && !confirm("Discard unsaved clan changes?")) return;
    ++editGeneration.current;
    setSaved(row);
    setDraft(row ? { ...row } : null);
    setNotice("");
    setError("");
    setReminderDirty(false);
    setShowDirectory(false);
    requestAnimationFrame(() => headingRef.current?.focus());
  }
  function change(key: string, value: string) {
    ++editGeneration.current;
    setDraft((current) => (current ? { ...current, [key]: value } : null));
  }
  async function run(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    ++editGeneration.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update clan.");
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  async function save() {
    if (!draft || !saved) return;
    await run(async () => {
      const values = Object.fromEntries(
        Object.entries(draft).filter(
          ([key, value]) =>
            !["tag", "revision"].includes(key) && value !== saved[key],
        ),
      );
      const result = await api<Clan>(path(saved.tag), "PATCH", {
        revision: saved.revision,
        values,
      });
      setSaved(result);
      setDraft(result);
      setNotice("Clan saved. Discord uses these same settings.");
      await load();
    });
  }
  async function action(kind: "emoji" | "thread") {
    if (
      !saved ||
      !confirm(
        kind === "emoji"
          ? "Create a clan emoji from the saved logo?"
          : "Find or create the clan thread?",
      )
    )
      return;
    await run(async () => {
      const result = await api<{ status_url: string }>(
        path(saved.tag) + "/actions/" + kind,
        "POST",
        { revision: saved.revision, request_id: crypto.randomUUID() },
      );
      setStatusUrl(result.status_url);
      setNotice("Waiting for the bot…");
    });
  }
  async function upload(slot: string, file?: File) {
    if (!saved || !draft) return;
    await run(async () => {
      const endpoint =
        path(saved.tag) +
        "/images/" +
        slot +
        "?revision=" +
        encodeURIComponent(saved.revision);
      const result = file
        ? await apiUpload<{ url: string }>(endpoint, file)
        : await api<{ url: string }>(endpoint, "POST", { url: draft[slot] });
      change(slot, result.url);
      setNotice("Image uploaded. Save changes to use it.");
    });
  }
  const disabled = busy || reminderBusy || !!statusUrl;

  function changeView(next: typeof view) {
    if (disabled || next === view) return;
    if (dirty && !confirm("Discard unsaved clan changes?")) return;
    if (dirty) setDraft(saved);
    ++editGeneration.current;
    setReminderDirty(false);
    setView(next);
    setAdding(false);
  }
  function openReminderClan(clan: Clan) {
    ++editGeneration.current;
    setOverviewReturnTag(clan.tag);
    setSaved(clan);
    setDraft({ ...clan });
    setReminderDirty(false);
    setSection("War reminders");
    setView("clans");
    setAdding(false);
    setError("");
    setNotice("");
    setShowDirectory(false);
    requestAnimationFrame(() => headingRef.current?.focus());
    void load();
  }
  return (
    <section className="clan-management">
      <div className="page-head">
        <div>
          <p className="eyebrow">Clan management</p>
          <h1>Family clans</h1>
          <p>
            Monitor your family’s reminders and manage each clan in one place.
          </p>
        </div>
        <button
          disabled={disabled}
          onClick={() => {
            setView("clans");
            setAdding(!adding);
          }}
        >
          + Add clan
        </button>
      </div>
      <div className="clan-tabs" aria-label="Clan management views">
        <button
          disabled={disabled}
          aria-pressed={view === "overview"}
          onClick={() => changeView("overview")}
        >
          Reminder overview
        </button>
        <button
          disabled={disabled}
          aria-pressed={view === "clans"}
          onClick={() => changeView("clans")}
        >
          Clans
        </button>
        <button
          disabled={disabled}
          aria-pressed={view === "history"}
          onClick={() => changeView("history")}
        >
          Activity & recovery
        </button>
      </div>
      <div hidden={view !== "overview"}>
        <ReminderOverview
          active={view === "overview"}
          channels={channels}
          channelsReady={channelsReady && !choicesError}
          choicesError={choicesError}
          onRetryChoices={() => void loadChoices()}
          onOpen={openReminderClan}
          returnTag={overviewReturnTag}
          onAdd={() => {
            setView("clans");
            setAdding(true);
          }}
        />
      </div>
      {view === "overview" ? null : view === "history" ? (
        <ClanHistory onRestored={() => void load()} />
      ) : (
        <>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          {choicesError && (
            <p className="notice error" role="alert">
              Roles and channels could not be loaded: {choicesError}{" "}
              <button disabled={disabled} onClick={() => void loadChoices()}>
                Retry roles and channels
              </button>
            </p>
          )}
          {notice && (
            <p className="notice" role="status">
              {notice}
            </p>
          )}
          {adding && (
            <form
              className="card clan-add"
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  const result = await api<Directory>("/manage/clans", "POST", {
                    tag: newTag,
                  });
                  setData(result);
                  setNewTag("");
                  setAdding(false);
                  setNotice("Clan added. Select it to finish its settings.");
                });
              }}
            >
              <label>
                Clan tag
                <input
                  required
                  placeholder="#CLANTAG"
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                />
              </label>
              <button disabled={disabled}>Add clan</button>
            </form>
          )}
          <div className="clan-layout">
            <ClanDirectory
              clans={data.clans}
              types={data.types}
              selected={saved}
              query={query}
              onQuery={setQuery}
              clanType={clanType}
              onType={setClanType}
              expanded={showDirectory}
              onExpanded={setShowDirectory}
              disabled={disabled}
              loading={directoryLoading}
              error={directoryError}
              onRetry={() => {
                setDirectoryLoading(true);
                void load();
              }}
              onSelect={select}
            />
            {draft ? (
              <section className="card">
                <div className="page-head">
                  <div>
                    <h2 ref={headingRef} tabIndex={-1}>
                      {draft.name}
                    </h2>
                    <small>{draft.tag}</small>
                  </div>
                  <button
                    disabled={disabled || reminderDirty}
                    onClick={() => {
                      if (
                        !dirty ||
                        confirm("Discard edits and load current settings?")
                      )
                        void run(() => load(true));
                    }}
                  >
                    Reload
                  </button>
                </div>
                <ClanSettingsNavigation
                  sections={sections}
                  value={section}
                  disabled={disabled}
                  onChange={(tab) => {
                    if (tab === section) return;
                    if (
                      reminderDirty &&
                      !confirm("Discard unsaved reminder changes?")
                    )
                      return;
                    setReminderDirty(false);
                    setSection(tab);
                  }}
                />
                {section === "War reminders" && clanDirty && (
                  <div className="clan-pending" role="status">
                    <span>
                      You have unsaved clan details. Reminder settings are saved
                      separately.
                    </span>
                    <button disabled={disabled} onClick={() => void save()}>
                      Save clan details
                    </button>
                  </div>
                )}
                <div
                  role="tabpanel"
                  id="clan-settings-panel"
                  aria-labelledby={"clan-section-" + sections.indexOf(section)}
                  tabIndex={0}
                >
                  {section === "War reminders" && (
                    <WarReminders
                      key={draft.tag}
                      tag={draft.tag}
                      channels={channels}
                      onDirty={reminderChanged}
                      onBusy={reminderActivityChanged}
                      disabled={busy}
                    />
                  )}
                  <ClanFields
                    section={section}
                    draft={draft}
                    saved={saved}
                    disabled={disabled}
                    dirty={clanDirty}
                    data={data}
                    channels={channels}
                    roles={roles}
                    memberQuery={memberQuery}
                    setMemberQuery={setMemberQuery}
                    members={members}
                    memberError={memberError}
                    change={change}
                    action={action}
                    upload={upload}
                  />
                </div>
                {section !== "War reminders" && (
                  <>
                    <div className="clan-actions">
                      <span className="small">
                        {clanDirty
                          ? "Unsaved clan changes"
                          : "Clan details saved"}
                      </span>
                      <button
                        className="primary"
                        disabled={disabled || !clanDirty}
                        onClick={() => void save()}
                      >
                        Save changes
                      </button>
                    </div>
                    <details className="clan-remove">
                      <summary>Remove clan</summary>
                      <p>
                        Removes this family clan from the bot. Existing CWL
                        history, Discord channels, roles and artwork are kept.
                      </p>
                      <button
                        className="danger-link"
                        disabled={disabled}
                        onClick={() => {
                          const confirmTag = prompt(
                            `Type ${saved?.tag} to remove this clan from the family directory.`,
                          );
                          if (confirmTag !== saved?.tag) return;
                          void run(async () => {
                            await api(path(saved!.tag), "DELETE", {
                              revision: saved!.revision,
                              confirm_tag: confirmTag,
                            });
                            setSaved(null);
                            setDraft(null);
                            await load();
                            setNotice(
                              "Clan removed from the family directory.",
                            );
                          });
                        }}
                      >
                        Remove clan…
                      </button>
                    </details>
                  </>
                )}
              </section>
            ) : (
              <section className="card">
                <h2>Select a clan</h2>
                <p>Choose a family clan or add one by tag.</p>
              </section>
            )}
          </div>
        </>
      )}
    </section>
  );
}
