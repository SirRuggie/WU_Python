import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, RefreshCw, WandSparkles } from "lucide-react";
import { api, ApiError, type Pool, type Season } from "./api";
import { draftPublicationStatus, type PublicationDraft } from "./publication";
import type { RosterSnapshot } from "./roster";
import RosterMenu from "./rosterUi/Menu";
import { Button } from "./rosterUi/primitives";
import "./RosterHeader.css";
import SignupActivity from "./SignupActivity";
import type { SignupChange } from "./signupActivityModel";
import PublicationAwarenessBanner from "./PublicationAwarenessBanner";
import { useHorizontalFades } from "./useHorizontalFades";
import "./horizontalFades.css";

type StatusFilter = "all" | "unassigned" | "missing_weight";

const monthNames = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function compactSeasonLabel(label: string): string {
  const match = /^(\S+)\s+(\d{4})$/.exec(label.trim());
  if (!match) return label;
  const month = monthNames.find(
    (name) => name.toLowerCase() === match[1].toLowerCase(),
  );
  return month ? `${month.slice(0, 3)} ${match[2]}` : label;
}

type Props = {
  onFillSignupSpot: (item: SignupChange) => boolean;
  onSignupDetails: (tag: string) => boolean;
  signupControls?: import("react").ReactNode;
  seasonId: string;
  seasons: Season[];
  roster: RosterSnapshot | null;
  pool: Pool | "all";
  canRoster: boolean;
  canSignups: boolean;
  canPublish: boolean;
  uiLocked: boolean;
  navigationDisabled?: boolean;
  archived: boolean;
  refreshKey?: number;
  activeStatuses?: readonly string[];
  onSeasonChange: (id: string) => void;
  onRefresh: () => void;
  onAutoPlace: (trigger: HTMLElement) => void;
  onFinalize?: () => void;
  onStatusFilter: (status: StatusFilter) => void;
  onAccessError: (error: ApiError) => void;
  onPublication?: (draft: PublicationDraft) => void;
  onCapacitySettings?: (tag: string) => void;
};

