import { useEffect, useMemo, useRef, useState } from "react";
import SearchPicker, { filterOptions, type PickerOption } from "./SearchPicker";
import { api, isExpectedCancel } from "./api";
import { memberName } from "./strikeActivityFilters";
import { strikeMemberOptions } from "./StrikeMemberSelect";
import type { ActivityAccount } from "./strikeActivityView";
import { discordIdentityName, type DiscordProfile } from "./DiscordIdentity";

type MemberReply = {
  members: {
    id: string;
    name: string;
    discord_profile?: { username?: string };
  }[];
};
function memberOptions(data: MemberReply): PickerOption[] {
  if (!Array.isArray(data.members))
    throw new Error("Member results are incomplete. Try again.");
  return data.members
    .filter((row) => /^[1-9][0-9]{14,21}$/.test(row.id))
    .map((row) => ({
      value: row.id,
      label:
        memberName({ discord_id: row.id, discord_name: row.name }) ||
        "Unknown member",
      detail:
        memberName({
          discord_id: row.id,
          discord_name: row.discord_profile?.username,
        }) || undefined,
    }));
}

/** Existing staff member-search API includes recruits without a family account. */
export default function StrikeRecruitSelect({
  accounts,
  value,
  onChange,
  disabled,
}: {
  accounts: ActivityAccount[];
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const [query, setQuery] = useState<string | null>(null);
  const [known, setKnown] = useState<Record<string, PickerOption>>({});
  const [matches, setMatches] = useState<PickerOption[]>([]);
  const [status, setStatus] = useState("");
  const turn = useRef(0);
  const selectedTurn = useRef(0);
  const local = useMemo(
    () =>
      strikeMemberOptions(accounts).map((row) => ({
        value: row.id,
        label: row.name,
        detail: row.username,
      })),
    [accounts],
  );
  const selectedKnown =
    !!known[value] || local.some((row) => row.value === value);
  useEffect(() => {
    const current = ++selectedTurn.current,
      controller = new AbortController();
    if (!disabled && /^[1-9][0-9]{14,21}$/.test(value) && !selectedKnown) {
      void api<{ options: DiscordProfile[] }>(
        `/strikes/members?ids=${encodeURIComponent(value)}`,
        "GET",
        undefined,
        { signal: controller.signal },
      )
        .then((data) => {
          if (current !== selectedTurn.current) return;
          if (!Array.isArray(data.options))
            throw new Error("Member results are incomplete. Try again.");
          const rows = data.options
            .filter((row) => row?.id === value)
            .map((row) => ({
              value: row.id,
              label: discordIdentityName(row.id, row) || "Unknown member",
              detail: discordIdentityName(row.id, {
                id: row.id,
                username: row.username,
              }),
            }));
          if (rows.length)
            setKnown((previous) => ({
              ...previous,
              ...Object.fromEntries(rows.map((row) => [row.value, row])),
            }));
        })
        // Keep the existing unavailable-selection fallback on an empty/failed lookup.
        // Stable dependencies prevent retries caused by unrelated search/cache updates.
        .catch(() => {});
    }
    return () => {
      controller.abort();
      selectedTurn.current++;
    };
  }, [value, disabled, selectedKnown]);
  useEffect(() => {
    const current = ++turn.current,
      controller = new AbortController();
    setMatches([]);
    setStatus(
      query !== null && query.trim().length < 2
        ? "Search all server members by name or username."
        : "",
    );
    if (query === null || query.trim().length < 2 || disabled) return;
    setStatus("Finding members…");
    const timer = setTimeout(() => {
      void api<MemberReply>(
        `/strikes/members?query=${encodeURIComponent(query.trim().slice(0, 80))}`,
        "GET",
        undefined,
        { signal: controller.signal },
      )
        .then((data) => {
          if (current !== turn.current) return;
          const rows = memberOptions(data);
          setMatches(rows);
          setKnown((previous) => ({
            ...previous,
            ...Object.fromEntries(rows.map((row) => [row.value, row])),
          }));
          setStatus("");
        })
        .catch((cause) => {
          if (
            current === turn.current &&
            !isExpectedCancel(cause, controller.signal)
          )
            setStatus(
              cause instanceof Error
                ? cause.message
                : "Members are unavailable. Try again.",
            );
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
      turn.current++;
    };
  }, [query, disabled]);
  const options = [
    ...new Map(
      [...local, ...Object.values(known)].map((row) => [row.value, row]),
    ).values(),
  ];
  return (
    <SearchPicker
      label="Member"
      value={value}
      options={options}
      onChange={onChange}
      placeholder="Select a recruit"
      searchPlaceholder="Name or username"
      emptyText="No server member found"
      clearable
      disabled={disabled}
      fallback={{ value, label: "Selected member unavailable" }}
      status={status}
      onSearchChange={setQuery}
      search={(text) =>
        text.trim().length >= 2 ? matches : filterOptions(options, text)
      }
      limit={30}
    />
  );
}
