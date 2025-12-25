import re
from pathlib import Path

file_path = Path("src/services/generation_handler.py")

try:
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    inside_handle_gen = False
    
    print("正在检查 indentation...")
    
    for i, line in enumerate(lines):
        # 强制修复 handle_generation 的缩进
        if "async def handle_generation(" in line:
            print(f"Found handle_generation at line {i+1}")
            stripped = line.lstrip()
            # 类的方法应该是 4 个空格缩进
            new_lines.append("    " + stripped)
            inside_handle_gen = True
            continue
            
        # 如果在 handle_generation 内部，且之前缩进有问题，可能需要调整
        # 这里主要确保定义行是对的，通常这就够了，除非整块代码缩进都错了
        
        # 检查上一个方法 check_token_availability 是否结束正确
        if "def check_token_availability" in line:
             print(f"Found check_token_availability at line {i+1}")

        new_lines.append(line)

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    
    print("✅ 修复完成：已强制重置 handle_generation 的缩进。")

except Exception as e:
    print(f"❌ 修复失败: {e}")
