# FWA War Messages

Open `/manage` → **FWA** → **War Messages**. The optional `section:FWA`
choice opens the FWA submenu. This private editor manages the **Win**, **Lose**,
**Mismatch**, and **Blacklisted** templates used by `/fwa war-plans`.

## Workflow

1. Choose a war outcome.
2. Select a named text block and edit its Markdown. The compact copy text is
   separate so instructions copied into clan chat can stay concise.
3. Optionally upload footer artwork or edit the six-digit accent color.
4. Use Message preview or Copy preview to check the draft with example war details.
5. Save changes to make the template available to future `/fwa war-plans` posts.

Saving a template does not publish a message or rewrite older announcements.
The existing war-plan command still selects the clan, opponent, result, and
announcement channel. The blacklist lookup and its success/failure note remain
runtime behavior of that command.

Footer uploads accept PNG, JPG, GIF, or WEBP images up to 10 MB. Uploading or
restoring artwork changes the draft; Save changes applies it to future posts.
Reset defaults has a confirmation screen and immediately saves the original
text, copy text, color, and artwork for the selected outcome.

The management UI uses gold styling. The public message preview uses the war
message's own appearance. Back returns one level and Management Home returns
to `/manage`; leaving unsaved changes requires an explicit choice.

## Access and storage

Editing requires the same **FWA Clan Rep** role as `/fwa war-plans`
(`769130325460254740`). The base-data editor's separate FWA Representative role
is not sufficient. Draft actions recheck the current user's role and bind the
draft to its opening user and server.

Saved templates belong to one server and one outcome. Until a template is saved,
the existing bundled message is used. Saves check the template revision so a
stale editor cannot silently overwrite a newer save.

Previews suppress mentions. Public war-plan posts allow only the selected clan
role to be pinged; editing template text does not expand allowed mentions.

## Dynamic values

The editor stores placeholders, not the details of a particular war:

| Placeholder | Filled when posting |
| --- | --- |
| `{opponent}` | Opposing clan name |
| `{author}` | Person declaring the war |
| `{clan_role}` | Selected clan's role ID; use `<@&{clan_role}>` for its mention |
| `{fwa_rep_role}` | FWA Clan Rep role ID; use `<@&{fwa_rep_role}>` for its mention |

Unknown or malformed placeholders are rejected. Previews use example values.
Text and copy limits account for placeholder expansion before a template is saved.

## Persistence

Uploaded artwork uses the existing media store under `fwa-war-messages/<guild id>`.
Templates live in `bot_config` as `fwa_war_template:<guild id>:<variant>`.
Schema version 1 records `guild_id`, `variant`, `sections`, `copy_text`,
`footer_url`, `accent`, `revision`, and `updated_by`. An absent record loads
the bundled defaults at revision 0. First saves use insert uniqueness; later
saves match the expected revision before advancing it. Resetting defaults is
also revision-checked, so it cannot silently replace someone else's new edit.
