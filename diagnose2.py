"""诊断2：带 stderr 捕获运行 itent.exe"""
import subprocess
import os
import sys
import tempfile

exe_path = r"C:\Users\人机\AppData\Local\Programs\itent\itent.exe"
work_dir = os.path.dirname(exe_path)

# 创建临时文件捕获输出
stdout_file = os.path.join(tempfile.gettempdir(), "itent_stdout.txt")
stderr_file = os.path.join(tempfile.gettempdir(), "itent_stderr.txt")

print("启动 itent.exe (5秒后自动终止)...")
print(f"工作目录: {work_dir}")
print()

try:
    with open(stdout_file, 'w') as f_out, open(stderr_file, 'w') as f_err:
        proc = subprocess.Popen(
            [exe_path],
            stdout=f_out,
            stderr=f_err,
            cwd=work_dir,
            env={**os.environ, "QT_DEBUG_PLUGINS": "1"}
        )
        
        # 等待5秒
        import time
        time.sleep(5)
        
        # 检查进程状态
        retcode = proc.poll()
        if retcode is None:
            print("进程仍在运行 (retcode=None) - 可能GUI已启动但窗口隐藏")
        else:
            print(f"进程已退出, 返回码: {retcode}")
        
        # 终止进程
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except:
            proc.kill()
        
        print(f"\n进程已终止")

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

# 读取输出
print("\n--- STDOUT ---")
try:
    with open(stdout_file, 'r') as f:
        content = f.read()
        if content.strip():
            print(content[:3000])
        else:
            print("(空)")
except:
    print("(无法读取)")

print("\n--- STDERR ---")
try:
    with open(stderr_file, 'r') as f:
        content = f.read()
        if content.strip():
            print(content[:5000])
        else:
            print("(空)")
except:
    print("(无法读取)")

# 检查是否有窗口可见
print("\n--- 检查窗口 ---")
try:
    import ctypes
    from ctypes import wintypes
    
    user32 = ctypes.windll.user32
    
    def enum_callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                # 获取进程ID
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if 'itent' in title.lower():
                    print(f"  [itent窗口] PID={pid.value}, 标题='{title}', 可见={user32.IsWindowVisible(hwnd)}")
        return True
    
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
except Exception as e:
    print(f"窗口检查失败: {e}")
