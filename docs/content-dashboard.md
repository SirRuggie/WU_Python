# Content dashboard

The shared management home is `/manage`; choose **Recruit Gauntlet** for this
onboarding editor, or use the optional `section` choice to open it directly.
See [Server Management](manage-dashboard.md) for navigation and permissions.

Recruit Gauntlet is a private, per-server Components V2 editor for Join the Family, About Us,
WU Strike System, Family Particulars, WU FAQ, and shared Family Rules, as well as
the existing Apply and Rite of Passage templates. Administrators with Manage Server can
edit named sections with heading and body together, replace images in R2, preview the public layout,
save a reusable template, and send the current draft to a selected channel.

Manage CWL messages, artwork, destinations, and timing through **CWL** in
`/manage` (or its optional `section` choice); see [CWL dashboard](cwl-dashboard.md).

## Choose a channel and send

Each public document (Join the Family, About Us, WU Strike System, Family Particulars, and WU FAQ) has its own
native Discord channel dropdown and **Send to channel** button. Choose a text
or announcement channel in this server. The choice is saved per server and
document and is shown in the editor when reopened. MongoDB stores it separately
from template text under `content_destination:<server id>:<document>` in
`bot_config`.

**Send to channel** publishes the current draft, including its text and artwork.
**Save template** separately saves those edits as the starting point for future
editing. Sending does not overwrite earlier posts or save the draft as a template.
After a successful send, the editor provides a link and remembers the posted message
under `content_published:<server id>:<document>` in `bot_config`. Reopening the
document loads that exact bot-authored post as the update target. Changing the
posting channel never silently retargets an unrelated message.

The acknowledgement buttons and their role grants remain attached to the posted
messages. The selected destination controls where this document is posted; it
does not change the existing acknowledgement roles or next-step channel links.
Bot access to the destination and acknowledgement setup are checked before sending.

The dashboard replaces `/setup recruit-aboutus`, `/setup recruit-strikesystem`,
and `/setup recruit-familyparticulars`; those three slash commands are retired.
`/setup recruit-check` remains available for onboarding diagnostics.

## Edit a section and update its post

The dropdown lists logical sections rather than separate heading/body entries.
A section's modal puts **Heading / Title** above **Body**. Decorations are preserved;
a section that genuinely contains only a heading does not invent a body.
Existing stored text layouts remain compatible.

After a text edit, the editor offers to update the linked published message.
The confirmation identifies that post; updates edit its existing message ID,
retain acknowledgement buttons and needed attachments, and guard against a post
that changed elsewhere. Deleted or inaccessible posts produce actionable feedback,
not an automatic duplicate. Template saving and publishing results are reported
separately when one succeeds and the other fails.

Existing Join the Family, About Us, and WU Strike System posts have been linked.
Family Particulars will be tracked on its first successful **Send to channel**.

## Replace an image

1. Open `/manage` and choose **Recruit Gauntlet**.
2. Choose the document to edit.
3. Select the image in the image menu. The editor shows its current draft image
   beneath the menu so you can confirm the selection, then click **Upload replacement**.
4. Choose a PNG, JPG, GIF, or WEBP in Discord's upload modal. It must fit the
   bot's 10 MB byte and 40-million-pixel limits.
5. The preview refreshes to the uploaded image in the same private editor.
   The image is uploaded to R2 but is still
   a draft; the template and public post have not changed.
6. Use **Preview**, then **Save template** for future setup posts. Saving a
   template does not update previously published messages.

Images are uploaded through the dashboard's **Upload replacement** button;
there is no separate upload command. The uploader must still own the draft,
be in the same guild, and have Manage Server permission.

To restore the original artwork, select the image and click **Restore default
image**, then preview and use the green **Save template** button.
The restore button is disabled when the draft already uses the default image.
The selection stays active and the editor immediately shows the restored default.

| Document           | Editable images                                                     |
| ------------------ | ------------------------------------------------------------------- |
| Join the Family    | Welcome banner                                                      |
| About Us           | Welcome banner                                                      |
| WU Strike System   | Basic rules banner; main clan strike chart; FWA strike chart        |
| Family Particulars | Welcome banner; CWL banner                                          |
| WU FAQ             | None; Who we are, registry clans, shared Family Rules and Questions |
| Family Rules       | None; shared Heading and Body, with no standalone post              |

## WU FAQ and shared Family Rules (259)

