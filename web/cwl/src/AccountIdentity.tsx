import type { Session } from "./api";
import DiscordIdentity from "./DiscordIdentity";
export function AccountIdentity({ user }: { user: Session["user"] }) {
  return (
    <DiscordIdentity
      userId={user.id}
      resolvedMember={user}
      variant="compact"
      contact={false}
      username={false}
      className="user-pill"
    />
  );
}
