import lightbulb
import asyncio
import hikari
import re
from datetime import datetime, timezone
from aiohttp.web_routedef import delete
from hikari import GatewayBot
from hikari.api import LinkButtonBuilder
from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    ThumbnailComponentBuilder as Thumbnail,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    LinkButtonBuilder as LinkButton
)

from extensions.commands.recruit import loader, recruit
from extensions.commands.fwa.helpers import get_fwa_base_object
from utils.constants import (
    GOLDENROD_ACCENT,
    RED_ACCENT,
    GOLD_ACCENT,
    BLUE_ACCENT,
    GREEN_ACCENT,
    FWA_WAR_BASE,
    FWA_ACTIVE_WAR_BASE,
)
from utils.emoji import emojis
from utils.mongo import MongoClient
from extensions.components import register_action

@recruit.register()
class RecruitQuestions(
    lightbulb.SlashCommand,
    name="questions",
    description="Select a new recruit to send them recruit questions"
):
    user = lightbulb.user(
        "discord-user",
        "select a new recruit",
    )

    @lightbulb.invoke
    async def invoke(
        self, 
        ctx: lightbulb.Context, 
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        await ctx.defer(ephemeral=True)
        data = {
            "_id": str(ctx.interaction.id),
            "user_id" : self.user.id
        }
        await mongo.button_store.insert_one(data)
        components = await recruit_questions_page(action_id=str(ctx.interaction.id), **data)
        await ctx.respond(components=components, ephemeral=True)


@register_action("primary_questions", no_return=True)
@lightbulb.di.with_di
async def primary_questions(
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):

    ctx: lightbulb.components.MenuContext = kwargs.get("ctx")
    choice = ctx.interaction.values[0]
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)
    mention_allowed = {
        # don’t auto-parse @everyone or @here
        "parse": [],
        # only ping this one user
        "users": [user.id],
        # no role pings
        "roles": []
    }
    if choice == "attack_strategies":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## ⚔️ **Attack Strategy Breakdown** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "Help us understand your go-to attack strategies!\n\n"
                        f"{emojis.red_arrow_right} **Main Village strategies**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} _e.g. Hybrid, Queen Charge w/ Hydra, Lalo_\n\n"
                        f"{emojis.red_arrow_right} **Clan Capital Attack Strategies**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} _e.g. Super Miners w/ Freeze_\n\n"
                        f"{emojis.red_arrow_right} **Highest Clan Capital Hall level you’ve attacked**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} _e.g. CH 8, CH 9, etc.\n\n_"
                        "*Your detailed breakdown helps us match you to the perfect clan!*"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png"),
                    ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]

    elif choice == "discord_basic_skills":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## 🎓 **Discord Basics Check** · {user.mention}"),
                    Separator(divider=True),
                    Text(
                        content=(
                            "We utilize three main methods to communicate within the Warriors United Server:\n\n"
                            "1️⃣ A comment\n"
                            "2️⃣ A ping within that comment to a specific person/role.\n"
                            "3️⃣ An emoji reaction to a comment.\n\n"
                            "**You've proven #1. Now prove to us you can do #2 and #3...👍🏼**\n\n"
                            "**Click/touch the🛡below to begin.**"
                        )
                    ),
                    Separator(divider=True),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            ),
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        emoji="🛡",
                        custom_id=f"shield_basics:{user.id}:{ctx.member.id}",
                    )
                ]
            ),
        ]
    elif choice == "age_bracket":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## ⏳ **What's Your Age Bracket?** · {user.mention}"),
                    Separator(divider=True),
                    Text(content="**What age bracket do you fall into?**\n\n"),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right}"
                                    "**16 & Under** *(Family-Friendly Clan)*"
                                )
                            )
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="🧒16 & Under",
                            custom_id=f"age:16_under_{user.id}",
                        ),
                    ),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right}"
                                    "**17 – 25**"
                                )
                            )
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="🧑17 – 25",
                            custom_id=f"age:17_25_{user.id}",
                        ),
                    ),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right}"
                                    "**Over 25**"
                                )
                            )
                        ],
                        accessory=Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="🧓Over 25",
                            custom_id=f"age:over_25_{user.id}",
                        ),
                    ),

                    Text(
                        content="*Don’t worry, we’re not knocking on your door! Just helps us get to know you better. 😄👍*"),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png"),
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            ),

        ]
    elif choice == "family_codes":
        # Store listener info in MongoDB
        listener_data = {
            "_id": f"codes_{ctx.interaction.id}_{user_id}",
            "interaction_id": str(ctx.interaction.id),
            "channel_id": ctx.channel_id,
            "user_id": user_id,
            "moderator_id": ctx.member.id,
            "created_at": datetime.now(timezone.utc),
            "completed": False,
            "type": "family_codes"
        }
        await mongo.recruit_onboarding.insert_one(listener_data)
        
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## 🏰 **Keeping it in the Family** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "Warriors United family members may move around the family for "
                        "donations, a Friendly Challenge with an available member, helping "
                        "with Clan Games, or participation in a Family Event. When sending "
                        "a Clan Request use one of these three emoji combos as your "
                        "request message....\n\n"
                        "**⚔️⚔️⚔️**\n"
                        "**⚔️🍻⚔️**\n"
                        "**⚔️☠️⚔️**\n\n"
                        "**DO NOT** use the default join message... I'd like to join your clan.\n\n"
                        "Acknowledge you understand this by sending one of the above "
                        "three codes down below in chat. Just as you would if you were "
                        "going to request to join!"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png"),
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "leaders_checking_you_out":
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=f"## 🔍 **Application Under Review** · {user.mention}"),
                    Separator(divider=True),
                    Text(
                        content=(
                            "Thank you for completing your application! 🎉\n\n"
                            "Our leadership team is now reviewing your responses to find the perfect clan match. "
                            "Please sit tight, we’ll be with you shortly! ⏳\n\n"
                            "We truly appreciate your interest in the Kings Alliance and can’t wait to welcome you aboard!"
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="assets/Red_Footer.png"),
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "welcome_to_family":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## 🛡️ **Welcome to the Family!** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        f"Welcome to the Family!\n\n"
                        f"You are all good to go {user.mention}! Several channels will be available to you on the Main Server shortly. "
                        f"You will receive a ping in the <https://discord.com/channels/644963518025826315/1128966424082255872> and all the appropriate server roles you will need: "
                        f"as well as a link to assigned Clan.\n\n"
                        f"**Once you receive the aforementioned ping, __ping__ your Recruiter to acknowledge you're there.**\n\n"
                        f"They will in turn kick off a server walkthrough guiding you to important channels related to your day to day play.\n\n"
                        f"# Welcome to the Family...here's your 🛡️! Let's get you into Battle!"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png"),
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    message = await bot.rest.create_message(
        components=components,
        channel=ctx.channel_id,
        user_mentions = [user.id],
        role_mentions = True,
    )
    
    
    await asyncio.sleep(20)

    action_id = ctx.interaction.custom_id.split(":", 1)[1]
    new_components = await recruit_questions_page(
        action_id=action_id,
        user_id=user_id,
        ctx=ctx,
    )
    try:
        await ctx.interaction.delete_initial_response()
    except hikari.NotFoundError:
        # Message already deleted or interaction expired, that's fine
        pass
    
    await ctx.respond(
        components=new_components,
        ephemeral=True,
    )

@register_action("age", no_return=True)
@lightbulb.di.with_di
async def on_age_button(
    action_id: str,
    bot: GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):
    ctx: lightbulb.components.MenuContext = kwargs["ctx"]
    bracket, user_id = action_id.rsplit("_", 1)
    user_id = int(user_id)
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)

    if int(ctx.user.id) != user_id:
        await ctx.respond(
            f"Sorry {ctx.user.mention}, this button is only for {user.mention} to click. Please let them continue!",
            ephemeral=True
        )
        return

    await ctx.interaction.delete_initial_response()

    if bracket == "16_under":
        components = [
            Text(content=f"🎉 **16 & Under Registered!** · {user.mention}"),

            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "Got it! You're bringing that youthful energy!\n\n"
                            "We'll find you a family-friendly clan that's the perfect fit for you.\n\n"
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="https://c.tenor.com/oxxT2JPSQccAAAAC/tenor.gif"),
                        ]
                    ),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ],
            )]
        await bot.rest.create_message(
            components=components,
            channel=ctx.channel_id,
            user_mentions = [user.id],
            role_mentions = True,

        )
    elif bracket == "17_25":
        components = [
            Text(content=f"🎮 **17–25 Confirmed** · {user.mention}"),

            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "Understood! You’re in prime gaming years!\n\n"
                            "Time to conquer the Clash world! 🏆\n\n"
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="https://c.tenor.com/twdtlMLE8UIAAAAC/tenor.gif"),
                        ]
                    ),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ],
        )]
        await bot.rest.create_message(
            components=components,
            channel=ctx.channel_id,
            user_mentions = [user.id],
            role_mentions = True,
        )
    elif bracket == "over_25":
        components = [
            Text(content=f"🏅 **Age Locked In** · {user.mention}"),

            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "Awesome! Experience meets strategy!\n\n"
                            "Welcome to the veteran league of Clashers! 💪\n\n"
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="https://c.tenor.com/m6o-4dKGdVAAAAAC/tenor.gif"),
                        ]
                    ),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ],
        )]
        await bot.rest.create_message(
            components=components,
            channel=ctx.channel_id,
            user_mentions = [user.id],
            role_mentions = True,
        )

