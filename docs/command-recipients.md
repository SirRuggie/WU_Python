# Per-use command recipients

In Command triggers, enable **Choose a user or role each time**, and optionally **Ping only the selected user or role**. Save the trigger. Type the trigger without a mention, click Choose recipient, and select one server member or role in the private picker. Selection posts the Components V2 reply in the original channel, with the selected mention above it. No fixed recipient is saved in the command. Existing triggers default to the old behavior.

The initial Choose recipient button is public because prefix messages cannot create private responses; the member/role selection is an ephemeral interaction. Only the original caller can operate it. Pickers expire after 10 minutes and check the command fingerprint, enabled status, guild and channel. Mongo component_state with its existing TTL index stores the per-use state. An atomic claim prevents duplicate deliveries; uncertain sends are not automatically retried. Saved reply actions pointing at a recipient-enabled trigger direct the user to run that trigger instead.

Recipient mode allows only the selected mention to ping. Fixed mentions, @everyone and @here remain silent. Unmentionable role pings require the invoking member's Discord MENTION_ROLES permission, and bot/Discord notification permissions still apply. No DMs are sent. Notifications are never guaranteed because Discord user notification preferences also apply.

Validation: 60 backend command/dispatch tests passed and 111 frontend tests passed. Production build succeeded. Isolated browser verification confirmed checkbox save round-trip, preview recipient label and mobile controls. Bot runtime imports and recipient payload passed in the deployed virtualenv. No live Discord messages or pings were sent for testing.

Reference: https://github.com/discord/discord-api-docs/blob/main/developers/interactions/receiving-and-responding.mdx
