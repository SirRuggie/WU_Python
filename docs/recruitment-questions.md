# Recruitment Questions

Open `/manage` and choose **Recruitment Questions**, or use the optional
`section` choice. This private workspace edits the reusable messages in the
**Primary Questions** menu of `/recruit questions`:

- Attack Strategies
- Discord Basics
- Family Codes
- Application Under Review
- Welcome to the Family
- Warriors United CWL

The existing `/recruit questions` command still selects a recruit and sends
messages in the recruitment channel. The management editor only changes
reusable templates. Saving does not send a message or rewrite previous posts.
FWA question menus remain separate, and the disabled Age Bracket question
stays disabled.

## Editing and access

Manage Server or Administrator permission is required. Each editor action checks
permissions, draft ownership, and server membership. Choose a message, edit its
named text blocks, preview it privately, and save when ready. The editor uses
gold styling and includes Back and Management Home navigation. Leaving unsaved
changes requires confirmation.

Artwork and accent changes are staged until Save. Messages with artwork support
native image uploads and restoration of their original artwork. Discord Basics
keeps its button layout without an artwork slot. Reset defaults asks for
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
challenge workflow, outside this six-message editor.

## Storage

Saved templates are scoped to a server and question in MongoDB's `bot_config`
collection, with IDs `recruit_question_template:<server id>:<question>`.
Draft editor state expires after 30 minutes. Saves check revisions
to prevent an older open editor from overwriting a newer save. If no saved
customization exists, sending uses the original built-in message.

Uploaded image files use the existing media store; templates save image URLs.
