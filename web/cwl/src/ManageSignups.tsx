import { useCallback, useEffect, useState } from "react";
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
  onRoster: () => void;
};

export default function ManageSignups({
  season,
  onDirty,
  onBusy,
  onSeasonRefresh,
  onRoster,
}: Props) {
  const canSignups = useDashboardPermission("cwl_signups");
  const [activeGroup, setActiveGroup] = useState("");
  const [revision, setRevision] = useState(0);
  const [placement, setPlacement] = useState("all");
  const locked = !!activeGroup;
  const [formDirty, setFormDirty] = useState(false);
  const [formBusy, setFormBusy] = useState(false);
  const [editorBusy, setEditorBusy] = useState(false);
  useUnsavedWork(formDirty || formBusy || editorBusy || locked, onDirty);
  useEffect(() => {
    onBusy(formBusy || editorBusy);
    return () => onBusy(false);
  }, [formBusy, editorBusy, onBusy]);
  const [rows, setRows] = useState<Signup[]>([]);
  const [member, setMember] = useState("");
  const [findMember, setFindMember] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [namesError, setNamesError] = useState(false);
  const [namesLoading, setNamesLoading] = useState(true);
  const [nameRefresh, setNameRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setNamesLoading(true);
    setNamesError(false);
    setNames({});
    api<{ options: MemberOption[] }>(
      `/staff-signup-members?season_id=${season.id}`,
    )
      .then((data) => {
        if (active)
          setNames((current) => ({
            ...current,
            ...Object.fromEntries(
              data.options.map((option) => [
                option.id,
                option.display_name || option.username,
              ]),
            ),
          }));
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
  const [loading, setLoading] = useState(false);
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
        }
      })
      .catch((cause) => {
        if (active) {
          setRows([]);
          setError(cause.message);
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
      ].some((value) => value?.toLowerCase().includes(term)),
  );
  const groups = new Map<string, Signup[]>();
  matching.forEach((row) => {
    const key = row.user_id || `unlinked:${row.tag}`;
    groups.set(key, [...(groups.get(key) || []), row]);
  });
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
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Saved signups</h2>
            <p>Manage who is signed up. Assign clans in Roster.</p>
          </div>
          <button disabled={locked || editorBusy} onClick={onRoster}>
            Open roster
          </button>
        </div>
        {namesError && (
          <p className="notice" role="status">
            Discord names could not be loaded.
            <button onClick={() => setNameRefresh((value) => value + 1)}>
              Retry names
            </button>
          </p>
        )}

        <button
          disabled={locked || editorBusy}
          aria-expanded={findMember}
          onClick={() => setFindMember((value) => !value)}
        >
          Find by Discord member{member ? " · Filter active" : ""}
        </button>
        {findMember && (
          <MemberPicker
            label="Filter signups by member"
            value={member}
            disabled={locked || editorBusy}
            endpoint="/staff-signup-members"
            showRoles={false}
            onChange={(value) => {
              setMember(String(value || ""));
              setPage(0);
            }}
            onOptions={(options) =>
              setNames((current) => ({
                ...current,
                ...Object.fromEntries(
                  options.map((option) => [
                    option.id,
                    option.display_name || option.username,
                  ]),
                ),
              }))
            }
          />
        )}
        {member && (
          <button
            disabled={locked || editorBusy}
            onClick={() => {
              setMember("");
              setPage(0);
            }}
          >
            Show all members
          </button>
        )}
        <div
          className="workflow-tabs staff-add-modes"
          role="group"
          aria-label="Signup pool filter"
        >
          {["all", "main", "lazy"].map((value) => (
            <button
              disabled={locked || editorBusy}
              key={value}
              aria-pressed={pool === value}
              onClick={() => {
                setPool(value);
                setPage(0);
              }}
            >
              {value === "all"
                ? "All signups"
                : value === "main"
                  ? "Main"
                  : "Lazy"}
            </button>
          ))}
        </div>
        <div className="staff-signup-list-tools">
          <label>
            Find a signup
            <input
              disabled={locked || editorBusy}
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
              placeholder="Player, member, tag or clan"
            />
          </label>
          <label>
            Placement
            <select
              disabled={locked || editorBusy}
              value={placement}
              onChange={(e) => {
                setPlacement(e.target.value);
                setPage(0);
              }}
            >
              <option value="all">All placements</option>
              <option value="assigned">Assigned</option>
              <option value="waiting">Awaiting placement</option>
            </select>
          </label>
          <button
            disabled={loading || locked || editorBusy}
            onClick={() => void reload()}
          >
            Refresh
          </button>
        </div>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {loading && <p role="status">Loading signups…</p>}
        {!error && (
          <>
            <p>
              {matching.length} {matching.length === 1 ? "account" : "accounts"}{" "}
              · {groups.size}{" "}
              {groups.size === 1 ? "member group" : "member groups"}
            </p>
            {!matching.length && (
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
                  onChanged={reload}
                />
              ))}
            {lastPage > 0 && (
              <nav
                className="staff-signup-list-tools"
                aria-label="Signup member pages"
              >
                <button
                  disabled={locked || editorBusy || !currentPage}
                  onClick={() => setPage(currentPage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {currentPage + 1} of {lastPage + 1}
                </span>
                <button
                  disabled={locked || editorBusy || currentPage === lastPage}
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