**Family Rules** has two editable fields, Heading and Body, under
`content:family-rules:<guild id>`. The body may contain Markdown subheadings.
It has no posting channel, Send button, acknowledgement button, or role grant.
**WU FAQ** is one public Components V2 message with four containers: Who we are
(gold), Our Clans (green), shared Family Rules (red), and Questions (no accent).
The seven new Who/Clans fields are editable; clan names/tags are generated by the
same single read-only filtered, sorted and Markdown-escaped registry used by
About Us. CWL, archived and removed clans are excluded. A failed, incomplete or
empty type list blocks Preview, Send and Update; no empty fallback is posted.

`content:wu-faq:<guild id>` retains Questions heading/body at indices 0/1 and
appends seven fields. Existing saved Questions strings and revision are preserved
exactly; missing new fields read as the approved defaults. Neither template reads
nor legacy published-message import rewrites stored data. Changes persist only on
an explicit Save. Staff-facing Warrior Desk labels and saved panel text remain
unchanged; only the member-facing default heading is Warrior Help Desk.

After saving Family Rules, explicitly choose **Update linked posts** to update
the existing linked WU FAQ and About Us messages. The offer identifies each
post and snapshots its complete text and media. Confirmation rechecks the saved
rules revision, tracked message pointer, guild, author, layout, text, media, and
each existing publication lease. It preserves each published post's own text and
artwork. One successful update and one failed update are reported separately;
the rules stay saved. Saving does not send a new message or automatically edit
either post. An interrupted or uncertain update is not automatically retried;
check the existing posts before opening a fresh review. Drafts and update claims
survive a restart for their existing component-state lifetime.

The existing web content adapter passes its database/guild context to the same
renderer. Family Rules has no web channel or publish action either. After saving
shared rules from the web editor, open Family Rules in Discord `/manage` to review
and explicitly update its linked posts.

The current plain-content WU FAQ is not adopted, edited, or deleted by this
feature. An administrator must explicitly send the new V2 FAQ and separately
remove the old post when authorized. Untracked plain messages cannot become
update targets by guessing their type.

About Us retains its twelve legacy fields, appends the approved box headings and guide, and inserts Family Rules in its own red container immediately
before Next Step. Tactical, Flexible Fun, and FWA names/tags and the corresponding
offer counts are derived from one read-only clan-registry query. CWL, archived,
and removed clans are excluded; names are sorted, and clan names are escaped for
Discord Markdown. The registry is read only when rendering Preview, Send, or Update. Native
menu/template selection does not read it. About Us retains its existing eager web
preview. WU FAQ editor GET loads only editable text; its visible web preview uses
the existing Preview POST, including for a clean document. A hidden mobile preview
does not query the registry; opening Preview does. Explicit and automatic preview
requests are deduplicated. A registry failure or incomplete active list is visible
and blocks sending/updating; it never posts empty fallback lists.

Existing saved About Us templates are not migrated or rewritten on read. Only
leading old manual name/tag lines are omitted when composing the public clan
details; description text remains intact. Legacy V2 About Us posts can still be
reviewed as linked targets before their first explicit update to the new layout.

The authoritative November 20 final-copy fixture with ten clans in **each** of
the three types renders **3,831 characters**, leaving **169** under the existing
4,000-character policy. The extra old built-in-copy comparison renders **4,161**
and remains over the limit. Real clan names or saved text may be longer: the full
rendered payload, including rules and generated lists, is checked before Preview,
Send, and Update. Over-limit text is shown as an actionable error; no copy is cut,
saved data rewritten, or template silently substituted.

Strike System's first four labels are **How strikes work heading**, **How strikes
work**, **At 4 strikes heading**, and **At 4 strikes**. Family Particulars uses
**Intro heading** and **Intro** in place of Golden rule labels. These label changes
do not change field counts, order, decorations, roles, or routing.

Validation covers exact approved copy, registry filtering/sorting/counts/failure,
rendered-size boundaries, saved-data preservation, permission and draft ownership,
rules CAS conflicts, no-ack/no-Send controls, linked stale/media/pointer guards,
partial update/restart behavior, and disabled mentions. Tests use synthetic clans
and simulated Discord responses; they do not prove live delivery. The final review
report records the focused and builder network-isolated full-suite results. 270 also checks the generic web preview change with full frontend/type validation,
then builds the exact committed frontend once for review.

## Storage and publication

Templates live at `content:<document>:<guild id>` in MongoDB with text sections,
named `media` overrides, a revision, and the most recent editor/time. Missing
media fields retain the bundled defaults, so existing records require no bulk
migration. About Us also reads its previous `recruit_aboutus:<guild id>` record
when no unified template is available.

