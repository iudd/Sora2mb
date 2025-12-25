import re
import sys

def fix_indentation():
    file_path = "src/services/generation_handler.py"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        fixed_lines = []
        in_check_token = False
        
        print(f"Checking {file_path} for indentation issues...")
        
        for i, line in enumerate(lines):
            # 找到 check_token_availability 方法
            if "def check_token_availability" in line:
                in_check_token = True
                fixed_lines.append(line)
                continue
                
            # 找到 handle_generation 方法
            if "async def handle_generation" in line:
                # 检查当前缩进
                current_indent = len(line) - len(line.lstrip())
                if current_indent > 4:
                    print(f"⚠️ Found incorrect indentation at line {i+1}: {current_indent} spaces. Fixing to 4 spaces.")
                    # 强制修复为 4 个空格缩进（类的层级）
                    line = "    " + line.lstrip()
                in_check_token = False  # 退出上一个方法的范围
            
            fixed_lines.append(line)
            
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)
            
        print("✅ Indentation fix applied successfully.")
        
    except Exception as e:
        print(f"❌ Error fixing file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    fix_indentation()
