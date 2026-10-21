# WU dashboard interaction standard

Use this standard for new or meaningfully changed dashboard workflows. The family
clan reminder overview is the first complete application, not a claim that every
existing dashboard screen already meets these rules or is WCAG-certified.

## Evidence and design comparisons

These are comparisons with published administrative product/design-system patterns,
not claims of testing private installations of other products.

| Reference | Useful pattern | WU application |
| --- | --- | --- |
| [IBM Carbon data tables](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) | Keep search, filters, and global actions together; use expansion for secondary detail. | Searchable family index, count filters, explicit row action, separate clan editor. |
| [Shopify Polaris patterns](https://polaris-site-prod-kit.shopify.prod.shopifyapps.com/patterns) | Resource indexes organize objects and the actions taken on them; loading should preserve context. | Overview to clan editor and back, preserving filters and focus; no duplicate editing system. |
| [Atlassian empty states](https://atlassian.design/components/empty-state/) | Explain the absence of data and what the user can do next. | Different loading, empty family, unmatched filter, and service-failure states. |
| [Carbon disclosures](https://www.carbondesignsystem.com/building-blocks/core/patterns/disclosures) | Reveal secondary interactive content when requested. | Testing, verbose history, and explanation sections start collapsed. |
| [GOV.UK validation recovery](https://design-system.service.gov.uk/patterns/validation/) | Distinguish user input errors from service/permission problems and provide recovery. | Preserve edits after failed saves; service retry does not masquerade as an empty family; revoked access clears overview data. |
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Keyboard operation, visible/unobscured focus, adequate targets, reflow, and status feedback. | Native controls, manual-activation settings tabs, mobile cards, visible focus, 44px control targets, and short-screen sticky-bar fallback. |

## Required interaction rules

1. **Design around frequency.** The landing view answers what exists, what is on,
   and what needs attention. Open an editor for changes. Collapse occasional tools
   and long explanations, but never hide the only indication of an error.
2. **Keep the user's place.** Preserve search/filter state when returning from a
   detail view. Restore focus to the triggering row, falling back to the overview
   heading if that row has disappeared. Avoid automatic scrolling during refresh.
3. **Use explicit actions.** Name the action and its object. Opening a row must not
   enable a feature, send a message, or save edits. Keep the existing channel picker,
   provider APIs, and editor instead of building duplicate implementations.
4. **Be honest about state.** Enabled is not healthy. Differentiate missing setup,
   disabled, awaiting verification, current monitoring, outdated checks, and failed
   or uncertain delivery. Display dates for checks and deliveries. Exclude sample
   sends from scheduled-delivery health. Never use color alone to communicate status.
5. **Separate absent data from failed loading.** Initial loading, an empty account,
   no filter matches, an unavailable service, and lost permission need distinct
   feedback. A failed refresh may retain clearly labeled old data; a 401/403 must
   clear protected overview data. Retrying a read must not retry a notification.
6. **Protect work.** Preserve unsaved input after errors, confirm discarding it, and
   block conflicting local actions while a mutation is pending. Settings use
   revisions. Notifications use durable request identities and do not automatically
   replay an uncertain delivery.
7. **Make mobile an equally complete workflow.** Use one-column labeled records
   when a comparison table no longer fits. Avoid horizontal page scrolling and
   hover-only controls. Retain all important fields and actions. Prefer 44px tap
   targets (a product standard stronger than WCAG 2.2 AA's 24px minimum, which has
   documented exceptions). Test at 390px and 320px as well as desktop.
8. **Use native semantics and predictable movement.** Use buttons for actions,
   links for destinations, details/summary for disclosures, labeled inputs, and
   semantic tables. Settings tabs use arrow/Home/End focus movement and Enter/Space
   activation. Focus must stay visible above sticky controls; disable sticky save
   bars on short viewports. Honor reduced-motion preferences. No decorative motion
   is needed to make an administrative interface feel polished.
9. **Refresh without fighting the user.** Poll only visible/active views. Prevent
   overlapping reads, ignore responses for abandoned views, and preserve filters.
   Keep a visible refresh action and last-loaded time. Do not load preview data
   while the preview section is collapsed.
10. **Reuse visual hierarchy.** One page heading, one focused task heading, a compact
    toolbar, then content. Use restrained colors and consistent spacing; amber is
    attention or selection, never the sole status signal. Avoid adding cards,
    switches, warnings, and explanatory paragraphs without a specific user need.

## Review before shipping

Run the feature's automated quality gate, then verify the actual rendered UI with
isolated data. For clan management use `./.venv/bin/python tools/check_war_reminders.py`.

- Complete search → filter → open clan → edit/save → return, using mouse and keyboard.
- Check long names, symbols, 25+ clans, no clans, no matches, disabled setup, missing
  channels, stale checks, settings changed since last check, and uncertain sends.
- Fail a read and a save; revoke permission; leave while a read is in flight.
  Confirm no stale response overwrites a newer view and no failed read changes data.
- Check narrow/short viewports, focus visibility, labels, and target sizes. Browser
  accessibility-tree checks help but do not replace testing with assistive technology.
- Verify a sample Discord rendering independently of dashboard navigation. UI tests
  do not prove live push notifications. Send live tests only to authorized destinations.
- Record scope, passed checks, existing warnings, and remaining limitations. Avoid
  claiming exhaustive coverage of the entire bot from a feature-specific review.

## Next adoption opportunities

Apply this standard as ticket, roster, announcement, and campaign workflows are
next changed. Audit their landing summaries, empty/error states, save boundaries,
return navigation, and occasional diagnostic tools before redesigning visuals.
Do not introduce an app-wide component library or bulk rewrite merely to conform
names: extract a shared component when multiple real uses need the same behavior.
