import { useCallback, useEffect, useRef, useState } from "react";
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
  const allowed = useDashboardPermission("member_roles");
  const [filters, setFilters] = useState<Filters>(emptyFilters),
    [sort, setSort] = useState<MemberSort>("name"),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [page, setPage] = useState(0),
    [personId, setPersonId] = useState<string | null>(
      initialMember || new URLSearchParams(location.search).get("account"),
    ),
    [panelDirty, setPanelDirty] = useState(false),
    [nameBusy, setNameBusy] = useState(false),
    [nameOpen, setNameOpen] = useState(false),
    [fixTrigger, setFixTrigger] = useState(0),
    [fixIds, setFixIds] = useState<readonly string[] | undefined>(),
    [action, setAction] = useState<RoleAction | null>(null),
    [actionError, setActionError] = useState(""),
    [denied, setDenied] = useState(false),
    [lastWasUndo, setLastWasUndo] = useState(false);
  const scroll = useRef<HTMLDivElement | null>(null),
    savedScroll = useRef(0),
    opener = useRef<HTMLElement | null>(null),
    headerCheck = useRef<HTMLInputElement | null>(null),
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
    if (headerCheck.current)
      headerCheck.current.indeterminate = summary.partial;
  }, [summary.partial]);
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
      if (scroll.current) scroll.current.scrollTop = savedScroll.current;
      opener.current?.focus({ preventScroll: true });
    });
  };
  const openPerson = (id: string, trigger: HTMLElement) => {
    opener.current = trigger;
    savedScroll.current = scroll.current?.scrollTop || 0;
    setPersonId(id);
    setActionError("");
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
  if (!allowed || denied) return <p role="alert">{t.roleUnavailable}</p>;
  return (
    <main
      className={`roster-ui members-workspace${person ? " has-panel" : ""}`}
    >
      <header>
        <h1>{t.title}</h1>
        <div>
          <button
            disabled={busy || panelDirty || directory.loading}
            onClick={() => void directory.load()}
          >
            {t.refresh}
          </button>
          <button
            disabled={busy || panelDirty || !data || unknown}
            onClick={() => fix(selected.size ? [...selected] : undefined)}
          >
            {t.fixNames}
          </button>
        </div>
      </header>
      {directory.error && <p role="alert">{directory.error}</p>}
      {!person && (actionError || roles.error) && (
        <p role="alert">{actionError || roles.error}</p>
      )}
      {directory.loading && !data && <p role="status">{t.loading}</p>}
      {data && (
        <>
          <MemberFilters
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
          <div className="members-selection-tools">
            <label className="members-checkbox">
              <input
                ref={headerCheck}
                type="checkbox"
                checked={summary.all}
                aria-label={t.selectPage}
                onChange={() => {
                  if (summary.all)
                    setSelected(
                      (old) =>
                        new Set(
                          [...old].filter(
                            (id) =>
                              !visible.some((row) => row.discord_id === id),
                          ),
                        ),
                    );
                  else setSelected((old) => selectPage(old, visible));
                }}
              />
              {t.selectPage}
            </label>
            <button
              onClick={() => setSelected((old) => selectMatching(old, rows))}
            >
              {t.selectMatching(rows.filter((row) => !row.bot).length)}
            </button>
            <span>
              {t.showing(
                rows.length ? currentPage * 25 + 1 : 0,
                Math.min((currentPage + 1) * 25, rows.length),
                rows.length,
              )}
            </span>
          </div>
          {unknown && <p role="alert">{t.selectedLeft}</p>}
          <div className="members-directory-scroll" ref={scroll}>
            <Standardize
              disabled={roles.active || roles.busy || !!action || panelDirty}
              members={data.members}
              onDenied={deny}
              onBusy={setNameBusy}
              onOpenChange={setNameOpen}
              onImported={() => void directory.load()}
              hideEntry
              externalTrigger={fixTrigger}
              selectedIds={fixIds}
              visibleIds={filteredIds}
            />
            {(roles.run || roles.error) && (
              <section ref={progress} tabIndex={-1} aria-label={t.roleProgress}>
                <h2>{t.roleRun}</h2>
                {roles.run && (
                  <details open={roles.active}>
                    <summary>{t.roleRun}</summary>
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
          <MemberBulkBar
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
        </>
      )}
      {person && data && (
        <MemberPersonPanel
          key={person.discord_id}
          member={person}
          data={data}
          busy={busy}
          navigationBusy={navigationBusy}
          roleError={actionError || roles.error}
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
    </main>
  );
}
