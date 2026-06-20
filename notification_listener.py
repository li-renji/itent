#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# notification_listener.py - Windows 通知拦截 + 窗口监控
# ============================================================
# 功能：
#   1. 通过 Windows.UI.Notifications COM 接口监听 Toast 通知
#   2. 定时轮询 EnumWindows 监控窗口标题变化
#   3. 将通知聚合到 itent 的统一通知中心
# ============================================================

import ctypes
import ctypes.wintypes
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, field

# ============================================================
# 数据模型
# ============================================================

@dataclass
class Notification:
    """统一通知对象"""
    app_name: str          # 来源软件名
    app_icon: str = ""     # 软件图标路径（.png 缓存）
    title: str = ""        # 通知标题
    body: str = ""         # 通知内容
    timestamp: float = 0.0 # 时间戳
    source: str = "window" # window / toast / system
    pid: int = 0           # 来源进程 PID
    raw_data: Dict = field(default_factory=dict)


# ============================================================
# WindowMonitor - 窗口标题变化监控
# ============================================================
class WindowMonitor(threading.Thread):
    """
    定时轮询 EnumWindows，监控目标软件窗口标题变化。
    标题变化 → 产生通知事件。
    """

    def __init__(self, target_processes: Dict[str, List[str]],
                 on_notification: Callable[[Notification], None],
                 interval: float = 1.5):
        """
        Args:
            target_processes: {app_name: [process_name1, process_name2]}
            on_notification: 通知回调
            interval: 轮询间隔（秒）
        """
        super().__init__(daemon=True)
        self.target_processes = target_processes
        self.on_notification = on_notification
        self.interval = interval
        self._running = True
        self._known_titles: Dict[int, str] = {}  # hwnd -> last_title
        self._pid_cache: Dict[int, str] = {}     # pid -> app_name

    def run(self):
        while self._running:
            try:
                self._poll_windows()
            except Exception:
                pass
            time.sleep(self.interval)

    def stop(self):
        self._running = False

    def _poll_windows(self):
        """轮询所有可见窗口"""
        import psutil

        windows = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
        def enum_proc(hwnd, lParam):
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            pid = ctypes.c_int()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title and len(title.strip()) > 1:
                windows.append((hwnd, pid.value, title.strip()))
            return True

        ctypes.windll.user32.EnumWindows(enum_proc, 0)

        for hwnd, pid, title in windows:
            app_name = self._get_app_name_for_pid(pid)
            if not app_name:
                continue

            last_title = self._known_titles.get(hwnd, "")
            if title != last_title:
                self._known_titles[hwnd] = title
                # 窗口标题变化 → 产生通知
                if last_title:  # 不是首次发现
                    self.on_notification(Notification(
                        app_name=app_name,
                        title=f"{app_name} 窗口更新",
                        body=title[:200],  # 截断过长标题
                        timestamp=time.time(),
                        source="window",
                        pid=pid,
                    ))

    def _get_app_name_for_pid(self, pid: int) -> Optional[str]:
        """通过 PID 查找对应的 app_name"""
        if pid in self._pid_cache:
            return self._pid_cache[pid]
        try:
            import psutil
            p = psutil.Process(pid)
            proc_name = p.name().lower()
            for app_name, proc_list in self.target_processes.items():
                if any(pn.lower() == proc_name for pn in proc_list):
                    self._pid_cache[pid] = app_name
                    return app_name
        except Exception:
            pass
        return None


