# War Weight management

Open **/manage → FWA → War Weight**. Administrator permission is checked both when opening the panel and on every change.

- **Edit a Town Hall:** change its minimum/maximum total war weight and emoji.
- **Add Town Hall:** add a new level, including future levels such as TH19. Enter actual known ranges; the bot does not invent future game values.
- **Lowest Town Hall to show:** choose TH13 to display TH13 through the highest configured level. This only filters the reference guide, not the calculation or FWA suitability threshold.
- **Emoji:** blank automatically matches `TH_<level>` or `TH<level>`, case-insensitively, in cached guild emojis or application emojis. A custom emoji name or pasted Discord custom emoji overrides this. Existing built-in Town Hall emojis remain fallbacks, followed by 🏛️.

`/fwa weight` remains the calculator. It reads these settings for each new result; existing messages are not rewritten. Existing TH9–18 ranges and minimum TH9 remain the defaults until edited. Total weights must be 1–500,000, increasing, nonoverlapping, with minimum less than maximum. Up to 25 configured entries are supported. The existing 115,000 FWA suitability threshold is unchanged.

## Storage and ownership

Owner: `utils/war_weight.py`. Permanent `war_weight_settings` collection in the database backing `mongo.fwa_data`; one document per guild, string guild ID as `_id`, schema version 1. Fields: `guild_id`, `ranges` keyed by Town Hall number, `minimum_th`, `revision`, `updated_by`, `updated_at`. No TTL and no `button_store` usage. Defaults are read without writing; the first edit creates the record. Revision-based compare-and-swap prevents stale panels/modals from replacing newer settings.

Private editor sessions use the existing TTL-backed `component_state` collection for 30 minutes and bind the guild, user, editor type, and revision. Durable settings survive restarts independently of these sessions.
