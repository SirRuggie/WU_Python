import lightbulb
import hikari

loader = lightbulb.Loader()


@loader.command
class DenDenMushi(
    lightbulb.SlashCommand,
    name="den-den-mushi",
    description="Broadcasts your message via the Den Den Mushi transponder snail 📞🐌",
):
    text = lightbulb.string(
        "message",
        "🐌 Message to broadcast",
        min_length=1,
        max_length=2000
    )

    anonymous = lightbulb.boolean(
        "anonymous",
        "Send anonymously (default: false)",
        default=False
    )

    @lightbulb.invoke
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Build the message content
        if self.anonymous:
            content = (
                "📞 **Den Den Mushi Broadcast**\n"
                "Puru puru puru... *click*\n\n"
                f"{self.text}\n\n"
                "*click* ... Gacha!\n"
                "🎭 _Anonymous transmission_"
            )
        else:
            content = (
                "📞 **Den Den Mushi Broadcast**\n"
                "Puru puru puru... *click*\n\n"
                f"{self.text}\n\n"
                "*click* ... Gacha!\n"
                f"📡 _Transmitted by {ctx.member.display_name}_"
            )

        # Send the broadcast
        await bot.rest.create_message(
            channel=ctx.channel_id,
            content=content,
            user_mentions=True,
            role_mentions=True
        )

        # Send confirmation to user
        await ctx.respond(
            f"✅ Your Den Den Mushi broadcast has been transmitted!\n"
            f"Anonymous: **{'Yes' if self.anonymous else 'No'}**",
            ephemeral=True
        )


loader.command(DenDenMushi)