export default function RosterHeader({
  seasonId,
  seasons,
  roster,
  pool,
  canRoster,
  canSignups,
  canPublish,
  uiLocked,
  navigationDisabled = uiLocked,
  archived,
  refreshKey = 0,
  activeStatuses = [],
  onSeasonChange,
  onRefresh,
  onAutoPlace,
  onFinalize,
  onStatusFilter,
  onAccessError,
  signupControls,
  onFillSignupSpot,
  onSignupDetails,
  onPublication,
  onCapacitySettings,
}: Props) {
  const [publication, setPublication] = useState<{
    seasonId: string;
    status: ReturnType<typeof draftPublicationStatus> | "unavailable";
    publishedAt: string | null;
    draft?: PublicationDraft;
  } | null>(null);
  const [publicationAttempt, setPublicationAttempt] = useState(0);
  const actions = useRef<HTMLDetailsElement>(null);
  const workingFades = useHorizontalFades<HTMLDivElement>();
  const actionsTrigger = useRef<HTMLElement>(null);
  const request = useRef(0);
  const onAccessErrorRef = useRef(onAccessError);
  onAccessErrorRef.current = onAccessError;
  const publicationCallback = useRef(onPublication);
  publicationCallback.current = onPublication;

  useEffect(() => {
    if (!seasonId || (!canRoster && !canSignups && !canPublish)) {
      setPublication(null);
      return;
    }
    const turn = ++request.current;
    let active = true;
    // Retain this season’s last status until the replacement read completes.
    void api<PublicationDraft>(
      `/seasons/${encodeURIComponent(seasonId)}/publication`,
    )
      .then((draft) => {
        if (!active || turn !== request.current) return;
        setPublication({
          seasonId,
          status: draftPublicationStatus(draft),
          publishedAt: draft.published?.published_at ?? null,
          draft,
        });
        publicationCallback.current?.(draft);
      })
      .catch((error) => {
        if (!active || turn !== request.current) return;
        setPublication({ seasonId, status: "unavailable", publishedAt: null });
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        )
          onAccessErrorRef.current(error);
      });
    return () => {
      active = false;
      request.current++;
    };
  }, [
    seasonId,
    roster?.revision,
    refreshKey,
    publicationAttempt,
    canRoster,
    canSignups,
    canPublish,
  ]);

  const accounts =
    roster?.accounts.filter(
      (account) => pool === "all" || account.pool === pool,
    ) ?? [];
  const allAccounts = roster?.accounts ?? [];
  const assigned = accounts.filter(
    (account) => account.assigned_clan_tag !== null,
  ).length;
  const unplaced = accounts.length - assigned;
  const missingWeight = allAccounts.filter(
    (account) => account.effective_weight === null,
  ).length;
  const publicationStatus =
    publication?.seasonId === seasonId ? publication.status : null;
  const selectedSeasonLabel = seasons.find(
    (season) => String(season.id) === seasonId,
  )?.label;
  const canAutoPlace =
    canRoster &&
    !archived &&
    unplaced > 0 &&
    !!roster?.clans.some((clan) => !clan.archived);
  const assignedClanTags = new Set(
    allAccounts.map((account) => account.assigned_clan_tag).filter(Boolean),
  );
  const missingCapacityClans =
    roster?.clans.filter(
      (clan) =>
        !clan.archived &&
        clan.pool &&
        assignedClanTags.has(clan.tag) &&
        clan.capacity !== 15 &&
        clan.capacity !== 30,
    ) ?? [];
  useEffect(() => {
    if (uiLocked) actions.current?.removeAttribute("open");
  }, [uiLocked]);

  return (
    <header className="roster-header roster-ui" aria-label="Roster overview">
      <div className="roster-header-title-row">
        <div className="roster-header-title">
          <p className="eyebrow">Staff roster</p>
          <h1>Build roster</h1>
        </div>
        <div className="roster-header-title-actions">
          {roster && (
            <details
              ref={actions}
              className="roster-header-more"
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  actions.current?.removeAttribute("open");
                  actionsTrigger.current?.focus();
                }
              }}
            >
              <summary
                ref={actionsTrigger}
                aria-label="More roster actions"
                aria-disabled={uiLocked}
                onClick={(event) => {
                  if (uiLocked) event.preventDefault();
                }}
                onKeyDown={(event) => {
                  if (uiLocked && (event.key === "Enter" || event.key === " "))
                    event.preventDefault();
                }}
              >
                <MoreHorizontal aria-hidden="true" />
              </summary>
              <div className="roster-header-actions">
                <Button
                  icon={RefreshCw}
                  disabled={uiLocked}
                  onClick={() => {
                    actions.current?.removeAttribute("open");
                    onRefresh();
                  }}
                >
                  Refresh roster
                </Button>
                {canAutoPlace && (
                  <Button
                    icon={WandSparkles}
                    disabled={uiLocked}
                    onClick={() => {
                      actions.current?.removeAttribute("open");
                      if (actionsTrigger.current)
                        onAutoPlace(actionsTrigger.current);
                    }}
                  >
                    Auto-place unassigned
                  </Button>
                )}
              </div>
            </details>
          )}
        </div>
      </div>
      <div className="roster-header-publication" role="status">
        <RosterMenu
          label="Season"
          value={seasonId}
          aria-label={`Season: ${selectedSeasonLabel || "Select a season"}`}
          disabled={navigationDisabled}
          onValueChange={onSeasonChange}
          options={[
            { value: "", label: "Select a season" },
            ...seasons.map((season) => ({
              value: String(season.id),
              label: season.label,
            })),
          ]}
        />
        <span className="roster-header-season-short" aria-hidden="true">
          {selectedSeasonLabel
            ? compactSeasonLabel(selectedSeasonLabel)
            : "Season"}
        </span>
        {publicationStatus === "unavailable" && (
          <Button onClick={() => setPublicationAttempt((value) => value + 1)}>
            Retry status
          </Button>
        )}
      </div>
      {signupControls && (
        <div className="roster-header-signups">{signupControls}</div>
      )}
      {seasonId &&
        (publication?.seasonId === seasonId && publication.draft ? (
          <PublicationAwarenessBanner
            published={publication.draft.published}
            lastPublication={publication.draft.last_publication}
            changed={publication.draft.draft_changed}
            canPublish={canPublish}
            onReview={onFinalize}
            disabled={uiLocked}
          />
        ) : (
          <div className="publication-awareness" role="status">
            {publicationStatus === "unavailable"
              ? "Publication status unavailable"
              : "Checking publication…"}
          </div>
        ))}
      {seasonId && canSignups && (
        <SignupActivity
          key={seasonId}
          seasonId={seasonId}
          roster={roster}
          publishedVersion={
            publication?.seasonId === seasonId
              ? publication.draft?.published?.version
              : undefined
          }
          disabled={uiLocked}
          canCompare={canRoster}
          onFill={onFillSignupSpot}
          onDetails={onSignupDetails}
        />
      )}
      {canRoster && missingCapacityClans.length > 0 && (
        <div className="roster-capacity-alert">
          <span>
            ⚠ {missingCapacityClans.length === 1
              ? `${missingCapacityClans[0].name} has`
              : `${missingCapacityClans.length} clans have`} no capacity set
          </span>
          {onCapacitySettings && (
            <button
              type="button"
              disabled={navigationDisabled}
              onClick={() => onCapacitySettings(missingCapacityClans[0].tag)}
            >
              Set in Clan settings ›
            </button>
          )}
        </div>
      )}
      {roster && (
        <div
          ref={workingFades.ref}
          className="roster-header-working has-horizontal-fades"
          data-fade-left={workingFades.left}
          data-fade-right={workingFades.right}
          aria-label="Working roster counts"
        >
          <Button onClick={() => onStatusFilter("all")} disabled={uiLocked}>
            <strong>{accounts.length}</strong> signed
          </Button>
          <div className="roster-header-unplaced">
            <Button
              aria-pressed={activeStatuses.includes("unassigned")}
              onClick={() => onStatusFilter("unassigned")}
              disabled={uiLocked}
            >
              <strong>{unplaced}</strong> unplaced
            </Button>
            {canAutoPlace && (
              <Button
                icon={WandSparkles}
                disabled={uiLocked}
                onClick={(event) => onAutoPlace(event.currentTarget)}
              >
                Auto-place
              </Button>
            )}
          </div>
          <Button
            aria-pressed={activeStatuses.includes("missing_weight")}
            onClick={() => onStatusFilter("missing_weight")}
            disabled={uiLocked}
          >
            <strong>{missingWeight}</strong> no weight
            {pool === "all" ? "" : " (all pools)"}
          </Button>
        </div>
      )}
    </header>
  );
}
