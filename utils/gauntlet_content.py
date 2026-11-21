"""Lossless, read-only box/field projection for the four info documents.

The existing content editor remains the only persistence owner. Legacy prefix
strings are retained; appended box fields are initialized once, never remapped
onto a saved canonical list. No database, Discord or dashboard dependency.
"""
import re

ABOUT_LEGACY_DEFAULTS = ['## 🛡️ Welcome',
 'We are an English-speaking clan family based in the USA, with Clashers from all over the world. '
 'You can play in wars while you upgrade your base.\n'
 '\n'
 '**Note:** Our CWL clans do not support accounts that need a Family Friendly clan. If your '
 'account needs one, find a different clan family.\n'
 '\n'
 '**What we offer:**\n'
 '🛡️ 1 tactical clan\n'
 '🛡️ 2 Flexible Fun war clans\n'
 '🛡️ 7 FWA clans for farmers\n'
 '🛡️ CWL every month, for everyone',
 '## ☠️ Tactical Clan',
 '**Funnies** `#2Q9RLRCG`\n'
 '**For:** players who want serious wars and 3-star attacks.\n'
 '**Requirements:**\n'
 '• TH13 or higher, with your previous Town Hall level fully maxed\n'
 '• No heroes upgrading during war. Wars are always at full strength.\n'
 '**What we expect:** Follow the war plan and work as a team. Not every attack will be perfect, '
 'but always try for 3 stars.',
 '## 🪖 Flexible Fun War Clans',
 '**Warriors United** `#2YRVY8YCP`\n'
 '**Arcane Oasis** `#Y2J0ULYR`\n'
 '**For:** lower-level players and players who want relaxed wars. Wars are 50v50, or the largest '
 'size possible.\n'
 '**Requirements:** None. Heroes are not required.\n'
 '**What we expect:**\n'
 '• Use your first attack in every war. There is no performance target.\n'
 '• Relaxed does not mean inactive. We play to win.\n'
 '• If you do not war, you cannot stay in the clan.\n'
 '**Tip:** Heroes upgrading in the tactical clan? Move to a Flexible Fun clan for war loot. Move '
 'back when your upgrades are done.',
 '## 💰 FWA Clans',
 '**Clash of Thrones** `#Q889GPL`\n'
 '**CoT Wildlings** `#2YJVQUCYJ`\n'
 '**Four and Twenty** `#8CV0GPPR`\n'
 '**The Horde** `#2RRCJCI0`\n'
 '**PlaneClashers** `#9UGQ0GL`\n'
 '**Edrag Rush** `#2PPCL2GYP`\n'
 '**Wonder Wall** `#C002YRYG`\n'
 '**For:** farmers who want loot from back-to-back wars.\n'
 '**How it works:** FWA (Farm War Alliance) sets the result of each war before it starts. A simple '
 'war plan tells you how to get that result. Heroes are not required.\n'
 '**Requirements:**\n'
 '• TH12 or higher\n'
 '• War weight of 115 or higher\n'
 '• All buildings built for your Town Hall level',
 '### ⚖️ Final decision',
 'These requirements are a guide. Leadership looks at each recruit and makes the final decision. '
 'Your interview gives more detail about each clan type.',
 '## ⏩ Next Step',
 'Select **I understand - Continue** to confirm that you read about our clans and the Family '
 'Rules. Then read the WU Strike System.']
