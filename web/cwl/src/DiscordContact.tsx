export default function DiscordContact({userId, compact=false}:{userId?:string|null;compact?:boolean}) {
  if (!userId || !/^[0-9]{15,22}$/.test(userId)) return <small>No Discord linked</small>
  return <a className="button discord-contact" href={`https://discord.com/users/${userId}`} target="_blank" rel="noopener noreferrer" title="Open their Discord profile, then choose Message">{compact ? 'DM ↗' : 'Message on Discord ↗'}</a>
}
