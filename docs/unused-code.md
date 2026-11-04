# Unused bot code — removal backlog

Started 2026-11-04 by Shaka, at Ruggie's request: "mark all parts that are NO LONGER USED … recorded to be removed at a later date. I do not want to update text on unused code."

- **Checked against** live commit `3bcfe99b` (the code paths are the same on today's live `9552757e`), read-only export `/nvme0n1-disk/Projects/claude-review-210`.
- **Method:**
  - Six cheap scout agents checked where each of the 484 wording items lives. Their results are in `.local/ste-bot-audit/reach-*.tsv`.
  - My own script found each item's enclosing function and counted callers.
  - A seventh scout tried to prove each "unused" claim wrong (`.local/ste-bot-audit/refute-unused.tsv`). It overturned 2 claims (CL-67 and CL-68 are used), and they stay in review.
  - I confirmed the `tickets/manage.py` and card-import findings myself.
- **Removal rule:** don't delete anything from this list without a fresh check on the current main. Code moves.

## A. Whole files that never load

| File | Why it never runs | Evidence | Wording items |
|---|---|---|---|
| `extensions/commands/cards.py`, `extensions/tasks/cards_sticky.py`, `extensions/tasks/cards_deadlines.py` | In `RETIRED_EXTENSIONS`. The Clash of Cards event ended in Sept 2026. | `utils/startup.py:24-31`; `main.py` lists the two tasks, but `active_extensions()` drops them | CD-1 to CD-73 |
| `utils/cards.py`, `utils/card_board.py` | Imported only by the retired card files above | No other importer in `extensions/`, `utils/`, `cwl_web/` or `main.py` | (part of CD) |
| `extensions/commands/cards_bulk_preview.py`, `cards_preview.py`, `poll_bar_preview.py` | In `DISABLED_PREVIEW_EXTENSIONS` (developer previews) | `utils/startup.py:14-18` | (not audited) |
| `extensions/commands/clan/info_hub/info.py` | In `RETIRED_EXTENSIONS` | `utils/startup.py:29` | CL-25; part of CL-1 |
| `extensions/commands/clan/info_hub/explanations.py`, `handlers.py` | Imported by nothing live; `handlers.py` is reached only through `explanations.py` | grep finds no importer | CL-19, 20, 21, 24, 106, 108, 109; part of CL-22, 23, 107, 110 |
| `extensions/commands/clan/list.py` | In `RETIRED_EXTENSIONS` | `utils/startup.py:28` | CL-26, 27; part of CL-3, 28, 143 |
| `extensions/commands/tickets/manage.py` | Never imported by `extensions/commands/tickets/__init__.py` (lines 376–420 import every other module) | Confirmed by Shaka | TK-52; part of TK-50, 51 |
| `extensions/commands/cwl_announcement.py` | Its command class is never registered on the loader | No `@loader.command`; no importer | BT-204, 205 |

**Ruggie's call:** the card code is switched off, not deleted. The code comment says it can be turned on again for another Clash of Cards event. Decide whether it goes or stays.

## B. Dead functions inside live files

| Function | File | Evidence | Wording items |
|---|---|---|---|
| `_candidate_account_copy` | `extensions/commands/tickets/thread_service.py:1318-1345` | No caller anywhere | TK-21 to TK-24 |
| `_hub_picker_placeholder` | `extensions/commands/tickets/console.py:696` | No caller | part of TK-10 |
| `win_message` | `extensions/commands/fwa/message_templates.py` | Defined once, never called | CL-41 |
| `create_declaration_complete_message`, `create_closed_message`, `create_open_message` | `extensions/commands/lazyprep.py` | No callers; `/lazyprep` is marked retired | CL-64, 65; part of CL-8 |

## C. Likely unused: buttons no live code creates any more
Only a button on an old Discord message that is already posted could still trigger these. Before removing them, check that no live channel message still carries the button (for example, search the saved panel and message records for the `custom_id`).

| Handler | File | Evidence | Wording items |
|---|---|---|---|
| `cwl_member_start` | `extensions/commands/cwl_member.py:575` | No builder of `cwl_member_start`; `/cwl` signup uses `_new_session` | BT-182 |
| `cwl_settings` (edit/submit settings) | `extensions/commands/cwl_dashboard.py:1775` | No builder of `cwl_settings:` | BT-201 |
| `cwl_apply_review`, `apply_cycle`, `apply_defaults`, `_apply_scope` | `extensions/commands/cwl_dashboard.py:1841-1861` | No builder, and no callers | BT-202 |
| `cwl_delivery` branch of `_open_message_modal` | `extensions/commands/cwl_dashboard.py:1065-1095` | No builder of `cwl_delivery` | BT-109 |
| `copy_war_message` | `extensions/commands/fwa/message_templates.py:343` | No builder found | CL-42 |
| `fwa_war_save` | `extensions/commands/fwa_war_messages.py:457-461` | No builder found | part of CL-51, CL-103 |

## D. What changed in the wording review
- The 93 wording items in A and B, plus the 5 whole items in C, are taken out of review; they will not be reworded. Ruggie had already approved 73 card items, so those approvals are void.
- **Partly unused (14 items):** CL-1, 3, 8, 22, 23, 28, 51, 103, 107, 110, 143, TK-10, 50, 51. They stay in review. Only their live places change, and the unused places are listed on each item.
- **Review page:** https://claude.ai/artifact/8fVPKFzDo1ZVztc6CpaUje. 416 live items; 98 shown at the end as "Not used any more".
- **The dashboard was not part of this check.** Its wording batch (155) is already live.
