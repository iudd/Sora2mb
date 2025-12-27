# Google Drive 集成完成指南

## 📋 当前状态

### ✅ 已完成（在 hf-spaces 分支）
1. **配置文件** - `config/setting.toml` 已添加 Google Drive 配置
2. **依赖** - `requirements.txt` 已添加 `gradio_client`
3. **配置类** - `src/core/config.py` 已添加配置属性
4. **上传服务** - `src/services/google_drive_uploader.py` 已创建
5. **导入和初始化** - `src/services/generation_handler.py` 已添加导入和初始化

### ⚠️ 需要完成

**最后一步：修改缓存逻辑**

由于 `generation_handler.py` 文件太大，API 无法直接上传，你需要：

## 🚀 完成步骤

### 方法1: 使用自动脚本（推荐）

```bash
# 1. 切换到 hf-spaces 分支
git checkout hf-spaces

# 2. 拉取最新代码
git pull

# 3. 运行自动修改脚本
python apply_google_drive_patch.py

# 4. 查看修改
git diff src/services/generation_handler.py

# 5. 提交修改
git add src/services/generation_handler.py
git commit -m "feat: 完成 Google Drive 上传集成"
git push
```

### 方法2: 手动修改

编辑 `src/services/generation_handler.py`，找到约**第658行**：

**查找：**
```python
# 4) Cache watermark-free video (if cache enabled)
if config.cache_enabled:
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
```

## 🎯 使用方法

完成修改后，启用 Google Drive 上传：

### 环境变量方式（推荐）

```bash
export GOOGLE_DRIVE_ENABLED=true
export GOOGLE_DRIVE_PASSWORD="sk-123456"
```

### 配置文件方式

编辑 `config/setting.toml`:

```toml
[google_drive]
enabled = true
password = "sk-123456"
```

## 📊 工作流程

启用后的流程：

1. Sora 生成视频 ✅
2. 发布视频获取 `post_id` ✅
3. 第三方/自定义解析获取无水印URL ✅
4. **调用 Gradio API 上传到 Google Drive** ⬅️ 新功能
5. 返回 Google Drive 直链 ✅

## 📝 日志示例

成功上传时你会看到：

```
🚀 Uploading to Google Drive via https://leeykike-url2drive.hf.space: https://...
✅ Google Drive upload success: https://drive.google.com/uc?id=...
✅ Video uploaded to Google Drive successfully!
```

## 🔧 优先级

```
Google Drive 上传 > 本地缓存 > 直接使用无水印URL
```

- 当 `google_drive.enabled = true` 时优先使用 Google Drive
- 上传失败会自动回退到无水印URL
- 兼容原有的本地缓存逻辑

## 📚 相关文件

- `MODIFICATION_GUIDE.md` - 详细修改指南
- `google_drive_integration.patch` - 补丁文件
- `apply_google_drive_patch.py` - 自动应用脚本
- `GOOGLE_DRIVE_INTEGRATION.md` - 功能说明

---

**所有代码已准备就绪，只需运行 `apply_google_drive_patch.py` 即可完成！** 🎉
