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
from utils.constants import GOLDENROD_ACCENT, GOLD_ACCENT, BLUE_ACCENT
from utils.emoji import emojis


def native_components(variant: str, *, recruit_mention: str, recruiter_mention: str,
                      action_id: str = "preview") -> list:
    if variant == 'fwa_clan_chat':
        return [
                    Container(
                        accent_color=GOLDENROD_ACCENT,
                        components=[
                            Text(content=f"## 💬 **FWA Clan Chat** · {recruit_mention}"),
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
                        accent_color=GOLD_ACCENT,
                        components=[
                            Text(content=f"## ⚖️ **War Weight Check** · {recruit_mention}"),
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
                        accent_color=GOLDENROD_ACCENT,
                        components=[
                            Text(content=f"## 🛋️ **Lazy CWL Overview** · {recruit_mention}"),
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'lazy_cwl_explanation':
        return [
                    Container(
                        accent_color=BLUE_ACCENT,
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'fwa_leaders_reviewing':
        return [
                    Container(
                        accent_color=GOLDENROD_ACCENT,
                        components=[
                            Text(content=f"## 🔎 **FWA Leadership Review** · {recruit_mention}"),
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'fwa_bases_upon_approval':
        return [
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
                                    MediaItem(media="assets/Blue_Footer.png")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'what_is_fwa':
        return [
                    Container(
                        accent_color=BLUE_ACCENT,
                        components=[
                            Text(content=f"## <a:FWA:1398229188363948055> **FWA Clans Quick Overview** · {recruit_mention}"),
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
                                        media="assets/fwa/static/Default_FWA_Base.jpg")
                                ]),
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'what_is_flexible_fun':
        return [
                    Container(
                        accent_color=BLUE_ACCENT,
                        components=[
                            Text(content=f"## 📌 **Flexible Fun War Clan: A Quick Overview** · {recruit_mention}"),
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'what_is_tactical':
        return [
                    Container(
                        accent_color=GOLDENROD_ACCENT,
                        components=[
                            Text(content=f"## ⚔️ **Tactical/Competitive Clans** ⚔️ · {recruit_mention}"),
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'fwa_war_plans':
        return [
                    Container(
                        accent_color=GOLDENROD_ACCENT,
                        components=[
                            Text(content=f"## ⚔️ **FWA War Plans** ⚔️ · {recruit_mention}"),
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
                            Text(content=f"-# Requested by {recruiter_mention}"),
                        ]
                    )
                ]
    if variant == 'waiting_response':
        return [
                    Text(content=f"{recruit_mention}"),
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
    if variant == 'circles':
        return [
                    Text(content=f"{recruit_mention}"),
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
    if variant == 'today':
        return [
                    Text(content=f"{recruit_mention}"),
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
    if variant == 'chop_chop':
        return [
                    Text(content=f"{recruit_mention}"),
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
    raise ValueError("Choose a supported recruitment question.")


def native_base_result(*, recruit_mention: str, recruiter_mention: str,
                       friendly_name: str, th_number: str, base_info: str,
                       base_link: str, war_base_media: str, active_war_base_media: str) -> list:
    return [
                Text(content=f"{recruit_mention}"),
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
