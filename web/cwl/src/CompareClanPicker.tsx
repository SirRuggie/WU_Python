import { useState } from "react";
import { ArrowUp, ArrowDown, X } from "lucide-react";
import ActionPanel from "./ActionPanel";
import { Button, Input } from "./rosterUi/primitives";
import RosterMenu from "./rosterUi/Menu";
import { clanSortOptions, sortClans, type ClanSort } from "./clanSort";
import { moveComparisonClan } from "./compare";
import type { RosterClan } from "./roster";
export default function CompareClanPicker({
  clans,
  availableTags,
  chosen,
  trigger,
  onClose,
  onChange,
  replace,
  onReplace,
}: {
  clans: RosterClan[];
  availableTags: string[];
  chosen: string[];
  trigger: HTMLElement | null;
  onClose: () => void;
  onChange: (tags: string[]) => void;
  replace?: string;
  onReplace: (tag: string) => void;
}) {
  const [search, setSearch] = useState("");
  const matching = clans
    .filter((clan) => availableTags.includes(clan.tag))
    .filter((clan) =>
      `${clan.name} ${clan.tag}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
    );
  return (
    <ActionPanel
      title={replace ? "Change clan in this column" : "Choose clans"}
      trigger={trigger}
      onClose={onClose}
      className="roster-ui"
      expandOnSearchFocus
    >
      <Input
        label="Find a clan"
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Clan name or tag"
      />
      {!replace && (
        <>
          <p>{chosen.length} of 10 chosen</p>
          <RosterMenu
            label="Sort chosen clans"
            value=""
            options={clanSortOptions.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            onValueChange={(value) =>
              onChange(
                sortClans(
                  clans.filter((clan) => chosen.includes(clan.tag)),
                  value as ClanSort,
                ).map((clan) => clan.tag),
              )
            }
          />
          <ol className="compare-picked-order">
            {chosen.map((tag, index) => (
              <li key={tag}>
                <span>
                  {clans.find((clan) => clan.tag === tag)?.name || tag}
                </span>
                <div>
                  <Button
                    icon={ArrowUp}
                    variant="icon"
                    label={`Move ${tag} up`}
                    disabled={index === 0}
                    onClick={() =>
                      onChange(
                        moveComparisonClan(chosen, tag, chosen[index - 1]),
                      )
                    }
                  />
                  <Button
                    icon={ArrowDown}
                    variant="icon"
                    label={`Move ${tag} down`}
                    disabled={index === chosen.length - 1}
                    onClick={() =>
                      onChange(
                        moveComparisonClan(chosen, tag, chosen[index + 1]),
                      )
                    }
                  />
                  <Button
                    icon={X}
                    variant="icon"
                    label={`Remove ${tag}`}
                    onClick={() =>
                      onChange(chosen.filter((value) => value !== tag))
                    }
                  />
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
      <div className="compare-picker-list">
        {matching.map((clan) =>
          replace ? (
            <Button
              key={clan.tag}
              onClick={() => {
                onChange(
                  chosen.map((tag) =>
                    tag === replace
                      ? clan.tag
                      : tag === clan.tag
                        ? replace
                        : tag,
                  ),
                );
                onReplace(clan.tag);
                onClose();
              }}
            >
              {clan.name}
            </Button>
          ) : (
            <label key={clan.tag}>
              <input
                type="checkbox"
                checked={chosen.includes(clan.tag)}
                disabled={!chosen.includes(clan.tag) && chosen.length >= 10}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...chosen, clan.tag]
                      : chosen.filter((tag) => tag !== clan.tag),
                  )
                }
              />
              <span>
                {clan.name}
                <small>
                  {clan.cwl_league || "League unavailable"} · {clan.tag}
                </small>
              </span>
            </label>
          ),
        )}
      </div>
      {!matching.length && <p>No clans match this search.</p>}
      {!replace && (
        <Button onClick={() => onChange([])} disabled={!chosen.length}>
          Clear choices
        </Button>
      )}
    </ActionPanel>
  );
}
