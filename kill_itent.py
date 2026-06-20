"""终止所有 itent.exe 进程"""
import os, signal, subprocess

result = subprocess.run(
    ['taskkill', '/F', '/IM', 'itent.exe'],
    capture_output=True, text=True
)
print(result.stdout)
print(result.stderr)
print("Done - all itent processes killed")
