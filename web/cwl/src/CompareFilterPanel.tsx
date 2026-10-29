import { useState } from "react";
import ActionPanel from "./ActionPanel";
import RosterFilterOptions from "./RosterFilterOptions";
import { Button } from "./rosterUi/primitives";
import { comparisonFilters } from "./compareFilters";
import type { RosterAccount, RosterClan } from "./roster";
export default function CompareFilterPanel({
  accounts,
  clans,
  chosen,
  leagues,
  townHalls,
  trigger,
  onClose,
  onApply,
}: {
  accounts: RosterAccount[];
  clans: RosterClan[];
  chosen: string[];
  leagues: string[];
  townHalls: string[];
  trigger: HTMLElement | null;
  onClose: () => void;
  onApply: (leagues: string[], halls: string[]) => void;
}) {
  const [draftLeagues, setLeagues] = useState(leagues),
    [draftHalls, setHalls] = useState(townHalls);
  const options = comparisonFilters(
    accounts,
    clans,
    chosen,
    draftLeagues,
    draftHalls,
  );
  return (
    <ActionPanel
      title="Filter comparison"
      trigger={trigger}
      onClose={onClose}
      className="roster-ui roster-filters-panel"
      footer={
        <div className="roster-filters-footer">
          <Button
            onClick={() => {
              setLeagues([]);
              setHalls([]);
            }}
          >
            Reset
          </Button>
          <Button
            variant="primary"
            onClick={() => onApply(draftLeagues, draftHalls)}
          >
            Show {options.count} players
          </Button>
        </div>
      }
    >
      <div className="roster-filters-fields">
        <p>Filters hide players; clan totals include everyone.</p>
        <RosterFilterOptions
          title="CWL league"
          options={options.leagues}
          selected={draftLeagues}
          onChange={setLeagues}
        />
        <RosterFilterOptions
          title="Town Hall"
          options={options.townHalls}
          selected={draftHalls}
          onChange={setHalls}
        />
      </div>
    </ActionPanel>
  );
}
