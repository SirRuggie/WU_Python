import RefreshControl, { useRefreshTime } from "./RefreshControl";
import EmptyState from "./EmptyState";
import DashboardLink from "./DashboardLink";
import LoadError from "./LoadError";
import { visibleRefresh } from "./visibleRefresh";
import CwlPageHeader from "./CwlPageHeader";
import "./rosterUi/tokens.css";
import "./MemberRefreshNote.css";
import { memberSignupsOpen } from "./memberSeason";
import {
  mergeAssignmentLocations,
  assignmentArrivalLabel,
} from "./memberAssignmentLocations";
import type { LocationRecords } from "./comparisonLocation";
import JoiningInstructionsCard from "./JoiningInstructionsCard";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, type Season } from "./api";
import { groupAssignments } from "./assignmentGroups";
import {
  clanDeepLink,
  memberPlacementStatus,
  type MyAssignments,
} from "./publication";
import "./MemberAssignments.css";
import { memberDateLines } from "./MemberSignupStatus";

type Props = {
  steps?: ReactNode;
  seasonId: string;
  seasons: Season[];
  onSignup?: () => void;
  onChange?: () => void;
};
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Assignments could not be loaded. Try again.";

export default function MemberAssignments({
  steps,
  seasonId,
  seasons,
  onSignup,
  onChange,
}: Props) {
  const [data, setData] = useState<MyAssignments | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [paused, setPaused] = useState(false);
  const updatedAt = useRefreshTime(loading, !!data, error);
  const locations = useRef<LocationRecords>({});
  const inFlight = useRef(false);
  const requestId = useRef(0);
  const activeSeason = useRef(seasonId);
  activeSeason.current = seasonId;
  const load = useCallback(
    async (_background = false) => {
      if (!seasonId || inFlight.current) return;
      inFlight.current = true;
      const sid = seasonId;
      const id = ++requestId.current;
      setLoading(true);
      setError("");
      try {
        const result = await api<MyAssignments>(
          `/seasons/${encodeURIComponent(sid)}/my-assignments`,
        );
        if (id === requestId.current && activeSeason.current === sid) {
          const next = mergeAssignmentLocations(locations.current, result);
          locations.current = next.records;
          setData(next.data);
        }
      } catch (cause) {
        if (id === requestId.current && activeSeason.current === sid) {
          if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
            setData(null);
            locations.current = {};
          }
          setError(errorText(cause));
        }
      } finally {
        if (id === requestId.current) inFlight.current = false;
        if (id === requestId.current && activeSeason.current === sid)
          setLoading(false);
      }
    },
    [seasonId],
  );
  useEffect(() => {
    requestId.current += 1;
    setData(null);
    locations.current = {};
    setError("");
    if (seasonId) void load();
    return () => {
      requestId.current += 1;
    };
  }, [seasonId, load]);
  useEffect(() => {
    if (paused) return;
    return visibleRefresh(() => load(true), 30000, { focus: true });
  }, [load, paused]);
  const season = seasons.find((item) => String(item.id) === seasonId);
  const groups = groupAssignments(data?.accounts || []);
  const awaiting = groups.find((group) => !group.clanTag)?.accounts.length || 0;
  const assignedGroups = groups.filter((group) => group.clanTag).length;
  const waitingList = (
    <ul>
      {groups
        .filter((group) => !group.clanTag)
        .flatMap((group) => group.accounts)
        .map((account) => (
          <li key={account.tag}>
            {account.player_name} · {account.pool === "main" ? "Main" : "Lazy"}
          </li>
        ))}
    </ul>
  );
  return (
    <div className="member-assignments roster-ui">
      <CwlPageHeader
        title={<h1>My clan assignments</h1>}
        description="Your accounts, grouped by assigned clan."
      >
        <RefreshControl
          updatedAt={updatedAt}
          busy={loading}
          onRefresh={load}
          intervalSeconds={30}
          paused={paused}
          onPauseChange={(next) => {
            setPaused(next);
            if (!next) void load();
          }}
          showRefresh={!error}
        />
        <p className="cwl-page-header-season" aria-label="Season">
          {seasons.find((item) => String(item.id) === seasonId)?.label ||
            "No CWL season available"}
        </p>
      </CwlPageHeader>
      {steps}
      {!seasonId && (
        <EmptyState
          title="No CWL season available"
          line="Staff will make your CWL season available here."
        />
      )}
      <LoadError
        message={data && error ? "Could not refresh." : error}
        note={data ? "Showing the last update." : undefined}
        onRetry={load}
        busy={loading}
        retryContext="clan assignments"
      />
      {loading && <p role="status">Loading current assignments…</p>}
      {data && (
        <>
          {data.published?.joining_instructions && (
            <JoiningInstructionsCard
              text={data.published.joining_instructions}
            />
          )}
          {!data.accounts.length && (
            <div className="member-signup-summary">
              <section className="member-signup-empty">
                <h2>You have not signed up any accounts yet.</h2>
                {memberSignupsOpen(season) ? (
                  onSignup ? (
                    <DashboardLink href="/signup" onNavigate={onSignup}>
                      Sign up for CWL ›
                    </DashboardLink>
                  ) : (
                    <a href="/signup">Sign up for CWL ›</a>
                  )
                ) : (
                  <p>Signups are closed. Ask staff for help.</p>
                )}
              </section>
            </div>
          )}
          {data.accounts.length > 0 && assignedGroups === 0 && (
            <section className="card member-unpublished-status">
              <h2>Waiting for a clan</h2>
              {memberDateLines(season, !!data.published, Date.now())
                .slice(-1)
                .map((line) => (
                  <p key={line}>{line}</p>
                ))}
              <p>
                {data.accounts.length} account
                {data.accounts.length === 1 ? "" : "s"} signed up ·{" "}
                <a
                  href="/my-signups"
                  onClick={(event) => {
                    if (onChange) {
                      event.preventDefault();
                      onChange();
                    }
                  }}
                >
                  My signups ›
                </a>
              </p>
              {waitingList}
            </section>
          )}
          {assignedGroups > 0 && (
            <div className="card member-compact-status">
              <div className="member-status-line">
                <div>
                  <strong>
                    Clan assignments
                    {memberPlacementStatus(data) === "provisional"
                      ? " · May change"
                      : ""}
                  </strong>
                </div>
              </div>
            </div>
          )}
          {awaiting > 0 && assignedGroups > 0 && (
            <section className="card">
              <h2>Waiting for a clan</h2>
              {waitingList}
            </section>
          )}
          {assignedGroups > 0 ? (
            <>
              <p className="member-assignment-count">
                {data.accounts.length} account
                {data.accounts.length === 1 ? "" : "s"} · {assignedGroups}{" "}
                hosting clan{assignedGroups === 1 ? "" : "s"}
                {awaiting ? ` · ${awaiting} waiting for a clan` : ""}
              </p>
              <p>✅ = in the right clan</p>
              <div className="member-clan-list">
                {groups
                  .filter((group) => group.clanTag)
                  .map((group, index) => (
                    <section
                      className={`card member-clan-card ${group.clanTag ? "" : "member-awaiting-card"}`}
                      id={`member-clan-${index}`}
                      key={group.key}
                    >
                      <div className="member-clan-head">
                        <div>
                          <h2>
                            {group.clanName}
                            {group.clanTag &&
                            memberPlacementStatus(data) === "provisional"
                              ? " · May change"
                              : ""}
                          </h2>
                          <small>
                            {group.clanTag
                              ? `${group.clanTag} · ${assignmentArrivalLabel(group.accounts)}`
                              : `${group.accounts.length} account${group.accounts.length === 1 ? "" : "s"} waiting for a clan`}
                          </small>
                        </div>
                        {group.clanTag && (
                          <a
                            className="button member-open-clan"
                            href={clanDeepLink(group.clanTag)}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Open ${group.clanName} in Clash of Clans`}
                          >
                            <span>Open Clan</span>
                            <svg
                              className="member-open-arrow"
                              width="20"
                              height="20"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              aria-hidden="true"
                              focusable="false"
                            >
                              <path d="M7 17 17 7M7 7h10v10" />
                            </svg>
                          </a>
                        )}
                      </div>
                      {!group.clanTag && (
                        <p className="member-awaiting-note">
                          Signed up · Waiting for a clan.
                        </p>
                      )}
                      <div className="member-clan-rows">
                        {group.accounts.map((account) => (
                          <div className="member-clan-row" key={account.tag}>
                            <div>
                              <strong>
                                {account.player_name}
                                {account.arrival_status === "arrived" && (
                                  <span role="img" aria-label="In clan">
                                    {" "}
                                    ✅
                                  </span>
                                )}
                              </strong>
                              <small>{account.tag}</small>
                              {account.arrival_status === "missing" && (
                                <small>Not in clan yet</small>
                              )}
                            </div>
                            <span>
                              TH {account.town_hall ?? "—"} ·{" "}
                              {account.pool === "main" ? "Main" : "Lazy"}
                            </span>
                          </div>
                        ))}
                      </div>
                    </section>
                  ))}
              </div>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
