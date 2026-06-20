#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# process_manager.py - 系统级进程墓碑管理器
# ============================================================
# 负责：枚举系统所有进程、核心进程保护、挂起/恢复
# ============================================================

import ctypes
import ctypes.wintypes
import psutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ============================================================
# 核心系统进程保护列表
# ============================================================
CORE_PROCESSES = {
    # Windows 核心进程（绝对不能挂起）
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "dwm.exe",
    "winlogon.exe",
    "system",
    "idle",
    "ntoskrnl.exe",
    "ntfs.sys",
    "kernel32.dll",
    # 桌面窗口管理器
    "explorer.exe",
    # itent 自身
    "itent.exe",
    "python.exe",
    "pythonw.exe",
    # 安全软件（避免冲突）
    "msmpeng.exe",      # Windows Defender
    "windefend.exe",
    "securityhealthservice.exe",
}

# 核心进程关键字（部分匹配）
CORE_PROCESS_KEYWORDS = {
    "windows.internal.",
    "systemsettings",
    "sihost.exe",
    "ctfmon.exe",
    "taskhostw.exe",
    "dllhost.exe",
    "smss.exe",
}


# ============================================================
# Win32 底层绑定
# ============================================================
_ntdll = ctypes.windll.ntdll if hasattr(ctypes.windll, "ntdll") else None


def _NtSuspendProcess(hProcess: int) -> int:
    """返回 NTSTATUS，0=成功"""
    try:
        func = _ntdll.NtSuspendProcess
        func.argtypes = [ctypes.c_void_p]
        func.restype = ctypes.c_long
        return func(hProcess)
    except Exception:
        return -1


def _NtResumeProcess(hProcess: int) -> int:
    try:
        func = _ntdll.NtResumeProcess
        func.argtypes = [ctypes.c_void_p]
        func.restype = ctypes.c_long
        return func(hProcess)
    except Exception:
        return -1


def _empty_working_set(pid: int) -> bool:
    """调用 EmptyWorkingSet 清空进程工作集，强制内存换出到页面文件"""
    try:
        psapi = ctypes.windll.psapi
        func = psapi.EmptyWorkingSet
        func.argtypes = [ctypes.c_void_p]
        func.restype = ctypes.c_int
        hProcess = ctypes.windll.kernel32.OpenProcess(0x001F0FFF, False, pid)
        if not hProcess:
            return False
        ret = func(hProcess)
        ctypes.windll.kernel32.CloseHandle(hProcess)
        return ret != 0
    except Exception:
        return False


def _is_core_process(name: str) -> bool:
    """判断进程名是否为核心系统进程"""
    n = name.lower().strip()
    if n in CORE_PROCESSES:
        return True
    for kw in CORE_PROCESS_KEYWORDS:
        if kw in n:
            return True
    return False


# ============================================================
# SystemProcessMonitor - 系统进程监控线程
# ============================================================
class SystemProcessMonitor(threading.Thread):
    """
    后台线程：定期扫描目标软件进程，
    发现新进程自动纳入管理，退出进程自动清理。
    """

    def __init__(self, on_new_process: callable, on_process_exit: callable,
                 target_proc_names: set = None, interval: float = 3.0):
        """
        Args:
            on_new_process: 回调 (pid, name) -> None
            on_process_exit: 回调 (pid) -> None
            target_proc_names: 目标进程名集合（小写），只管理这些进程
            interval: 扫描间隔（秒）
        """
        super().__init__(daemon=True)
        self.on_new_process = on_new_process
        self.on_process_exit = on_process_exit
        self.interval = interval
        self._running = True
        self._known_pids: Dict[int, str] = {}  # pid -> name
        self._target_proc_names = target_proc_names or set()

    def set_target_procs(self, proc_names: set):
        """动态更新目标进程名列表"""
        self._target_proc_names = {n.lower() for n in proc_names}

    def run(self):
        while self._running:
            try:
                current = {}
                for p in psutil.process_iter(attrs=["pid", "name"]):
                    try:
                        pid = p.info["pid"]
                        name = (p.info["name"] or "").lower()
                        # 只关注目标进程 + 核心进程（用于保护）
                        if name in self._target_proc_names:
                            current[pid] = name
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # 发现新进程
                for pid, name in current.items():
                    if pid not in self._known_pids:
                        self.on_new_process(pid, name)

                # 发现退出进程
                for pid in list(self._known_pids.keys()):
                    if pid not in current:
                        self.on_process_exit(pid)

                self._known_pids = current
            except Exception:
                pass

            time.sleep(self.interval)

    def stop(self):
        self._running = False


