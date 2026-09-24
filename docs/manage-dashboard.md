# Server Management

`/manage` opens the private Warriors United management home. It brings
the existing editors together; their stored data and publishing workflows stay
in their existing systems. The optional `section` dropdown jumps directly to
a workspace. Omitting it, or choosing Server, opens home. These are choices
on one command, not separate subcommands.

| Command | Workspace | Purpose |
| --- | --- | --- |
| `/manage` | Server Management | Choose a management workspace |
| `/manage section:Recruit Gauntlet` | Recruit Gauntlet | Edit onboarding messages and artwork: About Us, WU Strike System, and Family Particulars |
| `/manage section:FWA` | FWA | Manage base links, images, descriptions, and Town Hall upgrade notes |
| `/manage section:FWA War Messages` | FWA War Messages | Edit Win, Lose, Mismatch, and Blacklisted war-plan templates |
| `/manage section:CWL` | CWL | Manage campaign messages, schedules, and delivery settings |
| `/manage section:CWL Rosters` | CWL Rosters | Manage saved Main/FWA rosters and FWA return reminders |

Recruit Gauntlet is the onboarding **content editor**. The member-specific
`/recruit dashboard` workflow remains separate. The old `/content dashboard`,
`/cwl dashboard`, `/cwl rosters`, and `/clan dashboard` slash-command entry
points have been removed. Open these management workspaces through `/manage`.

## Permissions and interaction design

The home shows five named workspaces with separators and Open buttons.
Workspaces outside the current member's access are locked. Back returns to
the previous screen; Management Home returns to the central dashboard. Each
workspace rechecks its existing authorization rules: Manage Server or
Administrator for onboarding content, Administrator for CWL campaigns and
rosters, the FWA Representative role for FWA data, and the FWA Clan Rep role
used by `/fwa war-plans` for FWA War Messages. Opening the management
home does not grant new privileges.

Normal management screens use the bot's gold accent. Labels and explanatory
text communicate state without relying on color. Destructive actions retain
their explicit warning and confirmation flows. Management responses are private;
publishing content or sending announcements still requires the destination
editor's explicit action.

Leaving a Recruit Gauntlet document for its document list or Management Home
requires confirmation.
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
