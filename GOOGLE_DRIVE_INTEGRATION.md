# Google Drive 上传集成说明

## 功能说明

当启用 Google Drive 上传功能后，视频生成完成的处理流程如下：

1. **Sora 生成视频** → 获取带水印的视频URL
2. **发布视频** → 获取 `post_id`
3. **第三方/自定义解析** → 获取无水印视频直链URL
4. **调用 Gradio API** → 将无水印URL上传到 Google Drive
5. **返回结果** → Google Drive 直链返回给用户

## 配置步骤

### 1. 设置环境变量

在启动服务前设置 Google Drive 密码：

```bash
export GOOGLE_DRIVE_PASSWORD="sk-123456"
```

或在 Docker 环境中：

```yaml
# docker-compose.yml
services:
  sora2api:
    environment:
      - GOOGLE_DRIVE_PASSWORD=sk-123456
```

### 2. 修改配置文件

编辑 `config/setting.toml`：

```toml
[google_drive]
enabled = true  # 启用 Google Drive 上传
space_url = "https://iyougame-url2drive.hf.space"  # Gradio Space 地址
password = ""  # 留空，通过环境变量设置
```

### 3. 禁用本地缓存（可选）

如果完全使用 Google Drive 存储，可以禁用本地缓存：

```toml
[cache]
enabled = false
```

## 工作原理

### 原来的流程（本地缓存）
```
无水印URL → 下载到 /tmp → 返回本地链接
```

### 新流程（Google Drive）
```
无水印URL → Gradio API 上传 → 返回 Google Drive 直链
```

### 代码修改位置

需要修改 `src/services/generation_handler.py` 中的以下部分：

#### 修改点1：在 `__init__` 中初始化 Google Drive Uploader

```python
from .google_drive_uploader import GoogleDriveUploader

def __init__(self, ...):
    # ... 现有代码 ...
    self.google_drive_uploader = GoogleDriveUploader()
```

#### 修改点2：替换缓存逻辑（约在第 630-680 行）

在 `_poll_task_result` 方法中，找到以下代码段：

**原代码：**
```python
# 4) Cache watermark-free video (if cache enabled)
if config.cache_enabled:
    try:
        cached_filename = await self._download_with_retry(watermark_free_url, "video")
        local_url = f"{self._get_base_url()}/tmp/{cached_filename}"
        if stream:
            yield self._format_stream_chunk(
                reasoning_content="Watermark-free video cached successfully. Preparing final response...\n"
            )
    except Exception as cache_error:
        # Fallback to watermark-free URL if caching fails
        local_url = watermark_free_url
        if stream:
            yield self._format_stream_chunk(
                reasoning_content=(
                    f"Warning: Failed to cache file - {str(cache_error)}\n"
                    "Using original watermark-free URL instead...\n"
                )
            )
else:
    # Cache disabled: use watermark-free URL directly
    local_url = watermark_free_url
    if stream:
        yield self._format_stream_chunk(
            reasoning_content="Cache is disabled. Using watermark-free URL directly...\n"
        )
```

**替换为：**
```python
# 4) Upload to Google Drive or cache locally
if config.google_drive_enabled:
    try:
        if stream:
            yield self._format_stream_chunk(
                reasoning_content="Uploading watermark-free video to Google Drive...\n"
            )
        
        # Upload to Google Drive via Gradio API
        local_url = await self.google_drive_uploader.upload_file_via_api(watermark_free_url)
        
        if local_url:
            if stream:
                yield self._format_stream_chunk(
                    reasoning_content=f"✅ Video uploaded to Google Drive successfully!\n"
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
                    reasoning_content="Warning: Google Drive upload failed. Using watermark-free URL instead...\n"
                )
    except Exception as upload_error:
        # Fallback to watermark-free URL if upload fails
        local_url = watermark_free_url
        if stream:
            yield self._format_stream_chunk(
                reasoning_content=(
                    f"Warning: Failed to upload to Google Drive - {str(upload_error)}\n"
                    "Using original watermark-free URL instead...\n"
                )
            )
elif config.cache_enabled:
    # 原来的本地缓存逻辑保持不变
    try:
        cached_filename = await self._download_with_retry(watermark_free_url, "video")
        local_url = f"{self._get_base_url()}/tmp/{cached_filename}"
        if stream:
            yield self._format_stream_chunk(
                reasoning_content="Watermark-free video cached successfully. Preparing final response...\n"
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
                    f"Warning: Failed to cache file - {str(cache_error)}\n"
                    "Using original watermark-free URL instead...\n"
                )
            )
else:
    # Cache disabled: use watermark-free URL directly
    local_url = watermark_free_url
    if stream:
        yield self._format_stream_chunk(
            reasoning_content="Cache is disabled. Using watermark-free URL directly...\n"
        )
```

#### 修改点3：同样修改普通模式（无水印模式关闭时）的缓存逻辑（约在第 700-730 行）

找到这段代码：

```python
else:
    # Normal mode: use downloadable_url instead of url
    url = item.get("downloadable_url") or item.get("url")
    if url:
        # Cache video file (if cache enabled)
        if config.cache_enabled:
            # ... 缓存逻辑 ...
```

在这里也添加 Google Drive 上传支持（与上面类似的逻辑）。

## 测试

启动服务后，生成视频时会看到以下日志：

```
🚀 Uploading to Google Drive via https://iyougame-url2drive.hf.space: https://...
✅ Google Drive upload success: https://drive.google.com/...
✅ Video uploaded to Google Drive successfully!
```

## 注意事项

1. **环境变量优先级**：`GOOGLE_DRIVE_PASSWORD` 环境变量优先于配置文件
2. **失败回退**：如果 Google Drive 上传失败，会自动回退到使用无水印URL
3. **兼容性**：保留了本地缓存选项，可以根据需要选择存储方式
4. **性能**：Google Drive 上传可能比本地缓存慢，但节省了服务器存储空间

## 优先级

```
Google Drive 上传 > 本地缓存 > 直接使用无水印URL
```

当 `google_drive.enabled = true` 时，即使 `cache.enabled = true`，也会优先使用 Google Drive。
