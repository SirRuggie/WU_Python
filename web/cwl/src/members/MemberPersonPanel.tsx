import { useEffect, useLayoutEffect, useState } from "react";
import { api, ApiError } from "../api";
import DetailsFrame from "../DetailsFrame";
import { requestDetailsNavigation } from "../detailsNavigation";
import DiscordIdentity, { discordIdentityName } from "../DiscordIdentity";
import MemberTimezoneEditor from "../memberTimezones/MemberTimezoneEditor";
import type { RequestState } from "../memberTimezones/types";
import type { MembersDirectory } from "./useMembersDirectory";
import { localMemberTime, type DirectoryMember } from "./model";
import { membersText as t } from "./strings";
function Accounts({ id, onDenied }: { id: string; onDenied: () => void }) {
  const [rows, setRows] = useState<
      { tag: string; name: string; townHallLevel: number }[] | null
    >(null),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    void api<{
      accounts: { tag: string; name: string; townHallLevel: number }[];
    }>(
      `/manage/member-timezones/${encodeURIComponent(id)}/choices`,
      "GET",
      undefined,
      { signal: controller.signal },
    )
      .then((result) => {
        if (
          !Array.isArray(result.accounts) ||
          result.accounts.some(
            (row) =>
              !row ||
              typeof row.tag !== "string" ||
              typeof row.name !== "string" ||
              !Number.isFinite(row.townHallLevel),
          )
        )
          throw new Error(t.accountsUnavailable);
        if (alive) setRows(result.accounts);
      })
      .catch((cause) => {
        if (!alive) return;
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          onDenied();
        setError(cause instanceof Error ? cause.message : t.roleUnavailable);
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [id]);
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {!rows ? (
        <p role="status">{t.loadingAccounts}</p>
      ) : rows.length ? (
        <ul>
          {rows.map((row) => (
            <li key={row.tag}>
              {row.name} · {row.tag}
            </li>
          ))}
        </ul>
      ) : (
        <p>{t.noAccounts}</p>
      )}
    </>
  );
}
function PersonRoles({
  member,
  data,
  busy,
  onRole,
}: {
  member: DirectoryMember;
  data: MembersDirectory;
  busy: boolean;
  onRole: (
    id: string,
    operation: "add" | "remove",
    trigger: HTMLElement,
  ) => void;
}) {
  const [query, setQuery] = useState("");
  const manageable = new Set(data.manageable_roles.map((role) => role.id));
  const rows = data.roles
    .filter((role) =>
      role.name
        .normalize("NFKC")
        .toLocaleLowerCase()
        .includes(query.normalize("NFKC").toLocaleLowerCase()),
    )
    .sort(
      (a, b) =>
        Number(member.role_ids.includes(b.id)) -
          Number(member.role_ids.includes(a.id)) ||
        a.name.localeCompare(b.name),
    );
  return (
    <>
      <label>
        {t.roleSearch}
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <div className="members-person-role-list">
        {rows.map((role) => (
          <label className="members-checkbox" key={role.id}>
            <input
              type="checkbox"
              role="switch"
              checked={member.role_ids.includes(role.id)}
              disabled={busy || member.bot || !manageable.has(role.id)}
              onChange={(event) =>
                onRole(
                  role.id,
                  event.target.checked ? "add" : "remove",
                  event.currentTarget,
                )
              }
            />
            {role.name}
          </label>
        ))}
      </div>
    </>
  );
}
export default function MemberPersonPanel({
  member,
  data,
  busy,
  navigationBusy,
  roleError,
  refreshRoles,
  onClose,
  onDirty,
  onDenied,
  onChanged,
  onRole,
  onFix,
  undo,
}: {
  member: DirectoryMember;
  data: MembersDirectory;
  busy: boolean;
  navigationBusy: boolean;
  roleError: string;
  refreshRoles?: () => void;
  onClose: () => void;
  onDirty: (dirty: boolean) => void;
  onDenied: () => void;
  onChanged: () => void;
  onRole: (
    id: string,
    operation: "add" | "remove",
    trigger: HTMLElement,
  ) => void;
  onFix: () => void;
  undo?: () => void;
}) {
  const [dirty, setDirty] = useState(false),
    [profileOpen, setProfileOpen] = useState(false),
    [accountsOpen, setAccountsOpen] = useState(false),
    [request, setRequest] = useState<RequestState | null>(null);
  useLayoutEffect(() => {
    setDirty(false);
    setProfileOpen(false);
    setAccountsOpen(false);
    setRequest(null);
    onDirty(false);
  }, [member.discord_id]);
  const pending = !!request && ["pending", "running"].includes(request.status);
  const name =
    discordIdentityName(
      member.discord_id,
      member.discord_profile,
      member.name,
    ) || t.unavailable;
  useEffect(() => {
    onDirty(dirty || pending);
    return () => onDirty(false);
  }, [dirty, pending, onDirty]);
  useEffect(() => {
    if (!request || !["pending", "running"].includes(request.status)) return;
    let stopped = false,
      inflight = false;
    const controller = new AbortController();
    const poll = async () => {
      if (stopped || inflight || document.visibilityState === "hidden") return;
      inflight = true;
      try {
        const result = await api<RequestState>(
          request.status_url,
          "GET",
          undefined,
          { signal: controller.signal },
        );
        if (stopped) return;
        setRequest(result);
        if (result.status === "done") {
          setDirty(false);
          setProfileOpen(false);
          onChanged();
        }
      } catch (cause) {
        if (!stopped) {
          if (cause instanceof ApiError && [401, 403].includes(cause.status))
            onDenied();
          else
            setRequest({
              ...request,
              status: "uncertain",
              message: cause instanceof Error ? cause.message : t.roleUncertain,
            });
        }
      } finally {
        inflight = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    void poll();
    return () => {
      stopped = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [request?.request_id, request?.status]);
  const sections = [
    {
      id: "roles",
      label: t.roles,
      content: (
        <>
          <PersonRoles
            key={member.discord_id}
            member={member}
            data={data}
            busy={busy || pending || dirty}
            onRole={onRole}
          />
          {roleError && <p role="alert">{roleError}</p>}
          {refreshRoles && (
            <button disabled={navigationBusy || pending} onClick={refreshRoles}>
              {t.refreshProgress}
            </button>
          )}
          {undo && (
            <button disabled={busy || pending || dirty} onClick={undo}>
              {t.undo}
            </button>
          )}
        </>
      ),
    },
    {
      id: "zone",
      label: t.timeZoneFlag,
      content: (
        <>
          <p>{member.profile ? t.saved : t.notSaved}</p>
          <div className="members-zone-current">
            {member.profile?.flag || t.noFlag} ·{" "}
            <details className="members-zone-help">
              <summary>
                {member.profile?.gmt_label || member.parsed?.label || t.noZone}
              </summary>
              <p>{t.zoneExplanation}</p>
            </details>
            {localMemberTime(member) &&
              ` · ${t.localTime(localMemberTime(member)!)}`}
          </div>
          {!profileOpen ? (
            <button
              disabled={busy || pending || member.bot}
              onClick={() => setProfileOpen(true)}
            >
              {t.editTimeZone}
            </button>
          ) : (
            <MemberTimezoneEditor
              member={member}
              data={data}
              busy={busy || pending}
              outcome={request}
              onQueue={setRequest}
              onDirty={setDirty}
              onDenied={onDenied}
              onClose={() =>
                requestDetailsNavigation(() => {
                  setProfileOpen(false);
                  setDirty(false);
                })
              }
            />
          )}
          {request && !profileOpen && <p role="status">{request.message}</p>}
        </>
      ),
    },
    {
      id: "nickname",
      label: t.nickname,
      content: (
        <>
          <p>{member.nickname || t.noNickname}</p>
          <button
            disabled={busy || pending || dirty || member.bot}
            onClick={onFix}
          >
            {t.fixNames}
          </button>
        </>
      ),
    },
    {
      id: "accounts",
      label: t.linkedAccounts,
      content: (
        <details
          open={accountsOpen}
          onToggle={(event) => setAccountsOpen(event.currentTarget.open)}
        >
          <summary>{t.linkedAccounts}</summary>
          {accountsOpen && (
            <Accounts id={member.discord_id} onDenied={onDenied} />
          )}
        </details>
      ),
    },
    {
      id: "moderation",
      label: t.moderationHistory,
      content: <a href="/server/moderation">{t.moderationHistory}</a>,
    },
  ];
  return (
    <DetailsFrame
      tag={member.discord_id}
      name={name}
      dirty={dirty}
      busy={navigationBusy || pending}
      onClose={onClose}
      backLabel={t.back}
      browseLabel={t.browsePeople}
      discardSubject={t.discardSubject}
      discardConfirmLabel={t.discardChanges}
    >
      <DiscordIdentity
        userId={member.discord_id}
        resolvedMember={member.discord_profile || null}
        displayName={member.name}
      />
      {sections.map((section) => (
        <section
          className="members-person-section"
          aria-label={section.label}
          key={section.id}
        >
          <h2>{section.label}</h2>
          {section.content}
        </section>
      ))}
    </DetailsFrame>
  );
}