@register_action("shield_basics", no_return=True)
@lightbulb.di.with_di
async def on_shield_basics_button(
    action_id: str,
    bot: GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):
    ctx: lightbulb.components.MenuContext = kwargs["ctx"]
    # Parse user_id and recruiter_id from action_id
    parts = action_id.split(":")
    user_id = int(parts[0])
    original_recruiter_id = int(parts[1]) if len(parts) > 1 else ctx.member.id
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)
    original_recruiter = await bot.rest.fetch_member(ctx.guild_id, original_recruiter_id)

    if int(ctx.user.id) != user_id:
        await ctx.respond(
            f"Sorry {ctx.user.mention}, this button is only for {user.mention} to click. Please let them continue!",
            ephemeral=True
        )
        return
    
    # Get the original interaction ID from the custom_id
    original_interaction_id = ctx.interaction.custom_id.split(":")[0].replace("shield_basics", "primary_questions")
    
    # Try to get the message ID from the interaction message
    message_id = ctx.interaction.message.id
    
    # Try to edit the message to remove the button
    if message_id:
        try:
            # Create the same message but without the button
            components_without_button = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"## 🎓 **Discord Basics Check** · <@{user_id}>"),
                        Separator(divider=True),
                        Text(
                            content=(
                                "We utilize three main methods to communicate within the Warriors United Server:\n\n"
                                "1️⃣ A comment\n"
                                "2️⃣ A ping within that comment to a specific person/role.\n"
                                "3️⃣ An emoji reaction to a comment.\n\n"
                                "**You've proven #1. Now prove to us you can do #2 and #3...👍🏼**\n\n"
                                "**Shield challenge started!**"
                            )
                        ),
                        Separator(divider=True),
                        Text(content=f"-# Requested by <@{original_recruiter_id}>"),
                    ]
                ),
            ]
            await bot.rest.edit_message(ctx.channel_id, message_id, components=components_without_button)
        except Exception as e:
            print(f"[ShieldBasics] Could not edit message to remove button: {e}")
    
    # Clean up any existing challenges for this user/channel combination
    delete_result = await mongo.button_store.delete_many({
        "channel_id": ctx.channel_id,
        "user_id": user_id,
        "challenge_type": "goblin_ping"
    })
    
    if delete_result.deleted_count > 0:
        print(f"[ShieldBasics] Cleaned up {delete_result.deleted_count} existing challenge(s) for user {user_id}")
    
    # Store the new goblin challenge in MongoDB
    challenge_data = {
        "channel_id": ctx.channel_id,
        "user_id": user_id,
        "recruiter_id": original_recruiter_id,  # The original recruiter who initiated the questions
        "challenge_type": "goblin_ping",
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    }
    result = await mongo.button_store.insert_one(challenge_data)
    print(f"[ShieldBasics] Stored goblin challenge: channel={ctx.channel_id}, user={user_id}, recruiter={original_recruiter_id}, id={result.inserted_id}")
    
    # Send the message with goblin gif
    components = [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=f"Excellent!! {user.mention} You in essence reacted to a reaction."),
                Separator(divider=True),
                Text(
                    content=(
                        "You've proven to be 50% smarter than the average discord user....👍🏻\n\n"
                        "Now respond with the word Goblin and actually ping the Recruiter helping you with your ticket.\n\n"
                        "If you don't now how to ping a person/role in Discord, no worries... respond with How to ping."
                    )
                ),
                Media(
                    items=[
                        MediaItem(media="https://c.tenor.com/QU6S8dijTV4AAAAC/tenor.gif")
                    ]
                ),
                Text(content=f"-# Requested by <@{original_recruiter_id}>"),
            ]
        )
    ]
    
    await bot.rest.create_message(
        components=components,
        channel=ctx.channel_id,
        user_mentions=[user.id],
        role_mentions=True,
    )
    

