"""
Google Drive Token 获取工具
简单的本地脚本，自动处理OAuth授权
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import webbrowser
import json
import requests

# 配置
CLIENT_ID = input("请输入你的Client ID: ").strip()
CLIENT_SECRET = input("请输入你的Client Secret: ").strip()

REDIRECT_URI = "http://localhost:8080"
SCOPES = "https://www.googleapis.com/auth/drive.file"

# 全局变量存储授权码
auth_code = None

class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        
        # 解析URL参数
        query = urlparse(self.path).query
        params = parse_qs(query)
        
        if 'code' in params:
            auth_code = params['code'][0]
            
            # 返回成功页面
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>授权成功</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    }
                    .container {
                        background: white;
                        padding: 40px;
                        border-radius: 10px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                        text-align: center;
                    }
                    h1 { color: #28a745; }
                    p { color: #666; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>✅ 授权成功！</h1>
                    <p>你可以关闭这个窗口了</p>
                    <p>请返回终端查看Token信息</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode())
        else:
            self.send_response(400)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # 禁用日志输出

def get_refresh_token():
    global auth_code
    
    print("\n🚀 启动本地服务器...")
    print(f"📍 重定向URI: {REDIRECT_URI}")
    
    # 构建授权URL
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={SCOPES}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    
    print("\n🌐 正在打开浏览器...")
    print("如果浏览器没有自动打开，请手动访问以下链接：")
    print(auth_url)
    
    # 打开浏览器
    webbrowser.open(auth_url)
    
    # 启动本地服务器接收回调
    server = HTTPServer(('localhost', 8080), OAuthHandler)
    print("\n⏳ 等待授权...")
    
    while auth_code is None:
        server.handle_request()
    
    print("\n✅ 收到授权码！")
    
    # 交换授权码获取token
    print("🔄 正在获取Refresh Token...")
    
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, data=data)
    
    if response.status_code == 200:
        tokens = response.json()
        
        print("\n" + "="*60)
        print("✅ 成功获取Token！")
        print("="*60)
        print("\n📋 Refresh Token:")
        print(tokens.get('refresh_token', '未获取到refresh_token'))
        print("\n📋 Access Token:")
        print(tokens.get('access_token', ''))
        print("\n" + "="*60)
        print("\n💾 环境变量配置：")
        print("="*60)
        print(f"GOOGLE_DRIVE_CLIENT_ID={CLIENT_ID}")
        print(f"GOOGLE_DRIVE_CLIENT_SECRET={CLIENT_SECRET}")
        print(f"GOOGLE_DRIVE_REFRESH_TOKEN={tokens.get('refresh_token', '')}")
        print("="*60)
        
        # 保存到文件
        config = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': tokens.get('refresh_token'),
            'access_token': tokens.get('access_token')
        }
        
        with open('google_drive_config.json', 'w') as f:
            json.dump(config, f, indent=2)
        
        print("\n✅ 配置已保存到 google_drive_config.json")
        
    else:
        print(f"\n❌ 获取Token失败: {response.status_code}")
        print(response.text)

if __name__ == '__main__':
    print("="*60)
    print("Google Drive Token 获取工具")
    print("="*60)
    print("\n⚠️  重要提示：")
    print("在Google Cloud Console中，请确保OAuth客户端的")
    print("'已获授权的重定向 URI' 包含：")
    print("  http://localhost:8080")
    print("\n如果还没添加，请先添加后再继续！")
    print("="*60)
    
    input("\n按回车键继续...")
    
    try:
        get_refresh_token()
    except KeyboardInterrupt:
        print("\n\n❌ 已取消")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
