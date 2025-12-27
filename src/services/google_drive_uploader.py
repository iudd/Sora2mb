"""Google Drive upload service using Gradio Client"""
import asyncio
from typing import Optional
from gradio_client import Client
from ..core.config import config
from ..core.logger import debug_logger


class GoogleDriveUploader:
    """Handle file uploads to Google Drive via Gradio Space"""

    def __init__(self):
        self.space_url = config.google_drive_space_url
        self.space_url_backup = config.google_drive_space_url_backup
        self.password = config.google_drive_password

    async def upload_file_via_api(self, file_url: str, username: Optional[str] = None, metadata: Optional[dict] = None) -> Optional[str]:
        """
        Upload file to Google Drive via Gradio API with backup fallback
        """
        if not self.password:
            debug_logger.log_error(
                error_message="Google Drive password not configured. Please set GOOGLE_DRIVE_PASSWORD environment variable",
                status_code=500,
                response_text="Missing Google Drive password"
            )
            return None

        # 1. Try primary URL
        result = await self._try_upload(self.space_url, file_url, username, metadata)
        if result:
            return result

        # 2. Try backup URL if available and different
        if self.space_url_backup and self.space_url_backup != self.space_url:
            debug_logger.log_info(f"🔄 Primary upload failed. Retrying with backup URL: {self.space_url_backup}")
            result = await self._try_upload(self.space_url_backup, file_url, username, metadata)
            if result:
                return result

        return None

    async def _try_upload(self, space_url: str, file_url: str, username: Optional[str] = None, metadata: Optional[dict] = None) -> Optional[str]:
        """Helper to attempt upload to a specific space URL"""
        try:
            debug_logger.log_info(f"🚀 Uploading to Google Drive via {space_url}: {file_url}")

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._sync_upload,
                space_url,
                file_url,
                username,
                metadata
            )

            if result and isinstance(result, dict):
                status = result.get('status')
                if status == 'success':
                    download_link = result.get('download_link')
                    folder_path = result.get('folder_path')
                    debug_logger.log_info(f"✅ Google Drive upload success: {download_link} (Folder: {folder_path})")
                    return download_link
                else:
                    error_msg = result.get('message', 'Unknown error')
                    debug_logger.log_error(
                        error_message=f"Google Drive upload failed ({space_url}): {error_msg}",
                        status_code=500,
                        response_text=str(result)
                    )
                    return None
            else:
                debug_logger.log_error(
                    error_message=f"Unexpected result format from Google Drive API ({space_url}): {result}",
                    status_code=500,
                    response_text=str(result)
                )
                return None

        except Exception as e:
            error_msg = str(e)
            if "Could not fetch config" in error_msg:
                debug_logger.log_info(
                    f"⚠️ Google Drive upload skipped for {space_url} (Space not accessible): {error_msg}"
                )
            else:
                debug_logger.log_error(
                    error_message=f"Failed to upload to Google Drive ({space_url}): {error_msg}",
                    status_code=500,
                    response_text=error_msg
                )
            return None

    def _sync_upload(self, space_url: str, file_url: str, username: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
        """Synchronous upload function (runs in executor)"""
        client = Client(space_url)

        # Construct request payload for /upload_json endpoint
        payload = {
            "url": file_url,
            "password": self.password,
            "username": username,
            "metadata": metadata
        }

        # Call "upload_json" API
        result = client.predict(
            payload,      # 参数1: JSON对象
            api_name="/upload_json"
        )

        return result
