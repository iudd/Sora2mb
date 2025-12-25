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
        self.password = config.google_drive_password

    async def upload_file_via_api(self, file_url: str) -> Optional[str]:
        """
        Upload file to Google Drive via Gradio API

        Args:
            file_url: URL of the file to upload

        Returns:
            Google Drive direct download link, or None if failed
        """
        if not self.password:
            debug_logger.log_error(
                error_message="Google Drive password not configured. Please set GOOGLE_DRIVE_PASSWORD environment variable",
                status_code=500,
                response_text="Missing Google Drive password"
            )
            return None

        try:
            debug_logger.log_info(f"🚀 Uploading to Google Drive via {self.space_url}: {file_url}")

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._sync_upload,
                file_url
            )

            if result and isinstance(result, dict):
                status = result.get('status')
                if status == 'success':
                    download_link = result.get('download_link')
                    debug_logger.log_info(f"✅ Google Drive upload success: {download_link}")
                    return download_link
                else:
                    error_msg = result.get('message', 'Unknown error')
                    debug_logger.log_error(
                        error_message=f"Google Drive upload failed: {error_msg}",
                        status_code=500,
                        response_text=str(result)
                    )
                    return None
            else:
                debug_logger.log_error(
                    error_message=f"Unexpected result format from Google Drive API: {result}",
                    status_code=500,
                    response_text=str(result)
                )
                return None

        except Exception as e:
            debug_logger.log_error(
                error_message=f"Failed to upload to Google Drive: {str(e)}",
                status_code=500,
                response_text=str(e)
            )
            return None

    def _sync_upload(self, file_url: str) -> dict:
        """Synchronous upload function (runs in executor)"""
        client = Client(self.space_url)

        # Call "upload" API with file URL and password
        result = client.predict(
            file_url,      # 参数1: URL
            self.password,  # 参数2: 密码
            api_name="/upload"
        )

        return result
