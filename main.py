import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import os
import hikari
import lightbulb
from dotenv import load_dotenv
from utils.mongo import MongoClient
import coc
from utils.startup import load_cogs
from utils.cloudinary_client import CloudinaryClient
from extensions.autocomplete import preload_autocomplete_cache
from extensions.events.message import dm_screenshot_upload
from utils import bot_data

load_dotenv()

# Create a GatewayBot instance with intents
bot = hikari.GatewayBot(
    token=os.getenv("DISCORD_TOKEN"),
    intents=(
        hikari.Intents.GUILD_MESSAGES
        | hikari.Intents.MESSAGE_CONTENT
        | hikari.Intents.GUILDS
        | hikari.Intents.GUILD_MEMBERS
        | hikari.Intents.GUILD_MODERATION
        | hikari.Intents.GUILD_MESSAGE_REACTIONS
    ),
)

client = lightbulb.client_from_app(bot)

mongo_client = MongoClient(uri=os.getenv("MONGODB_URI"))
clash_client = coc.Client(
    base_url='https://proxy.clashk.ing/v1',
    key_count=10,
    load_game_data=coc.LoadGameData(default=False),
    raw_attribute=True,
)

cloudinary_client = CloudinaryClient()

bot_data.data["mongo"] = mongo_client
bot_data.data["cloudinary_client"] = cloudinary_client
bot_data.data["bot"] = bot
bot_data.data["coc_client"] = clash_client

registry = client.di.registry_for(lightbulb.di.Contexts.DEFAULT)
registry.register_value(MongoClient, mongo_client)
registry.register_value(coc.Client, clash_client)
registry.register_value(CloudinaryClient, cloudinary_client)
registry.register_value(hikari.GatewayBot, bot)

@bot.listen(hikari.StartingEvent)
async def on_starting(_: hikari.StartingEvent) -> None:
    """Bot starting event"""
    all_extensions = [
        "extensions.components",
        "extensions.commands.clan.list",
        "extensions.commands.fwa.bases",
        "extensions.context_menus.get_message_id",
        "extensions.context_menus.get_user_id",
        "extensions.tasks.band_monitor",
        "extensions.commands.fwa.upload_images",
        "extensions.commands.fwa.war_plans",
        "extensions.commands.tickets",
        "extensions.events.channel.ticket_channel_monitor",
    ] + load_cogs(disallowed={"example"})

    await client.load_extensions(*all_extensions)
    await client.start()
    await clash_client.login_with_tokens("")


@bot.listen(hikari.StartedEvent)
async def on_bot_start(event: hikari.StartedEvent):
    """Load FWA URLs from database on startup"""
    fwa_data = await mongo_client.fwa_data.find_one({"_id": "fwa_config"})

    if fwa_data:
        from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE

        # Load war base images
        if "war_base_images" in fwa_data:
            FWA_WAR_BASE.update(fwa_data["war_base_images"])
            print(f"[INFO] Loaded {len(fwa_data['war_base_images'])} FWA war base URLs")

        # Load active base images
        if "active_base_images" in fwa_data:
            FWA_ACTIVE_WAR_BASE.update(fwa_data["active_base_images"])
            print(f"[INFO] Loaded {len(fwa_data['active_base_images'])} FWA active base URLs")


@bot.listen(hikari.StoppingEvent)
async def on_stopping(_: hikari.StoppingEvent) -> None:
    """Bot stopping event"""
    dm_screenshot_upload.unload(bot)
    # print("Bot stopped, event listeners unloaded")
    # Properly close the coc.py client to avoid unclosed session warnings
    await clash_client.close()

bot.run()