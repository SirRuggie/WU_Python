"""Pre-270 builders extracted verbatim from git8165462e for fixture-only regression. No transport."""

import hikari

from hikari.impl import MessageActionRowBuilder as ActionRow, InteractiveButtonBuilder as Button, ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text, SeparatorComponentBuilder as Separator, MediaGalleryComponentBuilder as Media, MediaGalleryItemBuilder as MediaItem

from utils.constants import WU_GOLD

from utils.dashboard_urls import SIGNUP_URL

ICONS = {"yes": 1397096942907166831}

def build_aboutus(sections=None, *, media=None, action_id="preview", preview=False,
                  family_rules=None, clans=None, include_family_rules=True):
    """Build the public shape; registry I/O belongs to the shared async renderer."""
    from utils.info_channel_content import (
        about_us_defaults, about_us_sections, family_rules_sections, validate_fields,
    )
    fields = about_us_defaults() if sections is None else list(sections)
    validate_fields(fields, 12, "About Us")
    if clans is not None:
        fields = about_us_sections(fields, clans)
    media = media or {}
    components = [
        Media(items=[MediaItem(media=media.get("welcome", "assets/branding/banners/Warriors_United.gif"))]),
        Container(accent_color=WU_GOLD, components=[
            Text(content=fields[0]), Separator(divider=True), Text(content=fields[1]),
            Separator(divider=True), Text(content=fields[2]), Text(content=fields[3]),
        ]),
        Container(accent_color=WU_GOLD, components=[Text(content=fields[4]), Text(content=fields[5])]),
        Container(accent_color=WU_GOLD, components=[
            Text(content=fields[6]), Text(content=fields[7]), Separator(divider=True),
            Text(content=fields[8]), Text(content=fields[9]),
        ]),
    ]
    if include_family_rules:
        rules = family_rules_sections(family_rules)
        components.append(Container(accent_color=WU_GOLD, components=[Text(content=rules[0]), Text(content=rules[1])]))
    components.append(Container(accent_color=WU_GOLD, components=[
        Text(content=fields[10]), Text(content=fields[11]),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SUCCESS,
            custom_id=f"aboutus_acknowledge:{action_id}",
            label="I understand - Continue", emoji=hikari.Snowflake(ICONS["yes"]),
            is_disabled=preview,
        )]),
    ]))
    return components

