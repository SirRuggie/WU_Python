import { useCallback, useEffect, useRef, useState } from "react";
import { useClock } from "../activity/useClock";
import { requestDetailsNavigation } from "../detailsNavigation";
import { useDashboardPermission } from "../DashboardPermissions";
import Standardize from "../memberTimezones/Standardize";
import NicknameRun from "../memberTimezones/NicknameRun";
import { MemberPages } from "../memberTimezones/NicknameReview";
import MemberFilters from "./MemberFilters";
import MemberBulkBar from "./MemberBulkBar";
import MemberRow from "./MemberRow";
import MemberPersonPanel from "./MemberPersonPanel";
import RoleChangeReview from "./RoleChangeReview";
import useMembersDirectory from "./useMembersDirectory";
import useRoleRun from "./useRoleRun";
import {
  emptyFilters,
  filterMembers,
  statusCounts,
  sortMembers,
  type MemberSort,
  type MemberFilters as Filters,
} from "./model";
import {
  confirmedTargets,
  selectPage,
  selectMatching,
  selectionSummary,
  toggleMember,
} from "./selection";
import { membersText as t } from "./strings";
import "../memberTimezones/MemberTimezones.css";
import "./Members.css";
import ActionMenu from "../rosterUi/ActionMenu";
import LoadError from "../LoadError";
import ActionPanel from "../ActionPanel";

