import { api } from "../api";
import type { AccountOverview } from "./types";

export async function loadAccountDetail(tag: string) {
  const query = `/strikes/accounts?query=${encodeURIComponent(tag)}&status=all`;
  const [ledger, activity] = await Promise.all([
    api<AccountOverview>(query),
    api<AccountOverview>(`${query}&activity=true`),
  ]);
  const canonical = ledger.accounts.find((row) => row.player_tag === tag);
  const observed = activity.accounts.find((row) => row.player_tag === tag);
  if (!canonical) return observed;
  return {
    ...canonical,
    ...observed,
    active_strikes: canonical.active_strikes,
    total_strikes: canonical.total_strikes,
    link_status: canonical.link_status,
  };
}
