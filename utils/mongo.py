from pymongo import AsyncMongoClient


class MongoClient(AsyncMongoClient):
    def __init__(self, uri: str, **kwargs):
        super().__init__(host=uri, **kwargs)
        self.__settings = self.get_database("settings")
        self.button_store = self.__settings.get_collection("button_store")
        self.clans = self.__settings.get_collection("clan_data")
        #self.clan_recruitment = self.__settings.get_collection("clan_recruitment")
        self.fwa_data = self.__settings.get_collection("fwa_data")
        self.fwa_band_data = self.__settings.get_collection("fwa_band_data")
        self.ticket_setup = self.__settings.get_collection("ticket_setup")
        #self.user_tasks = self.__settings.get_collection("user_tasks")
        self.bot_config = self.__settings.get_collection("bot_config")
        #self.reddit_monitor = self.__settings.get_collection("reddit_monitor")
        #self.reddit_notifications = self.__settings.get_collection("reddit_notifications")
        #self.clan_bidding = self.__settings.get_collection("clan_bidding")
        #self.new_recruits = self.__settings.get_collection("new_recruits")
        self.ticket_automation_state = self.__settings.get_collection("ticket_automation_state")
        self.recruit_onboarding = self.__settings.get_collection("recruit_onboarding")
        self.lazy_cwl_snapshots = self.__settings.get_collection("lazy_cwl_snapshots")
        self.cwl_pending_reminders = self.__settings.get_collection("cwl_pending_reminders")