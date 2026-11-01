import DiscordIdentity, { discordIdentityName } from "../DiscordIdentity";
import { localMemberTime, type DirectoryMember } from "./model";
import { membersText as t } from "./strings";
import "./Members.css";
export default function MemberRow({
  member,
  selected,
  onSelect,
  onOpen,
  pending = false,
  error = "",
}: {
  member: DirectoryMember;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
  pending?: boolean;
  error?: string;
}) {
  const profile = {
    id: member.discord_id,
    display_name: member.name,
    ...member.discord_profile,
  };
  const name =
    discordIdentityName(
      member.discord_id,
      profile,
      member.nickname || member.name,
    ) || t.unavailable;
  const zone = member.profile?.gmt_label || member.parsed?.label;
  const local = localMemberTime(member);
  return (
    <article className="members-person" data-member-id={member.discord_id}>
      <label className="members-row-select">
        <input
          type="checkbox"
          checked={selected}
          disabled={member.bot}
          aria-label={t.selectOne(name)}
          onChange={onSelect}
        />
        <span className="sr-only">{t.selectOne(name)}</span>
      </label>
      <button
        type="button"
        className="members-person-open"
        onClick={onOpen}
        aria-label={`${t.openPerson}: ${name}`}
      >
        <DiscordIdentity
          userId={member.discord_id}
          resolvedMember={profile}
          displayName={member.name}
          variant="compact"
          contact={false}
        />
        <span className="members-person-zone">
          {member.profile?.flag || t.noFlag} · {zone || t.noZone}
          {local && ` · ${t.localTime(local)}`}
        </span>
      </button>
      {pending && <p role="status">{t.pending}</p>}
      {error && <p role="alert">{error}</p>}
    </article>
  );
}
