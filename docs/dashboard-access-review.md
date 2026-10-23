# Dashboard access and member administration review

Reviewed October 23, 2026. Scope: owner access directory/editor and shared member
selection for Discord role administration. Existing owner identities, grants,
permission IDs, Mongo storage and routes are preserved; no migration is needed.

## Changes

- Protected owners use the same read-only Discord identity lookup as staff:
  display name, username, avatar and explicit Discord ID. Missing/unavailable
  identities remain distinguishable. Presentation does not confer authority.
- Permission sections disclose individual switches and show enabled counts.
  Pending additions/removals are summarized before saving. Only the two existing
  owners manage access; user and role grants remain additive.
- Save has a synchronous duplicate guard. A revision conflict preserves the draft
  and blocks resubmission until refresh. Unsaved edits and in-flight writes protect
  navigation. Successful saves return focus to the directory heading.
- Single-member pickers compact after selection, with a deliberate Change member
  action. Changing the member clears draft role choices. Role actions stay separate
  from dashboard grants and retain Discord hierarchy checks.
- Non-owners are not offered roles that confer dashboard access; the write endpoint
  independently rechecks the current policy before changing roles.

## Evidence

- 281 frontend tests passed, including compact identity selection without a write.
- 56 focused backend tests passed: identity fallbacks, protected owners, current
  permissions/revocation, role failures, CAS conflicts, malformed input, hierarchy,
  protected grant roles and role mutation behavior. Existing aiohttp warnings remain.
- Production frontend build passed. Existing bundle-size warning remains.
- Isolated browser inspection at 320, 390 and 1280 pixels: owner avatars and IDs,
  long names, disclosure counts, individual toggles, pending changes, removal
  cancellation and stacked buttons, conflict draft preservation, refresh recovery,
  successful save and return focus. No horizontal clipping observed. A duplicated
  section legend found during inspection was given locally scoped hidden styling.
- Read-only lookup using deployed service credentials resolved both real protected
  owners' names, usernames and avatars successfully.

## Limits

Browser writes used isolated fixture data; no real access grants, Discord roles,
owner IDs or messages were changed. This is not a live role-delivery test. Physical
Android/iOS, full screen-reader and high-zoom testing remain outstanding. Discord
role changes and policy edits are not a cross-system transaction: hierarchy and
policy are checked before writes, but an external concurrent change remains a
limit. Partial role-delivery failures require reviewing current roles; no blind
notification retry was introduced. Mongo remains the durable policy owner.
