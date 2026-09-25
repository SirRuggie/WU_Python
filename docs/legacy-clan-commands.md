# Retired clan information commands

`/clan info` and `/clan list` belonged to the previous bot setup and are disabled
for this server. They are absent from command registration and the help catalog.
The older `/clan dashboard` entry point was already retired in favor of `/manage`.

The associated legacy message controls are not registered:

- `clan_select_menu`
- `show_competitive`, `show_casual`, `show_zen`, `show_fwa`, `show_trial`
- `what_is_zen_info`, `what_is_fwa_info`
- `back_to_zen_clans`, `back_to_fwa_clans`

Clicks on old posts follow the dispatcher's unavailable/stale-panel response;
they cannot execute the old clan introduction or information handlers.
Existing posted messages and clan database records are not deleted.

The clan dashboard package still provides shared FWA editing and clan helpers
used by current features. `/manage`, recruitment, and `/family-links` remain
available. The `/family-links` action `view_clan_info` is a separate current
feature and is not part of the retired info hub.
