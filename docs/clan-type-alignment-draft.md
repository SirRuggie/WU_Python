# Parked clan-type alignment — not approved for release

Prepared separately for handoff 112. Do not merge or include this commit in the
Family clans release until Ruggie decides the roster/signup scope.

The draft retains legacy Competitive and adds CWL to five existing readers:
LiveProviders.family_clans, member account directory validation, return dashboard
single/bulk directories, and the legacy Lazy CWL clan selector. It does not change
saved clan types, remove signups, or modify FWA-only filters. The provider change
also expands approved-clan/hosting choices and changes CWL account classification
from outside to approved. Those downstream effects are the pending decision.

Fixture census (not production): the provider test has one each of FWA, Tactical,
CWL, Competitive, CWL Hosting and Unknown. Four are accepted; CWL Hosting and
Unknown stay excluded. Flexible Fun remains accepted by the query but has zero
rows in this fixture. The member test separately exercises CWL and Competitive,
retaining each saved type. No production directory count is inferred.

The legacy info-hub Competitive-only display group still needs a separate scope
choice: adding CWL there changes its named group. It is inventoried but unchanged
in this draft. The configured editable CLAN_TYPES list remains unchanged; legacy
Competitive is preserved only in readers. Before release, incorporate the final
scope, review all readers and run the full regression suite and affected UI checks.
