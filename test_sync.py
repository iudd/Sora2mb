import requests
import json
import sys

# === 配置 ===
URL = "http://127.0.0.1:7860/v1/videos/sync"
KEY = "han1234"

def test_sync():
    print(f"🚀 发送同步请求到: {URL}")
    
    try:
        response = requests.post(
            URL,
            headers={"Authorization": f"Bearer {KEY}"},
            json={
                "limit": 1,  # 只同步最新的一条
                "stream": True
            },
            stream=True
        )

        if response.status_code != 200:
            print(f"❌ 请求失败: {response.status_code}\n{response.text}")
            return

        print("✅ 连接成功，正在同步...\n" + "-"*30)

        # 处理流式输出
        for line in response.iter_lines():
            if not line: continue
            
            line_text = line.decode('utf-8').replace('data: ', '').strip()
            
            if line_text == '' or line_text == '[DONE]':
                print("-" * 30 + "\n🏁 同步结束")
                break
                
            try:
                data = json.loads(line_text)
                delta = data['choices'][0]['delta']
                
                if 'reasoning_content' in delta and delta['reasoning_content']:
                    print(f"🔄 {delta['reasoning_content'].strip()}")
                
                if 'content' in delta and delta['content']:
                    print(f"\n🎉 结果:\n{delta['content']}")
                    
            except json.JSONDecodeError:
                pass

    except Exception as e:
        print(f"❌ 发生错误: {e}")

if __name__ == "__main__":
    test_sync()
