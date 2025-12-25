# Google Drive 集成修改指南

## 已完成的修改

1. ✅ `config/setting.toml` - 添加了 Google Drive 配置
2. ✅ `requirements.txt` - 添加了 `gradio_client` 依赖  
3. ✅ `src/core/config.py` - 添加了 Google Drive 配置属性
4. ✅ `src/services/google_drive_uploader.py` - 创建了上传服务
5. ⚠️ `src/services/generation_handler.py` - **需要完成以下修改**

## generation_handler.py 需要的修改

### 修改1: 导入 GoogleDriveUploader (第17行)

**已添加：**
```python
from .google_drive_uploader import GoogleDriveUploader
```

### 修改2: 初始化 Google Drive Uploader (第78行后)

**已添加：**
```python
# 初始化 Google Drive 上传器
self.google_drive_uploader = GoogleDriveUploader()
```

### 修改3: 替换无水印视频缓存逻辑 (约第658-700行)

**查找这段代码：**
```python
# 4) Cache watermark-free video (if cache enabled)
if config.cache_enabled:
    try:
        cached_filename = await self._download_with_retry(watermark_free_url, "video")
        local_url = f"{self._get_base_url()}/tmp/{cached_filename}"
        ...
```

**替换为：**
```python
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
    # 原来的本地缓存逻辑保持不变
    try:
        cached_filename = await self._download_with_retry(watermark_free_url, "video")
        local_url = f"{self._get_base_url()}/tmp/{cached_filename}"
        if stream:
            yield self._format_stream_chunk(
                reasoning_content="Watermark-free video cached successfully. Preparing final response...\\n"
            )

        # Delete the published post after caching (best-effort)
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
    except Exception as cache_error:
        # Fallback to watermark-free URL if caching fails
        local_url = watermark_free_url
        if stream:
            yield self._format_stream_chunk(
                reasoning_content=(
                    f"Warning: Failed to cache file - {str(cache_error)}\\n"
                    "Using original watermark-free URL instead...\\n"
                )
            )
else:
    # Cache disabled: use watermark-free URL directly
    local_url = watermark_free_url
    if stream:
        yield self._format_stream_chunk(
            reasoning_content="Cache is disabled. Using watermark-free URL directly...\\n"
        )
```

## 如何使用

### 启用 Google Drive 上传

**方法1: 环境变量（推荐）**
```bash
export GOOGLE_DRIVE_ENABLED=true
export GOOGLE_DRIVE_PASSWORD="your-password-here"
```

**方法2: 修改配置文件**
编辑 `config/setting.toml`:
```toml
[google_drive]
enabled = true
password = "your-password-here"
```

## 测试

设置好环境变量后，生成视频时应该看到：
```
🚀 Uploading to Google Drive via https://iyougame-url2drive.hf.space: https://...
✅ Google Drive upload success: https://drive.google.com/...
✅ Video uploaded to Google Drive successfully!
```

## 注意事项

- Google Drive 上传优先级 > 本地缓存 > 直接使用URL
- 上传失败会自动回退到原无水印URL
- 密码可以通过环境变量或配置文件设置（环境变量优先）