### FWA Questions Section
@register_action("fwa_questions" ,no_return=True)
@lightbulb.di.with_di
async def fwa_questions(
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):

    ctx: lightbulb.components.MenuContext = kwargs.get("ctx")
    choice = ctx.interaction.values[0]
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)

    if choice == "fwa_clan_chat":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## 💬 **FWA Clan Chat** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "An important thing that needs to be addressed about our FWA clan activity/chat. "
                        "Due to how the FWA works we offer one of the easiest methods to gain loot in the game, "
                        "and that is most attractive to players who aren't as active as players who either play "
                        "the game socially or competitively. On the norm, the clans aren't that chatty. "
                        "The clan chat is quiet most of the time, and receiving donations isn't always the quickest either. "
                        "Not to say you won't get them just not always lighting fast. "
                        "Our Discord Server is a good means for a social chat if you desire.\n\n"
                        "**Would any of this be an issue for you?**"
                    )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1753732333/misc_images/WU_ClanChat.jpg"),
                        ]
                    ),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "get_war_weight":
        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content=f"## ⚖️ **War Weight Check** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "We need your **current war weight** to ensure fair matchups. Please:\n\n"
                        f"{emojis.red_arrow_right} **Post** a Friendly Challenge in-game.\n"
                        f"{emojis.red_arrow_right} **Scout** that challenge you posted\n"
                        f"{emojis.red_arrow_right} **Tap** on your Town Hall, then hit **Info**.\n"
                        f"{emojis.red_arrow_right} **Upload** a screenshot of the Town Hall info_hub popup here.\n\n"
                        "*See the example below for reference.*"
                    )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1751550804/TH_Weight.png"),
                        ]
                    ),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "heard_of_lazy_cwl":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## 🛋️ **Lazy CWL Overview** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "Have you ever heard of **Lazy CWL** before? 🤔\n\n"
                        "**Lazy CWL** is our laid-back twist on Clan War Leagues,\n"
                        "designed for fun, flexibility, and zero stress.\n\n"
                        f"{emojis.white_arrow_right} **Have you played lazy CWL?**\n"
                        f"{emojis.white_arrow_right} **If so, what's your experience or understanding of it?**\n\n"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "lazy_cwl_explanation":
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"## 🛋️ **Lazy CWL Deep Dive** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "**What is Lazy CWL?**\n"
                        "We run CWL in a laid-back, flexible way,\n"
                        "perfect if you’d otherwise go inactive during league week. \n"
                        "No stress over attacks or donations; just jump in when you can."
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                ]
            ),
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=(
                        "**How It Works**\n"
                        f"{emojis.red_arrow_right} **Brand-New Clans**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} Created each CWL season. Old clans reused in lower leagues.\n\n"
                        f"{emojis.red_arrow_right} **FWA Season Transition**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} During the last **FWA War**, complete both attacks and **join your assigned CWL Clan** before the war ends.\n"
                        f"{emojis.blank}{emojis.white_arrow_right} Announcements will be posted to guide you.\n\n"
                        f"{emojis.red_arrow_right} **League Search**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} Once everyone is in their assigned CWL Clan, we will start the search.\n"
                        f"{emojis.blank}{emojis.white_arrow_right} After the search begins, **return to your Home FWA Clan**  immediately.\n"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                ]
            ),
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=(
                        "**Participation & Rewards**\n"
                        f"{emojis.red_arrow_right} **Bonus Medals**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} Medals are awarded through a lottery system.\n\n"
                        f"{emojis.red_arrow_right} **Participation Requirement**\n"
                        f"{emojis.blank}{emojis.white_arrow_right} Follow Lazy CWL Rules and complete **at least 4+ attacks (60%)**\n"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                ]
            ),
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=(
                        "**How to Sign Up**\n"
                        "If you **WANT to participate** in CWL, signing up is **mandatory!**\n\n"
                        f"{emojis.red_arrow_right} Sign up for **each CWL season** in <#1072728485233180692> or channel name #fwa-lazycwl-signups , visible after joining the clan.\n\n"
                        f"{emojis.red_arrow_right} **Last-minute signups are strongly discouraged** and may not be accepted. We run several Lazy CWL clans, and proper planning is crucial.\n\n"
                    )),
                    Section(
                        components=[
                            Text(
                                content=(
                                    f"{emojis.white_arrow_right}"
                                    "**More Info**"
                                )
                            )
                        ],
                        accessory=LinkButton(
                            url="https://docs.google.com/document/d/13HrxwaUkenWZ4F1QNCPzdM5n5uXYcLqQYOdQzyQksuA/edit?tab=t.0",
                            label="Deep-Dive Lazy CWL Rules",
                        ),
                    ),
                    Separator(divider=True),
                    Text(content=(
                        "## **<a:Alert:1398260063075827745>IMPORTANT:**\n"
                        "*Participating in CWL outside of Warriors United is **__not allowed if__** you are part of our FWA Operation.*\n\n"
                        "If you're good with the Lazy Way, respond with...\n"
                        "**__Lazy Way is My Way!!__**"
                    )),

                    Media(
                        items=[
                            MediaItem(media="https://c.tenor.com/MMuc_dX1D7AAAAAC/tenor.gif")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "fwa_leaders_reviewing":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## 🔎 **FWA Leadership Review** · {user.mention}"),
                    Separator(divider=True),
                    Text(
                        content=(
                            "Thank you for applying! Our **FWA leadership team** is now reviewing your submission. "
                            "This can take a little time as we adjust rosters and to accommodate your application.\n\n"
                            "We kindly ask that you **do not ping anyone** during this time.\n"
                            "Rest assured, we are aware of your presence and will update you as soon as possible."
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "fwa_bases_upon_approval":
        action_id = ctx.interaction.custom_id.split(":", 1)[1]

        fwa = await get_fwa_base_object(mongo)
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## Select FWA Base Town Hall Level"),
                    Text(
                        content="Use the dropdown menu below to assign the appropriate Town Hall level for the recruit."),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                max_values=1,
                                custom_id=f"th_select:{action_id}",
                                placeholder="Select a Base...",
                                options=[
                                    SelectOption(
                                        emoji=emojis.TH17.partial_emoji,
                                        label="TH17",
                                        value="th17"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH17.partial_emoji,
                                        label="TH17 New",
                                        value="th17_new"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH16.partial_emoji,
                                        label="TH16",
                                        value="th16"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH16.partial_emoji,
                                        label="TH16 New",
                                        value="th16_new"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH15.partial_emoji,
                                        label="TH15",
                                        value="th15"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH14.partial_emoji,
                                        label="TH14",
                                        value="th14"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH13.partial_emoji,
                                        label="TH13",
                                        value="th13"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH12.partial_emoji,
                                        label="TH12",
                                        value="th12"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH11.partial_emoji,
                                        label="TH11",
                                        value="th11"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH10.partial_emoji,
                                        label="TH10",
                                        value="th10"
                                    ),
                                    SelectOption(
                                        emoji=emojis.TH9.partial_emoji,
                                        label="TH9",
                                        value="th9"
                                    ),
                                ],
                            ),
                        ]
                    ),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
        await ctx.respond(
            components=components,
            ephemeral=True,
        )

    if choice != "fwa_bases_upon_approval":
        await bot.rest.create_message(
            components=components,
            channel=ctx.channel_id,
            user_mentions = [user.id],
            role_mentions = True,
        )

    await asyncio.sleep(10)
    action_id = ctx.interaction.custom_id.split(":", 1)[1]
    new_components = await recruit_questions_page(
        action_id=action_id,
        user_id=user_id,
        ctx=ctx,
    )
    try:
        await ctx.interaction.delete_initial_response()
    except hikari.NotFoundError:
        # Message already deleted or interaction expired, that's fine
        pass
    await ctx.respond(
        components=new_components,
        ephemeral=True,
    )

@register_action("th_select" ,no_return=True)
@lightbulb.di.with_di
async def th_select(
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
):

    ctx: lightbulb.components.MenuContext = kwargs.get("ctx")
    choice = ctx.interaction.values[0]
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)
    fwa = await get_fwa_base_object(mongo)
    
    # Check if FWA data exists
    if not fwa:
        await ctx.respond(
            "❌ **FWA Data Not Found**\n\n"
            "The FWA data is not in the database yet. "
            "Please use the `/clan dashboard` command to add all FWA data first.",
            ephemeral=True
        )
        return
    
    # Format display name properly for _new variants
    if choice.endswith('_new'):
        base_th = choice.replace('_new', '')
        th_number = base_th.lstrip('th')
        display_name = f"TH{th_number} New"
        friendly_name = f"Town Hall {th_number} New"
    else:
        th_number = choice.lstrip('th')
        display_name = f"TH{th_number}"
        friendly_name = f"Town Hall {th_number}"
    
    base_link = getattr(fwa.fwa_base_links, choice, None)
    
    # Check if base_link exists
    if not base_link:
        await ctx.respond(
            f"❌ **FWA Base Link Not Found**\n\n"
            f"The FWA base link for {display_name} is not configured in the database. "
            "Please use the `/clan dashboard` command to add all FWA base links.",
            ephemeral=True
        )
        return
    
    # Check if media URLs exist
    war_base_media = FWA_WAR_BASE.get(choice)
    active_war_base_media = FWA_ACTIVE_WAR_BASE.get(choice)
    
    if not war_base_media or not active_war_base_media:
        await ctx.respond(
            f"❌ **FWA Base Images Not Found**\n\n"
            f"The FWA base images for {display_name} are not configured. "
            "Please contact an administrator to add the FWA base images.",
            ephemeral=True
        )
        return
    
    components = [
        Text(content=f"{user.mention}"),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"## {friendly_name}"),
                Media(
                    items=[
                        MediaItem(media=war_base_media),
                    ]
                ),
                ActionRow(
                    components=[
                        LinkButton(
                            url=base_link,
                            label="Click Me!",
                        )
                    ]
                ),
            ]
        ),
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="### FWA Base"),
                Text(content=(
                    "In order to proceed further, we request that you switch your active war base to the link provided above.\n\n"
                    "Once you have made the switch, please send us a screenshot like below to confirm the update.\n"
                )),
                Media(
                    items=[
                        MediaItem(media=active_war_base_media),
                    ]
                ),
                Text(content=f"-# Requested by {ctx.member.mention}"),
            ]
        )
    ]
    await bot.rest.create_message(
        components=components,
        channel=ctx.channel_id,
        user_mentions = [user.id],
        role_mentions=True,
    )

