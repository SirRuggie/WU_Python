import { useEffect, useId, useRef, useState } from "react";
import type { Pool } from "../api";
import type { AnnouncementChannel } from "../announcements";
import type { Campaign, Occurrence } from "../reminderCampaign";
import { dashboardPath } from "../dashboardHistory";
import {
  backOutOfPanelEntry,
  installPanelBackHandler,
  isTopActionPanel,
  panelHistoryState,
  registerActionPanel,
} from "../actionPanelHistory";
import ActionPanel from "../ActionPanel";
import SectionTabs from "../SectionTabs";
import ListToolbar from "../rosterUi/ListToolbar";
import FiltersTrigger from "../rosterUi/FiltersTrigger";
import SortTrigger from "../rosterUi/SortTrigger";
import { RefreshButton } from "../RefreshControl";
import useCompactPreview from "../useCompactPreview";
import ReminderMessageRow from "./ReminderMessageRow";
import ReminderMessageEditor from "./ReminderMessageEditor";
import type { ReminderLookup } from "./reminderErrors";
import {
  initialEditorPool,
  reminderRows,
  visibleReminderRows,
  type ReminderListFilters,
  type ReminderListSort,
  type ReminderPoolScope,
} from "./reminderList";

type Lookup<T extends { id: string }> = ReminderLookup<T> & {
  retry: () => void;
};

