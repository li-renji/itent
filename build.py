#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NSIS 安装包生成脚本
由 打包.bat 自动调用，也可单独运行：python build.py
"""

import subprocess
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "itent"

def run(cmd, desc=""):
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"  命令: {cmd}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, cwd=BASE)
    if result.returncode != 0:
        print(f"\n[ERROR] {desc} 失败! 返回码: {result.returncode}")
        sys.exit(1)
    print(f"\n[OK] {desc} 完成")

# 打包前杀掉旧进程，避免文件被占用
print("[*] 杀掉旧 itent 进程...")
subprocess.run(['taskkill', '/F', '/IM', 'itent.exe'],
               capture_output=True, text=True)

# 检查 exe 是否存在
exe_path = os.path.join(BASE, "dist", APP_NAME, f"{APP_NAME}.exe")
if not os.path.exists(exe_path):
    print(f"[ERROR] 未找到 {exe_path}")
    print("  请先运行 打包.bat 或手动打包 exe")
    sys.exit(1)

size_mb = os.path.getsize(exe_path) / (1024*1024)
print(f"[OK] 找到 {APP_NAME}.exe ({size_mb:.1f} MB)")

# 删除旧安装包
for f in os.listdir(BASE):
    if f.endswith("_setup.exe"):
        os.remove(os.path.join(BASE, f))
        print(f"  已删除旧安装包: {f}")

# 查找 NSIS
nsis_paths = [
    r"C:\Program Files (x86)\NSIS\makensis.exe",
    r"C:\Program Files\NSIS\makensis.exe",
]
makensis = None
for p in nsis_paths:
    if os.path.exists(p):
        makensis = p
        break

if makensis:
    print(f"\n找到 NSIS: {makensis}")
    nsi_file = os.path.join(BASE, f"{APP_NAME}_installer.nsi")
    if not os.path.exists(nsi_file):
        print(f"[WARN] 未找到 {nsi_file}，跳过安装包生成")
        print(f"  如需生成安装包，请确保 {APP_NAME}_installer.nsi 存在")
        sys.exit(0)
    run(f'"{makensis}" "{nsi_file}"', "NSIS 生成安装包")
else:
    print("\n未找到 NSIS，跳过安装包生成")
    print("  如需生成安装包，请安装 NSIS: https://nsis.sourceforge.io/Download")
    print(f"  安装后重新运行: python build.py")
    sys.exit(0)

# 显示结果
setup_path = os.path.join(BASE, f"{APP_NAME}_setup.exe")
if os.path.exists(setup_path):
    size_mb = os.path.getsize(setup_path) / (1024*1024)
    print(f"\n{'='*60}")
    print(f"  安装包生成完成！")
    print(f"  文件: {setup_path}")
    print(f"  大小: {size_mb:.1f} MB")
    print(f"{'='*60}")
    print(f"\n  把 {APP_NAME}_setup.exe 发给别人就能安装了！")
else:
    print(f"\n[WARN] 未找到生成的安装包，请检查 NSIS 脚本")
