"""诊断 itent 启动问题"""
import subprocess
import os
import sys
import traceback

exe_path = r"C:\Users\人机\AppData\Local\Programs\itent\itent.exe"

print("=" * 60)
print("itent 启动诊断工具")
print("=" * 60)

# 1. 检查 exe 存在
if not os.path.exists(exe_path):
    print(f"[ERROR] itent.exe 不存在: {exe_path}")
    sys.exit(1)
print(f"[OK] itent.exe 存在")

# 2. 检查 _internal 目录
internal_dir = os.path.join(os.path.dirname(exe_path), "_internal")
if os.path.exists(internal_dir):
    pyside = os.path.join(internal_dir, "PySide6")
    qt_bin = os.path.join(pyside, "Qt", "bin") if os.path.exists(pyside) else ""
    if os.path.exists(qt_bin):
        print(f"[OK] Qt binaries 目录存在")
    else:
        print(f"[WARN] Qt binaries 可能缺失: {qt_bin}")
else:
    print(f"[ERROR] _internal 目录不存在!")

# 3. 尝试带输出运行（捕获错误）
print("\n正在尝试启动 itent.exe 并捕获错误...")
print("-" * 40)

try:
    # 用 subprocess 运行，捕获 stderr
    result = subprocess.run(
        [exe_path],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONFAULTHANDLER": "1"}
    )
    print(f"返回码: {result.returncode}")
    if result.stdout:
        print(f"STDOUT:\n{result.stdout[:2000]}")
    if result.stderr:
        print(f"STDERR:\n{result.stderr[:2000]}")
except subprocess.TimeoutExpired:
    print("[OK] itent.exe 在 10 秒内未退出，说明 GUI 可能已启动")
except FileNotFoundError:
    print(f"[ERROR] 找不到 itent.exe")
except Exception as e:
    print(f"[ERROR] 启动异常: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("诊断完成")
