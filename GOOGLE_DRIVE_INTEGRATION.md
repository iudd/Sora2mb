# Google Drive 上传集成说明

## 功能说明

当启用 Google Drive 上传功能后，视频生成完成的处理流程如下：

1. **Sora 生成视频** → 获取带水印的视频URL
2. **发布视频** → 获取 `post_id`
3. **第三方/自定义解析** → 获取无水印视频直链URL
4. **调用 Gradio API** → 将无水印URL上传到 Google Drive
5. **返回结果** → Google Drive 直链返回给用户

## 配置步骤

### 方法1: 环境变量配置（推荐）

设置环境变量：

```bash
export GOOGLE_DRIVE_ENABLED=true
export GOOGLE_DRIVE_PASSWORD="sk-123456"
```

### 方法2: 配置文件

编辑 `config/setting.toml`：

```toml
[google_drive]
enabled = true  # 启用 Google Drive 上传
space_url = "https://iyougame-url2drive.hf.space"
password = "sk-123456"  # 或通过环境变量设置
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

## 优先级

```
Google Drive 上传 > 本地缓存 > 直接使用无水印URL
```

当 `google_drive.enabled = true` 时，即使 `cache.enabled = true`，也会优先使用 Google Drive。
