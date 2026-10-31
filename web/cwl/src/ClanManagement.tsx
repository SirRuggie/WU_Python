import {
  clanSections as sections,
  type ClanRoute,
} from "./clanManagement/routes";
import { useCallback, useEffect, useState, useRef } from "react";
import { api, apiUpload } from "./api";
import { useClanChoices } from "./useClanChoices";
import ReminderOverview from "./clanManagement/ReminderOverview";
import { clanCategory } from "./clanManagement/ClanCategories";
import ClanDirectory from "./clanManagement/ClanDirectory";
import ClanSettingsNavigation from "./clanManagement/ClanSettingsNavigation";
import ClanFields from "./clanManagement/ClanFields";
import type { Clan } from "./clanManagement/types";
import "./ClanManagement.css";
import ClanHistory from "./ClanHistory";
import AddClan from "./clanManagement/AddClan";
import UsageLinks from "./clanManagement/UsageLinks";
import WarReminders, { type ReminderEditor } from "./WarReminders";
import ConfirmDialog from "./ConfirmDialog";
type Directory = { clans: Clan[]; types: string[]; town_halls: string[] };
type Choice = { id: string; name: string; avatar_url?: string };
const path = (tag: string) => "/manage/clans/" + encodeURIComponent(tag);
function sectionSummary(section: string, clan: Clan, reminder: string): string {
  if (section === "Details") return clan.type || "Clan type not set";
  if (section === "Roles")
    return `${["leader_role_id", "role_id"].filter((key) => clan[key]).length} of 2 roles set`;
  if (section === "Channels")
    return `${["chat_channel_id", "announcement_id", "rules_channel_id", "leadership_channel_id", "thread_id"].filter((key) => clan[key]).length} of 5 set`;
  if (section === "Artwork")
    return `${["logo", "banner"].filter((key) => clan[key]).length} of 2 images set`;
  return reminder;
}
export default function ClanManagement({
  onDirty,
  initialRoute,
  onWorking,
  onNavigate,
}: {
  onDirty: (value: boolean) => void;
  initialRoute?: ClanRoute;
  onWorking?: (busy: boolean) => void;
  onNavigate?: (route: ClanRoute) => void;
}) {
  const [view, setView] = useState<"overview" | "clans" | "history">(
    initialRoute?.tab || "clans",
  );
  const reminderEditor = useRef<ReminderEditor | null>(null);
  const initialClanPending = useRef(initialRoute?.tag);
  const [reminderChanges, setReminderChanges] = useState(0);
  const [reminderSummary, setReminderSummary] = useState("Loading…");
  const [sectionCollapsed, setSectionCollapsed] = useState(false);
  const [setupTag, setSetupTag] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{
    text: string;
    resolve: (ok: boolean) => void;
  } | null>(null);
  const receiveEditor = useCallback((editor: ReminderEditor | null) => {
    reminderEditor.current = editor;
    setReminderChanges(editor?.changes || 0);
    setReminderSummary(editor?.summary || "Loading…");
  }, []);
  function confirmAction(text: string): Promise<boolean> {
    return new Promise((resolve) =>
      setConfirmation((current) => {
        current?.resolve(false);
        return { text, resolve };
      }),
    );
  }
  const [overviewReturnTag, setOverviewReturnTag] = useState<string | null>(
    null,
  );
  const { channelsReady, choicesError, loadChoices, roles, channels } =
    useClanChoices();
  const editGeneration = useRef(0),
    loadGeneration = useRef(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const running = useRef(false);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [directoryError, setDirectoryError] = useState("");
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
    [section, setSection] = useState<(typeof sections)[number]>(
      initialRoute?.section || "Details",
    ),
    [query, setQuery] = useState(""),
    [adding, setAdding] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
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
      if (initialClanPending.current) {
        const target = result.clans.find(
          (clan) => clan.tag === initialClanPending.current,
        );
        initialClanPending.current = undefined;
        if (target) {
          setSaved(target);
          setDraft({ ...target });
        } else setError("This clan is no longer in the family directory.");
      }
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
  async function select(row: Clan | null) {
    if (disabled) return;
    if (row?.tag === saved?.tag) {
      setShowDirectory(false);
      requestAnimationFrame(() => headingRef.current?.focus());
      return;
    }
    if (dirty && !(await confirmAction("Discard unsaved clan changes?")))
      return;
    ++editGeneration.current;
    setSectionCollapsed(false);
    setSetupTag(null);
    setSection("Details");
    onNavigate?.({ tab: "clans", tag: row?.tag, section: "Details" });
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
    if (!draft || !saved || disabled) return;
    if (
      draft.type !== saved.type &&
      (draft.type === "FWA" ||
        saved.type === "FWA" ||
        clanCategory(draft.type) === "CWL" ||
        clanCategory(saved.type) === "CWL")
    ) {
      const effects =
        saved.type === "FWA"
          ? "removes this clan from Clan weights and FWA strike rules"
          : draft.type === "FWA"
            ? "adds this clan to Clan weights and FWA strike rules; its members can only sign up for Lazy CWL"
            : "changes its CWL hosting classification; existing assignments are kept";
      if (
        !(await confirmAction(
          `Changing ${saved.type || "Not set"} → ${draft.type || "Not set"} ${effects}. Save this change?`,
        ))
      )
        return;
    }
    await run(async () => {
      const errors: string[] = [];
      if (clanDirty) {
        const values = Object.fromEntries(
          Object.entries(draft).filter(
            ([key, value]) =>
              !["tag", "revision"].includes(key) && value !== saved[key],
          ),
        );
        try {
          const result = await api<Clan>(path(saved.tag), "PATCH", {
            revision: saved.revision,
            values,
          });
          setSaved(result);
          setDraft(result);
          setData((current) => ({
            ...current,
            clans: current.clans.map((clan) =>
              clan.tag === result.tag ? result : clan,
            ),
          }));
        } catch (error) {
          errors.push(
            `Clan details: ${error instanceof Error ? error.message : "Could not save."} Reload that section to resolve a conflict.`,
          );
        }
      }
      if (reminderDirty && !(await reminderEditor.current?.save()))
        errors.push(
          "War reminders changed or could not be saved. Reload that section; other edits are kept.",
        );
      if (errors.length) setError(errors.join(" "));
      else setNotice("Clan settings saved.");
    });
  }
  function discard() {
    setDraft(saved);
    reminderEditor.current?.discard();
    setError("");
    setNotice("");
  }
  async function action(kind: "emoji" | "thread") {
    if (
      !saved ||
      !(await confirmAction(
        kind === "emoji"
          ? "Create a clan emoji from the saved logo?"
          : "Find or create the clan thread?",
      ))
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
    if (
      file &&
      (!["image/png", "image/jpeg", "image/gif", "image/webp"].includes(
        file.type,
      ) ||
        file.size > 10 * 1024 * 1024)
    ) {
      setError("Choose PNG, JPG, GIF or WEBP up to 10 MB.");
      return;
    }
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
  useEffect(() => {
    onWorking?.(disabled);
    return () => onWorking?.(false);
  }, [disabled, onWorking]);

  async function changeView(next: typeof view) {
    if (disabled || next === view) return;
    if (dirty && !(await confirmAction("Discard unsaved clan changes?")))
      return;
    if (dirty) setDraft(saved);
    ++editGeneration.current;
    setReminderDirty(false);
    onNavigate?.({ tab: next });
    setView(next);
    setAdding(false);
  }
  function openReminderClan(clan: Clan) {
    ++editGeneration.current;
    setOverviewReturnTag(clan.tag);
    setSaved(clan);
    setDraft({ ...clan });
    setReminderDirty(false);
    onNavigate?.({ tab: "clans", tag: clan.tag, section: "War reminders" });
    setSection("War reminders");
    setSectionCollapsed(false);
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
          <p>Set up each clan and its war reminders.</p>
        </div>
        <button
          disabled={disabled}
          onClick={async () => {
            if (dirty && !(await confirmAction("Discard unsaved clan changes?"))) return;
            ++editGeneration.current;
            setSaved(null);
            setDraft(null);
            setReminderDirty(false);
            setSetupTag(null);
            onNavigate?.({ tab: "clans" });
            setView("clans");
            setAdding(!adding);
          }}
        >
          + Add clan
        </button>
      </div>
      <div className="clan-tabs" aria-label="Clan management views">
        {(
          [
            ["clans", "Clans"],
            ["overview", "Reminders"],
            ["history", "History"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            disabled={disabled}
            aria-pressed={view === key}
            onClick={() => void changeView(key)}
          >
            {label}
          </button>
        ))}
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
            onNavigate?.({ tab: "clans" });
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
            <AddClan
              disabled={disabled}
              onBusy={setBusy}
              beforeAdd={async () =>
                !dirty || (await confirmAction("Discard unsaved clan changes?"))
              }
              onOpen={(clan, warning) => {
                void (async () => {
                  ++editGeneration.current;
                  setSetupTag(clan.tag);
                  setSaved(clan);
                  setDraft({ ...clan });
                  setReminderDirty(false);
                  setAdding(false);
                  setSection("Details");
                  setSectionCollapsed(false);
                  setShowDirectory(false);
                  setNotice(
                    warning || "Review the setup checklist for this clan.",
                  );
                  onNavigate?.({
                    tab: "clans",
                    tag: clan.tag,
                    section: "Details",
                  });
                  void load();
                  requestAnimationFrame(() => headingRef.current?.focus());
                })();
              }}
            />
          )}
          <div className={`clan-layout ${draft ? "clan-detail-open" : ""}`}>
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
              <section className="card clan-editor">
                <button
                  className="clan-all-link"
                  disabled={disabled}
                  onClick={() => void select(null)}
                >
                  ‹ All clans
                </button>
                <UsageLinks tag={draft.tag} revision={saved?.revision || ""} />
                {setupTag === draft.tag && (
                  <nav aria-label="Clan setup checklist" className="clan-tabs">
                    {(
                      [
                        ["Clan type", "Details", !!draft.type],
                        ["Leader role", "Roles", !!draft.leader_role_id],
                        ["Channels", "Channels", !!draft.chat_channel_id],
                        [
                          "War reminders",
                          "War reminders",
                          reminderSummary.startsWith("On"),
                        ],
                      ] as const
                    ).map(([label, target, complete]) => (
                      <button
                        key={label}
                        disabled={disabled}
                        onClick={() => {
                          setSection(target);
                          setSectionCollapsed(false);
                          onNavigate?.({
                            tab: "clans",
                            tag: draft.tag,
                            section: target,
                          });
                        }}
                      >
                        {complete ? "✓" : "✗"} {label}
                      </button>
                    ))}
                  </nav>
                )}
                <div className="page-head">
                  <div>
                    <h2 ref={headingRef} tabIndex={-1}>
                      {draft.name}
                    </h2>
                    <small>{draft.tag}</small>
                  </div>
                  <button
                    disabled={disabled}
                    onClick={async () => {
                      if (
                        !clanDirty ||
                        (await confirmAction(
                          "Discard clan details and load current settings? Other section edits stay.",
                        ))
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
                  onChange={(next) => {
                    onNavigate?.({
                      tab: "clans",
                      tag: draft.tag,
                      section: next,
                    });
                    setSection(next);
                    setSectionCollapsed(false);
                  }}
                />
                {sections.map((item, index) => (
                  <div key={item} className="clan-section-card">
                    <button
                      className="clan-section-toggle"
                      aria-expanded={section === item && !sectionCollapsed}
                      aria-controls={`clan-panel-${index}`}
                      disabled={disabled}
                      onClick={() => {
                        if (item !== section)
                          onNavigate?.({
                            tab: "clans",
                            tag: draft.tag,
                            section: item,
                          });
                        setSection(item);
                        setSectionCollapsed(
                          section === item && !sectionCollapsed,
                        );
                      }}
                    >
                      <strong>{item}</strong>
                      <span>
                        {sectionSummary(item, draft, reminderSummary)}
                      </span>
                    </button>
                    <div
                      hidden={section !== item || sectionCollapsed}
                      id={`clan-panel-${index}`}
                      role="tabpanel"
                      aria-labelledby={`clan-section-${index}`}
                    >
                      {item === "War reminders" ? (
                        <WarReminders
                          embedded
                          active={
                            section === "War reminders" && !sectionCollapsed
                          }
                          key={draft.tag}
                          tag={draft.tag}
                          channels={channels}
                          onDirty={reminderChanged}
                          onBusy={reminderActivityChanged}
                          onEditor={receiveEditor}
                          disabled={busy}
                        />
                      ) : (
                        <ClanFields
                          section={item}
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
                      )}
                    </div>
                  </div>
                ))}
                <div className="clan-actions">
                  <span role="status">
                    {Object.keys(draft).filter(
                      (key) =>
                        !["tag", "revision"].includes(key) &&
                        draft[key] !== saved?.[key],
                    ).length + reminderChanges}{" "}
                    unsaved changes
                  </span>
                  <button
                    className="primary"
                    disabled={disabled || !dirty}
                    onClick={() => void save()}
                  >
                    Save
                  </button>
                  <button
                    disabled={disabled || !dirty}
                    onClick={async () => {
                      if (await confirmAction("Discard unsaved clan changes?"))
                        discard();
                    }}
                  >
                    Discard
                  </button>
                </div>
                <section className="clan-danger-zone" aria-label="Danger zone">
                  <h3>Danger zone</h3>
                  <p>
                    Remove this family clan. You can restore its settings from
                    History.
                  </p>
                  <button
                    className="danger-link"
                    disabled={disabled}
                    onClick={async () => {
                      if (
                        !saved ||
                        !(await confirmAction(
                          `Remove ${saved.name}? You can restore it from History.`,
                        ))
                      )
                        return;
                      void run(async () => {
                        await api(path(saved.tag), "DELETE", {
                          revision: saved.revision,
                          confirm_tag: saved.tag,
                        });
                        setSaved(null);
                        setDraft(null);
                        setReminderDirty(false);
                        onNavigate?.({ tab: "clans" });
                        await load();
                        setNotice("Clan removed from the family directory.");
                      });
                    }}
                  >
                    Remove clan
                  </button>
                </section>
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
      {confirmation && (
        <ConfirmDialog
          text={confirmation.text}
          onCancel={() => {
            confirmation.resolve(false);
            setConfirmation(null);
          }}
          onConfirm={() => {
            confirmation.resolve(true);
            setConfirmation(null);
          }}
        />
      )}
    </section>
  );
}
