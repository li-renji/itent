"""最小启动测试——验证 PyInstaller 打包后 Qt 能否正常加载"""
import sys, os, traceback

print("[TEST] 开始测试...", flush=True)

# 1. 测试 Qt 导入
print("[TEST] 导入 PySide6...", flush=True)
try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QLabel
    from PySide6.QtCore import Qt
    print("[TEST] PySide6 导入成功", flush=True)
except Exception as e:
    print(f"[TEST] PySide6 导入失败: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

# 2. 测试 QApplication 创建
print("[TEST] 创建 QApplication...", flush=True)
try:
    app = QApplication(sys.argv)
    print("[TEST] QApplication 创建成功", flush=True)
except Exception as e:
    print(f"[TEST] QApplication 创建失败: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

# 3. 测试窗口创建
print("[TEST] 创建窗口...", flush=True)
try:
    win = QMainWindow()
    win.setWindowTitle("itent 启动测试")
    label = QLabel("启动成功！", win)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.setCentralWidget(label)
    win.resize(400, 200)
    print("[TEST] 窗口创建成功", flush=True)
except Exception as e:
    print(f"[TEST] 窗口创建失败: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

# 4. 显示并退出
print("[TEST] 显示窗口...", flush=True)
win.show()
print("[TEST] 一切正常！3秒后退出...", flush=True)
from PySide6.QtCore import QTimer
QTimer.singleShot(3000, app.quit)
app.exec()
print("[TEST] 测试完成", flush=True)