type RoleAction = {
  ids: readonly string[];
  operation: "add" | "remove";
  fixedRole?: string;
  guardRoleIds?: readonly string[];
};
export default function MembersPage({
  onDirty,
  initialMember,
  onInitialConsumed,
}: {
  onDirty: (dirty: boolean) => void;
  initialMember?: string | null;
  onInitialConsumed?: () => void;
}) {
  // Reuse the visible-page clock; local times update without directory polling.
  useClock();
  const allowed = useDashboardPermission("member_roles");
  const [filters, setFilters] = useState<Filters>(emptyFilters),
    [sort, setSort] = useState<MemberSort>("name"),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [page, setPage] = useState(0),
    [personId, setPersonId] = useState<string | null>(
      initialMember ||
        new URLSearchParams(location.search).get("account") ||
        new URLSearchParams(location.search).get("member"),
    ),
    [panelDirty, setPanelDirty] = useState(false),
    [nameBusy, setNameBusy] = useState(false),
    [nameOpen, setNameOpen] = useState(false),
    [fixTrigger, setFixTrigger] = useState(0),
    [historyTrigger, setHistoryTrigger] = useState(0),
    [helpTrigger, setHelpTrigger] = useState<HTMLElement | null>(null),
    [fixIds, setFixIds] = useState<readonly string[] | undefined>(),
    [action, setAction] = useState<RoleAction | null>(null),
    [actionError, setActionError] = useState(""),
    [denied, setDenied] = useState(false),
    [lastWasUndo, setLastWasUndo] = useState(false);
  const savedScroll = useRef(0),
    opener = useRef<HTMLElement | null>(null),
    initialConsumed = useRef(false),
    progress = useRef<HTMLElement | null>(null);
  const deny = useCallback(() => {
    setDenied(true);
    setSelected(new Set());
    setPersonId(null);
    setAction(null);
    setPanelDirty(false);
  }, []);
  const directory = useMembersDirectory(deny, allowed && !denied);
  const roles = useRoleRun(
    deny,
    () => void directory.load(),
    allowed && !denied,
  );
  const data = directory.data;
  const rows = data
    ? sortMembers(filterMembers(data.members, filters, selected), sort)
    : [];
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(rows.length / 25) - 1),
  );
  const visible = rows.slice(currentPage * 25, (currentPage + 1) * 25);
  const summary = selectionSummary(selected, visible);
  const unknown =
    !!data &&
    [...selected].some(
      (id) => !data.members.some((member) => member.discord_id === id),
    );
  const person = data?.members.find((member) => member.discord_id === personId);
  const busy = nameBusy || roles.busy || roles.active || !!action;
  const navigationBusy = nameBusy || roles.busy || !!action;
  const filteredIds = new Set(rows.map((member) => member.discord_id));
  const panelDirtyChange = useCallback(
    (value: boolean) => setPanelDirty(value),
    [],
  );
  useEffect(() => {
    onDirty(panelDirty || navigationBusy);
    return () => onDirty(false);
  }, [panelDirty, navigationBusy, onDirty]);
  useEffect(() => {
    if (!allowed) deny();
    else setDenied(false);
  }, [allowed, deny]);
  useEffect(() => {
    if (!personId || !data || initialConsumed.current) return;
    initialConsumed.current = true;
    onInitialConsumed?.();
    if (!person) setActionError(t.roleReviewChanged);
  }, [personId, data, person, onInitialConsumed]);
  useEffect(() => {
    if (
      roles.run &&
      ["queued", "stopping"].includes(roles.run.state) &&
      !person
    ) {
      progress.current?.scrollIntoView({ block: "start" });
      progress.current?.focus({ preventScroll: true });
    }
  }, [roles.run?.run_id]);
  const closePerson = () => {
    setPersonId(null);
    setPanelDirty(false);
    requestAnimationFrame(() => {
      window.scrollTo({ top: savedScroll.current, behavior: "instant" });
      opener.current?.focus({ preventScroll: true });
    });
  };
  const openPerson = (id: string, trigger: HTMLElement) => {
    if (personId === id) return;
    requestDetailsNavigation(() => {
      opener.current = trigger;
      savedScroll.current = window.scrollY;
      setPersonId(id);
      setActionError("");
    });
  };
  function roleAction(operation: "add" | "remove", trigger?: HTMLElement) {
    if (busy || unknown || !data) return;
    try {
      const ids = confirmedTargets(selected, data.members);
      if (!ids.length) return;
      opener.current = trigger || (document.activeElement as HTMLElement);
      setAction({ ids, operation });
      setActionError("");
      setLastWasUndo(false);
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : t.roleUnavailable,
      );
    }
  }
  function personRole(
    id: string,
    operation: "add" | "remove",
    trigger: HTMLElement,
  ) {
    if (busy || !person) return;
    opener.current = trigger;
    setLastWasUndo(false);
    setActionError("");
    setAction({
      ids: Object.freeze([person.discord_id]),
      operation,
      fixedRole: id,
    });
  }
  function fix(ids?: readonly string[]) {
    if (busy) return;
    setFixIds(ids?.length ? Object.freeze([...ids]) : undefined);
    setFixTrigger((value) => value + 1);
    setPersonId(null);
  }
  const receipt =
    roles.run?.state === "done" && roles.run.rows.length === 1
      ? roles.run.rows[0]
      : undefined;
  const undo =
    receipt?.status === "done" &&
    receipt.changed === true &&
    receipt.role_id &&
    receipt.operation &&
    receipt.expected_role_ids &&
    !lastWasUndo &&
    receipt.discord_id === personId
      ? () => {
          if (busy) return;
          const after = new Set(receipt.expected_role_ids);
          if (receipt.operation === "add") after.add(receipt.role_id!);
          else after.delete(receipt.role_id!);
          setLastWasUndo(true);
          setAction({
            ids: Object.freeze([receipt.discord_id]),
            operation: receipt.operation === "add" ? "remove" : "add",
            fixedRole: receipt.role_id,
            guardRoleIds: Object.freeze([...after].sort()),
          });
        }
      : undefined;
  if (!allowed || denied) return <p role="alert">{t.accessChanged}</p>;
  return (
    <section
      aria-label={t.title}
      data-dashboard-focus-fallback
      tabIndex={-1}
      className={`roster-ui members-workspace${person ? " has-panel" : ""}`}
    >
      <header>
        <h1>{t.title}</h1>
      </header>
      {helpTrigger && (
        <ActionPanel
          title={t.nicknameHelp}
          trigger={helpTrigger}
          onClose={() => setHelpTrigger(null)}
        >
          <p>{t.nicknameExplanation}</p>
        </ActionPanel>
      )}
      <LoadError
        message={directory.error}
        onRetry={!data ? () => void directory.load() : undefined}
        busy={directory.loading}
      />
      {!person && (actionError || roles.error) && (
        <p role="alert">{actionError || roles.error}</p>
      )}
      {directory.loading && !data && <p role="status">{t.loading}</p>}
      {data && (
        <>
          <div className="members-actions">
            <button
              type="button"
              disabled={busy || panelDirty || directory.loading}
              aria-busy={directory.loading || undefined}
              onClick={() => void directory.load()}
            >
              {t.refresh}
            </button>
            <button
              type="button"
              disabled={busy || panelDirty || unknown}
              onClick={() => fix(selected.size ? [...selected] : undefined)}
            >
              {t.fixNames}
            </button>
          </div>
          <MemberFilters
            actions={
              <ActionMenu
                name={t.title}
                disabled={busy || panelDirty}
                items={[
                  {
                    id: "past",
                    label: t.pastNames,
                    onAction: () => {
                      setPersonId(null);
                      setHistoryTrigger((value) => value + 1);
                    },
                  },
                  {
                    id: "about",
                    label: t.nicknameHelp,
                    onAction: setHelpTrigger,
                  },
                ]}
              />
            }
            value={filters}
            counts={statusCounts(data.members, filters, selected)}
            roles={data.roles}
            sort={sort}
            onSort={(value) => {
              setSort(value);
              setPage(0);
            }}
            onChange={(next) => {
              setFilters(next);
              setPage(0);
            }}
          />
          <p className="members-range">
            {t.showing(
              rows.length ? currentPage * 25 + 1 : 0,
              Math.min((currentPage + 1) * 25, rows.length),
              rows.length,
            )}
            {directory.loading ? (
              <span role="status"> · Updating member list…</span>
            ) : data.directory_cache?.cached ? (
              <span className="small" title="Refresh for latest">
                {" "}
                · Recent member list
              </span>
            ) : null}
          </p>
          {unknown && <p role="alert">{t.selectedLeft}</p>}
          <MemberBulkBar
            pageSelected={summary.all}
            pagePartial={summary.partial}
            onSelectPage={() =>
              setSelected((old) =>
                summary.all
                  ? new Set(
                      [...old].filter(
                        (id) => !visible.some((row) => row.discord_id === id),
                      ),
                    )
                  : selectPage(old, visible),
              )
            }
            matchingCount={rows.filter((row) => !row.bot).length}
            onSelectMatching={() =>
              setSelected((old) => selectMatching(old, rows))
            }
            count={selected.size}
            hidden={summary.hidden}
            canRoles
            canProfiles
            busy={busy || unknown || panelDirty}
            onShow={() => {
              setFilters({ ...emptyFilters, selectedOnly: true });
              setPage(0);
            }}
            onAdd={() => roleAction("add")}
            onRemove={() => roleAction("remove")}
            onFix={() => fix([...selected])}
            onClear={() => setSelected(new Set())}
          />
          <div className="members-directory-scroll">
            <Standardize
              disabled={roles.active || roles.busy || !!action || panelDirty}
              members={data.members}
              onDenied={deny}
              onBusy={setNameBusy}
              onOpenChange={setNameOpen}
              onImported={() => void directory.load()}
              hideEntry
              hideTools
              externalHistoryTrigger={historyTrigger}
              externalTrigger={fixTrigger}
              selectedIds={fixIds}
              visibleIds={filteredIds}
            />
            {(roles.run || roles.error) && (
              <section ref={progress} tabIndex={-1} aria-label={t.roleProgress}>
                <h2>{t.roleRun}</h2>
                {roles.run && (
                  <details open={roles.active}>
                    <summary>
                      {t.roleRun} · {t.roleState(roles.run.state)}
                    </summary>
                    <NicknameRun
                      run={roles.run}
                      members={data.members}
                      mode="roles"
                      onStop={() => void roles.stop()}
                      disabled={roles.busy}
                      showAttribution
                      visibleIds={filteredIds}
                    />
                  </details>
                )}
                <button
                  disabled={roles.busy}
                  onClick={() => void roles.refresh()}
                >
                  {t.refreshProgress}
                </button>
              </section>
            )}
            {!nameOpen && (
              <div className="members-list">
                {visible.length ? (
                  visible.map((member) => (
                    <MemberRow
                      key={member.discord_id}
                      member={member}
                      selected={selected.has(member.discord_id)}
                      onSelect={() =>
                        setSelected((old) =>
                          toggleMember(old, member.discord_id),
                        )
                      }
                      onOpen={() =>
                        openPerson(
                          member.discord_id,
                          document.activeElement as HTMLElement,
                        )
                      }
                      pending={roles.run?.rows.some(
                        (row) =>
                          row.discord_id === member.discord_id &&
                          ["waiting", "pending", "running"].includes(
                            row.status || "",
                          ),
                      )}
                      error={
                        roles.run?.rows.find(
                          (row) =>
                            row.discord_id === member.discord_id &&
                            ["failed", "uncertain"].includes(row.status || ""),
                        )?.message
                      }
                    />
                  ))
                ) : (
                  <p>{t.empty}</p>
                )}
                <MemberPages
                  page={currentPage}
                  total={rows.length}
                  onChange={setPage}
                />
              </div>
            )}
          </div>
        </>
      )}
      {person && data && (
        <MemberPersonPanel
          member={person}
          data={data}
          busy={busy}
          navigationBusy={navigationBusy}
          roleError={actionError || roles.error}
          roleOutcome={
            action?.fixedRole && action.ids.includes(person.discord_id)
              ? { status: "pending", message: t.roleUpdating }
              : roles.run?.rows.find(
                  (row) => row.discord_id === person.discord_id,
                )
          }
          refreshRoles={roles.error ? () => void roles.refresh() : undefined}
          onClose={closePerson}
          onDirty={panelDirtyChange}
          onDenied={deny}
          onChanged={() => void directory.load()}
          onRole={personRole}
          onFix={() => fix([person.discord_id])}
          undo={undo}
        />
      )}
      {action && data && (
        <RoleChangeReview
          ids={action.ids}
          operation={action.operation}
          roles={data.manageable_roles}
          fixedRole={action.fixedRole}
          guardRoleIds={action.guardRoleIds}
          onError={setActionError}
          onCancel={() => setAction(null)}
          onConfirm={roles.confirm}
          onDenied={deny}
          returnFocus={() => opener.current}
        />
      )}
    </section>
  );
}
