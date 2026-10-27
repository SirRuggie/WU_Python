import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, RefreshCw, WandSparkles } from "lucide-react";
import { api, ApiError, type Pool, type Season } from "./api";
import { draftPublicationStatus, type PublicationDraft } from "./publication";
import type { RosterSnapshot } from "./roster";
import RosterMenu from "./rosterUi/Menu";
import { Button, StatusPill } from "./rosterUi/primitives";
import "./RosterHeader.css";

type StatusFilter = "all" | "unassigned" | "missing_weight";

type Props = {
  seasonId: string;
  seasons: Season[];
  roster: RosterSnapshot | null;
  pool: Pool | "all";
  canRoster: boolean;
  canSignups: boolean;
  canPublish: boolean;
  uiLocked: boolean;
  archived: boolean;
  refreshKey?: number;
  onSeasonChange: (id: string) => void;
  onRefresh: () => void;
  onAutoPlace: (trigger: HTMLElement) => void;
  onFinalize?: () => void;
  onStatusFilter: (status: StatusFilter) => void;
  onAccessError: (error: ApiError) => void;
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
  archived,
  refreshKey = 0,
  onSeasonChange,
  onRefresh,
  onAutoPlace,
  onFinalize,
  onStatusFilter,
  onAccessError,
}: Props) {
  const [publication, setPublication] = useState<{
    seasonId: string;
    status: ReturnType<typeof draftPublicationStatus> | "unavailable";
    publishedAt: string | null;
  } | null>(null);
  const [publicationAttempt, setPublicationAttempt] = useState(0);
  const actions = useRef<HTMLDetailsElement>(null);
  const actionsTrigger = useRef<HTMLElement>(null);
  const request = useRef(0);
  const onAccessErrorRef = useRef(onAccessError);
  onAccessErrorRef.current = onAccessError;

  useEffect(() => {
    if (!seasonId || (!canRoster && !canSignups && !canPublish)) {
      setPublication(null);
      return;
    }
    const turn = ++request.current;
    let active = true;
    setPublication(null);
    void api<PublicationDraft>(
      `/seasons/${encodeURIComponent(seasonId)}/publication`,
    )
      .then((draft) => {
        if (!active || turn !== request.current) return;
        setPublication({
          seasonId,
          status: draftPublicationStatus(draft),
          publishedAt: draft.published?.published_at ?? null,
        });
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
  const publicationLabel =
    publicationStatus === "unpublished"
      ? "Draft · not published"
      : publicationStatus === "changed"
        ? "Published · Unpublished changes"
        : publicationStatus === "current"
          ? "Published ✓"
          : publicationStatus === "unavailable"
            ? "Publication status unavailable"
            : "Checking publication…";
  const publicationTone =
    publicationStatus === "current"
      ? "success"
      : publicationStatus === "changed" || publicationStatus === "unavailable"
        ? "warning"
        : "neutral";
  const canAutoPlace =
    canRoster &&
    !archived &&
    unplaced > 0 &&
    !!roster?.clans.some((clan) => !clan.archived);
  useEffect(() => {
    if (uiLocked) actions.current?.removeAttribute("open");
  }, [uiLocked]);

  return (
    <header className="roster-header roster-ui" aria-label="Roster overview">
      <div className="roster-header-title-row">
        <div className="roster-header-title">
          <p className="eyebrow">Staff roster</p>
          <h1>CWL roster &amp; signups</h1>
        </div>
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={uiLocked}
          onValueChange={onSeasonChange}
          options={[
            { value: "", label: "Select a season" },
            ...seasons.map((season) => ({
              value: String(season.id),
              label: season.label,
            })),
          ]}
        />
      </div>
      {seasonId && (
        <div className="roster-header-publication" role="status">
          <StatusPill tone={publicationTone}>{publicationLabel}</StatusPill>
          {publicationStatus === "unavailable" && (
            <Button onClick={() => setPublicationAttempt((value) => value + 1)}>
              Retry status
            </Button>
          )}
          {canPublish && onFinalize && publicationStatus !== "current" && (
            <Button
              disabled={uiLocked || !roster || archived}
              onClick={onFinalize}
            >
              Finalize →
            </Button>
          )}
        </div>
      )}
      {roster && (
        <div
          className="roster-header-working"
          aria-label="Working roster counts"
        >
          <Button onClick={() => onStatusFilter("all")} disabled={uiLocked}>
            <strong>{accounts.length}</strong> signed
          </Button>
          <div className="roster-header-unplaced">
            <Button
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
            onClick={() => onStatusFilter("missing_weight")}
            disabled={uiLocked}
          >
            <strong>{missingWeight}</strong> no weight · all
          </Button>
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
        </div>
      )}
    </header>
  );
}