# ============================================================
# SystemProcessManager - 系统级进程管理器
# ============================================================
class SystemProcessManager:
    """
    系统级进程墓碑管理器：
    - 扫描并管理所有非核心进程
    - 智能挂起/恢复进程（保留UI线程）
    - 维护墓碑状态
    """

    # 智能墓碑模式：只挂起非UI线程，保留UI线程响应
    SMART_SUSPEND = True

    def __init__(self, whitelist: Set[str]):
        """
        Args:
            whitelist: 白名单进程名集合（小写）
        """
        self.whitelist = whitelist
        self._suspended: Dict[int, float] = {}     # pid -> 挂起时间戳
        self._suspended_threads: Dict[int, List[int]] = {}  # pid -> [已挂起的线程ID列表]
        self._transient_wake: Dict[int, float] = {} # pid -> 唤醒过期时间戳
        self._managed_pids: Dict[int, str] = {}     # pid -> name
        self._lock = threading.Lock()

    def is_core_process(self, pid: int) -> bool:
        """判断 PID 是否为核心进程"""
        try:
            name = psutil.Process(pid).name().lower()
            return _is_core_process(name)
        except Exception:
            return True  # 无法访问的进程当作核心进程保护

    def is_whitelisted(self, pid: int) -> bool:
        """判断 PID 是否在白名单中"""
        try:
            p = psutil.Process(pid)
            name = p.name().lower()
            exe = (p.exe() or "").lower()
            return name in self.whitelist or exe in self.whitelist
        except Exception:
            return False

    def can_suspend(self, pid: int) -> bool:
        """判断进程是否可以被挂起"""
        if pid <= 0:
            return False
        if pid in self._suspended:
            return False  # 已挂起
        if self.is_core_process(pid):
            return False
        if self.is_whitelisted(pid):
            return False
        # 检查进程是否还存在
        try:
            psutil.Process(pid)
            return True
        except Exception:
            return False

    def suspend(self, pid: int) -> bool:
        """智能挂起进程（保留UI线程响应）。返回是否成功。"""
        if not self.can_suspend(pid):
            return False
        try:
            if self.SMART_SUSPEND:
                return self._smart_suspend(pid)
            else:
                return self._full_suspend(pid)
        except Exception:
            return False

    def _full_suspend(self, pid: int) -> bool:
        """完整挂起进程（旧逻辑，会卡UI）"""
        try:
            hProcess = ctypes.windll.kernel32.OpenProcess(0x001F0FFF, False, pid)
            if not hProcess:
                return False
            status = _NtSuspendProcess(hProcess)
            if status == 0:
                _empty_working_set(pid)
                with self._lock:
                    self._suspended[pid] = time.time()
                ctypes.windll.kernel32.CloseHandle(hProcess)
                return True
            else:
                ctypes.windll.kernel32.CloseHandle(hProcess)
                return self._suspend_by_threads(pid)
        except Exception:
            return False

    def _smart_suspend(self, pid: int) -> bool:
        """
        智能挂起：识别并保留 UI 线程，只挂起工作线程。
        策略：
        1. 找出进程的所有线程
        2. 识别 UI 线程（通常是创建了窗口的线程，或线程ID最小的线程）
        3. 只挂起非 UI 线程
        4. 释放内存
        """
        THREAD_SUSPEND_RESUME = 0x0002
        THREAD_QUERY_INFORMATION = 0x0040
        try:
            p = psutil.Process(pid)
            threads = list(p.threads())
            if not threads:
                return False

            # 识别 UI 线程
            main_tid = self._get_main_thread_id(pid, threads)
            suspended_tids = []

            for t in threads:
                tid = t.id
                # 跳过 UI 线程（保留界面响应）
                if tid == main_tid:
                    continue

                access = THREAD_SUSPEND_RESUME | THREAD_QUERY_INFORMATION
                hThread = ctypes.windll.kernel32.OpenThread(access, False, tid)
                if hThread:
                    ret = ctypes.windll.kernel32.SuspendThread(hThread)
                    if ret != -1:  # SuspendThread 返回之前的挂起计数，-1 表示失败
                        suspended_tids.append(tid)
                    ctypes.windll.kernel32.CloseHandle(hThread)

            if suspended_tids:
                # 释放内存到页面文件
                _empty_working_set(pid)
                with self._lock:
                    self._suspended[pid] = time.time()
                    self._suspended_threads[pid] = suspended_tids
                return True
            else:
                # 没有可挂起的工作线程（只有UI线程），退化为完整挂起
                return self._full_suspend(pid)

        except Exception:
            return False

    def _get_main_thread_id(self, pid: int, threads: list) -> int:
        """
        识别进程的 UI（主）线程。
        优先级：
        1. 拥有窗口的线程
        2. 线程 ID 最小的线程（通常是主线程）
        """
        # 方法1：通过 EnumThreadWindows 找到有窗口的线程
        gui_tids = set()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
        def enum_thread_wnd(hwnd, lParam):
            tid = ctypes.c_int()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(tid))
            pid_out = ctypes.c_int()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
            if pid_out.value == pid:
                gui_tids.add(tid.value)
            return True

        try:
            ctypes.windll.user32.EnumWindows(enum_thread_wnd, 0)
        except Exception:
            pass

        # 如果有 GUI 线程，返回第一个
        if gui_tids:
            # 返回最小的 GUI 线程 ID（通常是主线程）
            return min(gui_tids)

        # 方法2：返回线程 ID 最小的线程（通常是主线程）
        if threads:
            return min(t.id for t in threads)

        return 0

    def _suspend_by_threads(self, pid: int) -> bool:
        """回退方案：逐个挂起所有线程（旧逻辑，会卡UI）"""
        try:
            THREAD_SUSPEND_RESUME = 0x0002
            p = psutil.Process(pid)
            for t in p.threads():
                hThread = ctypes.windll.kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, t.id)
                if hThread:
                    ctypes.windll.kernel32.SuspendThread(hThread)
                    ctypes.windll.kernel32.CloseHandle(hThread)
            _empty_working_set(pid)
            with self._lock:
                self._suspended[pid] = time.time()
            return True
        except Exception:
            return False

    def resume(self, pid: int) -> bool:
        """智能恢复进程。返回是否成功。"""
        if pid <= 0:
            return False
        try:
            with self._lock:
                suspended_tids = self._suspended_threads.pop(pid, None)

            if suspended_tids:
                # 精准恢复：只恢复我们挂起的线程
                return self._smart_resume(pid, suspended_tids)
            else:
                # 回退：完整恢复
                return self._full_resume(pid)
        except Exception:
            return False

    def _smart_resume(self, pid: int, suspended_tids: List[int]) -> bool:
        """精准恢复之前挂起的工作线程"""
        THREAD_SUSPEND_RESUME = 0x0002
        try:
            success_count = 0
            for tid in suspended_tids:
                hThread = ctypes.windll.kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
                if hThread:
                    ret = ctypes.windll.kernel32.ResumeThread(hThread)
                    if ret != -1:
                        success_count += 1
                    ctypes.windll.kernel32.CloseHandle(hThread)

            with self._lock:
                self._suspended.pop(pid, None)
                self._transient_wake.pop(pid, None)

            return success_count > 0
        except Exception:
            return False

    def _full_resume(self, pid: int) -> bool:
        """完整恢复进程（旧逻辑）"""
        try:
            hProcess = ctypes.windll.kernel32.OpenProcess(0x001F0FFF, False, pid)
            if not hProcess:
                return False
            status = _NtResumeProcess(hProcess)
            if status == 0:
                with self._lock:
                    self._suspended.pop(pid, None)
                    self._transient_wake.pop(pid, None)
                ctypes.windll.kernel32.CloseHandle(hProcess)
                return True
            else:
                ctypes.windll.kernel32.CloseHandle(hProcess)
                return self._resume_by_threads(pid)
        except Exception:
            return False

    def _resume_by_threads(self, pid: int) -> bool:
        try:
            THREAD_SUSPEND_RESUME = 0x0002
            p = psutil.Process(pid)
            for t in p.threads():
                hThread = ctypes.windll.kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, t.id)
                if hThread:
                    ctypes.windll.kernel32.ResumeThread(hThread)
                    ctypes.windll.kernel32.CloseHandle(hThread)
            with self._lock:
                self._suspended.pop(pid, None)
                self._transient_wake.pop(pid, None)
            return True
        except Exception:
            return False

    def suspend_all_except(self, active_pids: List[int]):
        """挂起所有非 active_pids 的管理进程"""
        with self._lock:
            suspended_copy = dict(self._suspended)
            managed_copy = dict(self._managed_pids)

        for pid in list(managed_copy.keys()):
            if pid in active_pids:
                if pid in self._suspended:
                    self.resume(pid)
                continue
            if pid not in self._suspended and self.can_suspend(pid):
                self.suspend(pid)

    def set_transient_wake(self, pid: int, duration_sec: float):
        """设置进程短暂唤醒，duration_sec 秒后自动允许墓碑"""
        with self._lock:
            self._transient_wake[pid] = time.time() + duration_sec
        # 确保进程是恢复状态
        if pid in self._suspended:
            self.resume(pid)

    def check_transient_wake_expiry(self):
        """检查短暂唤醒是否过期，过期则清除标记"""
        now = time.time()
        expired = []
        with self._lock:
            for pid, expiry in self._transient_wake.items():
                if now >= expiry:
                    expired.append(pid)
            for pid in expired:
                del self._transient_wake[pid]
        return expired

    def get_process_info(self, pid: int) -> Optional[Dict]:
        """获取进程信息"""
        try:
            p = psutil.Process(pid)
            cpu = p.cpu_percent(interval=0.05)
            mem = p.memory_info().rss / (1024 * 1024)
            status = "suspended" if pid in self._suspended else "running"
            if pid in self._transient_wake:
                status = "transient_wake"
            if self.is_core_process(pid):
                status = "protected"
            if self.is_whitelisted(pid):
                status = "whitelisted"
            return {
                "pid": pid,
                "name": p.name(),
                "cpu": cpu,
                "mem_mb": mem,
                "status": status,
            }
        except Exception:
            return None

    def get_all_managed_pids(self) -> List[int]:
        """返回所有被管理的 PID 列表"""
        with self._lock:
            return list(self._managed_pids.keys())

    def add_managed_pid(self, pid: int, name: str):
        """添加一个被管理的 PID"""
        with self._lock:
            self._managed_pids[pid] = name

    def remove_managed_pid(self, pid: int):
        """移除一个被管理的 PID"""
        with self._lock:
            self._managed_pids.pop(pid, None)
            self._suspended.pop(pid, None)
            self._suspended_threads.pop(pid, None)
            self._transient_wake.pop(pid, None)

    def is_suspended(self, pid: int) -> bool:
        """检查进程是否已挂起"""
        with self._lock:
            return pid in self._suspended

    def is_transient_wake(self, pid: int) -> bool:
        """检查进程是否处于短暂唤醒状态"""
        with self._lock:
            return pid in self._transient_wake

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            total = len(self._managed_pids)
            suspended = len(self._suspended)
            wake = len(self._transient_wake)
        return {
            "total": total,
            "suspended": suspended,
            "transient_wake": wake,
            "active": total - suspended,
        }