STRIKE_LEGACY_DEFAULTS = ['## ❌ How Strikes Work',
 'A strike is a penalty for breaking a war rule or a clan rule. Each offense has a set number of '
 'strikes. The charts below list them.\n'
 'Strikes for missed war attacks are recorded automatically after each war. Leadership adds all '
 'other strikes.\n'
 'Strikes belong to each account. Moving to another family clan does not remove them.\n'
 '\n'
 '### ✅ Remove your strikes\n'
 '**Play 2 wars in a row** (use both attacks): 1 strike is removed.\n'
 '**Play 6 wars in a row**: all your strikes are removed.\n'
 'A strike also goes away by itself after **60 days**.\n'
 '**Approved leave** pauses strikes. Ask a leader before you go.',
 '## ⚠️ At 4 Strikes',
 '**1.** You have 12 hours to select **Contact staff** in <#1567967422118502441> and talk to us.\n'
 '**2.** No ticket in 12 hours: we remove you from your clan. You cannot join another family clan '
 'for 1 week.\n'
 '**3.** No reply in 1 week: your roles go back to new-member roles.',
 '## ⚔️ Main Clan Strikes',
 'This chart shows the strikes for our main clans.',
 '## 💰 FWA Strikes',
 'This chart shows the strikes for our FWA clans. An FWA mismatch war with a confirmed war plan '
 'gives no strike.',
 '## 📋 Terms',
 '• Leadership can give a warning instead of strikes, except for red-row offenses. We record '
 'warnings.\n'
 '• Leadership can remove a strike by majority vote.\n'
 '• Leadership can change this system between seasons.\n'
 '• A removed member can come back if all leaders vote yes.',
 '## 📜 Acknowledgment',
 'Select **I understand - Continue** to confirm that you read and agree to the WU Strike System. '
 'Then read Family Particulars.']
PARTICULARS_LEGACY_DEFAULTS = ['## 🛡️ How Our Clans Work',
 '### 📖 READ THIS FIRST',
 'This page tells you what we expect from you every day, in war, and in CWL.',
 'ᨖᨖᨖ',
 '### 🛡 **FRIENDLY CHALLENGES**',
 'Each time you log in, post a Friendly Challenge. Do this at every Town Hall level. It gives '
 'everyone a chance to practice.',
 'ᨖᨖᨖ',
 '### 🛡 **CLAN GAMES**',
 'Get at least **1,000 points** in each Clan Games. Builder Base challenges help. If 40 members '
 'get 1,250 points each, the clan gets the 50,000 points it needs.\n'
 'See your points on the [dashboard](https://dash.warriorsunited.cc), in Tasks → Clan Games.',
 'ᨖᨖᨖ',
 '## 🛡️ Family War Rules',
 '### 🛡 **WAR STATUS**',
 '**Tactical clan:** set your war status to **GREEN ✅** to join a war. Set it to **RED ❌** if you '
 'cannot play or your heroes are upgrading. If you do not, you get strikes. See the WU Strike '
 'System.\n'
 '**FWA and Flexible Fun clans:** wars are 50v50. Keep your status **GREEN ✅**, also when you '
 'upgrade.',
 'ᨖᨖᨖ',
 '### 🛡 **PREP DAY**',
 'Fill the Clan Castle of the member below you with the troops they ask for. This is a team job. '
 'One person must not fill them all.',
 'ᨖᨖᨖ',
 '### 🛡 **BATTLE DAY**',
 'Your War General posts a war plan with your target. Do not attack your mirror before you see the '
 "plan. If the plan is late, ping your clan's War General role.\n"
 'You have 24 hours to plan and attack. Attack for stars, not loot, unless your War General tells '
 'you different.',
 'ᨖᨖᨖ',
 '## 🛡️ Clan War League (CWL)',
 'CWL is our main team event every month. You have 2 options:\n'
 '• **Main CWL:** push for the best medals.\n'
 '• **LazyCWL:** easy CWL with no pressure.\n'
 '\n'
 '**Sign up on the [dashboard](https://dash.warriorsunited.cc/signup) before the deadline.** The '
 'dashboard shows the deadline. No sign-up, no play. There are no exceptions.\n'
 'Leaders and War Generals build the rosters. They place you by war activity, war performance, and '
 'account strength. When the roster is published, you see your clan on the dashboard. Max 3 of '
 'your accounts go on one clan roster.',
 'ᨖᨖᨖ',
 '### 🛡 **EVERY CWL BATTLE**',
 '• Be ready to attack, and request your attack Clan Castle troops.\n'
 '• Have your heroes ready.\n'
 '• Donate max-level defense troops to the player below you, or to at least one teammate.\n'
 '• Plan your attack. You have 24 hours for 1 attack.\n'
 'Need help? Ask in <#1005916813378465832>, or look in <#1568000309177876480>.',
 'ᨖᨖᨖ',
 '## 📜 ACKNOWLEDGMENT',
 'Select **I understand - Continue** to confirm that you read the Family Particulars. Then go to '
 'Apply and open an application ticket.\n'
 'There are 2 application ticket types. **Open only one.**']