### Explanation Section
@register_action("explanations", no_return=True)
@lightbulb.di.with_di
async def explanations(
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):

    ctx: lightbulb.components.MenuContext = kwargs.get("ctx")
    choice = ctx.interaction.values[0]
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)

    if choice == "what_is_fwa":
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"## <a:FWA:1398229188363948055> **FWA Clans Quick Overview** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "## 📌 FWA Clans in Clash of Clans: A Quick Overview\n"
                        f"> Minimum TH for FWA: TH13 {emojis.TH13}\n\n"
                        "FWA, or Farm War Alliance, is a unique concept in Clash of Clans. It's all about maximizing loot and clan XP, rather than focusing solely on winning wars.\n\n"
                        "### **__<a:FWA:1398229188363948055> What are the benefits?__**\n"
                        "**<a:Gold_Coins:1398229429892808745> Maximized Loot and XP**\n"
                        "FWA clans aim to ensure a steady stream of resources and XP, perfect for upgrading bases, troops, and heroes.\n\n"
                        "**<a:sleep_zzz:1398229533617946646> War Participation with Upgrading Heroes**\n"
                        "Unlike traditional wars, in FWA you can participate even if your heroes are down for upgrades, making continuous progress possible.\n\n"
                        "**<:CoolOP:1398229909339508839> Fair Wars**\n"
                        "War winners are decided via a lottery system, ensuring fair chances and significant loot for both sides.\n\n"
                        "**<:Waiting:1398229981003382815> Is it against the rules?**"
                        "No, as long as FWA clans follow the game rules and don't use any hacks or exploits, they are within the game's terms of service. It's a unique and accepted way of playing the game."
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                ]
            ),
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=(
                        "## ⚔️ FWA War Plans ⚔️\n"
                        "Below are your two main war plans for FWA. Follow these and all will be good\n"
                        "### 💎 WIN WAR💎\n"
                        "__1st hit:__⭐️⭐️⭐️ star your mirror.\n"
                        "__2nd hit:__⭐️⭐️ BASE #1 or any base above you for loot or wait for 8 hr cleanup call in Discord.\n"
                        "**Goal is 150 Stars!**\n\n"
                        "### ❌ LOSE WAR ❌\n"
                        "__1st hit:__⭐️⭐️star your mirror.\n"
                        "__2nd hit:__⭐️BASE #1 or any base above you for loot or wait for 8 hr cleanup call in Discord.\n"
                        "**Goal is 100 Stars!**\n\n"
                        "War Plans are posted via Discord and Clan Mail. Don't hesitate to ping an __FWA Clan Rep__ in your Clan's Chat Channel with any questions you may have."
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                ]
            ),
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=(
                        "## 🏰 Default FWA Base 🏰\n"
                        "Below is a picture of a TH13 default FWA War Base. Each TH Level is similar with the major difference being TH12+ where the TH is separate. It's a simple layout that allows you to strategically attack for a certain star count but still maximize the most loot available."
                    )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://res.cloudinary.com/dxmtzuomk/image/upload/v1751616880/Default_FWA_Base.jpg")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "what_is_flexible_fun":
        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"## 📌 **Flexible Fun War Clan: A Quick Overview** · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "### Concept\n"
                        "We are a laid-back farm/war clan — **NOT A CAMPING CLAN**. All Town Levels are welcomed here with no Heroes required to be in war. "
                        "Because of this scenario, we understand that some may not feel confident to attack in war. Solution, simple default war plan...Drop 2. "
                        "We require everyone to at least make their first war attack. No judgement on passed on the outcome, just do your best. "
                        "Our ultimate goal is a stress-free, fun and flexible experience.\n\n"
                        "### Purpose\n"
                        "Our goal is to cultivate a fun and flexible war environment. Here, heroes can be down, ensuring every member has the chance to partake "
                        "in war attacks, freeing the mind from the stress of sitting out due to hero upgrades.\n\n"
                        "### Core Rules\n"
                        "**No Camping Allowed:** This clan is dedicated to warring. Active participation is a must.\n"
                        "**Minimum Participation:** Even with heroes down, every member is required to execute at least one war attack. "
                        "Failure to participate in war earns a strike. Accumulate enough strikes, and you risk replacement."
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "what_is_tactical":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## ⚔️ **Tactical/Competitive Clans** ⚔️ · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "Our Tactical/Competitive War Clans are divided into two groups.\n\n"
                        "**High Level:** TH13+ Non Rushed\n\n"
                        "We always strive to obtain 3 ⭐'s in war. Not to worry if you fail; they can't all be perfect; "
                        "but we expect our members to follow the War Format set in place and are committed to winning every "
                        "war as part of an overall team effort.\n\n"
                        "**__WE WIN AS A TEAM. WE LOSE AS A TEAM.__**\n\n"
                        "Attacks are always at full strength (No major upgrades in place, Heroes, and the like)."
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Gold_Footer.png")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    elif choice == "fwa_war_plans":
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## ⚔️ **FWA War Plans** ⚔️ · {user.mention}"),
                    Separator(divider=True),
                    Text(content=(
                        "Below are your two main war plans for FWA. Follow these and all will be good.\n\n"
                        "**💎 __WIN WAR__ 💎**\n"
                        "1st hit: ⭐⭐⭐ star your mirror.\n"
                        "2nd hit: ⭐⭐ BASE 1 for loot or any base above you for loot or wait for 8 hr cleanup call in Discord. "
                        "**Goal is 150 Stars!!**\n\n"
                        "**❌ __LOSE WAR__ ❌**\n"
                        "1st hit: ⭐⭐ star your mirror.\n"
                        "2nd hit: ⭐ BASE 1 for loot or wait for 8 hr cleanup call in Discord. The goal is 100 Stars!\n\n"
                        "There are two other plans \"Blacklisted War\" and \"Mismatch War\" but the above two are the most used.\n\n"
                        "War Plans are posted via Discord and Clan Mail. Don't hesitate to ping me in your Clan's Chat Channel "
                        "with any questions you may have.\n\n"
                        "Following the posted war plans is an important part of FWA. Deviation can cause headaches and potentially "
                        "harm to the clan. **Don't be \"that guy\"**...🫡"
                    )),
                    Media(
                        items=[
                            MediaItem(media="assets/Blue_Footer.png")
                        ]),
                ]
            ),
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## ⚔️ **DAILY FWA EXPECTATIONS** ⚔️"),
                    Separator(divider=True),
                    Text(content=(
                        "✅ **Attack in wars. Every. Single. Time.**\n"
                        "✅ **Follow posted war plans. They're not suggestions—they're the playbook.**\n"
                        "✅ **Check Discord & Clan Mail for instructions.**\n\n"
                        "Wondering what happens if you ghost a war?\n"
                        "👻 **You land on the Naughty List.**\n"
                        "That means we start looking for a replacement. No hard feelings, just FWA business.\n\n"
                        "Let's keep it fun, but let's keep it serious too. 💥"
                    )),
                    Media(
                        items=[
                            MediaItem(media="https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExMjg1amo0dmdsa2lpbnB3NzAzOWhsYWkyczRuNGwwdmRiZHpxb3YxNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o6ZtnrDUtbqynaOys/giphy.gif")
                        ]),
                    Text(content=f"-# Requested by {ctx.member.mention}"),
                ]
            )
        ]
    await bot.rest.create_message(
        components=components,
        channel=ctx.channel_id,
        user_mentions = [user.id],
        role_mentions=True,
    )

    await asyncio.sleep(10)
    action_id = ctx.interaction.custom_id.split(":", 1)[1]
    new_components = await recruit_questions_page(
        action_id=action_id,
        user_id=user_id,
        ctx=ctx,
    )
    await ctx.interaction.delete_initial_response()
    await ctx.respond(
        components=new_components,
        ephemeral=True,
    )


