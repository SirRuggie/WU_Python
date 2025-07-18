import lightbulb

loader = lightbulb.Loader()

@loader.command
class GetUserId(
    lightbulb.UserCommand,
    name="Get User ID",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        # 'self.target' contains the user object the command was executed on
        await ctx.respond(self.target.id)
