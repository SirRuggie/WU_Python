import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Season, type Signup } from "./api";
import StaffSignupControls from "./StaffSignupControls";
import SignupMemberGroup from "./SignupMemberGroup";
import { useDashboardPermission } from "./DashboardPermissions";
import "./ManageSignups.css";
import useUnsavedWork from "./useUnsavedWork";
import MemberPicker, { type MemberOption } from "./MemberPicker";

type Props = {
  season: Season;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
  onSeasonRefresh: () => Promise<void>;
};

export default function ManageSignups({
  season,
  onDirty,
  onBusy,
  onSeasonRefresh,
}: Props) {
  const canSignups = useDashboardPermission("cwl_signups");
  const [activeGroup, setActiveGroup] = useState("");
  const [revision, setRevision] = useState(0);
  const [placement, setPlacement] = useState("all");
  const locked = !!activeGroup;
  const [formDirty, setFormDirty] = useState(false);
  const [formBusy, setFormBusy] = useState(false);
  const [editorBusy, setEditorBusy] = useState(false);
  const listBusy = locked || formDirty || formBusy || editorBusy;
  useUnsavedWork(formDirty || formBusy || editorBusy || locked, onDirty);
  useEffect(() => {
    onBusy(formBusy || editorBusy);
    return () => onBusy(false);
  }, [formBusy, editorBusy, onBusy]);
  const [rows, setRows] = useState<Signup[]>([]);
  const [member, setMember] = useState("");
  const [findMember, setFindMember] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [identities, setIdentities] = useState<Record<string, MemberOption>>({});
  const savedHeading = useRef<HTMLHeadingElement>(null);
  const focusAfterReload = useRef<{ key: string; target: number } | null>(null);
  const [namesError, setNamesError] = useState(false);
  const [namesLoading, setNamesLoading] = useState(true);
  const [nameRefresh, setNameRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setNamesLoading(true);
    setNamesError(false);
    setNames({});
    setIdentities({});
    api<{ options: MemberOption[] }>(
      `/staff-signup-members?season_id=${season.id}`,
    )
      .then((data) => {
        if (active) {
          setNames((current) => ({
            ...current,
            ...Object.fromEntries(data.options.map((option) => [option.id, option.display_name || option.username])),
          }));
          setIdentities((current) => ({
            ...current,
            ...Object.fromEntries(data.options.map((option) => [option.id, option])),
          }));
        }
      })
      .catch(() => {
        if (active) setNamesError(true);
      })
      .finally(() => {
        if (active) setNamesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [season.id, nameRefresh]);
  const [pool, setPool] = useState("all");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [changeNotice, setChangeNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedRefresh, setLoadedRefresh] = useState(-1);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState(0);
  const reload = useCallback(async () => {
    setRefresh((value) => value + 1);
    setNameRefresh((value) => value + 1);
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api<{ signups: Signup[]; revision: number }>(
      `/seasons/${season.id}/signups?all=1`,
    )
      .then((data) => {
        if (active) {
          setRows(data.signups);
          setRevision(data.revision);
          setError("");
          setLoadedRefresh(refresh);
        }
      })
      .catch((cause) => {
        if (active) {
          setRows([]);
          setActiveGroup("");
          setError(cause instanceof Error ? cause.message : "Could not load signups.");
          setLoadedRefresh(refresh);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [season.id, refresh]);
  const term = search.trim().toLowerCase();
  const matching = rows.filter(
    (row) =>
      (!member || row.user_id === member) &&
      (pool === "all" || row.pool === pool) &&
      (placement === "all" ||
        (placement === "assigned") === !!row.has_staff_placement) &&
      [
        row.player_name,
        row.tag,
        row.user_id,
        row.signup_clan_name,
        row.assigned_clan_name,
        names[row.user_id],
        identities[row.user_id]?.username,
      ].some((value) => value?.toLowerCase().includes(term)),
  );
  const groups = new Map<string, Signup[]>();
  matching.forEach((row) => {
    const key = row.user_id || `unlinked:${row.tag}`;
    groups.set(key, [...(groups.get(key) || []), row]);
  });
  useEffect(() => {
    const pending = focusAfterReload.current;
    if (!pending || loadedRefresh < pending.target || loading) return;
    focusAfterReload.current = null;
    requestAnimationFrame(() => {
      const group = [...document.querySelectorAll<HTMLElement>("[data-signup-group-key]")]
        .find((node) => node.dataset.signupGroupKey === pending.key);
      (group?.querySelector<HTMLElement>("h3") || savedHeading.current)?.focus({ preventScroll: true });
    });
  }, [loadedRefresh, loading, rows, pool, placement, member, search, page]);
  const lastPage = Math.max(0, Math.ceil(groups.size / 10) - 1);
  const currentPage = Math.min(page, lastPage);
  return (
    <div className="manage-signups">
      <fieldset className="signup-top-controls" disabled={locked || editorBusy}>
        <StaffSignupControls
          season={season}
          onDirty={setFormDirty}
          onBusy={setFormBusy}
          onChanged={async () => {
            await onSeasonRefresh();
            await reload();
          }}
        />
      </fieldset>
      <section className="manage-signups-list" aria-labelledby="saved-signups-title">
        <div className="manage-signups-heading">
          <h2 id="saved-signups-title" ref={savedHeading} tabIndex={-1}>Saved signups</h2>
          <span>{error ? "Signups unavailable" : loading && !rows.length ? "Loading signups…" : `${matching.length} ${matching.length === 1 ? "account" : "accounts"} · ${groups.size} ${groups.size === 1 ? "member" : "members"}`}</span>
        </div>
        {namesError && (
          <p className="notice" role="status">
            Discord names could not be loaded.
            <button onClick={() => setNameRefresh((value) => value + 1)}>Retry names</button>
          </p>
        )}
        <div className="manage-signups-filters">
          <label>
            Search signups
            <input
              disabled={listBusy}
              type="search"
              value={search}
              onChange={(event) => { setSearch(event.target.value); setPage(0); }}
              placeholder="Player, member, tag or clan"
            />
          </label>
          <label>
            CWL type
            <select disabled={listBusy} value={pool} onChange={(event) => { setPool(event.target.value); setPage(0); }}>
              <option value="all">All signups</option>
              <option value="main">Main CWL</option>
              <option value="lazy">Lazy CWL</option>
            </select>
          </label>
          <label>
            Placement
            <select disabled={listBusy} value={placement} onChange={(event) => { setPlacement(event.target.value); setPage(0); }}>
              <option value="all">All placements</option>
              <option value="assigned">Assigned</option>
              <option value="waiting">Awaiting placement</option>
            </select>
          </label>
          <button className="manage-signups-refresh" disabled={loading || listBusy} onClick={() => void reload()}>Refresh</button>
          <div className="manage-signups-member-filter">
            <button
              disabled={listBusy}
              aria-expanded={findMember}
              aria-controls={findMember ? "manage-signups-member-picker" : undefined}
              onClick={() => setFindMember((value) => !value)}
            >
              Discord member{member ? ` · ${names[member] || member}` : ""} {findMember ? "▴" : "▾"}
            </button>
            {member && <button disabled={listBusy} onClick={() => { setMember(""); setPage(0); }}>Clear member</button>}
          </div>
          {findMember && (
            <div id="manage-signups-member-picker" className="manage-signups-member-picker">
              <MemberPicker
                label="Filter signups by member"
                value={member}
                disabled={listBusy}
                endpoint="/staff-signup-members"
                showRoles={false}
                onChange={(value) => { setMember(String(value || "")); setPage(0); }}
                onOptions={(options) => {
                  setNames((current) => ({
                    ...current,
                    ...Object.fromEntries(options.map((option) => [option.id, option.display_name || option.username])),
                  }));
                  setIdentities((current) => ({
                    ...current,
                    ...Object.fromEntries(options.map((option) => [option.id, option])),
                  }));
                }}
              />
            </div>
          )}
        </div>
        {changeNotice && (
          <p className="notice success" role="status">{changeNotice}</p>
        )}
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {loading && <p role="status">Loading signups…</p>}
        {!error && (
          <>
            {!loading && !matching.length && (
              <p>
                {rows.length
                  ? "No signups match your search."
                  : "No accounts signed up yet."}
              </p>
            )}
            {[...groups.entries()]
              .slice(currentPage * 10, (currentPage + 1) * 10)
              .map(([key, accounts]) => (
                <SignupMemberGroup
                  key={`${season.id}:${key}`}
                  accounts={accounts}
                  name={
                    accounts[0].user_id
                      ? names[accounts[0].user_id] ||
                        (namesLoading
                          ? "Loading member name…"
                          : `Member · ${accounts[0].player_name || accounts[0].tag}`)
                      : "No Discord account"
                  }
                  seasonId={season.id}
                  identity={identities[accounts[0].user_id]}
                  groupKey={key}
                  revision={revision}
                  editable={season.status !== "archived" && canSignups}
                  disabled={
                    loading ||
                    formBusy ||
                    formDirty ||
                    (!!activeGroup && activeGroup !== key)
                  }
                  onActive={(active) => setActiveGroup(active ? key : "")}
                  onBusy={setEditorBusy}
                  onChanged={(notice) => {
                    setChangeNotice(notice);
                    focusAfterReload.current = { key, target: refresh + 1 };
                    return reload();
                  }}
                />
              ))}
            {lastPage > 0 && (
              <nav
                className="manage-signups-pagination"
                aria-label="Signup member pages"
              >
                <button
                  disabled={listBusy || !currentPage}
                  onClick={() => setPage(currentPage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {currentPage + 1} of {lastPage + 1}
                </span>
                <button
                  disabled={listBusy || currentPage === lastPage}
                  onClick={() => setPage(currentPage + 1)}
                >
                  Next
                </button>
              </nav>
            )}
          </>
        )}
      </section>
    </div>
  );
}
