#!/usr/bin/env python3
"""
自动应用 Google Drive 集成修改的脚本

使用方法:
    python apply_google_drive_patch.py
"""

import re

def apply_patch():
    file_path = "src/services/generation_handler.py"
    
    # 读取文件
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找需要替换的代码块（无水印视频缓存部分）
    # 这是原来的代码模式
    old_pattern = r'(\s+)# 4\) Cache watermark-free video \(if cache enabled\)\n\s+if config\.cache_enabled:'
    
    # 新的代码块
    new_code = r'''\1# 4) Upload to Google Drive or cache locally
\1if config.google_drive_enabled:
\1    try:
\1        if stream:
\1            yield self._format_stream_chunk(
\1                reasoning_content="Uploading watermark-free video to Google Drive...\\n"
\1            )
\1        
\1        # Upload to Google Drive via Gradio API
\1        local_url = await self.google_drive_uploader.upload_file_via_api(watermark_free_url)
\1        
\1        if local_url:
\1            if stream:
\1                yield self._format_stream_chunk(
\1                    reasoning_content=f"✅ Video uploaded to Google Drive successfully!\\n"
\1                )
\1            
\1            # Delete the published post after upload (best-effort)
\1            try:
\1                debug_logger.log_info(f"Deleting published post: {post_id}")
\1                await self.sora_client.delete_post(post_id, token)
\1                debug_logger.log_info(f"Published post deleted successfully: {post_id}")
\1            except Exception as delete_error:
\1                debug_logger.log_error(
\1                    error_message=f"Failed to delete published post {post_id}: {str(delete_error)}",
\1                    status_code=500,
\1                    response_text=str(delete_error)
\1                )
\1        else:
\1            # Fallback to watermark-free URL if upload fails
\1            local_url = watermark_free_url
\1            if stream:
\1                yield self._format_stream_chunk(
\1                    reasoning_content="Warning: Google Drive upload failed. Using watermark-free URL instead...\\n"
\1                )
\1    except Exception as upload_error:
\1        # Fallback to watermark-free URL if upload fails
\1        local_url = watermark_free_url
\1        if stream:
\1            yield self._format_stream_chunk(
\1                reasoning_content=(
\1                    f"Warning: Failed to upload to Google Drive - {str(upload_error)}\\n"
\1                    "Using original watermark-free URL instead...\\n"
\1                )
\1            )
\1elif config.cache_enabled:
\1    # 原来的本地缓存逻辑保持不变'''
    
    # 执行替换
    new_content, count = re.subn(old_pattern, new_code, content, count=1)
    
    if count == 0:
        print("❌ 未找到需要替换的代码块")
        print("可能已经应用过修改，或者文件结构已变化")
        return False
    
    # 写回文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✅ 成功应用 Google Drive 集成修改")
    print(f"   修改了 {count} 处代码")
    return True

if __name__ == "__main__":
    try:
        apply_patch()
    except FileNotFoundError:
        print("❌ 找不到文件: src/services/generation_handler.py")
        print("   请确保在项目根目录运行此脚本")
    except Exception as e:
        print(f"❌ 应用修改失败: {e}")
