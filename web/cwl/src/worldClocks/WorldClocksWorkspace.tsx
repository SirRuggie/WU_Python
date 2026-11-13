import LoadError from "../LoadError";
import CwlPageHeader from "../CwlPageHeader";
import { Ban } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import SectionTabs from "../SectionTabs";
import { Button } from "../rosterUi/primitives";
import AddClockDialog from "./AddClockDialog";
import ClockSettingsPanel, { RecentUpdates } from "./ClockSettingsPanel";
import WorldClockRow from "./WorldClockRow";
import {
  API_BASE,
  discordName,
  hasProblem,
  localTime,
  problemText,
  statusCounts,
  type WorldClock,
  type WorldClocksData,
} from "./worldClocksModel";
import "./WorldClocks.css";

type Section = "clocks" | "settings";

function DiscordPreview({
  clocks,
  categoryName,
}: {
  clocks: WorldClock[];
  categoryName: string;
}) {
  return (
    <div className="world-clock-discord" aria-label="Channel list in Discord">
      <p className="world-clock-discord-category">
        ⌄ {categoryName || "Clock channels"}
      </p>
      <ul>
        {clocks.map((clock) => (
          <li
            key={clock.id}
            className={
              hasProblem(clock) ? "is-missing" : clock.enabled ? "" : "is-off"
            }
          >
            <span aria-hidden="true">🔊</span>
            <span className="world-clock-discord-name">
              {clock.channel_missing
                ? "Missing channel"
                : clock.enabled
                  ? clock.name_now || discordName(clock)
                  : discordName(clock)}
            </span>
            {!clock.enabled && <small>frozen</small>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function WorldClocksWorkspace({
  onDirty,
}: {
  onDirty?: (dirty: boolean) => void;
}) {
  const [section, setSection] = useState<Section>("clocks");
  const [data, setData] = useState<WorldClocksData | null>(null);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [focusChannel, setFocusChannel] = useState(false);
  const [adding, setAdding] = useState(false);
  const dirtyParts = useRef(new Map<string, boolean>());
  const loadSeq = useRef(0);

  const setDirty = useCallback(
    (key: string, dirty: boolean) => {
      dirtyParts.current.set(key, dirty);
      onDirty?.([...dirtyParts.current.values()].some(Boolean));
    },
    [onDirty],
  );
  const rowDirty = useCallback(
    (dirty: boolean) => setDirty("row", dirty),
    [setDirty],
  );
  const addDirty = useCallback(
    (dirty: boolean) => setDirty("add", dirty),
    [setDirty],
  );
  const settingsDirty = useCallback(
    (dirty: boolean) => setDirty("settings", dirty),
    [setDirty],
  );

  const load = useCallback(async (message = "") => {
    const seq = ++loadSeq.current;
    try {
      const result = await api<WorldClocksData>(API_BASE);
      if (seq !== loadSeq.current) return; // A newer load won; ignore this stale response.
      setData(result);
      setLoadError("");
      setNotice(message);
    } catch (reason) {
      if (seq !== loadSeq.current) return;
      setLoadError(
        reason instanceof Error
          ? reason.message
          : "World clocks are unavailable.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      onDirty?.(false);
    };
  }, [load, onDirty]);

  const usedZones = useMemo(
    () => new Set((data?.clocks || []).map((clock) => clock.zone)),
    [data],
  );
  const categoryName =
    data?.categories.find((row) => row.id === data.settings.category_id)
      ?.name || "";

  if (!data)
    return (
      <section className="world-clocks" aria-labelledby="world-clocks-title">
        <Header />
        {loadError ? (
          <LoadError message={loadError} onRetry={() => void load()} />
        ) : (
          <p className="world-clock-help" role="status">
            Loading clocks…
          </p>
        )}
      </section>
    );

  const counts = statusCounts(data.clocks);
  const problems = data.clocks.filter(hasProblem);
  const full = data.clocks.length >= data.max_clocks;

  function openRow(id: string | null, toChannel = false) {
    setOpenId(id);
    setFocusChannel(toChannel);
    if (id === null) setDirty("row", false);
  }

  return (
    <section className="world-clocks" aria-labelledby="world-clocks-title">
      <Header />
      <SectionTabs
        className="world-clock-sections section-tabs--flow"
        label="World clocks sections"
        items={[
          { id: "clocks", label: "Clocks" },
          { id: "settings", label: "Settings" },
        ]}
        value={section}
        onChange={setSection}
      />
      {notice && (
        <p className="world-clock-notice" role="status">
          {notice}
        </p>
      )}
      {!data.channels_available && (
        <p className="world-clock-warning" role="status">
          Discord is unavailable. Channel names and lists may be out of date.
        </p>
      )}
      <div hidden={section !== "clocks"}>
        {data.clocks.length > 0 && (
          <p className="world-clock-status">
            <span>
              <strong>{counts.updating} updating</strong>
              {counts.problems > 0 && ` · ${counts.problems} with a problem`}
              {counts.off > 0 && ` · ${counts.off} off`}
            </span>
            <span>
              Next update <strong>{localTime(data.next_update)}</strong>
            </span>
          </p>
        )}
        {problems.length > 0 && (
          <div className="world-clock-alert" role="alert">
            <p>
              <Ban size={16} aria-hidden="true" />{" "}
              {problems.length === 1
                ? `${problems[0].name_now?.split(" · ")[0] || problems[0].zone}: ${problemText(problems[0])}`
                : `${problems.length} clocks have a problem.`}
            </p>
            <Button onClick={() => openRow(problems[0].id, true)}>Fix</Button>
          </div>
        )}
        <div className="world-clock-layout">
          <div className="world-clock-main">
            <div className="world-clock-add">
              <Button
                variant={openId ? "secondary" : "primary"}
                disabled={full}
                onClick={() => {
                  openRow(null);
                  setAdding(true);
                }}
              >
                + Add clock
              </Button>
              {full && (
                <span className="world-clock-help">
                  You have the maximum of {data.max_clocks} clocks.
                </span>
              )}
            </div>
            {data.clocks.length === 0 ? (
              <div className="world-clock-empty">
                <p>
                  <strong>No clocks yet.</strong>
                </p>
                <p className="world-clock-help">
                  Add a clock to show a local time as a voice channel name.
                  {!data.settings.category_id &&
                    " Select a category in Settings first."}
                </p>
              </div>
            ) : (
              <div className="world-clock-list">
                {data.clocks.map((clock) => (
                  <WorldClockRow
                    key={clock.id}
                    clock={clock}
                    open={openId === clock.id}
                    focusChannel={openId === clock.id && focusChannel}
                    chips={data.chips}
                    usedZones={usedZones}
                    voiceChannels={data.voice_channels}
                    channelsAvailable={data.channels_available}
                    onOpen={(open) => openRow(open ? clock.id : null)}
                    onDirty={rowDirty}
                    onSaved={(saved, nextUpdate) =>
                      setData(
                        (current) =>
                          current && {
                            ...current,
                            next_update: nextUpdate,
                            clocks: current.clocks.map((row) =>
                              row.id === saved.id ? { ...row, ...saved } : row,
                            ),
                          },
                      )
                    }
                    onReload={(message) => void load(message)}
                  />
                ))}
              </div>
            )}
            {data.clocks.length > 0 && (
              <details className="world-clock-phone-preview">
                <summary>Preview in Discord</summary>
                <DiscordPreview
                  clocks={data.clocks}
                  categoryName={categoryName}
                />
              </details>
            )}
            {data.runs.length > 0 && <RecentUpdates runs={data.runs} />}
          </div>
          {data.clocks.length > 0 && (
            <aside className="world-clock-aside">
              <p className="world-clock-aside-title">In Discord</p>
              <DiscordPreview
                clocks={data.clocks}
                categoryName={categoryName}
              />
              <p className="world-clock-help">
                Names update every {data.settings.interval_minutes} minutes.
              </p>
            </aside>
          )}
        </div>
      </div>
      <div hidden={section !== "settings"}>
        <ClockSettingsPanel
          settings={data.settings}
          categories={data.categories}
          channelsAvailable={data.channels_available}
          onSaved={(settings) =>
            setData((current) => current && { ...current, settings })
          }
          onConflict={(message) => void load(message)}
          onDirty={settingsDirty}
        />
      </div>
      {adding && (
        <AddClockDialog
          chips={data.chips}
          usedZones={usedZones}
          voiceChannels={data.voice_channels}
          categories={data.categories}
          settings={data.settings}
          channelsAvailable={data.channels_available}
          onDirty={addDirty}
          onClose={() => {
            addDirty(false);
            setAdding(false);
          }}
          onAdded={(message) => {
            addDirty(false);
            setAdding(false);
            void load(message);
          }}
        />
      )}
    </section>
  );
}

function Header() {
  return (
    <CwlPageHeader
      title={<h1 id="world-clocks-title">World clocks</h1>}
      description="Voice channel names that show local times."
    />
  );
}
