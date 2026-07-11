"""/fwa points - show the latest stored FWA win-calculator verdicts."""

import hikari
import lightbulb
from datetime import datetime

from extensions.commands.fwa import loader, fwa
from utils.mongo import MongoClient
from utils.constants import GOLD_ACCENT
from utils.fwa_points_parser import sanitize_tag

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    SectionComponentBuilder as Section,
    LinkButtonBuilder as LinkButton,
)


def _updated_stamp(iso: str) -> str:
    try:
        return f"<t:{int(datetime.fromisoformat(iso).timestamp())}:R>"
    except Exception:
        return "unknown"


@fwa.register()
class Points(lightbulb.SlashCommand, name="points",
            description="Show the latest FWA win-calculator verdicts (from the points database)"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer()
        try:
            config = await mongo.fwa_points.find_one({"_id": "config"}) or {}
            watch = config.get("watch_list", [])

            body = [Text(content="## 📊 **FWA Points**"), Separator(divider=True)]
            if not watch:
                body.append(Text(content="No clans are being watched yet."))
            for clan in watch:
                t = sanitize_tag(clan.get("tag", ""))
                name = clan.get("name", t)
                url = f"https://points.fwafarm.com/clan?tag={t}"
                rec = await mongo.fwa_points.find_one({"_id": t})
                if rec and rec.get("raw_verdict"):
                    text = (f"**{name}**\n{rec['raw_verdict']}\n"
                            f"War #{rec.get('war_number', '?')} · Sync #{rec.get('sync_number', '?')} · "
                            f"Balance {rec.get('point_balance', '?')} · updated {_updated_stamp(rec.get('scraped_at', ''))}")
                else:
                    text = f"**{name}**\nNo stored verdict yet - open the page directly."
                body.append(Section(components=[Text(content=text)],
                                    accessory=LinkButton(url=url, label="Open Page")))

            await ctx.respond(components=[Container(accent_color=GOLD_ACCENT, components=body)])
        except Exception as e:
            print(f"[FWA Points] /fwa points failed: {e}")
            await ctx.respond("⚠️ Could not load stored points. Try the links from `/fwa links`.", ephemeral=True)


loader.command(fwa)
