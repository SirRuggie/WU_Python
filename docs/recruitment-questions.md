# Recruitment Questions

Open `/manage` and choose **Recruitment Questions**, or use the optional
`section` choice. The editor mirrors all four dropdowns in `/recruit questions`
and includes every enabled option:

| Dropdown | Editable choices |
| --- | --- |
| Primary Questions | Attack Strategies; Discord Basic Skills; Family Codes; Leaders Checking You Out; Welcome to the Family; Warriors United CWL |
| FWA Questions | FWA Clan Chat; Get War Weight; Heard of Lazy CWL?; Lazy CWL Explanation; FWA Leaders Reviewing; FWA Bases (Upon Approval) |
| Explanations | What is FWA; FWA War Plans; What is Flexible Fun; What is Tactical |
| Keep It Moving | Waiting for Response...; Going in Circles...; Today Jr...; Chop Chop... |

Select a message to continue into its text, artwork, preview, and save controls.
Back returns to the four dropdowns. This covers 20 enabled choices; the disabled
Age Bracket question stays disabled.

The existing `/recruit questions` command still selects a recruit and sends
messages in the recruitment channel. The management editor only changes
reusable templates. Saving does not send a message or rewrite previous posts.

## Editing and access

Manage Server or Administrator permission is required. Each editor action checks
permissions, draft ownership, and server membership. Choose a message, edit its
named sections with heading and body together, preview it privately, and save when ready. The editor uses
gold styling and includes Back and Management Home navigation. Leaving unsaved
changes requires confirmation.

Artwork and accent changes are staged until Save. Messages with artwork support
native image uploads and restoration of their original artwork. For messages
with multiple images, choose the image slot before uploading or restoring it.
Discord Basics keeps its button layout without an artwork slot. Reset defaults asks for
confirmation before restoring the selected message's original template.

Previews suppress mentions and disable interactive challenge buttons. They do
not start a challenge or send anything to a recruit.

## Dynamic details and interactive checks

`{recruit}` becomes the selected recruit's mention and `{recruiter}` becomes
the sending recruiter's mention. These values are filled in when sending,
not saved as the details of a particular ticket.

Family Codes keeps a required `{family_codes}` placeholder that displays the
three codes accepted by the existing response checker. Its challenge state,
answer validation, and completion behavior remain part of the recruitment
workflow. Discord Basics retains its recruit-specific shield button and
challenge behavior when the reusable wording changes. The subsequent Goblin
challenge instructions and completion messages remain part of the existing
challenge workflow, outside these recruitment prompt templates.

FWA Bases uses live Town Hall data from the FWA workspace. Its base links,
per-Town-Hall descriptions, and base images remain in that shared data source;
recruitment templates edit the surrounding wording. Previews use example data
and disable the Town Hall selector so they cannot send messages to recruits.
Separate preview buttons show the selector and the public base message.

## Storage

Saved templates are scoped to a server and question in MongoDB's `bot_config`
collection, with IDs `recruit_question_template:<server id>:<question>`.
Draft editor state expires after 30 minutes. Saves check revisions
to prevent an older open editor from overwriting a newer save. If no saved
customization exists, sending uses the original built-in message.

Uploaded image files use the existing media store; templates save image URLs.