def build_strikesystem(sections=None, *, media=None, action_id="preview", preview=False):
    """Render the Strike System post for publishing or dashboard previews."""
    if sections is not None and len(sections) != 12:
        raise ValueError("Strike System requires exactly twelve editable text fields.")
    values = iter(sections) if sections is not None else None
    media = media or {}

    def text(default):
        return Text(content=next(values) if values is not None else default)

    def image(slot, default):
        return media.get(slot, default)

    components = [
            # Image at the top
            Media(
                items=[
                    MediaItem(
                        media=image("rules", "assets/recruit/strikes/WU_Strikes.gif")
                    )
                ]
            ),

            # Embed 1: Basic Rules
            Container(
                accent_color=WU_GOLD,
                components=[
                    text("## 📜 **Warriors United Basic Rules** 📜"),
                    Separator(divider=True),
                    text((
                        "🛡️**WARRIORS UNITED**🛡️ is an adult community with good morals and ethics. A little banter and joking "
                        "is fine, but we do not allow some things...\n\n"
                        "**1.** No form of sexism, racism, religious discrimination, or gender discrimination will be tolerated. "
                        "We ban you permanently, without a warning, if we see this anywhere on this server.\n\n"
                        "**2.** While cussing is allowed, do not cuss excessively or at someone. All such instances will be recorded. "
                        "A warning will be issued to you for each instance.\n\n"
                        "**3.** Do not post advertisements for free Nitro. We do not check if they are real, and we ban "
                        "without a warning.\n\n"
                        "**4.** Respect other members and their privacy. If you send direct messages to someone again and again after they tell you to stop, "
                        "you get a warning.\n\n"
                        "**5.** When you post a message, image, GIF or sticker, always follow the Discord Terms of Service: "
                        "https://discord.com/terms. Not following Discord ToS will lead to a one-day mute, "
                        "and a second instance will lead to a ban from the server.\n\n"
                        "After two warnings: you get a one-day timeout.\n"
                        "After three warnings: you get a one-week timeout.\n"
                        "After four warnings: you are banned from the server for good and removed from the family in CoC."
                    )),
                ]
            ),

            # Embed 2: Strike System Overview
            Container(
                accent_color=WU_GOLD,
                components=[
                    text("## ❌ **Warriors United Strike System** ❌"),
                    Separator(divider=True),
                    text((
                        "Our Strike System is a penalty system in which strikes are given to members who violate the rules and "
                        "principles implemented within the Warriors United clan family.\n\n"
                        "Each violation has a fixed number of strikes. What counts is the number of strikes, not the number of violations. "
                        "For example, missing both attacks in war is one violation that results "
                        "in two strikes. Members have a total of 4 strikes before disciplinary action takes place. When you get the maximum "
                        "number of strikes, you have 12 hours to open a ticket and talk about the case. If you do not, we remove you from the clan "
                        "and ban you from all other clans in the family for one week. After one "
                        "week with no reply, your clan roles will be removed, returning you to the status you had when you joined the server.\n\n"
                        "All strikes are given per individual account, with the exception of civil-behavior offenses. "
                        "If one action causes more than one strike, we count only the strikes of the worst offense. "
                        "We still note all strikes.\n\n"
                        "Strikes are recorded automatically. Staff manage them in Strikes & replacements. "
                        "Each strike resets after a set time. This is usually 60 days.\n\n"
                        "Below are charts of offenses and the value of each offense."
                    )),
                ]
            ),

            # Embed 3: Main Clan Strike System
            Container(
                accent_color=WU_GOLD,
                components=[
                    text("## ❌ **MAIN CLAN STRIKE SYSTEM** ❌"),
                    Separator(divider=True),
                    text("The rules for the Main clan strike system are below."),
                    Media(
                        items=[
                            MediaItem(
                                media=image("main-strikes", "assets/recruit/strikes/WU_Main_Strikes.jpg")
                            )
                        ]
                    ),
                ]
            ),

            # Embed 4: FWA Strike System
            Container(
                accent_color=WU_GOLD,
                components=[
                    text("## ❌ **FWA STRIKE SYSTEM** ❌"),
                    Separator(divider=True),
                    text("The rules for the FWA clan strike system are below."),
                    Media(
                        items=[
                            MediaItem(
                                media=image("fwa-strikes", "assets/recruit/strikes/WU_FWA_Strikes.jpg")
                            )
                        ]
                    ),
                ]
            ),

            # Embed 5: Terms and Conditions
            Container(
                accent_color=WU_GOLD,
                components=[
                    text("## ❌ **Terms and Conditions** ❌"),
                    Separator(divider=True),
                    text((
                        "• For all offenses except those in the Red Zone, we can give a warning before a strike. "
                        "The leadership team decides if it gives a warning. We log all warnings.\n\n"
                        "• Strikes can be withdrawn by leadership majority.\n\n"
                        "• Leadership can change this system at any time between seasons.\n\n"
                        "• A kicked person may be reinvited to the Family after a unanimous vote by Leadership."
                    )),
                ]
            ),

            # Embed 6: Acknowledgment
            Container(
                accent_color=WU_GOLD,
                components=[
                    text("## 📜 **ACKNOWLEDGMENT**"),
                    Separator(divider=True),
                    text((
                        "Select **I understand - Continue** to confirm you have read and agree to follow the Warriors United Strike System, "
                        "then continue to Family Particulars for the next Recruit Gauntlet step."
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"strikesystem_acknowledge:{action_id}",
                                label="I understand - Continue",
                                emoji=hikari.Snowflake(ICONS["yes"])
                            )
                        ]
                    )
                ]
            ),
    ]
    if preview:
        components[-1].components[-1].components[0].set_is_disabled(True)
    return components

