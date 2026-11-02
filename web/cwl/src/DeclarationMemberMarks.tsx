import DiscordIdentity from "./DiscordIdentity";
import DiscordContact from "./DiscordContact";
import type { DeclarationExtraClan } from "./declarationExtras";
import RosterFillerCheckbox, {
  type FillerSaveResult,
} from "./RosterFillerCheckbox";
export type DeclarationMarkControl = {
  seasonId: string;
  revision: number;
  onChanged: (result?: FillerSaveResult) => void | Promise<void>;
  disabled?: boolean;
};
type Member = NonNullable<DeclarationExtraClan["extras"]>[number];
export default function DeclarationMemberMarks({
  rows,
  control,
}: {
  rows: Member[];
  control?: DeclarationMarkControl;
}) {
  const groups = new Map<string, { userId?: string; accounts: Member[] }>();
  for (const row of rows) {
    const userId =
      row.discord_id && /^[0-9]{15,22}$/.test(row.discord_id)
        ? row.discord_id
        : undefined;
    const key = userId ? `member:${userId}` : `account:${row.tag}`;
    const group = groups.get(key) || { userId, accounts: [] };
    if (!group.accounts.some((account) => account.tag === row.tag))
      group.accounts.push(row);
    groups.set(key, group);
  }
  return (
    <ul className="declaration-member-list">
      {[...groups.entries()].map(([key, group]) => {
        const profile = group.accounts.find(
          (account) => account.discord_profile?.id === group.userId,
        )?.discord_profile;
        return (
          <li key={key} className="declaration-member-group">
            {group.userId && (
              <DiscordIdentity
                userId={group.userId}
                resolvedMember={profile || null}
                variant="compact"
                username={false}
                contact={false}
              />
            )}
            <ul className="declaration-member-accounts">
              {group.accounts.map((member, index) => (
                <li
                  key={member.tag}
                  className={`declaration-member-account${member.not_published_yet === true ? " is-unpublished" : ""}`}
                >
                  <strong>{member.name}</strong> ·{" "}
                  {member.town_hall
                    ? `TH ${member.town_hall}`
                    : "TH unavailable"}{" "}
                  · <code>{member.tag}</code>
                  {member.not_published_yet === true && (
                    <span className="declaration-member-context">
                      Moved here · not published yet
                    </span>
                  )}
                  <span className="declaration-member-context">
                    {member.context}
                  </span>
                  {(control || (index === 0 && group.userId)) && (
                    <div className="declaration-member-actions">
                      {control && (
                        <RosterFillerCheckbox
                          {...control}
                          tag={member.tag}
                          name={member.name}
                          value={!!member.roster_filler}
                          markRevision={member.roster_filler_revision || 0}
                        />
                      )}
                      {index === 0 && group.userId && (
                        <DiscordContact
                          userId={group.userId}
                          compact
                          className="declaration-member-dm"
                        />
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}