Uploads use `content/recruit/<guild id>/<document>/<slot>.<hash>.<extension>` in
R2. Changed image bytes produce a new URL. Previous objects remain available
because older posts may still reference them. Abandoned drafts can therefore
leave unused objects; automatic garbage collection and full revision-history
restore are not included. Reset restores the bundled default, not an arbitrary
previous uploaded version.

Drafts expire after 30 minutes and recheck user, guild, and Manage Server on
every interaction. Saving uses revision compare-and-swap. Linked post adoption
checks the bot author, guild, layout, text, and media. Updating a linked post
uses a short lease and rejects changes made since the draft opened. Discord's
rotating attachment signatures are normalized when comparing image identity.
When editing, the bot retains existing Discord attachments still used by the
rendered galleries and replaces unused ones. Legacy artwork adopted from a
Discord attachment still depends on that source attachment; use R2 uploads for
independent, durable image hosting. A saved reference is not a backup of a
Discord attachment that is later deleted or replaced.

Preview uses the public renderer and reuses its acknowledgement button as
**Back to editor**. This keeps Family Particulars within its existing 40-component
layout. Decorative text stays fixed and still counts toward the bot's
4,000-character total policy. Published acknowledgement actions retain their
original role behavior.

WU FAQ and Family Rules have no public acknowledgement control. Their private
previews add a separate Back to editor button, which is never part of a sent post.

## Setup checks

Run `/setup recruit-check` in the intended posting channel for a private
Components V2 report. The three `/setup recruit-*` commands now require Manage
Server and check prerequisites before posting: current-channel permissions,
acknowledgement role existence and assignability, and next-channel guild/type.
The report also indicates whether R2 configuration is present; this is not a
live bucket write test.

The onboarding role/channel IDs remain the current configured constants. The
check does not prove that every recruit's channel overwrites allow the next
step. Validate that with a test member during deployment.

See [research, architecture decision, and evidence](recruit-content-improvements.md)
for the primary sources and remaining design work.

## Native upload compatibility and verification

Discord's [File Upload component](https://docs.discord.com/developers/components/reference#file-upload)
uses a Label (type 18) containing a File Upload (type 19). Submission values
identify entries in `data.resolved.attachments`. The pinned Hikari 2.6.0 does
not expose those modal fields, so `utils/discord_file_upload.py` preserves only
`content_upload_submit:` submissions for one-shot consumption. Its cache is
bounded to 256 entries and expires entries after 20 minutes. `main.py` installs
the adapter before constructing `GatewayBot`, which caches its deserializers.

Verification on 2026-09-22:

- 18 native-upload tests cover documented payload deserialization, startup
  ordering, modal construction, dispatcher routing, same-editor updates,
  permissions/ownership/expiry, invalid files, upload failures, row limits,
  and the existing text-modal path.
- 141 focused upload, dashboard, dispatcher, state, startup, storage, and
  recruit-setup tests passed. Compilation and diff/encoding/structure checks
  passed.
- The full suite produced 2,320 passes, 2 skips, and 3 failures. All three
  failures were reproduced from unchanged baseline commit `1580736`: two
  clan-logo error-response fixtures lack the required role/context shape,
  and the help-catalog test expects 104 paths where the baseline has 105.
- A sandbox-only asyncio stall was isolated: the same card-trading test
  completed outside the sandbox. The full suite above ran outside it.

These tests exercise application/SDK behavior with simulated Discord uploads;
they do not establish a successful upload from a live Discord client.

## Join the Family

The first Gauntlet section is **Join the Family**, followed by About Us, WU Strike
System, and Family Particulars. Its WU_GOLD welcome card uses the shared Warriors
United banner and editable welcome/next-step copy. Choose its posting channel,
preview, save the template, and send it through the same editor as the other sections.

The public **Join the Family** button grants role `1551011479577165844` in the
server containing About Us (`1547241886954168430`). It then responds privately
with **Continue to About Us**. Discord cannot force a client to switch channels;
the recruit presses that link to continue. Existing role holders can use the
button again without a duplicate grant. Failed grants do not show a success link.
The shared public card is never replaced with one recruit's result.

The role has View Channel and Read Message History access to About Us. No
standalone setup command is added. Text and image changes are saved in
`bot_config` as `content:join-family:<guild id>`; the destination uses
`content_destination:<guild id>:join-family`.

About Us now grants role `1553110276251979937` and privately offers
**Continue to WU Strike System** for channel `1547242610819604560`.
This continues the Gauntlet; it does not imply recruitment acceptance.
The role can view and read that channel. The saved template and existing
About Us post use the updated next-step instructions rather than the old direct link.

## Standing Gauntlet channel permission convention