# ============================================================
# ToastListener - Windows Toast 通知监听
# ============================================================
class ToastListener(threading.Thread):
    """
    通过轮询 Windows 通知缓存来获取 Toast 通知。
    
    由于原生 COM API 需要 WinRT 绑定（较为复杂），
    这里采用简化方案：监控 Toast 通知相关的注册表/文件变化。
    
    备用方案：轮询 %LocalAppData%\\Microsoft\\Windows\\Notifications
    下的 wpndatabase.db（需要 ESE 数据库读取）。
    
    简化 v1 方案：通过进程窗口标题变化 + Toast 窗口类检测。
    """

    def __init__(self, target_processes: Dict[str, List[str]],
                 on_notification: Callable[[Notification], None],
                 interval: float = 2.0):
        super().__init__(daemon=True)
        self.target_processes = target_processes
        self.on_notification = on_notification
        self.interval = interval
        self._running = True
        self._seen_notifications: set = set()  # 去重

    def run(self):
        while self._running:
            try:
                self._check_toast_windows()
            except Exception:
                pass
            time.sleep(self.interval)

    def stop(self):
        self._running = False

    def _check_toast_windows(self):
        """
        检测 Windows Toast 通知窗口。
        Toast 通知窗口特征：类名通常是 Windows.UI.Core.CoreWindow
        或者 ApplicationFrameWindow，且有特定标题。
        """
        import psutil

        toast_windows = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
        def enum_proc(hwnd, lParam):
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True

            # 获取窗口类名
            class_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, class_buf, 256)
            class_name = class_buf.value or ""

            # Toast 通知窗口特征
            toast_classes = [
                "Windows.UI.Core.CoreWindow",
                "ApplicationFrameWindow",
                "ToastWindow",
                "NotificationWindow",
                "Shell_TrayWnd",  # 操作中心相关
            ]

            is_toast = any(tc.lower() in class_name.lower() for tc in toast_classes)

            # 也检测小窗口（通知通常较小）
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top

            if is_toast or (w < 400 and h < 300 and w > 100):
                pid = ctypes.c_int()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value or ""

                if title.strip() or is_toast:
                    toast_windows.append((hwnd, pid.value, title.strip(), class_name))

            return True

        ctypes.windll.user32.EnumWindows(enum_proc, 0)

        for hwnd, pid, title, class_name in toast_windows:
            app_name = self._find_app_for_pid(pid)
            if not app_name:
                continue

            # 去重
            key = f"{app_name}:{title}"
            if key in self._seen_notifications:
                continue
            self._seen_notifications.add(key)

            # 限制缓存大小
            if len(self._seen_notifications) > 500:
                self._seen_notifications.clear()

            body = title if title else f"{app_name} 推送了一条通知"
            self.on_notification(Notification(
                app_name=app_name,
                title=f"{app_name} 通知",
                body=body[:200],
                timestamp=time.time(),
                source="toast",
                pid=pid,
                raw_data={"window_class": class_name, "hwnd": hwnd},
            ))

    def _find_app_for_pid(self, pid: int) -> Optional[str]:
        try:
            import psutil
            p = psutil.Process(pid)
            proc_name = p.name().lower()
            for app_name, proc_list in self.target_processes.items():
                if any(pn.lower() == proc_name for pn in proc_list):
                    return app_name
        except Exception:
            pass
        return None


# ============================================================
# NotificationHub - 通知聚合中心
# ============================================================
class NotificationHub:
    """
    统一通知中心：管理 WindowMonitor 和 ToastListener，
    将通知聚合后发送到 GUI。
    """

    MAX_NOTIFICATIONS = 200

    def __init__(self, on_notification: Callable[[Notification], None]):
        self.on_notification = on_notification
        self._notifications: List[Notification] = []
        self._lock = threading.Lock()
        self._monitor: Optional[WindowMonitor] = None
        self._toast: Optional[ToastListener] = None

    def start(self, target_processes: Dict[str, List[str]]):
        """启动通知监听"""
        self._monitor = WindowMonitor(target_processes, self._on_notify)
        self._toast = ToastListener(target_processes, self._on_notify)
        self._monitor.start()
        self._toast.start()

    def stop(self):
        """停止通知监听"""
        if self._monitor:
            self._monitor.stop()
        if self._toast:
            self._toast.stop()

    def _on_notify(self, notification: Notification):
        """内部通知回调"""
        with self._lock:
            self._notifications.append(notification)
            if len(self._notifications) > self.MAX_NOTIFICATIONS:
                self._notifications = self._notifications[-self.MAX_NOTIFICATIONS:]
        self.on_notification(notification)

    def get_notifications(self, app_name: str = None, limit: int = 50) -> List[Notification]:
        """获取通知列表，可按软件筛选"""
        with self._lock:
            items = self._notifications[:]
        if app_name:
            items = [n for n in items if n.app_name == app_name]
        return items[-limit:]

    def get_recent_notifications(self, limit: int = 20) -> List[Notification]:
        """获取最近的通知"""
        with self._lock:
            return self._notifications[-limit:]

    def clear(self):
        with self._lock:
            self._notifications.clear()
