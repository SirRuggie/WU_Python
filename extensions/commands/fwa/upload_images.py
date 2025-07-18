# extensions/commands/fwa/upload_images.py
"""
Command for uploading FWA base images directly via Discord attachments.
Complements the FWA data management system.
"""

import os
import hikari
import lightbulb

from extensions.commands.fwa import loader, fwa
from utils.cloudinary_client import CloudinaryClient
from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE

# Cloudinary folders
CLOUDINARY_WAR_BASE_FOLDER = "fwa/war_bases"
CLOUDINARY_ACTIVE_BASE_FOLDER = "fwa/active_bases"

# TH levels we support
FWA_TH_LEVELS = ["th9", "th10", "th11", "th12", "th13", "th14", "th15", "th16", "th17"]


@fwa.register()
class UploadImages(
    lightbulb.SlashCommand,
    name="upload-images",
    description="Upload war and active base images for a specific Town Hall level",
):
    # Town hall level parameter
    th_level = lightbulb.string(
        "town-hall",
        "Select the Town Hall level (e.g., th9, th10, etc.)",
        choices=[
            lightbulb.Choice(name=f"Town Hall {th[2:]}", value=th)
            for th in FWA_TH_LEVELS
        ]
    )

    # War base image attachment
    war_base = lightbulb.attachment(
        "war-base",
        "The war base layout image",
        default=None
    )

    # Active base image attachment
    active_base = lightbulb.attachment(
        "active-base",
        "The active war base layout image",
        default=None
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            cloudinary_client: CloudinaryClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Ensure at least one image was provided
        if not self.war_base and not self.active_base:
            await ctx.respond(
                "❌ Please attach at least one image (war base or active base)."
            )
            return

        # Validate file types
        allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

        if self.war_base:
            war_ext = os.path.splitext(self.war_base.filename.lower())[1]
            if war_ext not in allowed_extensions:
                await ctx.respond(
                    f"❌ Invalid war base format: `{war_ext}`\n"
                    f"**Allowed formats:** {', '.join(allowed_extensions)}"
                )
                return

        if self.active_base:
            active_ext = os.path.splitext(self.active_base.filename.lower())[1]
            if active_ext not in allowed_extensions:
                await ctx.respond(
                    f"❌ Invalid active base format: `{active_ext}`\n"
                    f"**Allowed formats:** {', '.join(allowed_extensions)}"
                )
                return

        # Process uploads
        th_num = self.th_level.upper().replace("TH", "")
        upload_summary = []

        try:
            # Upload war base if provided
            if self.war_base:
                war_data = await self.war_base.read()

                war_result = await cloudinary_client.upload_image_from_bytes(
                    war_data,
                    folder=f"{CLOUDINARY_WAR_BASE_FOLDER}/{self.th_level}",
                    public_id=self.th_level
                )

                # Update the constant in memory
                FWA_WAR_BASE[self.th_level] = war_result["secure_url"]

                file_size_kb = self.war_base.size // 1024
                upload_summary.append(
                    f"✅ **War Base:** `{self.war_base.filename}` ({file_size_kb}KB)"
                )

            # Upload active base if provided
            if self.active_base:
                active_data = await self.active_base.read()

                active_result = await cloudinary_client.upload_image_from_bytes(
                    active_data,
                    folder=f"{CLOUDINARY_ACTIVE_BASE_FOLDER}/{self.th_level}",
                    public_id=self.th_level
                )

                # Update the constant in memory
                FWA_ACTIVE_WAR_BASE[self.th_level] = active_result["secure_url"]

                file_size_kb = self.active_base.size // 1024
                upload_summary.append(
                    f"✅ **Active Base:** `{self.active_base.filename}` ({file_size_kb}KB)"
                )

            # Build success response
            embed = hikari.Embed(
                title=f"✅ TH{th_num} Images Uploaded",
                description=(
                        f"Successfully uploaded FWA base images for Town Hall {th_num}.\n\n"
                        + "\n".join(upload_summary)
                ),
                color=0x00FF00
            )

            # Add thumbnails of uploaded images
            if self.war_base and war_result:
                embed.add_field(
                    name="War Base Preview",
                    value=f"[View Full Image]({war_result['secure_url']})",
                    inline=True
                )

            if self.active_base and active_result:
                embed.add_field(
                    name="Active Base Preview",
                    value=f"[View Full Image]({active_result['secure_url']})",
                    inline=True
                )

            embed.set_footer(
                text="Images stored on Cloudinary CDN",
                icon="https://res.cloudinary.com/demo/image/upload/cloudinary_icon.png"
            )

            await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            # Error handling
            error_embed = hikari.Embed(
                title="❌ Upload Failed",
                description=f"Failed to upload images for TH{th_num}.",
                color=0xFF0000
            )

            error_message = str(e)
            if len(error_message) > 200:
                error_message = error_message[:200] + "..."

            error_embed.add_field(
                name="Error Details",
                value=f"```{error_message}```",
                inline=False
            )

            error_embed.add_field(
                name="💡 Troubleshooting",
                value=(
                    "• Check file size (max 8MB)\n"
                    "• Ensure valid image format\n"
                    "• Try re-saving the image\n"
                    "• Check your internet connection"
                ),
                inline=False
            )

            await ctx.respond(embed=error_embed, ephemeral=True)


loader.command(fwa)