Each acknowledgement role must have an explicit overwrite on its next-step channel:
**View Channel: allow**, **Read Message History: allow**, and
**Send Messages: deny**. Apply this same read-only configuration to future
Gauntlet steps, preserving unrelated permission bits. Verify the overwrite after
changing it. This convention currently applies to:

- Join the Family role `1551011479577165844` in About Us `1547241886954168430`.
- About Us role `1553110276251979937` in WU Strike System `1547242610819604560`.

WU Strike System grants role `1553110508746448956` and privately offers
**Continue to Family Particulars** for channel `1547242699873325116`.
The role follows the same read-only convention: View Channel and Read Message
History allowed, Send Messages denied. Its saved template and future posts use
button-based next-step instructions, and the handler survives restarts.

Family Particulars completes the reading steps by granting role
`1553110621711634502` and privately offering **Continue to Apply** for the main
tickets application channel `1547242779711766528`. Recruits open one application
ticket there; this does not imply acceptance into the family. The acknowledgement
uses the same persistent, fresh-member role checks as the other Gauntlet steps.
The application-channel role overwrite allows View Channel and Read Message
History and denies Send Messages, preserving other permission settings.

## Gauntlet help and inactivity reminders

`/manage` → Recruit Gauntlet → **Help & reminders** controls the reminder delay
in whole minutes from 1 to 10,080 (default 30). Changes also retime pending
reminders from each recruit’s latest completed step. The lounge is `1553128653645160479`; all four
Gauntlet roles can view it, read its history, and send questions there. The
read-only convention for the instructional channels still applies.

A successful confirmation records the recruit's new stage in MongoDB. Further
progress replaces the pending timer; replaying an older step does not move the
recruit backward. A stalled stage gets one personal help ping, automatically
removed after 10 minutes. The text asks the recruit to ping assistance role
`1003797104088592444`; reminders notify only the recruit, not the assistance role.
Opening a main or FWA application ticket completes the journey and cancels further
reminders. No historical members are enrolled when the feature starts.

The general help sticky returns to the bottom after 30 minutes without human
conversation. Bot messages do not reset that quiet period. A sticky already at
the bottom stays in place. Settings, progress, message references, and pending
deletions live in `settings.bot_config` with `gauntlet_help` namespaces so normal
restarts preserve timers and message cleanup. The worker checks roughly once a
minute. Failed message deletions are retried; uncertain sends are reconciled
without blindly repeating recruit pings.

### CWL Signup Help stickies

The Main CWL chat (`801950200133976124`) and Lazy CWL chat
(`872692009066958879`) each have a gold **CWL Signup Help** sticky, on by
default. It asks members to ask their question here and ping CWL Commander
(`1574854005417316483`) themselves. The sticky sends silently with all mentions
disabled; it never pings the role. Nothing is posted in the announcement
channels. Future signup and reminder announcement help lines point to the
matching Main or Lazy chat; existing posts and legacy signup copy are unchanged.

Both CWL stickies reuse the Gauntlet durable sticky helper. A buried sticky
moves only after a human has posted after it and humans have been quiet for
30 minutes; bot messages alone never cause a repost. Missing CWL stickies also
wait for 30 minutes of human quiet. The worker checks every 60 seconds, creates
the replacement before deleting its stored predecessor, and never retries an
uncertain create. Each chat has separate guild-and-channel state in
`settings.bot_config`. Gauntlet keeps its existing document, deletion receipts,
30-minute human-quiet behavior and Recruitment Team role without a migration.

### Apply and Rite of Passage

Recruit Gauntlet also includes **Apply / Clan Entry** and **Rite of Passage**.
Both support grouped heading/body editing, image replacement, preview, and saved
per-server templates in `bot_config` (`content:apply:<guild id>` and
`content:rite-of-passage:<guild id>`).

Apply loads the authoritative public ticket post from the ticket rollout binding.
Use **Update published post**, or the save-and-update prompt after editing, to
refresh that same post. No resend is needed. Changing its posting channel or
creating a replacement belongs to ticket setup; the content editor cannot create
an unbound ticket panel. A changed binding requires reopening the editor.

Rite of Passage is private. **Save template** updates the text and guide image for
future chooser openings. Existing private messages remain unchanged; reopen
**Earn Your Rite of Passage** to see the latest template. Preview ticket buttons
are disabled. The editor does not alter ticket routing, categories, or counters.

### Parallel original and new Gauntlets

The original recruitment server (`1078723854303756298`) and new Warriors United
server (`644963518025826315`) can run simultaneously. `utils/gauntlet_routes.py`
selects roles and next channels by the interaction's server for About Us, Strike
System, and Family Particulars. Existing published buttons remain valid without
reposting. Destination channels are checked against that same server before any
role assignment. The original server keeps its original access roles and Apply
channel; the new server keeps its new progression and reminder tracking. Join the
Family and the new help reminders remain specific to the new server.

