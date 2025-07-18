import cloudinary
import cloudinary.uploader
import cloudinary.api
import os
from typing import Optional, Dict, Any
import aiohttp
import asyncio


class CloudinaryClient:
    """Handles all Cloudinary operations for the bot"""

    def __init__(self):
        # Configure Cloudinary using environment variables
        cloudinary.config(
            cloud_name="dxmtzuomk",
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True
        )

    async def upload_image_from_url(self, image_url: str, folder: str, public_id: Optional[str] = None) -> Dict[
        str, Any]:
        """
        Uploads an image from a URL to Cloudinary

        Args:
            image_url: The URL of the image to upload
            folder: The folder path in Cloudinary (e.g., "clan_logos" or "clan_banners")
            public_id: Optional custom ID for the image

        Returns:
            Dictionary containing upload results including the secure URL
        """
        try:
            # Run the upload in a thread pool since cloudinary.uploader is synchronous
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: cloudinary.uploader.upload(
                    image_url,
                    folder=folder,
                    public_id=public_id,
                    overwrite=True,
                    invalidate=True,
                    resource_type="image"
                )
            )
            return result
        except Exception as e:
            raise Exception(f"Failed to upload image to Cloudinary: {str(e)}")

    async def upload_image_from_bytes(self, image_data: bytes, folder: str, public_id: Optional[str] = None) -> Dict[
        str, Any]:
        """
        Uploads image data (bytes) to Cloudinary

        Args:
            image_data: The image data as bytes
            folder: The folder path in Cloudinary
            public_id: Optional custom ID for the image

        Returns:
            Dictionary containing upload results
        """
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: cloudinary.uploader.upload(
                    image_data,
                    folder=folder,
                    public_id=public_id,
                    overwrite=True,
                    invalidate=True,
                    resource_type="image"
                )
            )
            return result
        except Exception as e:
            raise Exception(f"Failed to upload image to Cloudinary: {str(e)}")

    async def delete_image(self, public_id: str) -> Dict[str, Any]:
        """
        Deletes an image from Cloudinary

        Args:
            public_id: The public ID of the image to delete

        Returns:
            Dictionary containing deletion results
        """
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: cloudinary.uploader.destroy(public_id)
            )
            return result
        except Exception as e:
            raise Exception(f"Failed to delete image from Cloudinary: {str(e)}")