### HURRY TF UP Section
@register_action("keep_it_moving", no_return=True)
@lightbulb.di.with_di
async def keep_it_moving(
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs
):

    ctx: lightbulb.components.MenuContext = kwargs.get("ctx")
    choice = ctx.interaction.values[0]
    user = await bot.rest.fetch_member(ctx.guild_id, user_id)

    if choice == "waiting_response":
        components = [
            Text(content=f"{user.mention}"),
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "At this rate, I’ll finish my snack and a three-course meal. Any day now... 🥪⏳\n"
                        )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://c.tenor.com/E4TulgtK2ssAAAAC/tenor.gif")
                        ]),
                ]
            ),
        ]
    elif choice == "circles":
        components = [
            Text(content=f"{user.mention}"),
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "Waiting for your response like: round and round we go… Any time now! 🌀⏳\n"
                        )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://c.tenor.com/NcibGDKTKQAAAAAd/tenor.gif")
                        ]),
                ]
            ),
        ]
    elif choice == "today":
        components = [
            Text(content=f"{user.mention}"),
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "Still waiting like it’s the DMV. T-t-t-today junior, the clan’s got places to be! 🕰️🚦\n"
                        )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://c.tenor.com/je0FzJYReA0AAAAd/tenor.gif")
                        ]),
                ]
            ),
        ]
    elif choice == "chop_chop":
        components = [
            Text(content=f"{user.mention}"),
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(
                        content=(
                            "Dragging this out won’t end well for anyone. Chop-chop, before I start sharpening the knives... 🔪⏳\n"
                        )),
                    Media(
                        items=[
                            MediaItem(
                                media="https://c.tenor.com/Q0fmnnIHcRoAAAAC/tenor.gif")
                        ]),
                ]
            ),
        ]
    await bot.rest.create_message(
        components=components,
        channel=ctx.channel_id,
        user_mentions = [user.id],
        role_mentions=True,
    )

    await asyncio.sleep(10)
    action_id = ctx.interaction.custom_id.split(":", 1)[1]
    new_components = await recruit_questions_page(
        action_id=action_id,
        user_id=user_id,
        ctx=ctx,
    )
    await ctx.interaction.delete_initial_response()
    await ctx.respond(
        components=new_components,
        ephemeral=True,
    )