# Each tuple is one editor screen: heading, then one field per sub-topic.
BOXES = {
    "about-us": (("Welcome", ((12,"Heading"),(1,"Overview and Family Friendly note"))),
                 ("Our Clans", ((13,"Heading"),(3,"Tactical"),(5,"Flexible Fun"),(7,"FWA"),(14,"Requirements guide"))),
                 ("Family Rules", ()), ("Next Step", ((15,"Heading"),(11,"Body")))),
    "strike-system": (("How Strikes Work", ((14,"Heading"),(12,"Body"))),
                      ("Remove Your Strikes", ((15,"Heading"),(13,"Body"))),
                      ("At 4 Strikes", ((16,"Heading"),(3,"Body"))),
                      ("Strike Charts", ((17,"Heading"),(5,"Main"),(7,"FWA"),(9,"Terms"))),
                      ("Next Step", ((18,"Heading"),(11,"Body")))),
    "family-particulars": (("How Our Clans Work", ((28,"Heading"),(29,"Intro"))),
                           ("Every Day", ((30,"Heading"),(5,"Friendly Challenges"),(8,"Clan Games"))),
                           ("War Days", ((31,"Heading"),(12,"War Status"),(15,"Prep Day"),(18,"Battle Day"))),
                           ("Clan War League", ((32,"Heading"),(21,"Overview"),(24,"Every CWL Battle"))),
                           ("Next Step", ((33,"Heading"),(27,"Body")))),
    "wu-faq": (("Who we are", ((2,"Heading"),(3,"Body"))),
               ("Our Clans", ((4,"Heading"),(5,"Tactical"),(6,"Flexible Fun"),(7,"FWA"),(8,"Footer"))),
               ("Family Rules", ()), ("Questions", ((0,"Heading"),(1,"Body")))),
}
LEGACY_LENGTHS = {"about-us":12, "strike-system":12, "family-particulars":28}
LENGTHS = {"about-us":16, "strike-system":19, "family-particulars":34, "wu-faq":9}
_REMOVE = re.compile(r"(?im)^#{1,6} *✅? *remove your strikes *$", re.MULTILINE)


def visible_indexes(key):
    return tuple(index for _box, fields in BOXES[key] for index, _label in fields)


