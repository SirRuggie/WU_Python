import DiscordIdentity from "./DiscordIdentity";
import type { DeclarationExtraClan } from "./declarationExtras";
import RosterFillerCheckbox from "./RosterFillerCheckbox";
export type DeclarationMarkControl = {
  seasonId: string;
  revision: number;
  onChanged: () => void | Promise<void>;
  disabled?: boolean;
};
export default function DeclarationMemberMarks({
  rows,
  control,
}: {
  rows: NonNullable<DeclarationExtraClan["extras"]>;
  control?: DeclarationMarkControl;
}) {
  return (
    <ul className="declaration-member-list">
      {rows.map((member) => (
        <li key={member.tag}>
          <strong>{member.name}</strong> ·{" "}
          {member.town_hall ? `TH ${member.town_hall}` : "TH unavailable"} ·{" "}
          <code>{member.tag}</code>
          <span className="declaration-member-context">{member.context}</span>
          {member.discord_id && member.discord_profile && (
            <DiscordIdentity
              userId={member.discord_id}
              resolvedMember={member.discord_profile}
              variant="compact"
              username={false}
            />
          )}
          {control && (
            <RosterFillerCheckbox
              {...control}
              tag={member.tag}
              name={member.name}
              value={!!member.roster_filler}
              markRevision={member.roster_filler_revision || 0}
            />
          )}
        </li>
      ))}
    </ul>
  );
}
