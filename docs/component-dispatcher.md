# The component dispatcher

Every button, select menu and modal in this bot routes through one file:
`extensions/components.py` (112 lines). Understand it before building anything
component-heavy — **and read the defects section, because they are real.**

## The contract

Interactive pages are plain async functions that **return a list of component
builders**. They are registered by decorator:

```python
@register_action("update_clan_information", group="clan_database")
@lightbulb.di.with_di
async def some_page(ctx, action_id, color, mongo=lightbulb.di.INJECTED, **kwargs):
    ...
    return components          # list of builders
```

`register_action(name, user_only=False, no_return=False, is_modal=False,
ephemeral=False, opens_modal=False, group=None)` stores a 7-tuple in the module
global `registered_functions`:

| Parameter | Effect |
|---|---|
| `user_only` | **Nothing. Stored and never enforced.** See defects. |
| `no_return` | Skip the automatic `ctx.respond(...)`; the handler responded itself. |
| `is_modal` | This handler services a modal submission — do not defer. |
| `ephemeral` | Passed to the automatic respond. |
| `opens_modal` | Handler will open a modal — do not defer (you cannot defer then modal). |
| `group` | Register this name as a select-menu router (see below). |

The decorator also wraps the function to coerce stdlib `datetime` arguments to
`pendulum.DateTime` where the type hint asks for it.

## Routing

custom_ids are `command_name:action_id`, split once at `components.py:74`.

- `command_name` selects the handler from `registered_functions`.
- `action_id` is the key into `button_store` holding that component's saved
  kwargs, fetched at `components.py:86` and splatted into the handler as
  `**kw`, unioned with `color`, `action_id` and `ctx`.

**Select-menu groups**: a handler registered with `group="x"` also writes an
entry under `"x"` marked as a group. When a custom_id names a group, the
dispatcher re-looks-up the real handler by `ctx.interaction.values[0]` — so the
select option's `value` must equal a registered action name. This is why
`dashboard.py` uses `custom_id="clan_database:"` with option values like
`view_clan_list`.

**Deferral**: `ctx.defer(edit=True)` is called for everything that is not a
modal and does not open one (`components.py:83-84`).

Contexts are hand-built in `build_ctx` — `lightbulb.components.MenuContext(
client, None, interaction, None, None, None, asyncio.Event())` — bypassing
lightbulb's own menu machinery.

## Renaming an action — always leave an alias

**Component custom_ids never expire.** Discord does not garbage-collect messages
and does not time out components. A button posted a year ago fires an
interaction today, carrying whatever action name it was built with, and there is
no documented expiry on `custom_id` anywhere in Discord's API.

That has a consequence people get wrong: **renaming an action silently breaks
every message already posted in the guild, permanently.** The old messages keep
looking clickable. There is no deprecation warning, no version negotiation, and
no way to reach back and edit a message you no longer have the ID of.

Before the dispatcher fix this was worse than a broken button — an unrecognised
name was tuple-unpacked from `None`, raising `TypeError` before any response, so
the user got a three-second hang and *"This interaction failed"*.

So: **never rename an action. Add the old name as an alias.**

```python
@register_action("ticket_console", aliases=("ticket_dashboard",))
```

`action_aliases` maps retired name → current name, resolved before lookup, so
every already-posted panel keeps working. Aliases cost one dict entry each.
**Leave them in place indefinitely** — deleting one re-breaks exactly the old
messages it was added to protect, and you cannot tell which those are.

This matters most for the console dashboard, whose whole design is persistent
panels that linger in staff channels. Without aliases, every iteration on an
action name would strand every panel posted before it. With them, the dashboard
is safe to rename and restructure freely.

## Why this exists instead of `lightbulb.components.Menu`

**lightbulb has no Components V2 support at any version** — verified by grepping
`lightbulb/components/` at tags 3.0.3 *and* 3.2.5 for `ContainerComponent`,
`SectionComponent`, `TextDisplay`, `MediaGallery`, `IS_COMPONENTS_V2`: zero
matches. `Menu` builds only `MessageActionRowBuilder` rows.