async def recruit_questions_page(
    action_id: str,
    user_id: int,
    **kwargs
):
    components = [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=(
                    "An all-in-one toolkit to efficiently recruit candidates into Warriors United\n\n"
                    f"{emojis.red_arrow_right} Primary Questions: Send tailored candidate questions.\n"
                    f"{emojis.red_arrow_right} Explanations: Summarise FWA\n"
                    f"{emojis.red_arrow_right} FWA Questions: Send core FWA questions.\n"
                    f"{emojis.red_arrow_right} Keep It Moving: Send quick “hurry up” GIFs.\n\n"
                    "Stay organized, efficient, and aligned with Kings recruitment standards.\n\n"
                )),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            max_values=1,
                            custom_id=f"primary_questions:{action_id}",
                            placeholder="Primary Questions",
                            options=[
                                SelectOption(
                                    emoji="⚔️",
                                    label="Attack Strategies",
                                    value="attack_strategies"),
                                SelectOption(
                                    emoji="💬",
                                    label="Discord Basic Skills",
                                    value="discord_basic_skills"),
                                # DISABLED - Age Bracket - 2025-07-25
                                # SelectOption(
                                #     emoji="🕐",
                                #     label="Age Bracket",
                                #     value="age_bracket"),
                                SelectOption(
                                    emoji="🏰",
                                    label="Family Codes",
                                    value="family_codes"),
                                SelectOption(
                                    emoji="👀",
                                    label="Leaders Checking You Out",
                                    value="leaders_checking_you_out"),
                                SelectOption(
                                    emoji="🛡️",
                                    label="Welcome to the Family",
                                    value="welcome_to_family"),
                    ]),
                ]),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            max_values=1,
                            custom_id=f"fwa_questions:{action_id}",
                            placeholder="FWA Questions",
                            options=[
                                SelectOption(
                                    emoji="💬",
                                    label="FWA Clan Chat",
                                    value="fwa_clan_chat"
                                ),
                                SelectOption(
                                    emoji="⚖️",
                                    label="Get War Weight",
                                    value="get_war_weight"
                                ),
                                SelectOption(
                                    emoji=1157399772018249828,
                                    label="Heard of Lazy CWL?",
                                    value="heard_of_lazy_cwl"
                                ),
                                SelectOption(
                                    emoji=1004110859729125466,
                                    label="Lazy CWL Explanation",
                                    value="lazy_cwl_explanation"
                                ),
                                SelectOption(
                                    emoji=1001907873170849792,
                                    label="FWA Leaders Reviewing",
                                    value="fwa_leaders_reviewing"
                                ),
                                SelectOption(
                                    emoji=1387844788853801081,
                                    label="FWA Bases (Upon Approval)",
                                    value="fwa_bases_upon_approval"
                                ),
                            ],
                        ),
                    ]
                ),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            max_values=1,
                            custom_id=f"explanations:{action_id}",
                            placeholder="Explanations",
                            options=[
                                SelectOption(
                                    emoji=1387882523358527608,
                                    label="What is FWA",
                                    value="what_is_fwa"
                                ),
                                SelectOption(
                                    emoji="⚔️",
                                    label="FWA War Plans",
                                    value="fwa_war_plans"
                                ),
                                SelectOption(
                                    emoji="🎯",
                                    label="What is Flexible Fun",
                                    value="what_is_flexible_fun"
                                ),
                                SelectOption(
                                    emoji="⚔️",
                                    label="What is Tactical",
                                    value="what_is_tactical"
                                ),
                            ],
                        ),
                    ]
                ),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            max_values=1,
                            custom_id=f"keep_it_moving:{action_id}",
                            placeholder="Keep It Moving",
                            options=[
                                SelectOption(
                                    emoji=1318704702443094150,
                                    label="Waiting for Response...",
                                    value="waiting_response"
                                ),
                                SelectOption(
                                    emoji=999526289738317834,
                                    label="Going in Circles...",
                                    value="circles"
                                ),
                                SelectOption(
                                    emoji=1231080049332191305,
                                    label="Today Jr...",
                                    value="today"
                                ),
                                SelectOption(
                                    emoji=1390616848730685500,
                                    label="Chop Chop...",
                                    value="chop_chop"
                                ),
                            ],
                        ),
                    ]
                ),
                Media(
                    items=[
                        MediaItem(media="assets/Gold_Footer.png")
                ]),
                Text(content="-# Warriors United – Where Strength Meets Honor"),
            ]),
        ]

    return components


