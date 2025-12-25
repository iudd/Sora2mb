#!/usr/bin/env python3
"""
修复 generation_handler.py - 恢复原始文件并应用 Google Drive 集成

这个脚本会:
1. 从 commit 6cb83da 恢复原始文件
2. 添加 GoogleDriveUploader 导入
3. 在 __init__ 中初始化 google_drive_uploader
4. 修改缓存逻辑以支持 Google Drive 上传
"""

import requests
import re

# GitHub raw URL for the original file
ORIGINAL_FILE_URL = "https://raw.githubusercontent.com/iudd/Sora2mb/6cb83da03e22ad29ee217b1b556cc8bb08637494/src/services/generation_handler.py"

print("📥 Downloading original generation_handler.py...")
response = requests.get(ORIGINAL_FILE_URL)
content = response.text

print("✏️  Applying modifications...")

# 1. Add GoogleDriveUploader import (after line 16)
import_pattern = r'(from \.concurrency_manager import ConcurrencyManager\n)'
import_replacement = r'\1from .google_drive_uploader import GoogleDriveUploader\n'
content = re.sub(import_pattern, import_replacement, content)

# 2. Add google_drive_uploader initialization in __init__ (after file_cache)
init_pattern = r'(self\.file_cache = FileCache\(\s+cache_dir="tmp",\s+default_timeout=config\.cache_timeout,\s+proxy_manager=proxy_manager\s+\)\n)'
init_replacement = r'''\1        # 初始化 Google Drive 上传器
        self.google_drive_uploader = GoogleDriveUploader()
'''
content = re.sub(init_pattern, init_replacement, content, flags=re.MULTILINE | re.DOTALL)

# 3. Replace cache logic with Google Drive upload (find the watermark-free caching block)
cache_pattern = r'''(\s+# 4\) Cache watermark-free video \(if cache enabled\)\n\s+if config\.cache_enabled:)'''

cache_replacement = r'''
                                                # 4) Upload to Google Drive or cache locally
                                                if config.google_drive_enabled:
                                                    try:
                                                        if stream:
                                                            yield self._format_stream_chunk(
                                                                reasoning_content="Uploading watermark-free video to Google Drive...\\n"
                                                            )
                                                        
                                                        # Upload to Google Drive via Gradio API
                                                        local_url = await self.google_drive_uploader.upload_file_via_api(watermark_free_url)
                                                        
                                                        if local_url:
                                                            if stream:
                                                                yield self._format_stream_chunk(
                                                                    reasoning_content=f"✅ Video uploaded to Google Drive successfully!\\n"
                                                                )
                                                            
                                                            # Delete the published post after upload (best-effort)
                                                            try:
                                                                debug_logger.log_info(f"Deleting published post: {post_id}")
                                                                await self.sora_client.delete_post(post_id, token)
                                                                debug_logger.log_info(f"Published post deleted successfully: {post_id}")
                                                            except Exception as delete_error:
                                                                debug_logger.log_error(
                                                                    error_message=f"Failed to delete published post {post_id}: {str(delete_error)}",
                                                                    status_code=500,
                                                                    response_text=str(delete_error)
                                                                )
                                                        else:
                                                            # Fallback to watermark-free URL if upload fails
                                                            local_url = watermark_free_url
                                                            if stream:
                                                                yield self._format_stream_chunk(
                                                                    reasoning_content="Warning: Google Drive upload failed. Using watermark-free URL instead...\\n"
                                                                )
                                                    except Exception as upload_error:
                                                        # Fallback to watermark-free URL if upload fails
                                                        local_url = watermark_free_url
                                                        if stream:
                                                            yield self._format_stream_chunk(
                                                                reasoning_content=(
                                                                    f"Warning: Failed to upload to Google Drive - {str(upload_error)}\\n"
                                                                    "Using original watermark-free URL instead...\\n"
                                                                )
                                                            )
                                                elif config.cache_enabled:
                                                    # 原来的本地缓存逻辑保持不变'''

content = re.sub(cache_pattern, cache_replacement, content)

# Save to file
OUTPUT_FILE = "src/services/generation_handler.py"
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"✅ File modified and saved to {OUTPUT_FILE}")
print("📊 Summary:")
print("  - Added GoogleDriveUploader import")
print("  - Added google_drive_uploader initialization")
print("  - Modified cache logic to support Google Drive upload")
print("\n🎯 Next: git add, commit, and push!")
