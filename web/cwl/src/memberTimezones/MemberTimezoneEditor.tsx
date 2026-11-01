import { nicknameName } from "./nicknameName";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Directory, Member, RequestState } from "./types";

type Account = { tag: string; name: string; townHallLevel: number };
export default function MemberTimezoneEditor({
  member,
  data,
  busy,
  onQueue,
  onClose,
  onDirty,
  onDenied,
  outcome,
}: {
  outcome?: RequestState | null;
  member: Member;
  data: Directory;
  busy: boolean;
  onQueue: (request: RequestState) => void;
  onClose: () => void;
  onDirty: (value: boolean) => void;
  onDenied: () => void;
}) {
  const [name, setName] = useState(
    nicknameName(member.nickname, member.name).name,
  );
  const [zone, setZone] = useState(member.profile?.zone_id || "");
  const [country, setCountry] = useState(member.profile?.country || "");
  const [allZones, setAllZones] = useState(() => {
    const choices = data.countries.find(
      (c) => c.code === member.profile?.country,
    )?.zones;
    return (
      !choices ||
      (!!member.profile?.zone_id &&
        !choices.some((z) => z.id === member.profile!.zone_id))
    );
  });
  const countryZones = data.countries.find((c) => c.code === country)?.zones;
  const visibleZones = allZones || !countryZones ? data.zones : countryZones;
  const [tag, setTag] = useState(member.profile?.name_source_tag || null);
  const [rename, setRename] = useState(false),
    [accounts, setAccounts] = useState<Account[]>([]),
    [loading, setLoading] = useState(true),
    [warning, setWarning] = useState(""),
    [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [base, setBase] = useState({
    revision: member.profile?.revision || 0,
    nickname: member.nickname,
  });
  const retryNeeded = useRef(false);
  useEffect(() => {
    if (outcome?.status === "failed") {
      retryNeeded.current = true;
      setError(outcome.message);
    }
  }, [outcome?.request_id, outcome?.status]);
  busy = busy || saving;
  const requestId = useRef(crypto.randomUUID()),
    edited = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    api<{ accounts: Account[]; suggested: Account | null; complete: boolean }>(
      `/manage/member-timezones/${member.discord_id}/choices`,
    )
      .then((result) => {
        if (cancelled) return;
        setAccounts(result.accounts);
        if (result.suggested && !edited.current && !member.nickname) {
          setName(result.suggested.name);
          setTag(result.suggested.tag);
        }
        if (!result.complete)
          setWarning(
            "Some linked accounts are unavailable. Choose a loaded account or type a name; no highest Town Hall was assumed.",
          );
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && [401, 403].includes(e.status)) onDenied();
        else setWarning("Linked names are unavailable. Type a name.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      alive.current = false;
    };
  }, [member.discord_id]);
  const change = () => {
    edited.current = true;
    requestId.current = crypto.randomUUID();
    onDirty(true);
  };
  const label = zone.toUpperCase();
  const emoji = /^[A-Za-z]{2}$/.test(country)
    ? Array.from(country.toUpperCase())
        .map((c) => String.fromCodePoint(c.charCodeAt(0) + 127397))
        .join("")
    : "";
  const preview = `${name.trim()} | ${label} ${emoji}`;
  const extra =
    member.profile && !data.zones.some((z) => z.id === member.profile!.zone_id)
      ? member.profile
      : null;
  async function save() {
    if (busy) return;
    setSaving(true);
    setError("");
    try {
      if (retryNeeded.current) {
        requestId.current = crypto.randomUUID();
        retryNeeded.current = false;
      }
      const result = await api<RequestState>(
        "/manage/member-timezones/save",
        "POST",
        {
          request_id: requestId.current,
          discord_id: member.discord_id,
          revision: base.revision,
          fields: {
            zone_id: zone,
            country: country.toUpperCase(),
            name_source_tag: tag,
          },
          rename,
          name,
          old_nickname: base.nickname,
        },
      );
      if (alive.current) onQueue(result);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && [401, 403].includes(e.status)) onDenied();
      else {
        if (e instanceof ApiError && [400, 409].includes(e.status))
          retryNeeded.current = true;
        setError(
          e instanceof Error ? e.message : "Profile could not be queued.",
        );
      }
    } finally {
      if (alive.current) setSaving(false);
    }
  }
  async function reloadBase() {
    if (busy) return;
    setSaving(true);
    try {
      const fresh = await api<Directory>("/manage/member-timezones");
      if (!alive.current) return;
      const current = fresh.members.find(
        (row) => row.discord_id === member.discord_id,
      );
      if (!current) throw new Error("This member is no longer available.");
      setBase({
        revision: current.profile?.revision || 0,
        nickname: current.nickname,
      });
      requestId.current = crypto.randomUUID();
      retryNeeded.current = false;
      setError("");
      setWarning(
        "Latest profile loaded. Your draft was kept; review the preview before saving again.",
      );
      onDirty(true);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && [401, 403].includes(e.status)) onDenied();
      else
        setError(
          e instanceof Error ? e.message : "Could not reload the profile.",
        );
    } finally {
      if (alive.current) setSaving(false);
    }
  }
  return (
    <section className="mt-editor" aria-label={`Edit ${member.name}`}>
      <h2>Edit {member.name}</h2>
      {warning && <p role="status">{warning}</p>}
      {error && (
        <div role="alert">
          {error}
          <button disabled={busy} onClick={() => void reloadBase()}>
            Reload latest and keep draft
          </button>
        </div>
      )}
      <label>
        In-game name
        <input
          value={name}
          disabled={busy}
          onChange={(e) => {
            change();
            setName(e.target.value);
            setTag(null);
          }}
        />
      </label>
      {loading ? (
        <p role="status">Loading linked names…</p>
      ) : (
        accounts.length > 0 && (
          <label>
            Which one do you want to name it?
            <select
              aria-label="Which one do you want to name it?"
              value={tag || ""}
              disabled={busy}
              onChange={(e) => {
                change();
                const account = accounts.find((a) => a.tag === e.target.value);
                setTag(account?.tag || null);
                if (account) setName(account.name);
              }}
            >
              <option value="">Type a name</option>
              {accounts.map((a) => (
                <option key={a.tag} value={a.tag}>
                  {a.name} · TH{a.townHallLevel}
                </option>
              ))}
            </select>
          </label>
        )
      )}
      <label>
        Time zone
        <select
          aria-label="Time zone"
          value={zone}
          disabled={busy}
          onChange={(e) => {
            change();
            setZone(e.target.value);
          }}
        >
          <option value="">Choose a time zone</option>
          {extra && (
            <option value={extra.zone_id}>
              {extra.gmt_label} · Imported offset
            </option>
          )}
          {visibleZones.map((z) => (
            <option key={z.id} value={z.id}>
              {z.label}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={allZones || busy}
        onClick={() => setAllZones(true)}
      >
        Show all zones
      </button>
      <label>
        Country
        <select
          aria-label="Country"
          value={
            data.countries.some((c) => c.code === country) ? country : "other"
          }
          disabled={busy}
          onChange={(e) => {
            change();
            setCountry(e.target.value === "other" ? "" : e.target.value);
            setAllZones(e.target.value === "other");
            setZone(
              data.countries.find((country) => country.code === e.target.value)
                ?.zone_id || "",
            );
          }}
        >
          <option value="other">Other / choose country</option>
          {data.countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.flag} {c.label}
            </option>
          ))}
        </select>
      </label>
      {!data.countries.some((c) => c.code === country) && (
        <label>
          Two-letter country code
          <input
            maxLength={2}
            value={country}
            disabled={busy}
            onChange={(e) => {
              change();
              setCountry(e.target.value.toUpperCase());
            }}
          />
        </label>
      )}
      <label className="mt-check">
        <input
          type="checkbox"
          checked={rename}
          disabled={busy || !!member.skip_reason}
          onChange={(e) => {
            change();
            setRename(e.target.checked);
          }}
        />
        Also change the Discord nickname
      </label>
      {member.skip_reason && <p>{member.skip_reason}</p>}
      {rename && (
        <p>
          Preview: <strong>{preview}</strong> ({Array.from(preview).length}/32
          characters)
        </p>
      )}
      <div className="mt-actions">
        <button
          disabled={
            busy ||
            !zone ||
            !emoji ||
            (rename && (!name.trim() || Array.from(preview).length > 32))
          }
          onClick={() => void save()}
        >
          Save profile{rename ? " and nickname" : ""}
        </button>
        <button disabled={busy} onClick={onClose}>
          Cancel
        </button>
      </div>
    </section>
  );
}
