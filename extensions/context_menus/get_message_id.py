import lightbulb

loader = lightbulb.Loader()

@loader.command
class GetMessageId(
    lightbulb.MessageCommand,
    name="Get Message ID",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        # 'self.target' contains the message object the command was executed oned on
        await ctx.respond(self.target.id)