export default function ReminderMessagesTab({
  draft,
  saved,
  schedule,
  activated,
  seasonId,
  active,
  busy,
  disabled,
  channelLookup,
  roleLookup,
  edit,
  previewDeadline,
  onRefresh,
}: {
  draft: Campaign;
  saved: Campaign;
  schedule: Occurrence[];
  activated: boolean;
  seasonId: string;
  active: boolean;
  busy: boolean;
  disabled: boolean;
  channelLookup: Lookup<AnnouncementChannel>;
  roleLookup: Lookup<{ id: string; name: string }>;
  edit: (next: Campaign) => void;
  previewDeadline?: string;
  onRefresh: () => void;
}) {
  const [scope, setScope] = useState<ReminderPoolScope>("all");
  const [filters, setFilters] = useState<ReminderListFilters>({
    hasError: false,
    off: false,
  });
  const [sort, setSort] = useState<ReminderListSort>("send_time");
  const [panel, setPanel] = useState<"filters" | "sort" | null>(null);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pool, setPool] = useState<Pool>("main");
  const [editorOpen, setEditorOpen] = useState(false);
  const compact = useCompactPreview(1099);
  const lookups = { channels: channelLookup, roles: roleLookup };
  const rows = reminderRows(draft, scope, lookups, schedule, activated);
  const visible = visibleReminderRows(rows, filters, sort);
  const selectedId =
    selected && draft.messages[selected]
      ? selected
      : !compact
        ? visible[0]?.id
        : undefined;
  const errorCount = rows.filter((row) => row.hasError).length;
  const filterCount = Number(filters.hasError) + Number(filters.off);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const marker = `reminder-editor:${useId()}`;
  const rowButtons = useRef(new Map<string, HTMLButtonElement>());
  const backButton = useRef<HTMLButtonElement>(null);
  const selectRow = (id: string) => {
    setSelected(id);
    setPool(initialEditorPool(draft, id, scope, lookups));
    setEditorOpen(true);
  };
  const selectionRef = useRef(selectedId);
  selectionRef.current = selectedId;
  const closeEditor = () => {
    if (busyRef.current) return;
    setEditorOpen(false);
    window.requestAnimationFrame(() => {
      if (selectedId) rowButtons.current.get(selectedId)?.focus();
    });
  };
  useEffect(() => {
    if (!compact || !active || !editorOpen) return;
    const unregister = registerActionPanel(marker);
    const panelState = panelHistoryState(history.state, marker);
    history.pushState(panelState, "", location.href);
    backButton.current?.focus({ preventScroll: true });
    const remove = installPanelBackHandler({
      windowPort: window,
      historyPort: history,
      marker,
      panelState,
      isBusy: () => busyRef.current,
      isTop: () => isTopActionPanel(marker),
      close: () => {
        setEditorOpen(false);
        window.requestAnimationFrame(() => {
          if (selectionRef.current)
            rowButtons.current.get(selectionRef.current)?.focus();
        });
      },
    });
    return () => {
      remove();
      backOutOfPanelEntry({ windowPort: window, historyPort: history, marker });
      unregister();
    };
  }, [compact, active, editorOpen, marker]);
  const currentIndex = visible.findIndex((row) => row.id === selectedId);
  const move = (offset: number) => {
    const row = visible[currentIndex + offset];
    if (row) selectRow(row.id);
  };
  return (
    <div
      className={`reminder-message-layout${compact && editorOpen ? " is-editing" : ""}`}
    >
      <div className="reminder-list-pane" hidden={compact && editorOpen}>
        <ListToolbar
          className="reminder-list-toolbar"
          sortBeforeFilters={false}
          scope={
            <SectionTabs
              mode="segmented"
              label="Message pool"
              value={scope}
              disabled={busy}
              items={[
                {
                  id: "all",
                  label: (
                    <>
                      All
                      <span className="roster-pool-label-extra"> messages</span>
                    </>
                  ),
                },
                {
                  id: "main",
                  label: (
                    <>
                      Main<span className="roster-pool-label-extra"> CWL</span>
                    </>
                  ),
                },
                {
                  id: "lazy",
                  label: (
                    <>
                      Lazy<span className="roster-pool-label-extra"> CWL</span>
                    </>
                  ),
                },
              ]}
              onChange={(value) => {
                setScope(value);
                if (value !== "all") setPool(value);
              }}
            />
          }
          filters={
            <FiltersTrigger
              count={filterCount}
              open={panel === "filters"}
              disabled={busy}
              onClick={(event) => {
                setTrigger(event.currentTarget);
                setPanel("filters");
              }}
            />
          }
          sort={
            <SortTrigger
              label={sort === "name" ? "Name" : "Send time"}
              disabled={busy}
              onClick={(event) => {
                setTrigger(event.currentTarget);
                setPanel("sort");
              }}
            />
          }
          actions={
            <RefreshButton
              busy={busy}
              onRefresh={onRefresh}
              label="Refresh reminders"
            />
          }
        />
        {(channelLookup.error ||
          roleLookup.error ||
          channelLookup.loading ||
          roleLookup.loading) && (
          <p className="reminder-names-unavailable">Names unavailable</p>
        )}
        <p className="reminder-timezone">
          Times in {Intl.DateTimeFormat().resolvedOptions().timeZone}
        </p>
        {errorCount > 0 && (
          <p className="reminder-error-line" role="status">
            {errorCount === 1
              ? "1 message has an error"
              : `${errorCount} messages have an error`}
          </p>
        )}
        <p className="reminder-list-count">
          {filterCount
            ? `${visible.length} of ${rows.length} messages · ${[filters.hasError && "Has error", filters.off && "Off"].filter(Boolean).join(" · ")}`
            : `${rows.length} messages`}
        </p>
        <div className="reminder-message-list">
          {visible.map((row) => (
            <ReminderMessageRow
              key={row.id}
              campaign={draft}
              id={row.id}
              scope={scope}
              next={row.next}
              activated={activated}
              channels={channelLookup.items}
              lookups={lookups}
              selected={row.id === selectedId}
              busy={busy}
              unsaved={
                JSON.stringify(draft.messages[row.id]) !==
                JSON.stringify(saved.messages[row.id])
              }
              onOpen={() => selectRow(row.id)}
              rowRef={(node) => {
                if (node) rowButtons.current.set(row.id, node);
                else rowButtons.current.delete(row.id);
              }}
            />
          ))}
        </div>
        {!rows.length ? (
          <p>No messages set up for this month.</p>
        ) : !visible.length ? (
          <div className="reminder-list-empty">
            <p>No messages match these filters.</p>
            <button
              type="button"
              onClick={() => setFilters({ hasError: false, off: false })}
            >
              Clear filters
            </button>
          </div>
        ) : null}
        <p className="reminder-announcements">
          Roster posts are on{" "}
          <a
            href={dashboardPath({
              view: "publication",
              step: "announce",
              season: seasonId,
            })}
          >
            Announcements ›
          </a>
        </p>
      </div>
      {selectedId && (!compact || editorOpen) && (
        <div className="reminder-editor-pane">
          {compact && (
            <nav
              className="reminder-editor-navigation"
              aria-label="Message navigation"
            >
              <button
                ref={backButton}
                type="button"
                onClick={closeEditor}
                disabled={busy}
              >
                Back to messages
              </button>
              <button
                type="button"
                disabled={busy || currentIndex <= 0}
                onClick={() => move(-1)}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={
                  busy || currentIndex < 0 || currentIndex >= visible.length - 1
                }
                onClick={() => move(1)}
              >
                Next
              </button>
            </nav>
          )}
          <ReminderMessageEditor
            draft={draft}
            messageId={selectedId}
            pool={
              selected
                ? pool
                : initialEditorPool(draft, selectedId, scope, lookups)
            }
            setPool={(value) => {
              setSelected(selectedId);
              setPool(value);
            }}
            showPoolSwitch={scope === "all"}
            disabled={disabled}
            compact={compact}
            channelLookup={channelLookup}
            roleLookup={roleLookup}
            edit={edit}
            previewDeadline={previewDeadline}
          />
        </div>
      )}
      {panel && (
        <ActionPanel
          title={panel === "filters" ? "Filter messages" : "Sort messages"}
          trigger={trigger}
          onClose={() => setPanel(null)}
          busy={busy}
          footer={
            <button type="button" onClick={() => setPanel(null)}>
              Done
            </button>
          }
        >
          {panel === "filters" ? (
            <>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={filters.hasError}
                  onChange={(event) =>
                    setFilters({ ...filters, hasError: event.target.checked })
                  }
                />
                Has error
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={filters.off}
                  onChange={(event) =>
                    setFilters({ ...filters, off: event.target.checked })
                  }
                />
                Off
              </label>
              <button
                type="button"
                onClick={() => setFilters({ hasError: false, off: false })}
              >
                Clear
              </button>
            </>
          ) : (
            <fieldset>
              <legend>Sort messages</legend>
              {(["send_time", "name"] as const).map((value) => (
                <label className="check-label" key={value}>
                  <input
                    type="radio"
                    name="reminder-sort"
                    value={value}
                    checked={sort === value}
                    onChange={() => setSort(value)}
                  />
                  {value === "name" ? "Name" : "Send time"}
                </label>
              ))}
            </fieldset>
          )}
        </ActionPanel>
      )}
    </div>
  );
}
