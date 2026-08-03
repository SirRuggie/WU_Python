# The component dispatcher

Every button, select menu and modal in this bot routes through one file:
`extensions/components.py` (~310 lines). Understand it before building anything
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
ephemeral=False, opens_modal=False, group=None)` stores an `Action` dataclass in the module
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

custom_ids are `command_name:action_id`, split once by `raw.partition(":")` in `_dispatch`.

- `command_name` selects the handler from `registered_functions`.
- `action_id` is the key into `button_store` holding that component's saved
  kwargs, fetched by the `button_store.find_one` in `_dispatch` and splatted into the handler as
  `**kw`, unioned with `color`, `action_id` and `ctx`.

**Select-menu groups**: a handler registered with `group="x"` also writes an
entry under `"x"` marked as a group. When a custom_id names a group, the
dispatcher re-looks-up the real handler by `ctx.interaction.values[0]` — so the
select option's `value` must equal a registered action name. This is why
`dashboard.py` uses `custom_id="clan_database:"` with option values like
`view_clan_list`.

**Deferral**: `ctx.defer(edit=True)` is called for everything that is not a
modal and does not open one (the `ctx.defer(edit=True)` in `_dispatch`).

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

## Defects — fixed in commits `23266e3` / `2f1f121` (2026-08-02)

- **No error boundary.** A raising handler produced the worst failure a component
  can have: `defer(edit=True)` sends `DEFERRED_MESSAGE_UPDATE`, which acks
  silently with no loading state, so the button simply un-pressed and nothing
  happened. Discord was already acked, so it never showed "This interaction
  failed" either — indistinguishable from a slow bot, which invites re-clicking.
  Now every failure produces an ephemeral message with a correlation ref that
  matches a logged traceback.
- **No unknown-action guard.** `.get()` returned `None` and was tuple-unpacked
  immediately → `TypeError` before any response. Now refuses with a "panel out of
  date" message. See *Renaming an action* above for the alias mechanism.
- **`custom_id` with no colon.** `split(":", 1)` raised `ValueError`; now
  `partition(":")`, which cannot raise.
- **A modal hitting a group entry** accessed `ctx.interaction.values`, which
  `ModalInteraction` does not have → `AttributeError`. Now `getattr`.
- **`ModalContext` has no `edit=` parameter** — it inherits the plain
  `MessageResponseMixin`, so `respond(..., edit=True)` raises `TypeError`. Dodged
  only because all 12 `is_modal=True` registrations also set `no_return=True`.
  Now branched explicitly.
- **A group-registered action could not be reached by a button** — see below.
  ⚠️ **Fixed by inspection, NOT demonstrated.** The reproduction requires a real
  image upload and has not been run. Every other item in this list was exercised
  by the 2026-08-02 smoke pass; this one was not.

### The group-routing bug, and how to actually reproduce it

The dispatcher branched on the *action's* `group` field rather than on whether
the interaction arrived via the group key, then required
`ctx.interaction.values`. A button has none, so it returned silently.

The only live instance is **`manage_fwa_data:main`** (`fwa_data.py:773`), because
`manage_fwa_data` is registered with `group="clan_database"` (`fwa_data.py:367`).

**⚠️ There is a lookalike that will fool you.** The per-Town-Hall edit view has a
button also labelled "Back" (`fwa_data.py:351`) whose custom_id is
`fwa_back_to_main:main`. That action is registered **without a group**
(`fwa_data.py:419`), takes `**kwargs`, and requires nothing — so it always
worked and is unaffected by the fix. Testing it proves nothing.

The affected button is labelled **"Back to Main Menu"** and lives only on the
image-upload success screen:

```
/clan dashboard → Manage FWA Data → select a Town Hall
  → Update Images → submit the modal with image URLs
  → "TH{n} Images Updated!" screen
     → "Back to Main Menu"   (grey/secondary)   ← the affected button
     → "Back to TH{n} Edit"  (blue/primary)     ← a different action