# Valid emoji codes for keeping it in the family
VALID_EMOJI_CODES = [
    "⚔️⚔️⚔️",
    "⚔️🍻⚔️",
    "⚔️☠️⚔️"
]

@loader.listener(hikari.GuildMessageCreateEvent)
@lightbulb.di.with_di
async def on_family_code_response(
        event: hikari.GuildMessageCreateEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED
):
    """Listen for emoji code responses from recruit questions"""
    
    # Ignore bot messages
    if event.is_bot:
        return
    
    # Check for None content first
    if event.content is None:
        return
    
    # Check if this user has an active family_codes listener
    listener = await mongo.recruit_onboarding.find_one({
        "user_id": event.author_id,
        "channel_id": event.channel_id,
        "type": "family_codes",
        "completed": False
    })
    
    if listener:
        # Check if message contains valid code
        message_content = event.content.strip()
        
        # Check if any of the valid codes appear anywhere in the message
        code_found = None
        for code in VALID_EMOJI_CODES:
            if code in message_content:
                code_found = code
                break
        
        if code_found:
            # Valid code received!
            # Update MongoDB
            await mongo.recruit_onboarding.update_one(
                {"_id": listener["_id"]},
                {
                    "$set": {
                        "completed": True,
                        "completed_at": datetime.now(timezone.utc),
                        "code_used": code_found
                    }
                }
            )
            
            # Get moderator info for footer
            try:
                moderator = await event.app.rest.fetch_member(event.guild_id, listener["moderator_id"])
                moderator_name = moderator.display_name
            except:
                moderator_name = "Unknown"
            
            # Send success message
            success_components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content="## ✅ Code Confirmed!"),
                        Separator(divider=True),
                        Text(content=(
                            f"{event.author.mention} **Thank you for acknowledging!**\n\n"
                            f"We encourage and allow temporary movement within the family but if you desire a permanent move to another clan we need to discuss it further with Leadership. So from here forward, the Clan you are assigned to is your **\"Home Clan\"**. Always come back home...👍🏼\n\n"
                            f"The **{code_found}**; or any of the code combinations; will get you in to any clan within the Family.... remember that...💪🏼.\n\n"
                        )),
                        Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
                        Text(content=f"-# Confirmation triggered by {moderator_name}"),
                    ]
                )
            ]
            
            await event.app.rest.create_message(
                channel=event.channel_id,
                components=success_components,
                user_mentions=[event.author_id, listener["moderator_id"]]
            )


loader.command(recruit)