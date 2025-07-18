import hikari
import lightbulb
from PIL import Image
from io import BytesIO

loader = lightbulb.Loader()


@loader.command
class StealEmoji(
    lightbulb.SlashCommand,
    name="steal",
    description="Steal a custom emoji into your bot application, replacing any with the same name.",
    default_member_permissions=hikari.Permissions.CREATE_GUILD_EXPRESSIONS
):
    emoji = lightbulb.string(
        "emoji",
        "The emoji to steal (e.g. <:some_name:1234567890>)"
    )
    new_name = lightbulb.string(
        "new_name",
        "What to call it in your application (optional)",
        default=None
    )
    compress = lightbulb.boolean(
        "compress",
        "Compress the emoji if it's too large (may reduce quality)",
        default=False
    )

    @lightbulb.invoke
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        await ctx.defer()

        # Parse emoji
        try:
            source: hikari.CustomEmoji = hikari.emojis.Emoji.parse(self.emoji)
        except Exception:
            await ctx.respond("❌ Invalid emoji format—make sure it looks like `<:name:id>` or `<a:name:id>`.")
            return

        # Verify it's a custom emoji
        if not isinstance(source, hikari.CustomEmoji):
            await ctx.respond("❌ This appears to be a Unicode emoji, not a custom Discord emoji.")
            return

        emoji_name = self.new_name or source.name

        # Validate emoji name
        if not (2 <= len(emoji_name) <= 32) or not emoji_name.replace('_', '').isalnum():
            await ctx.respond(
                "❌ Emoji names must be 2-32 characters and contain only letters, numbers, and underscores.")
            return

        application = await bot.rest.fetch_my_user()

        try:
            # Check for existing emoji with same name
            existing_emojis = await bot.rest.fetch_application_emojis(application.id)
            for emoji in existing_emojis:
                if emoji.name.lower() == emoji_name.lower():
                    await bot.rest.delete_application_emoji(
                        application=application.id,
                        emoji=emoji.id
                    )
                    break
        except hikari.ForbiddenError:
            await ctx.respond("❌ I don't have permission to manage application emojis.")
            return

        try:
            # Download emoji
            emoji_bytes = await source.read()

            # Compress if requested or if too large
            if self.compress or len(emoji_bytes) > 256 * 1024:
                emoji_bytes = self._compress_emoji(emoji_bytes)

            # Create emoji
            created = await bot.rest.create_application_emoji(
                application=application.id,
                name=emoji_name,
                image=emoji_bytes,
            )

            await ctx.respond(
                f"✅ Successfully {'stole' if not self.new_name else 'stole and renamed'} "
                f"`:{created.name}:`! {created.mention}\n"
                f"{'📦 Emoji was compressed to fit size limits.' if self.compress else ''}"
            )

        except hikari.BadRequestError as e:
            error_msg = str(e)
            if "File cannot be larger than" in error_msg:
                await ctx.respond(
                    "❌ The emoji is too large (>256KB). "
                    "Try running the command again with `compress: True`."
                )
            elif "Maximum number of emojis reached" in error_msg:
                await ctx.respond("❌ The bot has reached the maximum number of application emojis (2000).")
            else:
                await ctx.respond(f"❌ Failed to create emoji: {e}")
        except Exception as e:
            await ctx.respond(f"❌ An unexpected error occurred: {type(e).__name__}: {e}")

    def _compress_emoji(self, image_bytes: bytes, max_kb: int = 256) -> bytes:
        """Compress an emoji image to fit Discord's size requirements."""
        image = Image.open(BytesIO(image_bytes))

        # Resize if larger than 128x128
        if image.size[0] > 128 or image.size[1] > 128:
            image.thumbnail((128, 128), Image.Resampling.LANCZOS)

        # Try PNG first (better for emojis with transparency)
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)

        if buffer.tell() <= max_kb * 1024:
            buffer.seek(0)
            return buffer.getvalue()

        # If still too large and not animated, try WebP
        if not getattr(image, 'is_animated', False):
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=95, method=6)
            if buffer.tell() <= max_kb * 1024:
                buffer.seek(0)
                return buffer.getvalue()

        # Last resort: reduce quality
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True, compress_level=9)
        buffer.seek(0)
        return buffer.getvalue()