def sections_for(key, sections=None):
    if key == "wu-faq":
        from utils.info_channel_content import wu_faq_sections
        return wu_faq_sections(sections)
    defaults = {"about-us":ABOUT_LEGACY_DEFAULTS,"strike-system":STRIKE_LEGACY_DEFAULTS,
                "family-particulars":PARTICULARS_LEGACY_DEFAULTS}
    if sections is not None and (not isinstance(sections, (list,tuple)) or any(not isinstance(v,str) for v in sections)):
        raise ValueError("The saved info document has invalid text. Reopen it for review.")
    values = list(defaults[key] if sections is None else sections)
    if len(values) == LENGTHS[key]:
        return values
    if len(values) != LEGACY_LENGTHS[key]:
        raise ValueError("The saved info document has an incomplete field layout. Review it before saving.")
    if key == "about-us":
        values.extend(["## 🛡️ Welcome", "## 🏰 Our Clans",
                       "Requirements are a guide. Leadership makes the final decision.", "## ⏩ Next Step"])
    elif key == "strike-system":
        matches = list(_REMOVE.finditer(values[1]))
        if len(matches) == 1:
            marker = matches[0]
            before, boundary, after = values[1][:marker.start()], values[1][marker.start():marker.end()], values[1][marker.end():]
            assert before + boundary + after == values[1]
            how, removal = before.rstrip("\n"), after.lstrip("\n")
        else:
            # Keep ambiguous staff text visible. No policy is invented; Preview
            # and Save explain which new field staff must explicitly complete.
            how, removal = values[1], ""
        values.extend([how, removal, "## ❌ How Strikes Work", "## ✅ Remove Your Strikes",
                       "## ⚠️ At 4 Strikes", "## 📊 Strike Charts", "## ⏩ Next Step"])
    else:
        values.extend(["## 🛡️ How Our Clans Work",
                       "This page tells you what we expect from you every day, in war, and in CWL.",
                       "## ✅ Every Day", "## ⚔️ War Days", "## 🏆 Clan War League", "## ⏩ Next Step"])
    return values


def validate_sections(key, sections):
    fields = sections_for(key, sections)
    if key == "strike-system" and not fields[13].strip():
        raise ValueError("Review the saved How Strikes Work text and complete Remove Your Strikes. The original text is retained; nothing was saved or posted.")
    if any(not fields[index].strip() for index in visible_indexes(key)):
        raise ValueError("Complete every visible box field before saving or posting.")
    return fields


def subtopic(label, body):
    """A label occupies its own line; the staff-owned body remains unchanged."""
    return f"**{label}**\n{body}"


def without_label(label, text):
    prefix = f"**{label}**\n"
    if not text.startswith(prefix):
        raise ValueError("The published sub-topic layout changed. Reopen the editor.")
    return text[len(prefix):]


def project_public(key, texts, *, legacy=False):
    """Project post text onto editor fields, excluding registry/shared text."""
    if legacy:
        return sections_for(key, texts)
    fields = sections_for(key)
    if key == "about-us":
        from utils.info_channel_content import strip_manual_clan_prefix
        pairs = {12:0, 1:1, 13:2, 14:6, 15:9, 11:10}
        for target, source in pairs.items():
            fields[target] = texts[source]
        for target, source, label in ((3,3,"Tactical"),(5,4,"Flexible Fun"),(7,5,"FWA")):
            fields[target] = strip_manual_clan_prefix(without_label(label, texts[source]))
    elif key == "strike-system":
        for target, source in {14:0,12:1,15:2,13:3,16:4,3:5,17:6,18:10,11:11}.items():
            fields[target] = texts[source]
        for target, source, label in ((5,7,"Main"),(7,8,"FWA"),(9,9,"Terms")):
            fields[target] = without_label(label, texts[source])
    elif key == "family-particulars":
        for target, source in {28:0,29:1,30:2,31:5,32:9,21:10,33:12,27:13}.items():
            fields[target] = texts[source]
        for target, source, label in ((5,3,"Friendly Challenges"),(8,4,"Clan Games"),
                                      (12,6,"War Status"),(15,7,"Prep Day"),(18,8,"Battle Day"),(24,11,"Every CWL Battle")):
            fields[target] = without_label(label, texts[source])
    return fields


def merge_public(key, saved, imported):
    """Explicit Copy from Discord may change visible fields, never hidden data."""
    fields = sections_for(key, saved)
    imported = sections_for(key, imported)
    for index in visible_indexes(key):
        fields[index] = imported[index]
    return fields


def faq_type_body(kind, value):
    """1321: display-only label formatting; saved strings stay byte-exact."""
    marker = re.compile(r"^\*\*(?:[🎯🎉💰] *)?" + re.escape(kind) + r":\*\* *", re.IGNORECASE)
    return marker.sub("", value, count=1)