```

Reaching it requires a real image upload, so this is not a cheap test — and as
of 2026-08-02 **it has not been done**. The fix is sound by inspection; treat it
as unverified until someone clicks that specific button.

A caution on how this was nearly mis-verified: the first smoke pass reported the
per-Town-Hall "Back" as newly working. It was the lookalike, and it had always
worked. **A button that works is not evidence for a fix unless it is the button
the fix touched.**

`copy_war_message` (`message_templates.py:303`) is also registered with a group
but no custom_id references it, so it is unreachable dead code rather than a
second live instance.

### ⚠️ Exactly ONE colon in a custom_id — the extra-colon trap

`raw.partition(":")` splits at the **first** colon and everything after it is the
state key. So `f"action:{action_id}:{page}"` makes `action_id` the composite
string `"1234567890:2"`, which misses `button_store` — and the handler is called
with only the three injected keys.

**This is live and has a victim.** `manage_roles.py:366` and `:385` build
`custom_id=f"remove_roles_page:{action_id}:{page}"`. The handler at `:587-593`
parses the page correctly out of `parts[2]` — so the author knew the format —
then does `find_one({"_id": action_id})` using the **dispatcher-injected
composite** rather than `parts[1]`, misses, and returns
`error_response("Session expired")`. **That pagination has never worked.**
Confirmed by reading both ends; not executed.

`server_walkthrough.py:239` uses the same shape but parses `original_action_id`
itself and falls back to `ctx.user.id` on a miss, so it degrades instead of
breaking.

**Rule for new dashboards: one colon. Page, view and every other parameter live
in the state document, never in the custom_id.**

## Defects — still open

1. **`user_only` is never enforced.** It is stored on the `Action` and not read.
   In fact **no authorization of any kind happens in the dispatcher** — and
   `user_only=True` is used zero times in the repo, so nothing declared an intent
   that is being bypassed. Four files hand-roll their own role checks
   (`update_clan_info.py:60`, `fwa_data.py:386`, `questions.py:366`, `:474`);
   the other 36 have none. Currently masked by almost every dangerous surface
   being ephemeral, which is exactly the property a shared dashboard gives up.
2. **A dead guard.** `kw = kw or {}`, then a union with three always-present
   keys, then `if not kw: return` — which can never fire. The intended behaviour
   (detect expired or missing state) does not happen; the handler is called with
   only the three injected keys and 26 handlers that declare a required `user_id`
   then fail on the missing kwarg.
3. **`ephemeral` on an edit is a no-op.** Combining `edit=True` with
   `ephemeral=...` does nothing, because an existing message's ephemeral state
   cannot be changed. Left in place deliberately so the error-boundary commit
   changed nothing on the success path; remove it with the state work.
4. **Duplicate registration warns rather than raises.** Raising would stop the
   bot booting, which is not an acceptable outcome for a fix whose premise is not
   disturbing the running system. One duplicate exists — see below. Resolve it
   first, then consider raising.

### `back_to_clan_edit` — which one runs, and why it matters

Settled from the boot log on 2026-08-02:

| | File | Flags | Status |
|---|---|---|---|
| **Winner** | `update_clan_info.py:964` | `ephemeral=True` | **This is what production has always run** |
| **Loser** | `update_clan_info_general.py:129` | `ephemeral=True, no_return=True` | **Has never executed** |

They are not equivalent implementations of the same thing:

- The **winner** calls `clan_edit_menu(ctx, mongo=mongo, tag=action_id)` and
  returns the components, letting the dispatcher respond.
- The **loser** calls `clan_edit_menu.__wrapped__(...)` — deliberately reaching
  past the decorator, with a comment saying *"Call the undecorated function"* —
  passes an extra `action_id=action_id`, and then does its own
  `edit_initial_response`. That is why it needs `no_return=True`.

**So the loser's `no_return` semantics have never taken effect, and its
`__wrapped__` workaround has never been exercised.** Someone hit a problem and
wrote a bypass that was never validated, because the registry silently discarded
it at import. This is the same class as the `edit_last_response` bug — see
[lightbulb-context-api.md](lightbulb-context-api.md) — code that looks like
working code because nothing ever ran it.

**⚠️ Resolve the duplicate by deleting the LOSER**
(`update_clan_info_general.py:129`). Deleting the winner instead would *activate*
roughly twenty lines of never-executed code, including a `__wrapped__` call whose
premise nobody can now reconstruct. The safe move is to keep what production has
been running and delete the shadow.

Consequence for new work: **the expiry path is the one to design for.** State in
`button_store` is never pruned but is also never guaranteed present.

## The landmine for any ticket dashboard

The natural custom_id for a ticket action is `ticket_view:ticket_{channel_id}` —
the ticket's own `_id` is the obvious handle. Write that, and the state lookup in `_dispatch`
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
