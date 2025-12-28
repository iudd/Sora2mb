"""测试流式输出是否正常工作"""
import requests
import json
import sys

# 配置
API_URL = "http://127.0.0.1:8000/v1/chat/completions"
API_KEY = "your_api_key_here"  # 替换为你的 API Key

def test_stream():
    """测试流式响应"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "sora-video-10s",
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": "一只可爱的猫咪在草地上玩耍"
            }
        ]
    }
    
    print("🚀 开始测试流式输出...")
    print(f"📡 请求 URL: {API_URL}")
    print(f"📦 请求数据: {json.dumps(data, ensure_ascii=False, indent=2)}\n")
    
    try:
        response = requests.post(
            API_URL,
            headers=headers,
            json=data,
            stream=True,  # 关键：启用流式接收
            timeout=600
        )
        
        print(f"✅ HTTP 状态码: {response.status_code}")
        print(f"📋 Content-Type: {response.headers.get('Content-Type')}\n")
        
        if response.status_code != 200:
            print(f"❌ 请求失败: {response.text}")
            return
        
        print("=" * 80)
        print("📨 开始接收流式数据...")
        print("=" * 80 + "\n")
        
        chunk_count = 0
        for line in response.iter_lines():
            if not line:
                continue
                
            line_str = line.decode('utf-8')
            
            # 跳过空行
            if not line_str.strip():
                continue
            
            chunk_count += 1
            print(f"[Chunk #{chunk_count}] {line_str[:100]}...")
            
            # 解析 SSE 数据
            if line_str.startswith('data: '):
                data_str = line_str[6:]  # 移除 "data: " 前缀
                
                if data_str == '[DONE]':
                    print("\n✅ 流式传输完成！")
                    break
                
                try:
                    obj = json.loads(data_str)
                    
                    # 提取关键信息
                    if 'choices' in obj and len(obj['choices']) > 0:
                        delta = obj['choices'][0].get('delta', {})
                        
                        # 进度信息
                        if 'progress' in delta:
                            progress = delta['progress'] * 100
                            print(f"  📊 进度: {progress:.1f}%")
                        
                        # 推理内容
                        if 'reasoning_content' in delta and delta['reasoning_content']:
                            rc = delta['reasoning_content'].strip()
                            print(f"  💭 推理: {rc[:80]}...")
                        
                        # 输出内容
                        if 'content' in delta and delta['content']:
                            content = delta['content'].strip()
                            print(f"  📄 内容: {content[:80]}...")
                        
                        # 输出 URL
                        if 'output' in delta and delta['output']:
                            for output in delta['output']:
                                if 'url' in output:
                                    print(f"  🔗 URL: {output['url']}")
                    
                    print()  # 空行分隔
                    
                except json.JSONDecodeError as e:
                    print(f"  ⚠️  JSON 解析失败: {e}")
                    print(f"  原始数据: {data_str[:200]}")
        
        print(f"\n📊 总共接收 {chunk_count} 个数据块")
        
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保服务器正在运行")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🧪 Sora2mb 流式输出测试工具")
    print("=" * 80 + "\n")
    
    # 检查是否提供了 API Key
    if len(sys.argv) > 1:
        API_KEY = sys.argv[1]
    
    if API_KEY == "your_api_key_here":
        print("⚠️  请先设置 API Key！")
        print("使用方法: python test_stream.py YOUR_API_KEY")
        print("或者直接修改脚本中的 API_KEY 变量\n")
        sys.exit(1)
    
    test_stream()
