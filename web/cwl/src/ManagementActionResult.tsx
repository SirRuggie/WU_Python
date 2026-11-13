import { countLabel } from "./countLabel";
import { safeDiscordUrl, type ManagementResult } from "./serverManagement";

export default function ManagementActionResult({
  actionResult,
}: {
  actionResult: ManagementResult;
}) {
  return (
    <section className="manage-result" aria-label="Action result">
      <h3>Result</h3>
      {actionResult.message && <p>{actionResult.message}</p>}
      {actionResult.details && (
        <p className="manage-result-details">{actionResult.details}</p>
      )}
      {safeDiscordUrl(actionResult.url) && (
        <a
          className="target-44"
          href={safeDiscordUrl(actionResult.url)!}
          target="_blank"
          rel="noopener noreferrer"
        >
          View in Discord ↗
        </a>
      )}
      {actionResult.accounts && (
        <>
          <p>{countLabel(actionResult.accounts.length, "account")}</p>
          <ul>
            {actionResult.accounts.map((account, index) => (
              <li key={`${account.tag || account.player_tag || index}`}>
                <strong>
                  {account.name || account.player_name || "Account"}
                </strong>
                <span>{account.tag || account.player_tag}</span>
                <small>
                  {account.current_clan_name ||
                    account.clan_name ||
                    (typeof account.current_clan === "string"
                      ? account.current_clan
                      : account.current_clan?.name) ||
                    account.clan?.name ||
                    "No current clan"}
                </small>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
