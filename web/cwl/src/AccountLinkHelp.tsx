/** Linking remains with the providers; this dashboard only reads their links. */
export default function AccountLinkHelp({ onRefresh, busy = false }: { onRefresh: () => void; busy?: boolean }) {
  return <div className="account-link-help">
    <p>Link your player accounts to the same Discord account you use here.</p>
    <ol>
      <li>Open Discord and use ClashKing’s <code>/link</code> or ClashPerk’s <code>/link create</code> command.</li>
      <li>Choose your player tag and follow the bot’s instructions. If verification is requested, find your API token in Clash of Clans under Settings → More Settings.</li>
      <li>Return here and check your linked accounts. New links may take a minute to appear.</li>
    </ol>
    <div className="signup-action-buttons"><a className="button" href="https://discord.com/channels/644963518025826315" target="_blank" rel="noopener noreferrer">Open Discord</a><button disabled={busy} onClick={onRefresh}>{busy ? 'Checking accounts…' : 'Check linked accounts'}</button></div>
    <p className="small">Already linked but missing here? Check that you used the same Discord account and that the link is visible to shared lookups. If the bots show different owners, ask staff to help correct the link.</p>
  </div>
}
