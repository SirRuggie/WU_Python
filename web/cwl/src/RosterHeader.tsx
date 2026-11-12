import { monthSeasons, seasonMonthLabel } from "./seasonLabels";
import CwlPageHeader from "./CwlPageHeader";
import { useEffect, useRef, useState } from "react";
import { RefreshCw, WandSparkles } from "lucide-react";
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

type Props = {
  onFillSignupSpot: (item: SignupChange) => boolean;
  onSignupDetails: (tag: string) => boolean;
  signupControls?: import("react").ReactNode;
  signupAttention?: boolean;
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
  refreshInToolbar?: boolean;
  viewLabel?: string;
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
  refreshInToolbar = false,
  viewLabel = "Accounts & signups",
  activeStatuses = [],
  onSeasonChange,
  onRefresh,
  onAutoPlace,
  onFinalize,
  onStatusFilter,
  onAccessError,
  signupControls,
  signupAttention = false,
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
  const summary = useRef<HTMLDetailsElement>(null);
  const workingFades = useHorizontalFades<HTMLDivElement>();
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
  const poolMissingWeight = accounts.filter(
    (account) => account.effective_weight === null,
  ).length;
  const publicationStatus =
    publication?.seasonId === seasonId ? publication.status : null;
  const selectedSeason = seasons.find(
    (season) => String(season.id) === seasonId,
  );
  const selectedSeasonLabel = selectedSeason
    ? seasonMonthLabel(selectedSeason)
    : undefined;
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

  return (
    <header className="roster-header roster-ui" aria-label="Roster overview">
      <CwlPageHeader
        className="roster-header-title-row"
        title={
          <h1 data-roster-heading tabIndex={-1}>
            Build roster
          </h1>
        }
      >
        {!refreshInToolbar && (
          <Button
            icon={RefreshCw}
            label="Refresh roster"
            disabled={uiLocked}
            onClick={onRefresh}
          />
        )}
        <div className="roster-header-season">
          <RosterMenu
            label="Season"
            value={seasonId}
            aria-label={`Season: ${selectedSeasonLabel || "Select a season"}`}
            disabled={navigationDisabled}
            onValueChange={onSeasonChange}
            options={[
              { value: "", label: "Select a season" },
              ...monthSeasons(seasons).map((season) => ({
                value: String(season.id),
                label: seasonMonthLabel(season),
              })),
            ]}
          />
        </div>
      </CwlPageHeader>
      <details ref={summary} className="roster-header-summary">
        <summary>
          <span>
            {roster
              ? `${accounts.length} signups · ${unplaced} unplaced · ${missingWeight} no weight${pool !== "all" && missingWeight !== poolMissingWeight ? " (all pools)" : ""}`
              : "Loading roster…"}
          </span>
          <span className="roster-header-status" role="status">
            {selectedSeasonLabel &&
              `${archived ? "Archived" : seasons.find((season) => String(season.id) === seasonId)?.signup_open ? "Signups open" : "Signups closed"} · `}

            {publicationStatus === "current"
              ? `Published v${publication?.draft?.published?.version}`
              : publicationStatus === "changed"
                ? "Unpublished changes"
                : publicationStatus === "unavailable"
                  ? "Status unavailable"
                  : publicationStatus === "unpublished"
                    ? "Not published"
                    : "Checking publication…"}
            <span
              className="roster-header-view-label"
              style={{ whiteSpace: "nowrap" }}
            >
              {" "}
              · {viewLabel}
            </span>
            <span className="roster-header-details-label">
              {" "}
              · Signup &amp; status
            </span>
          </span>
        </summary>
        <div className="roster-header-summary-content">
          {seasonId &&
            publicationStatus === "current" &&
            publication?.draft && (
              <PublicationAwarenessBanner
                published={publication.draft.published}
                lastPublication={publication.draft.last_publication}
                changed={publication.draft.draft_changed}
                canPublish={canPublish}
                onReview={onFinalize}
                disabled={uiLocked}
              />
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
                <strong>{accounts.length}</strong> signup
                {accounts.length === 1 ? "" : "s"}
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
                {pool !== "all" && missingWeight !== poolMissingWeight
                  ? " (all pools)"
                  : ""}
              </Button>
            </div>
          )}{" "}
        </div>
      </details>
      {signupControls && (
        <div className="roster-header-signups" data-attention={signupAttention}>
          {signupControls}
        </div>
      )}

      {seasonId &&
        publicationStatus !== "current" &&
        (publication?.seasonId === seasonId && publication.draft ? (
          <PublicationAwarenessBanner
            published={publication.draft.published}
            lastPublication={publication.draft.last_publication}
            changed={publication.draft.draft_changed}
            canPublish={canPublish}
            onReview={onFinalize}
            disabled={uiLocked}
          />
        ) : publicationStatus === "unavailable" ? (
          <div className="publication-awareness" role="status">
            <span className="publication-awareness-status">
              Publication status unavailable
            </span>
            <Button
              disabled={uiLocked}
              onClick={() => setPublicationAttempt((value) => value + 1)}
            >
              Retry status
            </Button>
          </div>
        ) : null)}
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
            ⚠{" "}
            {missingCapacityClans.length === 1
              ? `${missingCapacityClans[0].name} has`
              : `${missingCapacityClans.length} clans have`}{" "}
            no clan size set
          </span>
          {onCapacitySettings && (
            <button
              type="button"
              disabled={navigationDisabled}
              onClick={() => onCapacitySettings(missingCapacityClans[0].tag)}
            >
              Set in Hosting clans ›
            </button>
          )}
        </div>
      )}
    </header>
  );
}
