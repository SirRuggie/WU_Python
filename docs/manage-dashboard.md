# Server Management

`/manage` opens the private Warriors United management home. It brings
the existing editors together; their stored data and publishing workflows stay
in their existing systems. The optional `section` dropdown jumps directly to
a workspace. Omitting it, or choosing Server, opens home. These are choices
on one command, not separate subcommands.

| Command | Workspace | Purpose |
| --- | --- | --- |
| `/manage` | Server Management | Choose a management workspace |
| `/manage section:Roles` | Roles | Add or remove roles for a member; browse a role’s complete member list and count |
| `/manage section:Recruit Gauntlet` | Recruit Gauntlet | Edit onboarding text and artwork, choose each section’s channel, and send About Us, WU Strike System, or Family Particulars |
| `/manage section:Recruitment Questions` | Recruitment Questions | Edit all Primary, FWA, Explanation, and Keep It Moving messages |
| `/manage section:FWA` | FWA | Choose Bases & Guidance, War Messages, Points Monitor, or Sync & Reminders |
| `/manage section:CWL` | CWL | Manage campaign messages, schedules, and delivery settings |
| `/manage section:CWL Rosters` | CWL Rosters | Manage saved Main/FWA rosters and FWA return reminders |

Recruit Gauntlet is the onboarding **content editor**. The member-specific
`/recruit dashboard` workflow remains separate. The old `/content dashboard`,
`/cwl dashboard`, `/cwl rosters`, and `/clan dashboard` slash-command entry
points have been removed. Open these management workspaces through `/manage`.

## Permissions and interaction design

The home shows six named workspaces with separators and Open buttons.
Workspaces outside the current member's access are locked. Back returns to
the previous screen; Management Home returns to the central dashboard. Each
workspace rechecks its existing authorization rules: Manage Server or
Administrator for onboarding content and recruitment questions, Administrator for CWL campaigns and
rosters, the FWA Representative role for FWA data, and the FWA Clan Rep role
used by `/fwa war-plans` for War Messages, and Administrator for Points Monitor and Sync & Reminders. Opening the management
home does not grant new privileges.

Normal management screens use the bot's gold accent. Labels and explanatory
text communicate state without relying on color. Destructive actions retain
their explicit warning and confirmation flows. Management responses are private;
publishing content or sending announcements still requires the destination
editor's explicit action.

Leaving a Recruit Gauntlet document for its document list or Management Home
requires confirmation only when its text or artwork differs from the last saved
(or initially opened) version. Unchanged drafts return immediately. Channel
selections are saved immediately and do not trigger the unsaved-edit warning.
Save the template first to retain edits; reopening starts a new content draft.
CWL campaign drafts are retained and resumed by the existing campaign editor.

## Research basis

The implementation follows Discord's native interaction model:

- [Application Commands](https://docs.discord.com/developers/interactions/application-commands):
  one discoverable command with an optional workspace choice.
- [Component Reference](https://docs.discord.com/developers/components/reference):
  Components V2 containers, concise button labels, grouped actions, no more than
  40 total message components, and unique custom IDs within Discord's limit.
- [Receiving and Responding](https://docs.discord.com/developers/interactions/receiving-and-responding):
  acknowledge before slow work, preserve private response visibility, and use
  message updates for navigation.

The existing editor guides document publication, drafts, and operational behavior:
[onboarding content](content-dashboard.md), [CWL campaigns](cwl-dashboard.md),
and [CWL rosters](lazycwl-dashboard.md).

[FWA War Messages](fwa-war-messages.md) documents the war-template editor,
preview behavior, and how saved changes reach future war-plan posts.

[Recruitment Questions](recruitment-questions.md) documents the main-question
message templates and the recruit-specific sending flow.

The legacy `/clan info` and `/clan list` commands and their public info/list
component handlers are also disabled. The active FWA workspace and recruitment
workflows retain their shared clan data and dashboard helpers.

## Roles

`/manage section:Roles` replaces `/role add`, `/role remove`, and `/role manage`.
Use the member and role selectors to prepare a change, then explicitly add or
remove the selected roles. The recruitment-specific **Apply Recruit Setup** shortcut remains in
`/recruit dashboard`. Multiple roles may be selected; each role is checked
individually, and unrelated roles are left intact.

Access remains limited to configured Main/FWA recruiters, the Recruitment Team,
and administrators. Each action rechecks access and role/member hierarchy;
integration roles, @everyone, and roles the bot cannot manage cannot be changed.

The role browser lists everyone holding a selected role, including bot accounts,
with a total and paginated member list. It fetches the complete server membership
instead of counting a potentially incomplete cache. Refresh updates the snapshot.
If Discord refuses the lookup, the panel reports the failure rather than showing
a misleading zero. These panels are private, with Back and Management Home
navigation, and expire after 30 minutes.

## FWA

FWA opens a gold submenu with four sections. **Bases & Guidance** is the existing
base-link, image, description, and Town Hall editor. **War Messages** edits the
four reusable war-announcement templates. **Points Monitor** controls automatic
points monitoring and shows current status and watched-clan results.
**Sync & Reminders** controls the BAND calendar poller and signup-panel destination.

The FWA entry is available when staff can access at least one of its sections;
other sections remain locked. Each section returns with **Back to FWA** and the
submenu has **Management Home**. War-message drafts still warn before abandoning
unsaved edits.

Points Monitor replaces `/fwapoints enable`, `disable`, `watch-add`,
`watch-remove`, and `status`. These controls use the existing monitor configuration
and do not create a second monitor. Automatic FWA clans stay sourced from clan
data; only manually added extras can be removed from this panel. The former
`/fwa points` results are also included here: verdict, war and sync numbers,
point balance, update time, and a link to each clan’s points page. See [FWA points monitor](fwa-points-monitor.md).

### Sync & Reminders

This Administrator-only panel replaces `/fwasync`. It offers status and recent
results, Enable/Disable, a feed check that sends no messages, an explicit test DM
to the clicking administrator, a native signup-channel dropdown, and a BAND
fallback-link editor. Channel selection checks the bot's destination permissions.
Return with **Back to FWA** or **Management Home**.

Members keep choosing their own reminders: one hour before, ten minutes before,
and at sync time. These are displayed as information, not an arbitrary offset
editor that could disagree with the public signup panel. The scheduler honors
supported member selections even if an older config omitted one of those times.

Legacy fixed-recipient broadcasts and their two settings are removed. Old saved
recipient fields are ignored; no historical data is deleted. Queued deliveries
without a current opt-in, or whose reminder was withdrawn, are abandoned without
sending. Existing signup responses and explicit **DM me the time** remain intact.
