from pymongo import AsyncMongoClient


class MongoClient(AsyncMongoClient):
    def __init__(self, uri: str, **kwargs):
        super().__init__(host=uri, **kwargs)
        self.__settings = self.get_database("settings")
        self.button_store = self.__settings.get_collection("button_store")
        # Fixed-lifetime kwargs for Components V2 interactions. The TTL index is
        # owned by utils.component_state; durable tickets never enter here.
        self.component_state = self.__settings.get_collection("component_state")
        self.clans = self.__settings.get_collection("clan_data")
        #self.clan_recruitment = self.__settings.get_collection("clan_recruitment")
        self.fwa_data = self.__settings.get_collection("fwa_data")
        self.fwa_band_data = self.__settings.get_collection("fwa_band_data")
        self.ticket_setup = self.__settings.get_collection("ticket_setup")
        # Durable ticket records. Historically these lived in button_store next to
        # ephemeral component state; see extensions/commands/tickets/store.py.
        # NO TTL INDEX ON THIS COLLECTION - ticket history is permanent.
        self.tickets = self.__settings.get_collection("tickets")
        # Short-lived idempotency leases for cross-system ticket creation.
        # Durable ticket history remains in tickets; handlers.py owns this TTL.
        self.ticket_creation_state = self.__settings.get_collection("ticket_creation_state")
        self.bot_config = self.__settings.get_collection("bot_config")
        #self.reddit_monitor = self.__settings.get_collection("reddit_monitor")
        #self.reddit_notifications = self.__settings.get_collection("reddit_notifications")
        #self.clan_bidding = self.__settings.get_collection("clan_bidding")
        #self.new_recruits = self.__settings.get_collection("new_recruits")
        self.ticket_automation_state = self.__settings.get_collection("ticket_automation_state")
        self.recruit_onboarding = self.__settings.get_collection("recruit_onboarding")
        # Short-lived message challenges used during recruitment. This stays
        # separate from durable walkthrough records in recruit_onboarding so a
        # TTL index cannot remove role-cleanup history.
        self.recruit_challenges = self.__settings.get_collection("recruit_challenges")
        self.lazy_cwl_snapshots = self.__settings.get_collection("lazy_cwl_snapshots")
        self.cwl_pending_reminders = self.__settings.get_collection("cwl_pending_reminders")
        self.fwa_points = self.__settings.get_collection("fwa_points")
        # Bounded discovery data for /todo. History/candidate rows and watches
        # both carry BSON-date TTL anchors; utils/clan_history.py owns indexes.
        self.player_clan_candidates = self.__settings.get_collection("player_clan_candidates")
        self.player_clan_watches = self.__settings.get_collection("player_clan_watches")
        self.clan_roster_snapshots = self.__settings.get_collection("clan_roster_snapshots")
        # Bounded DM /todo auto-refresh sessions. TTL index on expires_at is
        # created lazily by utils/todo_sessions.py.
        self.todo_sessions = self.__settings.get_collection("todo_sessions")
        # Durable, member-owned Clash of Cards inventories.  One document per
        # player tag; event cards are not exposed by Supercell's public API.
        self.card_inventories = self.__settings.get_collection("card_inventories")
        # Two-party card proposals and their expiring reservations. Completed
        # rows remain as a compact audit trail; no screenshots or tokens live here.
        self.card_trades = self.__settings.get_collection("card_trades")
