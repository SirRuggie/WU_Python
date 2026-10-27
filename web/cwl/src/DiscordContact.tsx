export function discordContact(userId?: string | null, compact = false) {
  return {
    href:
      userId && /^[0-9]{15,22}$/.test(userId)
        ? `https://discord.com/users/${userId}`
        : undefined,
    label: compact ? "DM ↗" : "Message on Discord ↗",
    unavailable: "No Discord linked",
    title: "Open their Discord profile, then choose Message",
  };
}
export default function DiscordContact({
  userId,
  compact = false,
}: {
  userId?: string | null;
  compact?: boolean;
}) {
  const contact = discordContact(userId, compact);
  if (!contact.href) return <small>{contact.unavailable}</small>;
  return (
    <a
      className="button discord-contact"
      href={contact.href}
      target="_blank"
      rel="noopener noreferrer"
      title={contact.title}
    >
      {contact.label}
    </a>
  );
}
