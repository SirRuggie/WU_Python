# Content dashboard

`/content dashboard` is a private, per-server editor for About Us, WU Strike
System, and Family Particulars. It preserves each post's existing media,
containers, separators, and acknowledgement action name while allowing named
Markdown blocks to be edited and previewed.

Drafts belong to the administrator who opened them, expire after 30 minutes,
and are checked again for user, guild, and Manage Server permission on every
interaction. Saving uses a revision compare-and-swap. An optional message link
can adopt and update a matching bot-authored post only after Discord confirms
the channel belongs to the current guild; publishing also uses a short lease
and refuses a post changed since the draft opened.

Templates are stored per server under `content:<document>:<guild id>`.
About Us also reads its previous `recruit_aboutus:<guild id>` template when no
unified record exists. Family Particulars keeps its decorative separators fixed
and validates the complete rendered text at Discord's 4,000 character limit.
The acknowledgement role and hardcoded destination channel behavior are the
existing onboarding flow and are not changed by this dashboard.
