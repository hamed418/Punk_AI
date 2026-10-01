"""
app/services/storage.py
────────────────────────
Asynchronous Cloudflare R2 / S3 storage service.
Handles file uploads, deletions, and generating public URLs.
"""

import aioboto3
from typing import Optional
from app.core.config import settings
from app.core.logging import logger
import botocore.exceptions
from botocore.config import Config

# Auto-retry transient R2/network errors instead of failing on the first blip.
_R2_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"})


class StorageService:
    def __init__(self):
        self.access_key = settings.R2_ACCESS_KEY_ID
        self.secret_key = settings.R2_SECRET_ACCESS_KEY
        self.bucket_name = settings.R2_BUCKET_NAME
        self.endpoint_url = settings.R2_ENDPOINT_URL
        self.public_url = settings.R2_PUBLIC_URL

        # Validate configuration
        if not all([self.access_key, self.secret_key, self.bucket_name, self.endpoint_url]):
            logger.warning("R2 Storage configuration is incomplete. Uploads will fail.")

    def _get_session(self):
        return aioboto3.Session()

    async def upload_file(
        self, 
        file_data: bytes, 
        file_name: str, 
        content_type: str,
        prefix: str = "media"
    ) -> Optional[str]:
        """
        Upload a file to R2 and return the public URL (or key if no public URL configured).
        """
        if not all([self.access_key, self.secret_key, self.bucket_name, self.endpoint_url]):
            logger.error("Cannot upload: R2 configuration missing.")
            return None

        key = f"{prefix}/{file_name}"
        session = self._get_session()

        try:
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=_R2_CONFIG,
            ) as s3:
                await s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=file_data,
                    ContentType=content_type,
                )
                
            logger.info(f"Successfully uploaded {file_name} to R2 bucket {self.bucket_name}")
            
            if self.public_url:
                return f"{self.public_url.rstrip('/')}/{key}"
            return key

        except botocore.exceptions.ClientError as e:
            logger.error(f"Failed to upload to R2: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during R2 upload: {str(e)}")
            return None

    async def download_file(self, key: str) -> Optional[bytes]:
        """Download a file from R2 by key or public URL. Returns None on failure."""
        if not all([self.access_key, self.secret_key, self.bucket_name, self.endpoint_url]):
            logger.error("Cannot download: R2 configuration missing.")
            return None

        # If key is a full URL, try to extract the relative key
        if self.public_url and key.startswith(self.public_url):
            key = key.replace(f"{self.public_url.rstrip('/')}/", "")

        session = self._get_session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=_R2_CONFIG,
            ) as s3:
                response = await s3.get_object(Bucket=self.bucket_name, Key=key)
                return await response["Body"].read()
        except Exception as e:
            logger.error(f"Failed to download {key} from R2: {str(e)}")
            return None

    async def delete_file(self, key: str) -> bool:
        """Delete a file from R2."""
        if not all([self.access_key, self.secret_key, self.bucket_name, self.endpoint_url]):
            logger.error("Cannot delete: R2 configuration missing.")
            return False

        # If key is a full URL, try to extract the relative key
        if self.public_url and key.startswith(self.public_url):
            key = key.replace(f"{self.public_url.rstrip('/')}/", "")

        session = self._get_session()
        try:
            async with session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=_R2_CONFIG,
            ) as s3:
                await s3.delete_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete {key} from R2: {str(e)}")
            return False

storage_service = StorageService()
