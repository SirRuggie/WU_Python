# extensions/commands/clan/upload.py

# Standard library imports
import os
from datetime import datetime

# Discord and bot framework imports
import hikari
import lightbulb

# Project-specific imports
from extensions.commands.clan import loader, clan
from extensions.autocomplete import clans
from utils.mongo import MongoClient
from utils.cloudinary_client import CloudinaryClient
from utils.text_utils import sanitize_filename


@clan.register()
class UploadImages(
    lightbulb.SlashCommand,
    name="upload-images",
    description="Upload logo and banner images for a clan",
):
    # Define the command parameters that users will fill in
    clan_tag = lightbulb.string(
        "clan",
        "The clan to update (e.g., Clan Name | #ABC123)",
        autocomplete=clans  # This connects to your existing clan autocomplete function
    )

    # Logo attachment parameter - optional
    logo = lightbulb.attachment(
        "logo",
        "The clan logo image (PNG, JPG, GIF, or WEBP)",
        default=None  # Making it optional allows users to upload just a banner
    )

    # Banner attachment parameter - optional
    banner = lightbulb.attachment(
        "banner",
        "The clan banner image (PNG, JPG, GIF, or WEBP)",
        default=None  # Making it optional allows users to upload just a logo
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            cloudinary_client: CloudinaryClient = lightbulb.di.INJECTED,
    ) -> None:
        # Defer the response since file uploads might take a few seconds
        # This prevents Discord from timing out while we process the images
        await ctx.defer(ephemeral=True)

        # Extract the clan tag from the autocomplete format
        # Your autocomplete returns "Clan Name | #TAG", so we need to extract just the tag
        if " | " in self.clan_tag:
            clan_tag = self.clan_tag.split(" | ")[-1]
        else:
            # If the user somehow entered just a tag directly, use it as-is
            clan_tag = self.clan_tag

        # Verify the clan exists in your database
        # This prevents uploads for clans that haven't been registered in your system
        clan_data = await mongo.clans.find_one({"tag": clan_tag})
        if not clan_data:
            await ctx.respond(
                "❌ I couldn't find that clan in our database.\n"
                "Please make sure you selected a valid clan from the dropdown."
            )
            return

        # Ensure at least one image was provided
        # This gives users flexibility to update just logo, just banner, or both
        if not self.logo and not self.banner:
            await ctx.respond(
                "❌ Please attach at least one image (logo or banner).\n\n"
                "**How to attach files:**\n"
                "1. Click the ➕ button next to the message box\n"
                "2. Select your image file(s)\n"
                "3. The files will appear in the command options"
            )
            return

        # Define allowed file extensions for security and compatibility
        allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

        # Validate logo file type if provided
        if self.logo:
            # Extract the file extension and convert to lowercase for comparison
            logo_ext = os.path.splitext(self.logo.filename.lower())[1]
            if logo_ext not in allowed_extensions:
                await ctx.respond(
                    f"❌ Invalid logo format: `{logo_ext}`\n"
                    f"**Allowed formats:** {', '.join(allowed_extensions)}"
                )
                return

        # Validate banner file type if provided
        if self.banner:
            banner_ext = os.path.splitext(self.banner.filename.lower())[1]
            if banner_ext not in allowed_extensions:
                await ctx.respond(
                    f"❌ Invalid banner format: `{banner_ext}`\n"
                    f"**Allowed formats:** {', '.join(allowed_extensions)}"
                )
                return

        # Get the sanitized clan name for use in filenames
        # This converts "Arcane Angels" to "Arcane_Angels", removing special characters
        clean_clan_name = sanitize_filename(clan_data['name'])

        # Prepare variables to track what we're updating
        update_data = {}  # Will store the URLs to save in the database
        upload_summary = []  # Will store success messages for user feedback

        try:
            # Process logo upload if provided
            if self.logo:
                # Read the attachment data into memory
                # This downloads the file from Discord's servers
                logo_data = await self.logo.read()

                # Create a descriptive public ID using the clan name
                # For "Arcane Angels", this becomes "Arcane_Angels"
                logo_public_id = clean_clan_name

                # Upload to Cloudinary with proper organization
                logo_result = await cloudinary_client.upload_image_from_bytes(
                    logo_data,
                    folder="clan_logos",  # Organizes logos in their own folder
                    public_id=logo_public_id  # Sets the filename
                )

                # Store the secure URL that Cloudinary returns
                # This URL will be saved in your database
                update_data["logo"] = logo_result["secure_url"]

                # Create a user-friendly summary of what was uploaded
                file_size_kb = self.logo.size // 1024  # Convert bytes to KB
                upload_summary.append(
                    f"✅ **Logo:** `{self.logo.filename}` ({file_size_kb}KB)"
                )

            # Process banner upload if provided
            if self.banner:
                # Read the banner attachment data
                banner_data = await self.banner.read()

                # Create a descriptive public ID with _Banner suffix
                # For "Arcane Angels", this becomes "Arcane_Angels_Banner"
                banner_public_id = f"{clean_clan_name}_Banner"

                # Upload to Cloudinary with proper organization
                banner_result = await cloudinary_client.upload_image_from_bytes(
                    banner_data,
                    folder="clan_banners",  # Banners get their own folder
                    public_id=banner_public_id
                )

                # Store the URL for database update
                update_data["banner"] = banner_result["secure_url"]

                # Add to the summary
                file_size_kb = self.banner.size // 1024
                upload_summary.append(
                    f"✅ **Banner:** `{self.banner.filename}` ({file_size_kb}KB)"
                )

            # Update the database with new image URLs
            # This only runs if at least one image was successfully uploaded
            if update_data:
                await mongo.clans.update_one(
                    {"tag": clan_tag},
                    {"$set": update_data}  # $set only updates specified fields
                )

            # Create a visually appealing success embed
            embed = hikari.Embed(
                title="✅ Images Uploaded Successfully",
                description=f"Images for **{clan_data['name']}** have been uploaded to cloud storage.",
                color=0x00FF00,  # Green color indicates success
                timestamp=datetime.utcnow()  # Shows when the upload completed
            )

            # Add details about what was uploaded
            embed.add_field(
                name="📤 Uploaded Files",
                value="\n".join(upload_summary),  # Lists each file uploaded
                inline=False
            )

            # Show the uploaded logo as a small thumbnail
            if "logo" in update_data:
                embed.set_thumbnail(update_data["logo"])

            # Show the uploaded banner as the main image
            if "banner" in update_data:
                embed.set_image(update_data["banner"])

            # Add informative footer about where images are stored
            embed.set_footer(
                text="Images are stored securely on Cloudinary CDN",
                icon="https://res.cloudinary.com/demo/image/upload/cloudinary_icon.png"
            )

            # Send the success response
            await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            # If anything goes wrong, provide helpful error information

            # Create an error embed with clear visual indicators
            error_embed = hikari.Embed(
                title="❌ Upload Failed",
                description="An error occurred while uploading your images.",
                color=0xFF0000  # Red color indicates an error
            )

            # Include error details, but truncate if too long
            # This prevents the embed from becoming too large
            error_message = str(e)
            if len(error_message) > 200:
                error_message = error_message[:200] + "..."

            error_embed.add_field(
                name="Error Details",
                value=f"```{error_message}```",  # Code block for readability
                inline=False
            )

            # Provide troubleshooting guidance
            error_embed.add_field(
                name="💡 Common Issues",
                value=(
                    "• **File corrupted:** Try opening the image in an editor and re-saving it\n"
                    "• **File too large:** Discord limits files to 8MB\n"
                    "• **Network issues:** Check your connection and try again\n"
                    "• **Invalid format:** Ensure the file is actually an image\n"
                    "• **Permissions:** Make sure I have permission to upload files"
                ),
                inline=False
            )

            # If it's a Cloudinary-specific error, add more targeted advice
            if "cloudinary" in error_message.lower():
                error_embed.add_field(
                    name="☁️ Cloudinary Issues",
                    value=(
                        "• **API limits:** Check if you've hit upload limits\n"
                        "• **Invalid characters:** Try renaming your file\n"
                        "• **Connection:** Cloudinary might be temporarily unavailable"
                    ),
                    inline=False
                )

            await ctx.respond(embed=error_embed, ephemeral=True)


loader.command(clan)