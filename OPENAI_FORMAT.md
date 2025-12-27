# Sora2API OpenAI格式返回说明

## 📋 API返回格式

### 1. 流式返回（SSE格式）

当 `stream=true` 时，API返回Server-Sent Events格式：

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"sora-1.0","choices":[{"index":0,"delta":{"content":"🎬 开始生成视频..."},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"sora-1.0","choices":[{"index":0,"delta":{"content":"✅ 视频生成完成"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"sora-1.0","choices":[{"index":0,"delta":{"content":"📤 发布视频获取Post ID..."},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"sora-1.0","choices":[{"index":0,"delta":{"content":"🔗 解析无水印URL..."},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"sora-1.0","choices":[{"index":0,"delta":{"content":"☁️ 上传到Google Drive..."},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"sora-1.0","choices":[{"index":0,"delta":{"content":"https://drive.google.com/file/d/xxx/view"},"finish_reason":"stop"}]}

data: [DONE]
```

### 2. 非流式返回

当 `stream=false` 时，API返回标准JSON格式：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "sora-1.0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "https://drive.google.com/file/d/xxx/view"
      },
      "finish_reason": "stop"
    }
  ]
}
```

## 🔄 容错机制

### 多层回退策略

1. **Google Drive上传失败** → 回退到第三方CDN URL
2. **第三方解析失败** → 回退到OpenAI原始URL
3. **备用CDN失败** → 尝试下一个备用URL

### 流程图

```
视频生成成功
    ↓
发布获取Post ID
    ↓
第三方解析（3个备用URL）
    ├─ oscdn2.dyysy.com (主)
    ├─ oscdn.dyysy.com (备1)
    └─ oscdn3.dyysy.com (备2)
    ↓
Google Drive上传（可选）
    ├─ leeykike-url2drive.hf.space (主)
    └─ iyougame-url2drive.hf.space (备)
    ↓
    ├─ 成功 → 返回Google Drive URL
    └─ 失败 → 回退到CDN URL
    ↓
最终返回URL（保证有结果）
```

## 📤 实际返回示例

### 成功场景1：Google Drive上传成功

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1703664000,
  "model": "sora-1.0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "https://drive.google.com/file/d/1a2b3c4d5e6f7g8h9i0j/view"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### 成功场景2：Google Drive失败，回退到CDN

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1703664000,
  "model": "sora-1.0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "https://oscdn2.dyysy.com/MP4/s_694fb875ab6881919a4d70e090a87522.mp4"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### 成功场景3：第三方解析失败，回退到OpenAI

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1703664000,
  "model": "sora-1.0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "https://videos.openai.com/az/files/00000000-82cc-7285-bf93-f29e2b5d9ab8/raw?se=2026-01-01..."
      },
      "finish_reason": "stop"
    }
  ]
}
```

## 🎯 调用方接收建议

### JavaScript示例

```javascript
// 流式调用
const response = await fetch('/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_API_KEY',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    model: 'sora-1.0',
    messages: [{role: 'user', content: 'A cat playing piano'}],
    stream: true
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = line.slice(6);
      if (data === '[DONE]') {
        console.log('Stream completed');
        break;
      }
      
      const json = JSON.parse(data);
      const content = json.choices[0].delta?.content;
      if (content) {
        console.log('Progress:', content);
        // 更新UI显示进度
      }
    }
  }
}
```

### Python示例

```python
import requests

# 非流式调用
response = requests.post(
    'https://your-api.com/v1/chat/completions',
    headers={
        'Authorization': 'Bearer YOUR_API_KEY',
        'Content-Type': 'application/json'
    },
    json={
        'model': 'sora-1.0',
        'messages': [{'role': 'user', 'content': 'A cat playing piano'}],
        'stream': False
    }
)

result = response.json()
video_url = result['choices'][0]['message']['content']
print(f'Video URL: {video_url}')
```

## ⚙️ 系统配置

### 在管理后台配置

1. **无水印模式**：系统设置 → 无水印模式 → 启用
2. **Google Drive上传**：系统设置 → Google Drive → 启用/禁用
3. **解析方式**：第三方解析（默认）或自定义解析

### 环境变量

```bash
# Google Drive上传密码（可选）
GOOGLE_DRIVE_PASSWORD=your_password

# JSONBin同步（可选）
JSONBIN_BIN_ID=your_bin_id
JSONBIN_MASTER_KEY=your_master_key
```

## 🔍 故障排查

### 1. Google Drive上传失败

**现象**：返回CDN URL而不是Google Drive URL

**原因**：
- url2drive服务的OAuth token过期
- 网络连接问题
- 服务不可用

**解决**：
- 系统会自动回退到CDN URL，不影响使用
- 联系url2drive服务管理员更新OAuth token
- 或暂时禁用Google Drive上传

### 2. 第三方解析失败

**现象**：返回OpenAI原始URL

**原因**：
- CDN服务暂时不可用
- 视频还未同步到CDN

**解决**：
- 系统会自动回退到OpenAI URL
- OpenAI URL同样可以下载视频

### 3. 视频生成失败

**现象**：返回错误信息

**原因**：
- Token额度不足
- 提示词违规
- 网络问题

**解决**：
- 检查Token状态
- 修改提示词
- 重试请求

## 📊 完整的容错保证

✅ **保证1**：只要视频生成成功，必定返回可用的URL  
✅ **保证2**：多层回退机制确保高可用性  
✅ **保证3**：流式输出让用户实时了解进度  
✅ **保证4**：符合OpenAI标准格式，易于集成  

---

**最后更新**：2025-12-27