So a custom dispatcher over raw `hikari.impl` builders is **the only path to a
V2 UI**, now and after any upgrade. Do not "migrate this to `Menu`" — it cannot
do what this bot already does.

A second, genuine advantage: lightbulb routes component interactions by scanning
`client._attached_menus` for a live in-memory `Menu` object. That state dies on
restart. This registry is keyed by the `command_name` half of the custom_id, so
handlers are **stateless and survive restarts** — which is what makes persistent
dashboard messages viable at all.

## Known defects

Flagged by a prior security audit; a fuller assessment was commissioned
2026-08-02. Treat these as confirmed-by-reading, severity as judgement.

1. **`user_only` is never enforced** (`components.py:75`). It is unpacked into a
   local named `owner_only` and then not used. Any user who can see a message can
   trigger its components, including ones registered as user-only.
2. **No error boundary.** `components.py:83-91` defers, then calls the handler
   with no `try`/`except`. A raising handler leaves Discord already told
   "thinking", so the user sees a permanent spinner and no error.
3. **No unknown-action guard.** `registered_functions.get(command_name)` returns
   `None` for an unknown key and is immediately tuple-unpacked → `TypeError`.
   **Renaming or removing an action breaks every existing message that
   references it**, and component messages persist indefinitely.
4. **A dead guard.** `components.py:86-90` does `kw = kw or {}`, then unions in
   three always-present keys, and only then checks `if not kw: return`. That
   check can never fire. The intended behaviour — detecting expired or missing
   component state — does not happen; the handler is called with only the three
   injected keys and typically fails on a missing kwarg.

5. **`ModalContext` has no `edit=` parameter.** `components.py:94` calls
   `ctx.respond(..., edit=True, ...)`. `ModalContext` inherits the plain
   `MessageResponseMixin`, not the `...WithEdit` variant, so that raises
   `TypeError`. **It is dodged by convention only** — all 12 `is_modal=True`
   registrations also pass `no_return=True`, which skips line 94. The first
   modal handler written without `no_return=True` crashes.
6. **`ephemeral` on an edit is a no-op.** `components.py:94` combines
   `edit=True` with `ephemeral=ephemeral`. An existing message's ephemeral state
   cannot be changed, so the flag does nothing on ~25 registered actions that
   read as if it works.
7. **A group-registered action cannot be reached by a button.** The dispatcher
   branches on the *action's* `group` field (`components.py:77`) rather than on
   whether the interaction arrived via the group key, then requires
   `ctx.interaction.values`. A button has none, so it returns at line 79.
   **Live example:** `fwa_data.py:773` renders a button with
   `custom_id="manage_fwa_data:main"`, and `fwa_data.py:367` registers
   `manage_fwa_data` with `group="clan_database"`. That "Back to Main Menu"
   button has never worked.

Consequence for new work: **the expiry path is the one to design for.** State in
`button_store` is never pruned but is also never guaranteed present.

## The landmine for any ticket dashboard

The natural custom_id for a ticket action is `ticket_view:ticket_{channel_id}` —
the ticket's own `_id` is the obvious handle. Write that, and `components.py:86`
loads **the ticket document** as handler kwargs. Every handler takes `**kwargs`,
so there is no error. And the house convention in `close.py` is to finish with
`delete_one({"_id": action_id})` (`close.py:471`, `:563`, `:688`) — so one
handler written in the established style **permanently deletes a ticket record**,
silently, with no backup.

Never use a `ticket_*` id as an `action_id`. Better: give the dispatcher its own
collection so it structurally cannot reach ticket documents.

## Related

- [ticket-data-model.md](ticket-data-model.md) — `button_store` is shared with
  ticket documents.
- [lightbulb-context-api.md](lightbulb-context-api.md) — what the hand-built
  contexts can actually be asked to do.
