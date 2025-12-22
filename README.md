---
title: Sora2mb
emoji: 🎬
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# Sora2mb

OpenAI 兼容的 Sora API 服务

## 功能特性

- 🎬 支持 Sora 视频生成
- 🖼️ 支持图像生成
- 🔄 Token 管理和负载均衡
- 📊 管理后台界面
- 🐳 Docker 部署支持
- 🤗 HuggingFace Spaces 部署支持

## HuggingFace Spaces 部署

### 环境变量配置 (Secrets)

在 HuggingFace Spaces 的 Settings -> Repository secrets 中配置：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_KEY` | API 访问密钥 | `han1234` |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | `admin` |
| `SORA_BASE_URL` | Sora API 地址 | `https://sora.chatgpt.com/backend` |
| `SERVER_PORT` | 服务端口 | `7860` |
| `DEBUG_ENABLED` | 调试模式 | `false` |
| `CACHE_ENABLED` | 缓存开关 | `false` |
| `CACHE_TIMEOUT` | 缓存超时(秒) | `600` |
| `IMAGE_TIMEOUT` | 图像生成超时(秒) | `300` |
| `VIDEO_TIMEOUT` | 视频生成超时(秒) | `1500` |

### 数据持久化

数据库文件存储在 `/data/sora.db`，HuggingFace Spaces 会自动持久化 `/data` 目录。

## Docker 本地部署

```bash
docker-compose up -d
```

## API 使用

服务启动后访问：
- 管理后台: `http://your-domain/login`
- API 文档: `http://your-domain/docs`

## License

MIT License