def build_familyparticulars(sections=None, *, media=None, action_id="preview", preview=False):
    """Render Family Particulars for publishing or dashboard previews."""
    if sections is not None and len(sections) != 28:
        raise ValueError("Family Particulars requires exactly twenty-eight text fields.")

    media = media or {}

    def image(slot, default):
        return media.get(slot, default)

    components = [
            # Image at the top
            Media(
                items=[
                    MediaItem(
                        media=image("welcome", "assets/recruit/static/WU_FamilyParticulars.gif")
                    )
                ]
            ),

            # Embed 1: Family Particulars
            Container(
                accent_color=WU_GOLD,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Warriors United Family Particulars**"),
                    Separator(divider=True),
                    Text(content="### **GOLDEN RULE**\n"),
                    Text(content=(
                        "The main rule for any group or gathering is: \"Treat and speak to others as you would expect to be "
                        "treated or spoken to.\" We understand that not every day is a good day. Just don't bring your bad day in here."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **FRIENDLY CHALLENGES**\n"),
                    Text(content=(
                        "Every time you open the game, post a Friendly Challenge. Do this at any Town Hall level. "
                        "It gives everyone a chance to practice."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **CLAN GAMES**\n"),
                    Text(content=(
                        "The goal is simple: each member must earn at least 1,000 points in Clan Games. "
                        "Builder Base challenges give you these points quickly. For example, 40 members who earn "
                        "1,250 points each make the 50,000 points that we need."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                ]
            ),

            # Embed 2: Family War Rules
            Container(
                accent_color=WU_GOLD,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Family War Rules**"),
                    Separator(divider=True),
                    Text(content="### 🛡 **WAR ELIGIBILITY**\n"),
                    Text(content=(
                        "To be included in war, you must have GREEN ✅ 🛡️ (opt-in) as your War Status. FWA/No Stress is explained below.\n\n"
                        "If you cannot take part in war for a personal reason, or your Heroes are upgrading in a clan that needs "
                        "Heroes in war, set your War Status to RED ❌ 🛡️ (opt-out).\n\n"
                        "If you do not tell us or do not change your war availability in one of these cases, you get a strike in the Warriors United Strike System.\n\n"
                        "If you are in one of our FWA Clans or one of our No Stress Clans, it's 50v50 wars, so no matter what your "
                        "base is upgrading, you should be ✅ with your War Status."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **PREP DAY**\n"),
                    Text(content=(
                        "Everyone must help fill Defensive CCs. Fill the Defensive CC of the member below you with the troops they ask for. "
                        "Do not leave one person to fill all of them."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **BATTLE DAY**\n"),
                    Text(content=(
                        "Our Clan War General will provide a scripted War Plan detailing your war assignment. Do not assume that you attack your mirror. "
                        "Wait for the War Plan before you attack. If there is no plan after a long time, ping the War General role of your clan "
                        "and ask. Do not attack alone without a plan. You have 24 hours to plan and attack. "
                        "Always attack for stars, not for loot or Hero status (unless given specific "
                        "direction by the War General)."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                ]
            ),

            # Embed 3: Clan War League
            Container(
                accent_color=WU_GOLD,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Warriors United Clan War League**"),
                    Separator(divider=True),
                    Text(content=(
                        "CWL is our biggest team event. Your clan counts on you. Help the whole team to win. "
                        "We split into different clans for this event. Three factors determine the "
                        "league in which you'll be placed:\n"
                        "1) War activity\n"
                        "2) War performance\n"
                        "3) Account strength.\n\n"
                        f"You do not have to take part in CWL. To take part, sign up on the dashboard before the deadline: {SIGNUP_URL}. "
                        "We make no exceptions. The signup information allows clan "
                        "Leaders and War Generals to produce clan rosters. We have several clans in the family, so everyone can have "
                        "a shot at some medals. If you have multiple accounts, only three are allotted to be in one clan roster.\n\n"
                        "No signup, no play."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **Principles for Every CWL Battle**\n"),
                    Text(content=(
                        "• Be available to attack and make sure you request offensive CC troops.\n\n"
                        "• Have your heroes ready for battle.\n\n"
                        "• Write your defensive CC troop request clearly (for example, Ice Golem/Dragon or IG/Drag).\n\n"
                        "• Donate Defensive CC troops to the player below you and/or at least one of your teammates, "
                        "making sure they are max-level troops.\n\n"
                        "• Make a plan of attack. You have 24 hours for one attack.\n\n"
                        "Ask our Attack Trainers for help in the \"Help-Me-Attack-This-Base\" channels."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Media(
                        items=[
                            MediaItem(
                                media=image("cwl", "assets/branding/banners/warriors_united_.gif")
                            )
                        ]
                    ),
                ]
            ),

            # Embed 4: Acknowledgment
            Container(
                accent_color=WU_GOLD,
                components=[
                    Text(content="## 📜 **ACKNOWLEDGMENT**"),
                    Separator(divider=True),
                    Text(content=(
                        "Select **I understand - Continue** to confirm that you read the Family Particulars. Then select Apply to open an application ticket.\n\nSelect only one application ticket option."
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"familyparticulars_acknowledge:{action_id}",
                                label="I understand - Continue",
                                emoji=hikari.Snowflake(ICONS["yes"])
                            )
                        ]
                    )
                ]
            ),
    ]
    if sections is not None:
        values = iter(sections)
        components = [
            Container(
                accent_color=component.accent_color,
                components=[
                    Text(content=next(values)) if isinstance(child, Text) else child
                    for child in component.components
                ],
            ) if isinstance(component, Container) else component
            for component in components
        ]
    if preview:
        components[-1].components[-1].components[0].set_is_disabled(True)
    return components


BLOCK_LABELS = {
    "join-family": ("Heading", "Welcome", "What happens next", "Call to action"),
    "about-us": ("Welcome heading", "Welcome overview", "Tactical heading", "Tactical details", "Flexible Fun heading", "Flexible Fun details", "FWA heading", "FWA details", "Disclaimer heading", "Disclaimer", "Next step heading", "Next step"),
    "strike-system": ("How strikes work heading", "How strikes work", "At 4 strikes heading", "At 4 strikes", "Main clan heading", "Main clan note", "FWA heading", "FWA note", "Terms heading", "Terms", "Acknowledgement heading", "Acknowledgement"),
    "family-particulars": ("Family heading", "Intro heading", "Intro", "Friendly challenges heading", "Friendly challenges", "Clan games heading", "Clan games", "War rules heading", "War eligibility heading", "War eligibility", "Prep day heading", "Prep day", "Battle day heading", "Battle day", "CWL heading", "CWL overview", "CWL principles heading", "CWL principles", "Acknowledgement heading", "Acknowledgement"),
    "apply": ("Heading", "Body"),
    "warrior_desk": ("Heading", "Body"),
    "rite-of-passage": ("Heading", "Introduction", "Main path", "FWA path", "Closing"),
    "family-rules": ("Heading", "Body"),
    "wu-faq": ("Questions heading", "Questions"),
}

MEDIA_SLOTS = {
    "join-family": (("welcome", "Welcome banner"),),
    "about-us": (("welcome", "Welcome banner"),),
    "strike-system": (
        ("rules", "Basic rules banner"),
        ("main-strikes", "Main clan strike chart"),
        ("fwa-strikes", "FWA strike chart"),
    ),
    "family-particulars": (("welcome", "Welcome banner"), ("cwl", "CWL banner")),
    "apply": (("footer", "Footer image"),),
    "warrior_desk": (("footer", "Footer image"),),
    "rite-of-passage": (("guide", "Rite of Passage guide"),),
    "family-rules": (),
    "wu-faq": (),
}

from copy import deepcopy
from types import SimpleNamespace
from aiohttp import web
API="/api/cwl"
def modules():
    return (SimpleNamespace(BLOCK_LABELS=BLOCK_LABELS,MEDIA_SLOTS=MEDIA_SLOTS,is_template_only=lambda key:False), None,None,None)


def schema(item, template):
    gauntlet, questions, staff, war = modules()
    prefix, key = item['id'].split('--', 1)
    fields = []
    def field(key, label, value, type='textarea', **extra):
        fields.append(dict(key=key, label=label, value=value, type=type, **extra))
    if prefix == 'destination':
        field('channel_id', 'Posting channel', template['channel_id'], 'channel')
    elif prefix == 'staff':
        for slot, section in template['sections'].items():
            label = staff.section_label(slot, section)
            field(f'sections.{slot}.title', f'{label}: title (optional)', section['title'], 'text')
            field(f'sections.{slot}.body', f'{label}: message', section['body'])
    else:
        module = {'gauntlet': gauntlet, 'question': questions, 'war': war}[prefix]
        for index, label in enumerate(module.BLOCK_LABELS[key]):
            field(f'sections.{index}', label, template['sections'][index])
        slots = dict(gauntlet.MEDIA_SLOTS[key]) if prefix == 'gauntlet' else getattr(module, 'MEDIA_LABELS', {}).get(key, {})
        for slot, label in slots.items():
            field(f'media.{slot}', label, template.get('media', {}).get(slot, ''), 'text', description='Public HTTPS image URL. Leave empty for original artwork.' if prefix == 'gauntlet' else 'Public HTTPS image URL.')
        if 'footer_url' in template and template['footer_url'] is not None:
            field('footer_url', 'Footer image', template['footer_url'], 'text')
        if 'accent' in template:
            field('accent', 'Accent color (hex)', f"#{template['accent']:06x}", 'text')
    from utils.url_safety import MAX_IMAGE_BYTES
    for entry in fields:
        if entry['key'].startswith('media.') or entry['key'] == 'footer_url':
            entry['upload_endpoint'] = API + '/manage/content/' + item['id'] + '/upload/' + entry['key']
            entry['upload_max_bytes'] = MAX_IMAGE_BYTES
            entry['upload_label'] = 'Upload ' + entry['label'].lower()
            purpose = ('Appears below the message text.' if entry['key'] == 'footer_url' or entry['key'] == 'media.footer'
                       else 'Replaces the ' + entry['label'].lower() + ' in this Discord message.')
            if entry['label'].startswith('Image '):
                purpose = 'Replaces image ' + entry['label'][6:] + ' in the message, counted from top to bottom.'
            entry['description'] = purpose + ' Save changes to apply this draft.' + (' Leave empty to use the original artwork.' if prefix == 'gauntlet' else '')
    actions = []
    if prefix == 'gauntlet' and not gauntlet.is_template_only(key):
        actions.append(dict(id='load-published', label='Copy from Discord', advanced=True, description='Copy the current Discord post into this draft. Save to keep it.', confirm='Replace the editor draft with the published copy? Nothing is saved yet.', endpoint=API + '/manage/content/' + item['id'] + '/load-published'))
    if prefix != 'destination':
        actions.append(dict(id='reset', label='Reset to default', advanced=True, description='Replace saved text and artwork with the bot’s default message.', confirm='Reset saved text and artwork to the default message? Your saved edits will be replaced. This does not update the Discord post.', endpoint=API + '/manage/content/' + item['id'] + '/reset'))
    if prefix == 'staff':
        actions.append(dict(id='add', label='Add staff message', endpoint=API + '/manage/content/' + item['id'] + '/add'))
        for slot, section in template['sections'].items():
            if slot.startswith('custom_'):
                actions.append(dict(id='remove-' + slot, label='Remove ' + staff.section_label(slot, section), confirm='Remove this additional staff message?', endpoint=API + '/manage/content/' + item['id'] + '/remove-' + slot))
    return {**{k: v for k, v in item.items() if k != 'permission'}, 'endpoint': API + '/manage/content/' + item['id'], 'revision': template['revision'], 'fields': fields, 'preview_supported': prefix != 'destination', 'publish_endpoint': API + '/manage/publish/' + key if prefix == 'gauntlet' and not gauntlet.is_template_only(key) else None, 'actions': actions}

def candidate(item, loaded, body):
    if not isinstance(body, dict) or set(body) - {'revision', 'values', 'request_id'} or not isinstance(body.get('values'), dict):
        raise ValueError('Provide the fields to save and their revision')
    if type(body.get('revision')) is not type(loaded['revision']) or body['revision'] != loaded['revision']:
        raise web.HTTPConflict(text='Someone changed this message. Reload it before saving.')
    allowed = {field['key'] for field in schema(item, loaded)['fields']}
    if set(body['values']) - allowed:
        raise ValueError('Unknown message fields')
    result = deepcopy(loaded)
    for path, value in body['values'].items():
        if not isinstance(value, str):
            raise ValueError('Message fields must be text')
        parts = path.split('.')
        if path == 'accent':
            import re
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('Use a color such as #DAA520')
            result[path] = int(value[1:], 16)
        elif parts[0] == 'sections':
            if isinstance(result['sections'], list):
                result['sections'][int(parts[1])] = value
            else:
                result['sections'][parts[1]][parts[2]] = value
        elif parts[0] == 'media':
            if value or not item['id'].startswith('gauntlet--'):
                result.setdefault('media', {})[parts[1]] = value
            else:
                result.setdefault('media', {}).pop(parts[1], None)
        else:
            result[path] = value
    return result

Document = SimpleNamespace


def text_nodes(components):
    return [child for component in components for child in getattr(component, "components", ())
            if getattr(child, "type", None) == hikari.ComponentType.TEXT_DISPLAY]

def editable_text_nodes(document, components):
    nodes = text_nodes(components)
    if document.key == "about-us" and len(nodes) == 14:
        return nodes[:10] + nodes[12:]
    if document.key == "wu-faq" and len(nodes) == 4:
        return nodes[2:]
    return nodes
