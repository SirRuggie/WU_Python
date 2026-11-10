"""Native layouts for the fourteen additional Recruit Questions messages.

Generated once from the original static component expressions. This checked-in
module has no runtime source parsing and preserves the original layout,
buttons, links, media, and container structure.
"""

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    LinkButtonBuilder as LinkButton,
)
from utils.constants import WU_GOLD
from utils.emoji import emojis

LAZY_CWL_RULES_URL = "https://docs.google.com/document/d/137zYF4CHwW-hqwZXzDVmQWONkao1X-XckjGs5Myg-h0/edit"


def native_components(variant: str, *, recruit_mention: str, recruiter_mention: str,
                      action_id: str = "preview") -> list:
    if variant == 'fwa_clan_chat':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## 💬 **FWA Clan Chat** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "Here’s what to expect from activity and chat in our FWA clans. "
                                "FWA is one of the easiest ways to get loot in the game. "
                                "It suits players who are less active than players who play for social contact or for competition. "
                                "So our clans are not very chatty. "
                                "Clan chat is quiet most of the time, and donations can take longer. You still get them, but they do not always come fast. "
                                "Our Discord server is a good place to talk if you want more conversation.\n\n"
                                "**Would any of this be an issue for you?**"
                            )),
                            Media(
                                items=[
                                    MediaItem(
                                        media="assets/recruit/static/WU_ClanChat.jpg"),
                                ]
                            ),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'get_war_weight':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## ⚖️ **War Weight Check** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "We need your **current war weight** to make fair matchups. Follow these steps:\n\n"
                                f"{emojis.gold_arrow_right} **Post** a Friendly Challenge in-game.\n"
                                f"{emojis.gold_arrow_right} **Scout** the challenge you posted.\n"
                                f"{emojis.gold_arrow_right} **Select** your Town Hall. Then select **Info**.\n"
                                f"{emojis.gold_arrow_right} **Upload** a screenshot of the Town Hall information popup here.\n\n"
                                "*See the example below for reference.*"
                            )),
                            Media(
                                items=[
                                    MediaItem(
                                        media="assets/recruit/static/TH_Weight.png"),
                                ]
                            ),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'heard_of_lazy_cwl':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## 🛋️ **Lazy CWL Overview** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "Have you ever heard of **Lazy CWL** before? 🤔\n\n"
                                "**Lazy CWL** is our relaxed way to play Clan War Leagues. It gives you fun, flexibility and no stress.\n\n"
                                f"{emojis.white_arrow_right} **Have you played Lazy CWL?**\n"
                                f"{emojis.white_arrow_right} **If yes, what do you know about it?**\n\n"
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'lazy_cwl_explanation':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## 🛋️ **Lazy CWL Deep Dive** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "**What is Lazy CWL?**\n"
                                "We run CWL in a laid-back, flexible way,\n"
                                "perfect if you’d otherwise go inactive during league week. \n"
                                "No stress over attacks or donations; just jump in when you can."
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                        ]
                    ),
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=(
                                "**How It Works**\n"
                                f"{emojis.gold_arrow_right} **Brand-New Clans**\n"
                                f"{emojis.blank}{emojis.white_arrow_right} Created each CWL season. Older clans are reused in lower leagues.\n\n"
                                f"{emojis.gold_arrow_right} **FWA Season Transition**\n"
                                f"{emojis.blank}{emojis.white_arrow_right} During the last **FWA War**, complete both attacks and **join your assigned CWL Clan** before the war ends.\n"
                                f"{emojis.blank}{emojis.white_arrow_right} Announcements will be posted to guide you.\n\n"
                                f"{emojis.gold_arrow_right} **League Search**\n"
                                f"{emojis.blank}{emojis.white_arrow_right} Once everyone is in their assigned CWL Clan, we will start the search.\n"
                                f"{emojis.blank}{emojis.white_arrow_right} After the search begins, **return to your Home FWA Clan** immediately.\n"
                            )),
                            ActionRow(components=[LinkButton(
                                url=LAZY_CWL_RULES_URL,
                                label="Lazy CWL Rules",
                            )]),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                        ]
                    ),
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=(
                                "**Participation & Rewards**\n"
                                f"{emojis.gold_arrow_right} **Bonus Medals**\n"
                                f"{emojis.blank}{emojis.white_arrow_right} Medals are awarded through a lottery system.\n\n"
                                f"{emojis.gold_arrow_right} **Participation Requirement**\n"
                                f"{emojis.blank}{emojis.white_arrow_right} Follow the Lazy CWL rules and complete **at least 4+ attacks (60%)**.\n"
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                        ]
                    ),
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=(
                                "**How to Sign Up**\n"
                                "If you **WANT to participate** in CWL, signing up is **mandatory!**\n\n"
                                f"{emojis.gold_arrow_right} Sign up for **each CWL season** in <#1072728485233180692> (#fwa-lazycwl-signups), which is visible after joining the clan.\n\n"
                                f"{emojis.gold_arrow_right} **Last-minute signups are strongly discouraged** and may not be accepted. We run several Lazy CWL clans, and proper planning is crucial.\n\n"
                            )),
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'fwa_leaders_reviewing':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## 🔎 **FWA Leadership Review** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(
                                content=(
                                    "Thank you for applying! Our **FWA leadership team** is now reviewing your submission. "
                                    "This can take a little time as we adjust rosters to accommodate your application.\n\n"
                                    "**Do not ping anyone** during this time.\n"
                                    "We know that you are here. We will update you as soon as we can."
                                )
                            ),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'fwa_bases_upon_approval':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content="## Select FWA Base Town Hall Level"),
                            Text(
                                content="Select the Town Hall level of the recruit in the menu below."),
                            ActionRow(
                                components=[
                                    TextSelectMenu(
                                        max_values=1,
                                        custom_id=f"th_select:{action_id}",
                                        placeholder="Select a Base...",
                                        options=[
                                            SelectOption(
                                                emoji=emojis.TH18.partial_emoji,
                                                label="TH18 New",
                                                value="th18_new"
                                            ),
                                            SelectOption(
                                                emoji=emojis.TH18.partial_emoji,
                                                label="TH18",
                                                value="th18"
                                            ),
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
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'what_is_fwa':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## <a:FWA:1398229188363948055> **FWA Clans Quick Overview** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "## 📌 FWA Clans in Clash of Clans: A Quick Overview\n"
                                f"> Minimum TH for FWA: TH13 {emojis.TH13}\n\n"
                                "FWA, or Farm War Alliance, is a unique concept in Clash of Clans. The goal is to get the most loot and clan XP, not only to win wars.\n\n"
                                "### **__<a:FWA:1398229188363948055> What are the benefits?__**\n"
                                "**<a:Gold_Coins:1398229429892808745> Maximized Loot and XP**\n"
                                "FWA clans give a steady supply of resources and XP. Use them to upgrade bases, troops and heroes.\n\n"
                                "**<a:sleep_zzz:1398229533617946646> War Participation with Upgrading Heroes**\n"
                                "In FWA you can take part in a war even when your heroes are down for upgrades. So you can upgrade all the time.\n\n"
                                "**<:CoolOP:1398229909339508839> Fair Wars**\n"
                                "A lottery decides the war winner. Both sides have a fair chance and get a lot of loot.\n\n"
                                "**<:Waiting:1398229981003382815> Is it against the rules?**\n"
                                "No. FWA clans follow the game rules and do not use hacks or exploits. They stay within the game's terms of service. It is a different but accepted way to play."
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                        ]
                    ),
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=(
                                "## ⚔️ FWA War Plans ⚔️\n"
                                "Below are the two main FWA war plans. Follow the posted plan for each war.\n"
                                "### 💎 WIN WAR 💎\n"
                                "__1st hit:__ ⭐️⭐️⭐️ on your mirror.\n"
                                "__2nd hit:__ ⭐️⭐️ on BASE #1 or any base above you for loot, or wait for the 8-hour cleanup call in Discord.\n"
                                "**The goal is 150 stars!**\n\n"
                                "### ❌ LOSE WAR ❌\n"
                                "__1st hit:__ ⭐️⭐️ on your mirror.\n"
                                "__2nd hit:__ ⭐️ on BASE #1 or any base above you for loot, or wait for the 8-hour cleanup call in Discord.\n"
                                "**The goal is 100 stars!**\n\n"
                                "War Plans are posted via Discord and Clan Mail. Don't hesitate to ping an __FWA Clan Rep__ in your Clan's Chat Channel with any questions you may have."
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                        ]
                    ),
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=(
                                "## 🏰 Default FWA Base 🏰\n"
                                "Below is a picture of a TH13 default FWA War Base. Each Town Hall level is similar. The main difference is at TH12 and above, where the Town Hall is separate. The layout is simple. You can attack for a set number of stars and still get a lot of loot."
                            )),
                            Media(
                                items=[
                                    MediaItem(
                                        media="assets/fwa/static/Default_FWA_Base.jpg")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'what_is_flexible_fun':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## 📌 **Flexible Fun War Clan: A Quick Overview** · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "### Concept\n"
                                "We are a laid-back farm/war clan — **NOT A CAMPING CLAN**. All Town Hall levels are welcome, and heroes are not required for war. "
                                "You may not feel sure about attacking without heroes. This is normal. Our simple default war plan is Drop 2. "
                                "Everyone must make at least the first war attack. We do not judge the result. Do your best. "
                                "Our ultimate goal is a stress-free, fun and flexible experience.\n\n"
                                "### Purpose\n"
                                "Our goal is a fun and flexible war clan. Heroes can be down here. "
                                "Every member can make war attacks, and nobody sits out because of hero upgrades.\n\n"
                                "### Core Rules\n"
                                "**No camping:** This clan is for war. Members must take part.\n"
                                "**Minimum Participation:** Even with heroes down, every member is required to execute at least one war attack. "
                                "Failure to participate in war earns a strike. If you get enough strikes, we can replace you."
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'what_is_tactical':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## ⚔️ **Tactical/Competitive Clans** ⚔️ · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "Our Tactical/Competitive War Clans are divided into two groups.\n\n"
                                "**High Level:** TH13+ Non-Rushed\n\n"
                                "We always aim for 3 ⭐ in war. Do not worry if you get fewer stars. Nobody is perfect. "
                                "We expect members to follow the war format and to work as a team to win every war.\n\n"
                                "**__WE WIN AS A TEAM. WE LOSE AS A TEAM.__**\n\n"
                                "Attack at full strength. Use your heroes. Do not upgrade anything big that makes your attack weaker."
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'fwa_war_plans':
        return [
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content=f"## ⚔️ **FWA War Plans** ⚔️ · {recruit_mention}"),
                            Separator(divider=True),
                            Text(content=(
                                "Below are the two main FWA war plans. Follow the posted plan for each war.\n\n"
                                "**💎 __WIN WAR__ 💎**\n"
                                "1st hit: ⭐⭐⭐ on your mirror.\n"
                                "2nd hit: ⭐⭐ on BASE 1 or any base above you for loot, or wait for the 8-hour cleanup call in Discord. "
                                "**The goal is 150 stars!!**\n\n"
                                "**❌ __LOSE WAR__ ❌**\n"
                                "1st hit: ⭐⭐ on your mirror.\n"
                                "2nd hit: ⭐ on BASE 1 for loot, or wait for the 8-hour cleanup call in Discord. The goal is 100 stars!\n\n"
                                "There are two other plans, \"Blacklisted War\" and \"Mismatch War\". We use the two plans above most of the time.\n\n"
                                "War Plans are posted via Discord and Clan Mail. Don't hesitate to ping me in your Clan's Chat Channel "
                                "with any questions you may have.\n\n"
                                "Follow the posted war plans. This is an important part of FWA. If you do not follow them, you can cause problems and harm the clan. "
                                "**Don't be \"that guy\"**...🫡"
                            )),
                            Media(
                                items=[
                                    MediaItem(media="assets/Gold_Footer.png")
                                ]),
                        ]
                    ),
                    Container(
                        accent_color=WU_GOLD,
                        components=[
                            Text(content="## ⚔️ **DAILY FWA EXPECTATIONS** ⚔️"),
                            Separator(divider=True),
                            Text(content=(
                                "✅ **Attack in wars. Every. Single. Time.**\n"
                                "✅ **Follow posted war plans. They're not suggestions—they're the playbook.**\n"
                                "✅ **Check Discord and Clan Mail for instructions.**\n\n"
                                "Wondering what happens if you ghost a war?\n"
                                "👻 **You land on the Naughty List.**\n"
                                "That means we look for a replacement. No hard feelings, just FWA business.\n\n"
                                "Let's keep it fun, but let's keep it serious too. 💥"
                            )),
                            Media(
                                items=[
                                    MediaItem(media="https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExMjg1amo0dmdsa2lpbnB3NzAzOWhsYWkyczRuNGwwdmRiZHpxb3YxNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o6ZtnrDUtbqynaOys/giphy.gif")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'waiting_response':
        return [
                    Text(content=f"{recruit_mention}"),
                    Container(
                        accent_color=WU_GOLD,
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
    if variant == 'circles':
        return [
                    Text(content=f"{recruit_mention}"),
                    Container(
                        accent_color=WU_GOLD,
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
    if variant == 'today':
        return [
                    Text(content=f"{recruit_mention}"),
                    Container(
                        accent_color=WU_GOLD,
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
    if variant == 'chop_chop':
        return [
                    Text(content=f"{recruit_mention}"),
                    Container(
                        accent_color=WU_GOLD,
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
    raise ValueError("Select a supported recruitment question.")


def native_base_result(*, recruit_mention: str, recruiter_mention: str,
                       friendly_name: str, th_number: str, base_info: str,
                       base_link: str, war_base_media: str, active_war_base_media: str) -> list:
    return [
                Text(content=f"{recruit_mention}"),
                Container(
                    accent_color=WU_GOLD,
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
                                    label="Open base link",
                                )
                            ]
                        ),
                    ]
                ),
                Container(
                    accent_color=WU_GOLD,
                    components=[
                        Text(content=f"### TH{th_number} FWA War Status and Base Layout"),
                        Text(content=base_info),
                        Media(
                            items=[
                                MediaItem(media=active_war_base_media),
                            ]
                        ),
                        Text(content=f"-# Requested by {recruiter_mention}"),
                    ]
                )
            ]