Continue links resolve the oldest message in the next channel when clicked,
including Join the Family → About Us in the new server. This starts the reader
at the beginning and follows replacement posts without storing a stale message
ID. If history is empty or temporarily unavailable, the link falls back to the
channel. This changes navigation only; it cannot enforce reading or scrolling.

### Gauntlet click diagnostics

`journalctl -u wu-bot.service` includes `gauntlet_click` records for all four
acknowledgement buttons. Each click is correlated by interaction ID, with guild,
channel, source message, and user IDs. Stages cover receipt (including interaction
age), Discord acknowledgement, channel/member checks, role assignment or existing
role, reminder tracking, first-message lookup, and private reply. Awaited steps
record start, success/failure, duration, and total elapsed milliseconds. Failure
records include exception class and Discord code, not raw HTTP exception text.
No interaction tokens, message bodies, or component-state suffixes are recorded.
`finished` means processing ended, not that every operation succeeded: inspect
stage results. A missing `received` record means this process did not log receipt;
it does not alone establish whether Discord, the client, or delivery failed.

Member-facing copy follows [Member text style](member-text-style.md).

## Box editors and saved-field mapping (270, G1–G4)

About Us, WU Strike System, Family Particulars and WU FAQ show one editor screen
per public box, in post order, followed by Images when the document has media.
Preview renders the whole post. Family Rules is a read-only shared screen with
an explicit action to open its existing editor; its storage and text are unchanged.
Discord modals hold up to five fields for one box, not fixed groups of four.

The existing content row and revision/CAS remain the storage owner. Reads append
missing new fields in memory only. An explicit Save stores the expanded list;
subsequent reads use its canonical fields directly and never remap the retained
prefix over staff edits. Incomplete intermediate lengths fail visibly.

| Document           | Existing fields used by the new boxes                                                                                                   | Appended fields                                                                                                              | Retained but hidden                                                                                          |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| About Us           | 1 overview; 3 Tactical; 5 Flexible Fun; 7 FWA; 11 Next Step body                                                                        | 12 Welcome heading; 13 Our Clans heading; 14 requirements guide; 15 Next Step heading                                        | 0, 2, 4, 6, 8 old headings; 9 former disclaimer; 10 former Next Step heading                                 |
| WU Strike System   | 3 At 4 Strikes body; 5 Main note; 7 FWA note; 9 Terms; 11 Next Step body                                                                | 12 How Strikes Work body; 13 Remove Your Strikes body; 14–18 box headings                                                    | Original 1 combined body; 0, 2, 4, 6, 8, 10 former headings                                                  |
| Family Particulars | 5 Friendly Challenges; 8 Clan Games; 12 War Status; 15 Prep Day; 18 Battle Day; 21 CWL overview; 24 Every CWL Battle; 27 Next Step body | 28 How Our Clans Work heading; 29 new intro; 30 Every Day heading; 31 War Days heading; 32 CWL heading; 33 Next Step heading | Golden Rule 1/2; decorative 3, 6, 9, 13, 16, 19, 22, 25; former headings 0, 4, 7, 10, 11, 14, 17, 20, 23, 26 |
| WU FAQ             | Original Questions 0/1                                                                                                                  | 2–8 Who we are and Our Clans fields                                                                                          | None                                                                                                         |

A legacy Strike removal subsection is split only at one recognized standalone
heading; the complete original combined body remains byte-exact in field 1.
Ambiguous custom text remains visible in How Strikes Work, with Remove Your
Strikes empty and an actionable review error. Staff must explicitly complete it
before Preview, Save, Send or Update. No policy is inferred from defaults.

The previous web schema enumerated 20 Family Particulars labels over 28 stored
text slots, so the CWL overview label addressed field 15 (Prep Day) instead of
field 21. The box mapping now uses the actual meaningful indices. Regression
coverage follows a saved edit through the real queued publish adapter to the
mocked Discord edit payload for all three Gauntlet posts. This proves the mapping
defect and corrected path; the precise cause of the reported historical live
incident remains an inference without its edited-field record.

Send and Update results name the document and link to the Discord message.
Tests simulate transport; they do not prove a live Discord post or update.

## Roles and clan links

`family-links` uses the existing posting-channel, Send, link-existing and Update flows. It has four editable text fields and one WU banner slot; its gold footer is fixed. Legacy role controls open the new private menus without applying stale selections. See [Roles and clan links](roles-and-clan-links.md).
