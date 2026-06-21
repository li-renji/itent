#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# main.py - itent 墓碑后台管理器（聊天窗口式界面）
# ============================================================
# 功能：
#   左侧：软件列表（图标 + 名称 + 状态 + 内存）
#   右侧：通知中心 / AI 对话 / 进程详情
# ============================================================

# ============================================================
# [0] 自动安装依赖
# ============================================================
def _auto_install_dependencies():
    import subprocess as _subprocess
    import sys as _sys
    import importlib as _importlib
    deps = [
        ("PySide6", "PySide6>=6.10"),
        ("psutil", "psutil"),
        ("pywin32", "pywin32"),
        ("websocket", "websocket-client"),
    ]
    missing = []
    for module_name, pip_name in deps:
        try:
            _importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"[itent] 检测到缺失依赖: {', '.join(missing)}")
        for pkg in missing:
            try:
                _subprocess.check_call(
                    [_sys.executable, "-m", "pip", "install", pkg],
                    stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
                )
                print(f"[itent] 已安装: {pkg}")
            except Exception as e:
                print(f"[itent] 安装 {pkg} 失败: {e}")
        print(f"[itent] 依赖安装完毕，正在启动程序...\n")

# ============================================================
# [1] 依赖导入
# ============================================================
import ctypes, ctypes.wintypes, json, os, sys, time, threading, subprocess, platform
import struct, traceback, shutil, glob, re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Set
from datetime import datetime

# 打包后（sys.frozen）跳过依赖安装，避免误判
if not getattr(sys, 'frozen', False):
    _auto_install_dependencies()

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QDialog,
    QCheckBox, QGridLayout, QLineEdit, QFileDialog, QMenu,
    QMessageBox, QScrollArea, QFrame, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QSlider, QSpinBox, QDoubleSpinBox, QComboBox, QProgressBar,
    QSystemTrayIcon, QStyle, QSplitter, QStackedWidget,
    QTextEdit, QPlainTextEdit, QGroupBox, QToolButton,
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QTimer, QSize, QPropertyAnimation,
    QEasingCurve, QRect, QPoint, QObject, Slot, QDateTime,
)
from PySide6.QtGui import (
    QIcon, QPixmap, QAction, QFont, QPalette, QColor, QPainter,
    QBrush, QPen, QCursor, QImage, QTextCursor, QFontMetrics,
)

import psutil
import winreg
try:
    import win32gui, win32process, win32api, win32con, win32security
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False

from process_manager import SystemProcessManager, SystemProcessMonitor, CORE_PROCESSES, _is_core_process
from policy_engine import TombstonePolicyEngine
from detectors import AudioDetector, NetworkDetector
from notification_listener import NotificationHub, Notification, WindowMonitor, ToastListener
from notification_toast import ToastManager
from ai_chat import AIChatManager, AI_PROVIDERS, ChatMessage
from agent import AgentManager, ToolExecutor, tool_get_system_info, tool_list_all_processes
from icon_extractor import IconCache
from codebuddy_panel import CodeBuddyAgentPanel

# ============================================================
# [2] 常量配置
# ============================================================
CONFIG_DIR = Path.home() / ".itent"
CONFIG_FILE = CONFIG_DIR / "config.json"
RULES_FILE = CONFIG_DIR / "app_rules.json"
ICON_PATH = CONFIG_DIR / "app_icon.png"
MONITOR_INTERVAL_MS = 3000
SCAN_INTERVAL_SEC = 3.0

# 预定义的内置软件（AI 助手 + 聊天软件，始终显示在列表）
# tombstone_mode: "suspend" = 挂起线程（聊天软件）, "kill" = 杀进程+重启（AI助手）
BUILTIN_APPS = {
    # AI 助手 → 墓碑时 kill 进程（内存彻底释放），唤醒时重启
    "千问": {"procs": ["qianwen.exe"], "exe_hint": "qianwen.exe", "ai_provider": "qianwen", "tombstone_mode": "kill", "builtin": True},
    "元宝": {"procs": ["yuanbao.exe"], "exe_hint": "yuanbao.exe", "ai_provider": "yuanbao", "tombstone_mode": "kill", "builtin": True},
    "豆包": {"procs": ["doubao.exe"], "exe_hint": "doubao.exe", "ai_provider": "doubao", "tombstone_mode": "kill", "builtin": True},
    "ChatGPT": {"procs": ["chatgpt.exe"], "exe_hint": "chatgpt.exe", "ai_provider": None, "tombstone_mode": "kill", "builtin": True},
    "Copilot": {"procs": ["microsoftcopilot.exe"], "exe_hint": "microsoftcopilot.exe", "ai_provider": None, "tombstone_mode": "kill", "builtin": True},
    # 聊天软件 → 墓碑时挂起线程（保持登录/接收消息）
    "微信": {"procs": ["wechat.exe"], "exe_hint": "wechat.exe", "ai_provider": None, "tombstone_mode": "suspend", "builtin": True},
    "QQ": {"procs": ["qq.exe", "qqguild.exe"], "exe_hint": "qq.exe", "ai_provider": None, "tombstone_mode": "suspend", "builtin": True},
    "钉钉": {"procs": ["dingtalk.exe"], "exe_hint": "dingtalk.exe", "ai_provider": None, "tombstone_mode": "suspend", "builtin": True},
    "飞书": {"procs": ["feishu.exe"], "exe_hint": "feishu.exe", "ai_provider": None, "tombstone_mode": "suspend", "builtin": True},
    "腾讯会议": {"procs": ["wemeet.exe", "tencentmeeting.exe"], "exe_hint": "wemeet.exe", "ai_provider": None, "tombstone_mode": "suspend", "builtin": True},
    # CodeBuddy Agent（内置 AI 助手，非进程管理）
    "CodeBuddy Agent": {"procs": [], "exe_hint": "", "ai_provider": "__codebuddy__", "tombstone_mode": "suspend", "builtin": True},
}

# 运行时动态扫描到的应用（自动发现 + 手动添加的聊天应用）
SCANNED_APPS: Dict[str, dict] = {}

# 合并后的完整目标应用列表（供所有模块使用）
TARGET_APPS: Dict[str, dict] = dict(BUILTIN_APPS)

# 用户手动添加到聊天的应用（可被 AI 服务商对话）
USER_CHAT_APPS: Dict[str, dict] = {}

# 系统进程黑名单（不会出现在扫描结果中）
SCAN_BLACKLIST = {
    "system idle process", "system", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "services.exe", "lsass.exe", "svchost.exe", "dwm.exe",
    "winlogon.exe", "explorer.exe", "sihost.exe", "ctfmon.exe", "taskhostw.exe",
    "dllhost.exe", "fontdrvhost.exe", "spoolsv.exe", "wlms.exe",
    "runtimebroker.exe", "shellexperiencehost.exe", "searchindexer.exe",
    "securityhealthservice.exe", "msmpeng.exe", "nis.exe", "smartscreen.exe",
    "audiodg.exe", "conhost.exe", "python.exe", "pythonw.exe",
}

# Catppuccin Mocha 配色
COLOR = {
    "bg_primary":   "#1e1e2e",
    "bg_secondary": "#181825",
    "bg_tertiary":  "#11111b",
    "text_primary":  "#cdd6f4",
    "text_secondary":"#a6adc8",
    "text_muted":    "#6c7086",
    "accent_blue":   "#89b4fa",
    "accent_teal":   "#94e2d5",
    "accent_green":  "#a6e3a1",
    "accent_yellow": "#f9e2af",
    "accent_red":    "#f38ba8",
    "accent_purple": "#cba6f7",
    "sidebar_bg":    "#1e1e2e",
    "sidebar_hover": "#313244",
    "sidebar_active":"#2a2a3e",
    "chat_bg":       "#1e1e2e",
    "chat_bubble_user": "#313244",
    "chat_bubble_ai":   "#252540",
}


# ============================================================
# [3] WhitelistManager
# ============================================================
class WhitelistManager(QObject):
    changed = Signal()
    def __init__(self):
        super().__init__()
        self._set: Set[str] = set()
        self._load()
    def _load(self):
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self._set = set(data.get("whitelist", []))
        except Exception:
            self._set = set()
    def _save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
        except Exception:
            data = {}
        data["whitelist"] = list(self._set)
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.changed.emit()
    def is_whitelisted(self, pid: int) -> bool:
        try:
            p = psutil.Process(pid)
            name = p.name().lower()
            exe = (p.exe() or "").lower()
            return name in self._set or exe in self._set
        except Exception:
            return False
    def is_whitelisted_name(self, name: str) -> bool:
        return name.lower() in self._set
    def add(self, identifier: str):
        self._set.add(identifier.lower())
        self._save()
    def remove(self, identifier: str):
        self._set.discard(identifier.lower())
        self._save()
    def get_all(self) -> List[str]:
        return list(self._set)
    def get_set(self) -> Set[str]:
        return self._set


# ============================================================
# [4] ResourceMonitorThread
# ============================================================
class ResourceMonitorThread(QThread):
    resource_updated = Signal(int, float, float)
    stats_updated = Signal(dict)
    def __init__(self, get_managed_pids: Callable, process_mgr: SystemProcessManager):
        super().__init__()
        self.get_managed_pids = get_managed_pids
        self.process_mgr = process_mgr
        self._running = True
    def run(self):
        while self._running:
            try:
                pids = self.get_managed_pids()
                for pid in pids:
                    try:
                        p = psutil.Process(pid)
                        cpu = p.cpu_percent(interval=0.05)
                        mem = p.memory_info().rss / (1024 * 1024)
                        self.resource_updated.emit(pid, cpu, mem)
                    except Exception:
                        pass
                stats = self.process_mgr.get_stats()
                self.stats_updated.emit(stats)
            except Exception:
                pass
            self.msleep(MONITOR_INTERVAL_MS)
    def stop(self):
        self._running = False
        self.quit()
        self.wait()


# ============================================================
# [5] AppListItem - 左侧软件列表项
# ============================================================
class AppListItem(QFrame):
    """左侧软件列表的自定义项"""
    clicked = Signal(str)  # app_name
    add_to_chat_requested = Signal(str)  # app_name - 右键"添加到聊天"

    STATUS_COLORS = {
        "running": "#a6e3a1",
        "suspended": "#6c7086",
        "killed": "#f38ba8",       # AI 助手被杀进程（墓碑）
        "transient_wake": "#89b4fa",
        "protected": "#f38ba8",
        "whitelisted": "#f9e2af",
        "not_running": "#45475a",
    }

    def __init__(self, app_name: str, icon: QIcon, is_chat_app: bool = False, is_scanned: bool = False, parent=None):
        super().__init__(parent)
        self.app_name = app_name
        self._icon = icon
        self._status = "not_running"
        self._memory_mb = 0.0
        self._cpu = 0.0
        self._pids: List[int] = []
        self._hover = False
        self._selected = False
        self._is_chat_app = is_chat_app  # 是否已添加到聊天
        self._is_scanned = is_scanned    # 是否是扫描发现的
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_chat_status(self, is_chat: bool):
        self._is_chat_app = is_chat
        self.update()

    def is_chat_app(self) -> bool:
        return self._is_chat_app

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: {COLOR['bg_secondary']}; color: {COLOR['text_primary']}; 
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 6px; padding: 4px; }}
            QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {COLOR['sidebar_hover']}; }}
            QMenu::separator {{ height: 1px; background: {COLOR['bg_tertiary']}; margin: 4px 8px; }}
        """)

        if self._is_chat_app:
            # 已在聊天中 → 移除
            remove_action = menu.addAction("🗑 从聊天中移除")
            remove_action.triggered.connect(lambda: self.add_to_chat_requested.emit("__remove__" + self.app_name))
        else:
            # 未在聊天中 → 添加
            add_action = menu.addAction("💬 添加到聊天")
            add_action.triggered.connect(lambda: self.add_to_chat_requested.emit(self.app_name))

        # 只对扫描的应用显示添加/移除
        if not self._is_scanned and self.app_name != "CodeBuddy Agent":
            # 内置应用默认已可管理，但可以移除聊天绑定
            if self._is_chat_app:
                remove_action = menu.addAction("🗑 从聊天中移除")
                remove_action.triggered.connect(lambda: self.add_to_chat_requested.emit("__remove__" + self.app_name))

        menu.exec(self.mapToGlobal(pos))

    def update_state(self, pids: List[int], status: str, mem_mb: float, cpu: float):
        self._pids = pids
        self._status = status
        self._memory_mb = mem_mb
        self._cpu = cpu
        self.update()

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        if self._selected:
            bg = QColor(COLOR["sidebar_active"])
        elif self._hover:
            bg = QColor(COLOR["sidebar_hover"])
        else:
            bg = QColor(COLOR["bg_secondary"])
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, w - 4, h - 4, 10, 10)

        # 图标
        icon_size = 36
        icon_x = 12
        icon_y = (h - icon_size) // 2
        pixmap = self._icon.pixmap(icon_size, icon_size)
        painter.drawPixmap(icon_x, icon_y, icon_size, icon_size, pixmap)

        # 状态圆点
        dot_color = QColor(self.STATUS_COLORS.get(self._status, "#45475a"))
        painter.setBrush(QBrush(dot_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPoint(icon_x + icon_size + 8, icon_y + 6), 5, 5)

        # 名称
        name_x = icon_x + icon_size + 20
        painter.setPen(QColor(COLOR["text_primary"]))
        font = QFont("Segoe UI", 12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(name_x, icon_y + 16, self.app_name)

        # 状态文字 + 内存
        painter.setPen(QColor(COLOR["text_muted"]))
        font2 = QFont("Segoe UI", 9)
        painter.setFont(font2)
        status_text = {
            "running": "运行中",
            "suspended": "已墓碑",
            "killed": "已墓碑 (kill)",
            "transient_wake": "短暂唤醒",
            "protected": "系统保护",
            "whitelisted": "白名单",
            "not_running": "未启动",
        }.get(self._status, self._status)
        info = f"{status_text}"
        if self._status != "not_running":
            info += f"  |  {self._memory_mb:.0f} MB  |  CPU {self._cpu:.1f}%"
        painter.drawText(name_x, icon_y + 34, info)

        # 右侧箭头
        painter.setPen(QColor(COLOR["text_muted"]))
        arrow_x = w - 24
        arrow_y = h // 2
        painter.drawText(QRect(arrow_x - 10, arrow_y - 8, 20, 16), Qt.AlignCenter, ">")

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        self.clicked.emit(self.app_name)


# ============================================================
# [6] AppListPanel - 左侧软件列表面板
# ============================================================
class AppListPanel(QWidget):
    """左侧软件列表（类似联系人列表）"""
    app_selected = Signal(str)  # app_name
    autostart_toggled = Signal(bool)  # enabled
    add_to_chat_requested = Signal(str)  # app_name - 添加到聊天
    remove_from_chat_requested = Signal(str)  # app_name - 从聊天移除

    def __init__(self, icon_cache: IconCache):
        super().__init__()
        self.icon_cache = icon_cache
        self._items: Dict[str, AppListItem] = {}
        self._selected_app: str = ""
        self._scanned_apps: Set[str] = set()  # 追踪扫描到的应用名
        self._init_ui()

    def _init_ui(self):
        self.setFixedWidth(260)
        self.setStyleSheet(f"background: {COLOR['bg_secondary']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题栏
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background: {COLOR['bg_tertiary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)

        logo = QLabel("itent")
        logo.setStyleSheet(f"font-size: 18px; font-weight: 900; color: {COLOR['accent_blue']}; letter-spacing: 2px;")
        h_layout.addWidget(logo)
        h_layout.addStretch()

        # 全部通知按钮
        self.all_btn = QPushButton("全部")
        self.all_btn.setFixedSize(50, 28)
        self.all_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_blue']}; color: {COLOR['bg_tertiary']}; 
                border: none; border-radius: 6px; font-size: 11px; font-weight: bold; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; }}
        """)
        self.all_btn.clicked.connect(lambda: self._select_app(""))
        h_layout.addWidget(self.all_btn)

        layout.addWidget(header)

        # 搜索框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索软件...")
        self.search_box.setFixedHeight(32)
        self.search_box.setStyleSheet(f"""
            QLineEdit {{ background: {COLOR['bg_primary']}; color: {COLOR['text_primary']};
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 6px;
                padding: 4px 10px; font-size: 12px; margin: 4px 8px; }}
            QLineEdit:focus {{ border: 1px solid {COLOR['accent_blue']}; }}
        """)
        self.search_box.textChanged.connect(self._on_search)
        layout.addWidget(self.search_box)

        # 软件列表（滚动区域）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: transparent; }}")

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(4, 4, 4, 4)
        self.list_layout.setSpacing(2)
        self.list_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self.list_widget)
        layout.addWidget(scroll, 1)

        # 自启动开关
        self.autostart_check = QCheckBox("开机自启动")
        self.autostart_check.setFixedHeight(32)
        self.autostart_check.setStyleSheet(f"""
            QCheckBox {{ color: {COLOR['text_muted']}; font-size: 11px; padding: 4px 16px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QCheckBox::indicator:unchecked {{ border: 1px solid {COLOR['bg_tertiary']}; border-radius: 3px; background: {COLOR['bg_primary']}; }}
            QCheckBox::indicator:checked {{ border: 1px solid {COLOR['accent_blue']}; border-radius: 3px; background: {COLOR['accent_blue']}; }}
        """)
        self.autostart_check.toggled.connect(self.autostart_toggled.emit)
        layout.addWidget(self.autostart_check)

        # 底部统计
        self.stats_label = QLabel("管理: 0  |  墓碑: 0  |  活跃: 0")
        self.stats_label.setFixedHeight(36)
        self.stats_label.setStyleSheet(f"""
            color: {COLOR['text_muted']}; font-size: 11px; 
            padding: 8px 16px; background: {COLOR['bg_tertiary']};
        """)
        layout.addWidget(self.stats_label)

    def populate_apps(self, target_apps: Dict):
        """填充软件列表"""
        for app_name in target_apps:
            info = target_apps.get(app_name, {})
            is_chat = app_name in USER_CHAT_APPS or info.get("ai_provider") == "__codebuddy__"
            is_scanned = info.get("scanned", False)
            icon = self.icon_cache.get_icon(app_name, size=36)
            item = AppListItem(app_name, icon, is_chat_app=is_chat, is_scanned=is_scanned)
            item.clicked.connect(self._on_item_clicked)
            item.add_to_chat_requested.connect(self._on_add_to_chat)
            self.list_layout.addWidget(item)
            self._items[app_name] = item

        self.list_layout.addStretch()

    def add_scanned_app(self, app_name: str, app_info: dict):
        """动态添加扫描发现的应用到列表"""
        if app_name in self._items:
            return  # 已存在
        is_chat = app_name in USER_CHAT_APPS
        icon = self.icon_cache.get_icon(app_name, size=36)
        item = AppListItem(app_name, icon, is_chat_app=is_chat, is_scanned=True)
        item.clicked.connect(self._on_item_clicked)
        item.add_to_chat_requested.connect(self._on_add_to_chat)
        # 插入到 stretch 之前
        self.list_layout.insertWidget(self.list_layout.count() - 1, item)
        self._items[app_name] = item
        self._scanned_apps.add(app_name)

    def get_scanned_apps(self) -> Set[str]:
        return self._scanned_apps

    def update_app_state(self, app_name: str, pids: List[int], status: str, mem_mb: float, cpu: float):
        """更新单个软件的状态"""
        if app_name in self._items:
            self._items[app_name].update_state(pids, status, mem_mb, cpu)

    def update_stats(self, total: int, suspended: int, active: int):
        self.stats_label.setText(f"管理: {total}  |  墓碑: {suspended}  |  活跃: {active}")

    def set_chat_status(self, app_name: str, is_chat: bool):
        """设置应用的聊天状态"""
        if app_name in self._items:
            self._items[app_name].set_chat_status(is_chat)

    def _on_item_clicked(self, app_name: str):
        self._select_app(app_name)

    def _on_add_to_chat(self, app_name: str):
        """处理右键菜单的添加/移除聊天"""
        if app_name.startswith("__remove__"):
            real_name = app_name[len("__remove__"):]
            self.remove_from_chat_requested.emit(real_name)
        else:
            self.add_to_chat_requested.emit(app_name)

    def _select_app(self, app_name: str):
        self._selected_app = app_name
        for name, item in self._items.items():
            item.set_selected(name == app_name)
        self.app_selected.emit(app_name)

    def _on_search(self, text: str):
        text = text.lower().strip()
        for name, item in self._items.items():
            item.setVisible(text in name.lower() if text else True)


# ============================================================
# [7] NotificationPanel - 右侧通知流面板
# ============================================================
class NotificationPanel(QWidget):
    """右侧通知/对话区"""

    def __init__(self):
        super().__init__()
        self._notifications: List[Notification] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-bottom: 1px solid {COLOR['bg_tertiary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        self.panel_title = QLabel("通知中心")
        self.panel_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR['text_primary']};")
        h_layout.addWidget(self.panel_title)
        h_layout.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(50, 24)
        clear_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['text_muted']}; 
                border: 1px solid {COLOR['text_muted']}; border-radius: 4px; font-size: 10px; }}
            QPushButton:hover {{ color: {COLOR['accent_red']}; border-color: {COLOR['accent_red']}; }}
        """)
        clear_btn.clicked.connect(self.clear)
        h_layout.addWidget(clear_btn)

        layout.addWidget(header)

        # 通知滚动区域
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {COLOR['chat_bg']}; }}")

        self.notify_widget = QWidget()
        self.notify_layout = QVBoxLayout(self.notify_widget)
        self.notify_layout.setContentsMargins(12, 8, 12, 8)
        self.notify_layout.setSpacing(6)
        self.notify_layout.setAlignment(Qt.AlignTop)

        self.scroll.setWidget(self.notify_widget)
        layout.addWidget(self.scroll, 1)

        # 底部输入栏（AI 对话时使用）
        self.input_widget = QWidget()
        self.input_widget.setFixedHeight(60)
        self.input_widget.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-top: 1px solid {COLOR['bg_tertiary']};")
        self.input_widget.hide()
        input_layout = QHBoxLayout(self.input_widget)
        input_layout.setContentsMargins(12, 8, 12, 8)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("输入消息...")
        self.chat_input.setStyleSheet(f"""
            QLineEdit {{ background: {COLOR['bg_primary']}; color: {COLOR['text_primary']};
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 8px; padding: 6px 12px; font-size: 13px; }}
            QLineEdit:focus {{ border: 1px solid {COLOR['accent_blue']}; }}
        """)
        self.chat_input.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.chat_input)

        send_btn = QPushButton("发送")
        send_btn.setFixedSize(60, 34)
        send_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_blue']}; color: {COLOR['bg_tertiary']}; 
                border: none; border-radius: 8px; font-weight: bold; font-size: 12px; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; }}
        """)
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        layout.addWidget(self.input_widget)

    def set_title(self, title: str):
        self.panel_title.setText(title)

    def show_input(self, show: bool):
        self.input_widget.setVisible(show)

    def add_notification(self, notification: Notification):
        """添加通知卡片"""
        self._notifications.append(notification)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{ background: {COLOR['bg_secondary']}; border-radius: 10px; 
                border-left: 3px solid {COLOR['accent_blue']}; }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(4)

        # 头部：来源 + 时间
        header_w = QWidget()
        header_l = QHBoxLayout(header_w)
        header_l.setContentsMargins(0, 0, 0, 0)

        source_label = QLabel(f"📱 {notification.app_name}")
        source_label.setStyleSheet(f"color: {COLOR['accent_blue']}; font-size: 11px; font-weight: bold;")
        header_l.addWidget(source_label)

        time_str = datetime.fromtimestamp(notification.timestamp).strftime("%H:%M:%S")
        time_label = QLabel(time_str)
        time_label.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 10px;")
        header_l.addWidget(time_label)
        header_l.addStretch()

        card_layout.addWidget(header_w)

        # 标题
        if notification.title:
            title_l = QLabel(notification.title)
            title_l.setStyleSheet(f"color: {COLOR['text_primary']}; font-size: 12px; font-weight: bold;")
            title_l.setWordWrap(True)
            card_layout.addWidget(title_l)

        # 内容
        if notification.body:
            body_l = QLabel(notification.body)
            body_l.setStyleSheet(f"color: {COLOR['text_secondary']}; font-size: 11px;")
            body_l.setWordWrap(True)
            card_layout.addWidget(body_l)

        self.notify_layout.insertWidget(0, card)

        # 限制数量
        while self.notify_layout.count() > 50:
            item = self.notify_layout.takeAt(self.notify_layout.count() - 1)
            if item and item.widget():
                item.widget().deleteLater()

    def clear(self):
        self._notifications.clear()
        while self.notify_layout.count():
            item = self.notify_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _on_send(self):
        text = self.chat_input.text().strip()
        if text:
            self.chat_input.clear()
            # 信号由 MainWindow 处理


# ============================================================
# [8] AIChatPanel - AI 对话面板
# ============================================================
class AIChatPanel(QWidget):
    """AI 对话界面"""
    message_sent = Signal(str, str)  # provider_key, message
    settings_requested = Signal(str)  # provider_key

    def __init__(self, provider_key: str, provider_name: str):
        super().__init__()
        self.provider_key = provider_key
        self.provider_name = provider_name
        self._messages: List[Tuple[str, str]] = []  # [(role, content)]
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-bottom: 1px solid {COLOR['bg_tertiary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        title = QLabel(f"💬 {self.provider_name}")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR['accent_blue']};")
        h_layout.addWidget(title)
        h_layout.addStretch()

        # 设置按钮
        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setFixedSize(60, 24)
        self.settings_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['accent_teal']}; 
                border: 1px solid {COLOR['accent_teal']}; border-radius: 4px; font-size: 10px; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; color: {COLOR['bg_primary']}; }}
        """)
        self.settings_btn.clicked.connect(lambda: self.settings_requested.emit(self.provider_key))
        h_layout.addWidget(self.settings_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(50, 24)
        clear_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['text_muted']}; 
                border: 1px solid {COLOR['text_muted']}; border-radius: 4px; font-size: 10px; }}
            QPushButton:hover {{ color: {COLOR['accent_red']}; border-color: {COLOR['accent_red']}; }}
        """)
        clear_btn.clicked.connect(self.clear)
        h_layout.addWidget(clear_btn)

        layout.addWidget(header)

        # 消息滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {COLOR['chat_bg']}; }}")

        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(12, 8, 12, 8)
        self.chat_layout.setSpacing(10)
        self.chat_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self.chat_widget)
        layout.addWidget(scroll, 1)

        # 底部输入栏
        input_widget = QWidget()
        input_widget.setFixedHeight(60)
        input_widget.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-top: 1px solid {COLOR['bg_tertiary']};")
        in_layout = QHBoxLayout(input_widget)
        in_layout.setContentsMargins(12, 8, 12, 8)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText(f"向 {self.provider_name} 提问...")
        self.chat_input.setStyleSheet(f"""
            QLineEdit {{ background: {COLOR['bg_primary']}; color: {COLOR['text_primary']};
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 8px; padding: 6px 12px; font-size: 13px; }}
            QLineEdit:focus {{ border: 1px solid {COLOR['accent_blue']}; }}
        """)
        self.chat_input.returnPressed.connect(self._send)
        in_layout.addWidget(self.chat_input)

        send_btn = QPushButton("发送")
        send_btn.setFixedSize(60, 34)
        send_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_blue']}; color: {COLOR['bg_tertiary']}; 
                border: none; border-radius: 8px; font-weight: bold; font-size: 12px; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; }}
        """)
        send_btn.clicked.connect(self._send)
        in_layout.addWidget(send_btn)

        layout.addWidget(input_widget)

    def add_message(self, role: str, content: str):
        """添加消息气泡"""
        self._messages.append((role, content))

        bubble = QFrame()
        is_user = (role == "user")
        bg = COLOR["chat_bubble_user"] if is_user else COLOR["chat_bubble_ai"]
        align = Qt.AlignRight if is_user else Qt.AlignLeft

        bubble.setStyleSheet(f"""
            QFrame {{ background: {bg}; border-radius: 12px; padding: 8px; }}
        """)
        bubble.setMaximumWidth(int(self.width() * 0.75))

        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(12, 8, 12, 8)

        role_l = QLabel("你" if is_user else self.provider_name)
        role_l.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 10px;")
        b_layout.addWidget(role_l)

        content_l = QLabel(content)
        content_l.setStyleSheet(f"color: {COLOR['text_primary']}; font-size: 13px;")
        content_l.setWordWrap(True)
        b_layout.addWidget(content_l)

        container = QWidget()
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        if is_user:
            c_layout.addStretch()
            c_layout.addWidget(bubble)
        else:
            c_layout.addWidget(bubble)
            c_layout.addStretch()

        self.chat_layout.addWidget(container)

        # 滚动到底部
        QTimer.singleShot(100, lambda: self._scroll_bottom())

    def _scroll_bottom(self):
        sb = self.parent().findChild(QScrollArea)
        if sb:
            sb.verticalScrollBar().setValue(sb.verticalScrollBar().maximum())

    def _send(self):
        text = self.chat_input.text().strip()
        if text:
            self.chat_input.clear()
            self.add_message("user", text)
            self.message_sent.emit(self.provider_key, text)

    def clear(self):
        self._messages.clear()
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(200, self._scroll_bottom)


# ============================================================
# [9] AppDetailPanel - 软件详情/操作面板
# ============================================================
class AppDetailPanel(QWidget):
    """右侧软件详情面板：显示进程信息 + 操作按钮"""
    wake_app = Signal(str)       # app_name
    suspend_app = Signal(str)
    kill_app = Signal(str)

    def __init__(self):
        super().__init__()
        self._current_app = ""
        self._tombstone_mode = "suspend"  # "suspend" 或 "kill"
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 头部
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-bottom: 1px solid {COLOR['bg_tertiary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        self.detail_title = QLabel("软件详情")
        self.detail_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR['text_primary']};")
        h_layout.addWidget(self.detail_title)
        h_layout.addStretch()
        layout.addWidget(header)

        # 内容区
        content = QWidget()
        content.setStyleSheet(f"background: {COLOR['chat_bg']};")
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(20, 20, 20, 20)
        c_layout.setSpacing(16)

        # 软件信息
        info_group = QGroupBox("软件信息")
        info_group.setStyleSheet(f"""
            QGroupBox {{ color: {COLOR['text_primary']}; font-weight: bold; font-size: 13px;
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 8px; padding: 16px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
        """)
        i_layout = QVBoxLayout(info_group)
        i_layout.setSpacing(8)
        self.info_label = QLabel("选择一个软件查看详情")
        self.info_label.setStyleSheet(f"color: {COLOR['text_secondary']}; font-size: 12px;")
        self.info_label.setWordWrap(True)
        i_layout.addWidget(self.info_label)
        c_layout.addWidget(info_group)

        # 墓碑模式说明
        self.mode_label = QLabel()
        self.mode_label.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 11px; padding: 4px 0;")
        self.mode_label.setWordWrap(True)
        c_layout.addWidget(self.mode_label)

        # 操作按钮
        btn_group = QGroupBox("操作")
        btn_group.setStyleSheet(f"""
            QGroupBox {{ color: {COLOR['text_primary']}; font-weight: bold; font-size: 13px;
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 8px; padding: 16px; margin-top: 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
        """)
        b_layout = QVBoxLayout(btn_group)
        b_layout.setSpacing(8)

        self.wake_btn = QPushButton("▶ 唤醒软件")
        self.wake_btn.setFixedHeight(36)
        self.wake_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_green']}; color: {COLOR['bg_tertiary']}; 
                border: none; border-radius: 8px; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: #7ec47a; }}
        """)
        self.wake_btn.clicked.connect(lambda: self.wake_app.emit(self._current_app))
        b_layout.addWidget(self.wake_btn)

        self.suspend_btn = QPushButton("⏸ 墓碑（冻结）")
        self.suspend_btn.setFixedHeight(36)
        self.suspend_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_purple']}; color: {COLOR['bg_tertiary']}; 
                border: none; border-radius: 8px; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: #b48ce0; }}
        """)
        self.suspend_btn.clicked.connect(lambda: self.suspend_app.emit(self._current_app))
        b_layout.addWidget(self.suspend_btn)

        self.kill_btn = QPushButton("✕ 结束进程")
        self.kill_btn.setFixedHeight(36)
        self.kill_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_red']}; color: {COLOR['bg_tertiary']}; 
                border: none; border-radius: 8px; font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: #e05c7a; }}
        """)
        self.kill_btn.clicked.connect(lambda: self.kill_app.emit(self._current_app))
        b_layout.addWidget(self.kill_btn)

        c_layout.addWidget(btn_group)
        c_layout.addStretch()
        layout.addWidget(content, 1)

    def set_app(self, app_name: str, info_text: str, is_running: bool, is_suspended: bool, tombstone_mode: str = "suspend"):
        self._current_app = app_name
        self._tombstone_mode = tombstone_mode
        self.detail_title.setText(f"📋 {app_name}")

        # 根据墓碑模式更新按钮文字
        if tombstone_mode == "kill":
            self.suspend_btn.setText("⏸ 墓碑（关闭进程）")
            self.wake_btn.setText("▶ 唤醒（重新启动）")
            self.mode_label.setText("💡 此软件使用 Kill 模式：墓碑时关闭进程释放所有内存，唤醒时自动重新启动。")
        else:
            self.suspend_btn.setText("⏸ 墓碑（冻结）")
            self.wake_btn.setText("▶ 唤醒软件")
            self.mode_label.setText("💡 此软件使用挂起模式：墓碑时冻结线程，保留登录状态和消息接收。")

        self.info_label.setText(info_text)
        self.wake_btn.setVisible(True)
        self.suspend_btn.setVisible(True)
        self.kill_btn.setVisible(is_running)


# ============================================================
# [10] MainWindow - 主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.whitelist_mgr = WhitelistManager()
        self.process_mgr = SystemProcessManager(self.whitelist_mgr.get_set())
        self.policy_engine = TombstonePolicyEngine(CONFIG_DIR)
        self.icon_cache = IconCache(str(CONFIG_DIR))
        self.ai_manager = AIChatManager(str(CONFIG_DIR))
        self.agent_manager = AgentManager(str(CONFIG_DIR))
        self._register_agent_tools()
        self.monitor_thread: Optional[ResourceMonitorThread] = None
        self.system_monitor: Optional[SystemProcessMonitor] = None
        self.notification_hub: Optional[NotificationHub] = None
        self.toast_mgr: Optional[ToastManager] = None
        self._current_view = "notifications"  # notifications / ai_chat / app_detail
        self._ai_panel_indices: Dict[str, int] = {}
        self._codebuddy_panel: Optional[CodeBuddyAgentPanel] = None
        self._node_process: Optional[subprocess.Popen] = None

        # 加载用户手动添加的聊天应用配置
        self._load_user_chat_apps()

        self._init_ui()
        self._init_toast_manager()
        self._start_system_monitor()
        self._start_resource_monitor()
        self._start_notification_listener()
        self._start_app_state_timer()

        # 初始化自启动复选框状态（避免发射 toggled 信号）
        self.app_list.autostart_check.setChecked(self._is_autostart_enabled())

    def _init_ui(self):
        self.setWindowTitle("itent - 智能后台管理器")
        self.setGeometry(100, 100, 1050, 700)
        self.setMinimumSize(800, 550)
        self.setStyleSheet(f"QMainWindow {{ background: {COLOR['bg_primary']}; }}")

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧：软件列表
        self.app_list = AppListPanel(self.icon_cache)
        self.app_list.populate_apps(TARGET_APPS)
        self.app_list.app_selected.connect(self._on_app_selected)
        self.app_list.autostart_toggled.connect(self._set_autostart)
        self.app_list.add_to_chat_requested.connect(self._on_add_app_to_chat)
        self.app_list.remove_from_chat_requested.connect(self._on_remove_app_from_chat)
        main_layout.addWidget(self.app_list)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COLOR['bg_tertiary']};")
        main_layout.addWidget(sep)

        # 右侧：堆叠面板
        self.right_stack = QStackedWidget()

        # 页面 0：通知中心
        self.notify_panel = NotificationPanel()
        self.right_stack.addWidget(self.notify_panel)

        # 页面 1：AI 对话（按需创建）
        self.ai_panels: Dict[str, AIChatPanel] = {}

        # 页面 2：软件详情
        self.detail_panel = AppDetailPanel()
        self.detail_panel.wake_app.connect(self._wake_app)
        self.detail_panel.suspend_app.connect(self._suspend_app)
        self.detail_panel.kill_app.connect(self._kill_app)
        self.right_stack.addWidget(self.detail_panel)

        # 页面 3：CodeBuddy Agent
        self._codebuddy_panel = CodeBuddyAgentPanel()
        self.right_stack.addWidget(self._codebuddy_panel)
        self._codebuddy_page_index = self.right_stack.indexOf(self._codebuddy_panel)

        main_layout.addWidget(self.right_stack, 1)

        # 系统托盘
        self._init_tray()

        # 启动 Node.js 后端服务
        self._start_node_server()

        # 默认显示通知中心
        self.right_stack.setCurrentIndex(0)

    def _register_agent_tools(self):
        """向 AgentManager 注册工具回调（桥接 itent 内部功能）"""
        mgr = self.agent_manager

        # 列出管理的软件状态
        mgr.register_tool("list_running_apps", self._tool_list_apps)

        # 墓碑软件
        mgr.register_tool("suspend_app", self._tool_suspend_app)

        # 唤醒软件
        mgr.register_tool("resume_app", self._tool_resume_app)

        # 终止软件
        mgr.register_tool("kill_app", self._tool_kill_app)

        # 启动软件
        mgr.register_tool("launch_app", self._tool_launch_app)

        # 系统信息（纯函数）
        mgr.register_tool("get_system_info", tool_get_system_info)

        # 进程列表（纯函数）
        mgr.register_tool("list_all_processes", tool_list_all_processes)

        # 一键优化
        mgr.register_tool("optimize_memory", self._tool_optimize)

    # ============================================================
    # Agent 工具实现
    # ============================================================
    def _tool_list_apps(self, args: dict) -> str:
        """列出 itent 管理的所有软件状态"""
        lines = ["当前 itent 管理的软件状态："]
        count = 0
        # 优先列出内置应用和用户添加的聊天应用
        priority_apps = list(BUILTIN_APPS.keys()) + list(USER_CHAT_APPS.keys())
        shown = set()
        
        # 先列优先应用
        for app_name in priority_apps:
            if app_name in TARGET_APPS and app_name not in shown:
                info = TARGET_APPS[app_name]
                tombstone_mode = info.get("tombstone_mode", "suspend")
                pids = self._find_pids_for_app(app_name)
                if not pids:
                    if tombstone_mode == "kill":
                        lines.append(f"  • {app_name} — 已墓碑 ❄️ (Kill模式)")
                    else:
                        lines.append(f"  • {app_name} — 未运行")
                else:
                    total_mem = 0.0
                    status = "运行中"
                    for pid in pids:
                        try:
                            p = psutil.Process(pid)
                            total_mem += p.memory_info().rss / (1024 * 1024)
                        except Exception:
                            pass
                        if self.process_mgr.is_suspended(pid):
                            status = "已墓碑 ❄️"
                        elif self.process_mgr.is_transient_wake(pid):
                            status = "短暂唤醒 ⚡"
                    lines.append(f"  • {app_name} — {status} | {total_mem:.1f} MB | {len(pids)} 进程")
                shown.add(app_name)
                count += 1

        # 然后列扫描到的运行中的应用（最多10个）
        scanned_count = 0
        for app_name, info in TARGET_APPS.items():
            if app_name in shown:
                continue
            if not info.get("scanned"):
                continue
            pids = self._find_pids_for_app(app_name)
            if not pids:
                continue  # 只显示运行中的扫描应用
            if scanned_count >= 15:
                lines.append(f"  ... 还有更多扫描到的应用（共 {len(SCANNED_APPS)} 个）")
                break
            total_mem = 0.0
            status = "运行中"
            for pid in pids:
                try:
                    p = psutil.Process(pid)
                    total_mem += p.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
                if self.process_mgr.is_suspended(pid):
                    status = "已墓碑 ❄️"
                elif self.process_mgr.is_transient_wake(pid):
                    status = "短暂唤醒 ⚡"
            lines.append(f"  • {app_name} — {status} | {total_mem:.1f} MB | {len(pids)} 进程")
            scanned_count += 1

        return "\n".join(lines)

    def _tool_suspend_app(self, args: dict) -> str:
        """墓碑指定软件"""
        app_name = args.get("app_name", "")
        if app_name not in TARGET_APPS:
            available = ", ".join(TARGET_APPS.keys())
            return f"未找到软件「{app_name}」。itent 目前管理: {available}"

        tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")
        pids = self._find_pids_for_app(app_name)

        if not pids:
            return f"「{app_name}」当前未运行，无需墓碑。"

        if tombstone_mode == "kill":
            # Kill 模式：杀进程
            count = len(pids)
            for pid in pids:
                self._kill_pid(pid)
                self.process_mgr.remove_managed_pid(pid)
            return f"已墓碑「{app_name}」的 {count} 个进程（Kill 模式），内存已彻底释放。"

        # 挂起模式
        count = 0
        for pid in pids:
            if not self.process_mgr.is_suspended(pid):
                self.process_mgr.suspend(pid)
                count += 1

        if count > 0:
            return f"已墓碑「{app_name}」的 {count} 个进程，内存已释放。"
        else:
            return f"「{app_name}」已经处于墓碑状态。"

    def _tool_resume_app(self, args: dict) -> str:
        """唤醒指定软件"""
        app_name = args.get("app_name", "")
        if app_name not in TARGET_APPS:
            available = ", ".join(TARGET_APPS.keys())
            return f"未找到软件「{app_name}」。itent 目前管理: {available}"

        tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")
        pids = self._find_pids_for_app(app_name)

        if tombstone_mode == "kill":
            # Kill 模式：重新启动
            if not pids:
                self._launch_app(app_name)
                return f"正在重新启动「{app_name}」（Kill 模式）..."
            else:
                self._bring_to_front(pids[0])
                return f"「{app_name}」已经在运行中。"

        if not pids:
            self._launch_app(app_name)
            return f"正在启动「{app_name}」..."

        count = 0
        for pid in pids:
            if self.process_mgr.is_suspended(pid):
                self.process_mgr.resume(pid)
                count += 1

        if count > 0:
            # 尝试带到前台
            self._bring_to_front(pids[0])
            return f"已唤醒「{app_name}」的 {count} 个进程。"
        else:
            return f"「{app_name}」已经在运行中。"

    def _tool_kill_app(self, args: dict) -> str:
        """终止指定软件"""
        app_name = args.get("app_name", "")
        if app_name not in TARGET_APPS:
            available = ", ".join(TARGET_APPS.keys())
            return f"未找到软件「{app_name}」。itent 目前管理: {available}"

        pids = self._find_pids_for_app(app_name)
        if not pids:
            return f"「{app_name}」当前未运行。"

        for pid in pids:
            try:
                p = psutil.Process(pid)
                p.terminate()
            except Exception:
                pass

        return f"已终止「{app_name}」的 {len(pids)} 个进程。"

    def _tool_launch_app(self, args: dict) -> str:
        """启动指定软件"""
        app_name = args.get("app_name", "")
        if app_name not in TARGET_APPS:
            available = ", ".join(TARGET_APPS.keys())
            return f"未找到软件「{app_name}」。itent 目前管理: {available}"

        pids = self._find_pids_for_app(app_name)
        if pids:
            return f"「{app_name}」已经在运行中。"

        self._launch_app(app_name)
        return f"正在启动「{app_name}」..."

    def _tool_optimize(self, args: dict) -> str:
        """一键优化：墓碑所有非活跃软件（仅优化内置应用和用户添加的聊天应用）"""
        suspended = []
        # 只优化内置应用和用户添加的聊天应用，不优化扫描到的其他应用
        optimizable_apps = set(BUILTIN_APPS.keys()) | set(USER_CHAT_APPS.keys())
        for app_name in optimizable_apps:
            if app_name not in TARGET_APPS:
                continue
            tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")
            pids = self._find_pids_for_app(app_name)

            if tombstone_mode == "kill":
                # Kill 模式：杀进程
                if pids:
                    for pid in pids:
                        self._kill_pid(pid)
                        self.process_mgr.remove_managed_pid(pid)
                    suspended.append(app_name)
            else:
                # 挂起模式
                for pid in pids:
                    if not self.process_mgr.is_suspended(pid) \
                       and not self.process_mgr.is_transient_wake(pid):
                        self.process_mgr.suspend(pid)
                        if app_name not in suspended:
                            suspended.append(app_name)

        if suspended:
            apps = "、".join(suspended)
            return f"已优化内存！墓碑了以下软件: {apps}。系统内存已释放。"
        else:
            return "当前没有可优化的软件，所有管理的软件都已经处于墓碑状态或正在活跃使用中。"

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        if ICON_PATH.exists():
            self.tray.setIcon(QIcon(str(ICON_PATH)))
        else:
            self.tray.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        self.tray.setToolTip("itent - 智能后台管理器")

        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.real_exit)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: int):
        """托盘图标被激活（单击/双击）时恢复窗口"""
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show()
            self.raise_()
            self.activateWindow()

    # ============================================================
    # Node.js 后端管理
    # ============================================================
    def _start_node_server(self):
        """启动 Node.js CodeBuddy Agent 后端服务"""
        import subprocess
        server_dir = Path(__file__).parent / "server"
        server_script = server_dir / "agent_server.cjs"

        if not server_script.exists():
            print("[itent] 后端脚本不存在: " + str(server_script))
            return

        env = os.environ.copy()
        # CodeBuddy API Key（用户提供的密钥）
        env["CODEBUDDY_API_KEY"] = "sk-cqed590671qvclwp4tc1f3gifvivdksurb9ivnbhxhufzqru"
        env["CODEBUDDY_INTERNET_ENVIRONMENT"] = "internal"

        try:
            self._node_process = subprocess.Popen(
                ["node", str(server_script)],
                cwd=str(server_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            print("[itent] CodeBuddy Agent 后端已启动 (PID: {})".format(self._node_process.pid))
        except Exception as e:
            print("[itent] 启动后端失败: " + str(e))

    def _stop_node_server(self):
        """停止 Node.js 后端"""
        if self._node_process:
            try:
                self._node_process.terminate()
                self._node_process.wait(timeout=5)
                print("[itent] CodeBuddy Agent 后端已停止")
            except Exception:
                try:
                    self._node_process.kill()
                except Exception:
                    pass
            self._node_process = None

    # ============================================================
    # 开机自启动（注册表）
    # ============================================================
    def _set_autostart(self, enable: bool):
        """写入/删除开机自启动注册表项（HKCU，不需要管理员权限）"""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable:
                exe_path = sys.executable
                winreg.SetValueEx(key, "itent", 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, "itent")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _is_autostart_enabled(self) -> bool:
        """检查开机自启动是否已启用"""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "itent")
            winreg.CloseKey(key)
            return value == sys.executable
        except Exception:
            return False

    def _init_toast_manager(self):
        """初始化顶部弹幕通知管理器"""
        self.toast_mgr = ToastManager(self.icon_cache)
        self.toast_mgr.wake_app_signal.connect(self._on_toast_wake_app)

    # ============================================================
    # 系统监控
    # ============================================================
    def _start_system_monitor(self):
        def on_new_process(pid, name):
            self.process_mgr.add_managed_pid(pid, name)
            # 如果是新发现的进程，自动添加到扫描列表和 UI
            self._on_new_process_discovered(pid, name)

        def on_process_exit(pid):
            self.process_mgr.remove_managed_pid(pid)

        # 收集所有目标进程名（小写）：内置 + 已扫描
        target_names = set()
        for info in TARGET_APPS.values():
            for p in info["procs"]:
                target_names.add(p.lower())

        self.system_monitor = SystemProcessMonitor(
            on_new_process, on_process_exit,
            target_proc_names=target_names,
            interval=SCAN_INTERVAL_SEC
        )
        self.system_monitor.start()

        # 初次扫描：扫描当前所有运行的非系统进程
        QTimer.singleShot(1000, self._initial_scan_all_processes)

    def _initial_scan_all_processes(self):
        """初次启动时扫描所有运行的非系统进程，自动加入列表"""
        try:
            for p in psutil.process_iter(attrs=["pid", "name", "exe"]):
                try:
                    name = (p.info["name"] or "").lower()
                    pid = p.info["pid"]
                    # 跳过黑名单进程
                    if name in SCAN_BLACKLIST:
                        continue
                    # 跳过已在内置列表中的
                    already_managed = False
                    for info in TARGET_APPS.values():
                        for proc_name in info.get("procs", []):
                            if proc_name.lower() == name:
                                already_managed = True
                                break
                        if already_managed:
                            break
                    if already_managed:
                        continue
                    # 跳过系统核心进程
                    if _is_core_process(name):
                        continue
                    # 跳过小于 10MB 内存的进程（减少噪音）
                    mem_mb = p.info.get("memory_info", None)
                    if mem_mb is None:
                        try:
                            mem_mb = p.memory_info().rss / (1024 * 1024)
                        except Exception:
                            mem_mb = 0
                    if mem_mb < 10:
                        continue

                    # 生成友好的应用名
                    display_name = name.replace(".exe", "").replace(".EXE", "").title()
                    if display_name not in SCANNED_APPS:
                        exe_path = p.info.get("exe") or ""
                        SCANNED_APPS[display_name] = {
                            "procs": [name],
                            "exe_hint": exe_path or name,
                            "ai_provider": None,
                            "tombstone_mode": "suspend",
                            "builtin": False,
                            "scanned": True,
                        }
                        TARGET_APPS[display_name] = SCANNED_APPS[display_name]
                        self.app_list.add_scanned_app(display_name, SCANNED_APPS[display_name])

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            # 更新系统监控的目标进程列表
            self._update_monitor_targets()
        except Exception:
            pass

    def _on_new_process_discovered(self, pid: int, name: str):
        """当系统监控发现新进程时，动态添加到列表"""
        name_lower = name.lower()
        # 检查是否是已知应用的进程
        for app_name, info in TARGET_APPS.items():
            for proc_name in info.get("procs", []):
                if proc_name.lower() == name_lower:
                    return  # 已存在

        # 跳过黑名单
        if name_lower in SCAN_BLACKLIST:
            return
        if _is_core_process(name_lower):
            return

        # 新进程，添加到扫描列表
        display_name = name_lower.replace(".exe", "").replace(".EXE", "").title()
        if display_name not in SCANNED_APPS:
            try:
                p = psutil.Process(pid)
                exe_path = (p.exe() or "")
                mem_mb = p.memory_info().rss / (1024 * 1024)
                if mem_mb < 5:  # 太小的进程忽略
                    return
            except Exception:
                exe_path = name_lower

            SCANNED_APPS[display_name] = {
                "procs": [name_lower],
                "exe_hint": exe_path or name_lower,
                "ai_provider": None,
                "tombstone_mode": "suspend",
                "builtin": False,
                "scanned": True,
            }
            TARGET_APPS[display_name] = SCANNED_APPS[display_name]
            self.app_list.add_scanned_app(display_name, SCANNED_APPS[display_name])
            self._update_monitor_targets()

    def _update_monitor_targets(self):
        """更新系统监控的目标进程名集合"""
        if self.system_monitor:
            target_names = set()
            for info in TARGET_APPS.values():
                for p in info.get("procs", []):
                    target_names.add(p.lower())
            self.system_monitor.set_target_procs(target_names)

    def _start_resource_monitor(self):
        self.monitor_thread = ResourceMonitorThread(
            self.process_mgr.get_all_managed_pids, self.process_mgr
        )
        self.monitor_thread.resource_updated.connect(self._on_resource_updated)
        self.monitor_thread.stats_updated.connect(self._on_stats_updated)
        self.monitor_thread.start()

        # 墓碑决策定时器
        self.policy_timer = QTimer()
        self.policy_timer.timeout.connect(self._apply_tombstone_policy)
        self.policy_timer.start(5000)

    def _start_notification_listener(self):
        """启动通知监听"""
        target_procs = {name: info["procs"] for name, info in TARGET_APPS.items()}

        def on_notify(notification: Notification):
            # 主线程安全
            self.notify_panel.add_notification(notification)
            # 弹出顶部弹幕通知
            if self.toast_mgr:
                self.toast_mgr.show_toast(
                    notification.app_name,
                    notification.title,
                    notification.body
                )
            # 短暂唤醒对应软件
            for name, info in TARGET_APPS.items():
                if name == notification.app_name:
                    for pid in self._find_pids_for_app(name):
                        self.process_mgr.set_transient_wake(pid, 5.0)
                    break

        self.notification_hub = NotificationHub(on_notify)
        self.notification_hub.start(target_procs)

    def _start_app_state_timer(self):
        """定时更新左侧软件列表的状态"""
        self.app_state_timer = QTimer()
        self.app_state_timer.timeout.connect(self._update_app_states)
        self.app_state_timer.start(3000)

    def _update_app_states(self):
        """更新每个软件在左侧列表中的状态"""
        for app_name, info in TARGET_APPS.items():
            pids = self._find_pids_for_app(app_name)
            tombstone_mode = info.get("tombstone_mode", "suspend")

            if not pids:
                # Kill 模式且没有 PID：显示为已墓碑（进程被杀）
                if tombstone_mode == "kill":
                    # 检查是否之前被墓碑过（通过检查 app_rules 或追踪状态）
                    self.app_list.update_app_state(app_name, [], "killed", 0, 0)
                else:
                    self.app_list.update_app_state(app_name, [], "not_running", 0, 0)
                continue

            # 聚合状态：取最高优先级
            status = "running"
            total_mem = 0.0
            total_cpu = 0.0
            for pid in pids:
                try:
                    p = psutil.Process(pid)
                    total_mem += p.memory_info().rss / (1024 * 1024)
                    total_cpu += p.cpu_percent(interval=0)
                except Exception:
                    pass

                if self.process_mgr.is_suspended(pid):
                    status = "suspended"
                elif self.process_mgr.is_transient_wake(pid):
                    if status != "suspended":
                        status = "transient_wake"
                elif self.process_mgr.is_whitelisted(pid):
                    if status not in ("suspended", "transient_wake"):
                        status = "whitelisted"

            self.app_list.update_app_state(app_name, pids, status, total_mem, total_cpu)

    def _find_pids_for_app(self, app_name: str) -> List[int]:
        """查找某个软件的所有 PID"""
        if app_name not in TARGET_APPS:
            return []
        target_procs = [p.lower() for p in TARGET_APPS[app_name]["procs"]]
        result = []
        for pid in self.process_mgr.get_all_managed_pids():
            try:
                name = psutil.Process(pid).name().lower()
                if any(tp in name for tp in target_procs):
                    result.append(pid)
            except Exception:
                pass
        return result

    def _find_app_name_for_pid(self, pid: int) -> Optional[str]:
        """根据 PID 找到对应的 app_name"""
        try:
            name = psutil.Process(pid).name().lower()
        except Exception:
            return None
        for app_name, info in TARGET_APPS.items():
            target_procs = [p.lower() for p in info["procs"]]
            if any(tp in name for tp in target_procs):
                return app_name
        return None

    def _is_pid_alive(self, pid: int) -> bool:
        """检查 PID 是否仍然存在"""
        try:
            psutil.Process(pid)
            return True
        except (psutil.NoSuchProcess, Exception):
            return False

    def _kill_pid(self, pid: int):
        """温和地终止进程（先 terminate，再 kill）"""
        try:
            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=3)
            except psutil.TimeoutExpired:
                p.kill()
        except Exception:
            pass

    def _apply_tombstone_policy(self):
        """只对内建应用和用户添加的聊天应用做墓碑决策。
        支持两种模式：
        - "suspend": 挂起线程（聊天软件），保留内存状态
        - "kill": 杀进程（AI 助手），彻底释放内存
        扫描到的其他应用不会被自动墓碑，仅作监控展示。
        """
        # 只对内置应用和用户添加的聊天应用做墓碑决策
        managed_pids = self.process_mgr.get_all_managed_pids()
        tombstone_apps = set(BUILTIN_APPS.keys()) | set(USER_CHAT_APPS.keys())

        # 过滤：只保留属于可墓碑应用的 PID
        tombstone_pids = []
        for pid in managed_pids:
            app_name = self._find_app_name_for_pid(pid)
            if app_name and app_name in tombstone_apps:
                tombstone_pids.append(pid)

        now = time.time()

        # 调试日志
        debug_log = CONFIG_DIR / "tombstone_debug.log"
        try:
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat()}] _apply_tombstone_policy: {len(managed_pids)} managed pids, {len(tombstone_pids)} tombstoneable\n")
                for pid in tombstone_pids:
                    try:
                        p = psutil.Process(pid)
                        f.write(f"  PID {pid}: {p.name()} suspended={self.process_mgr.is_suspended(pid)} transient={self.process_mgr.is_transient_wake(pid)}\n")
                    except Exception:
                        pass
        except Exception:
            pass

        # 检查短暂唤醒是否过期
        self.process_mgr.check_transient_wake_expiry()

        for pid in tombstone_pids:
            try:
                # 查找此 PID 属于哪个 app（用于获取 tombstone_mode）
                app_name = self._find_app_name_for_pid(pid)
                tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend") if app_name else "suspend"

                # 跳过核心进程和白名单
                if self.process_mgr.is_core_process(pid):
                    continue
                if self.process_mgr.is_whitelisted(pid):
                    continue

                # 检查是否在短暂唤醒中
                if self.process_mgr.is_transient_wake(pid):
                    # 短暂唤醒期间：kill 模式下需要重新启动进程
                    if tombstone_mode == "kill" and app_name:
                        if not self._is_pid_alive(pid):
                            self._launch_app(app_name)
                            try:
                                with open(debug_log, "a", encoding="utf-8") as f:
                                    f.write(f"  PID {pid} ({app_name}): transient wake, relaunched (kill mode)\n")
                            except Exception:
                                pass
                    elif self.process_mgr.is_suspended(pid):
                        self.process_mgr.resume(pid)
                        try:
                            with open(debug_log, "a", encoding="utf-8") as f:
                                f.write(f"  PID {pid}: transient wake, resumed\n")
                        except Exception:
                            pass
                    continue

                # 策略决策
                should_suspend, reason = self.policy_engine.should_suspend(
                    pid,
                    self.process_mgr.is_core_process(pid),
                    self.process_mgr.is_whitelisted(pid)
                )

                if should_suspend:
                    if tombstone_mode == "kill":
                        # Kill 模式：直接杀进程，彻底释放内存
                        if self._is_pid_alive(pid):
                            self._kill_pid(pid)
                            self.process_mgr.remove_managed_pid(pid)
                            try:
                                with open(debug_log, "a", encoding="utf-8") as f:
                                    f.write(f"  PID {pid} ({app_name}): killed (kill mode), reason={reason}\n")
                            except Exception:
                                pass
                    else:
                        # 挂起模式：冻结线程
                        if not self.process_mgr.is_suspended(pid):
                            self.process_mgr.suspend(pid)
                            try:
                                with open(debug_log, "a", encoding="utf-8") as f:
                                    f.write(f"  PID {pid}: suspended, reason={reason}\n")
                            except Exception:
                                pass
                else:
                    # 不应该墓碑：确保进程运行
                    if tombstone_mode == "kill" and app_name:
                        if not self._is_pid_alive(pid):
                            self._launch_app(app_name)
                            try:
                                with open(debug_log, "a", encoding="utf-8") as f:
                                    f.write(f"  PID {pid} ({app_name}): relaunched (should not suspend), reason={reason}\n")
                            except Exception:
                                pass
                    elif self.process_mgr.is_suspended(pid):
                        self.process_mgr.resume(pid)
                        try:
                            with open(debug_log, "a", encoding="utf-8") as f:
                                f.write(f"  PID {pid}: resumed, reason={reason}\n")
                        except Exception:
                            pass
            except Exception as e:
                try:
                    with open(debug_log, "a", encoding="utf-8") as f:
                        f.write(f"  PID {pid}: error {e}\n")
                except Exception:
                    pass

    def _on_resource_updated(self, pid: int, cpu: float, mem_mb: float):
        pass  # 状态由 _update_app_states 统一更新

    def _on_stats_updated(self, stats: Dict):
        self.app_list.update_stats(
            stats.get("total", 0),
            stats.get("suspended", 0),
            stats.get("active", 0),
        )

    # ============================================================
    # 应用选择与操作
    # ============================================================
    def _on_app_selected(self, app_name: str):
        """左侧软件被点击"""
        if not app_name:
            # 全部 → 显示通知中心
            self._show_notifications()
            return

        # 检查是否 CodeBuddy Agent
        if app_name == "CodeBuddy Agent":
            self._show_codebuddy_agent()
            return

        # 检查是否有预定义的 AI 对话（千问/元宝/豆包）
        ai_provider = TARGET_APPS.get(app_name, {}).get("ai_provider")
        if ai_provider and ai_provider != "__codebuddy__":
            self._show_ai_chat(app_name, ai_provider)
            return

        # 检查是否用户手动添加到了聊天中
        if app_name in USER_CHAT_APPS:
            chat_info = USER_CHAT_APPS[app_name]
            chat_provider = chat_info.get("ai_provider", "")
            if chat_provider:
                self._show_ai_chat(app_name, chat_provider)
                return

        # 扫描到的应用或没有 AI 绑定的内置应用 → 显示详情面板
        self._show_app_detail(app_name)

    def _on_add_app_to_chat(self, app_name: str):
        """将应用添加到聊天面板（让其他 AI 服务商可以对话管理）"""
        self._show_add_to_chat_dialog(app_name)

    def _on_remove_app_from_chat(self, app_name: str):
        """将应用从聊天面板中移除"""
        if app_name in USER_CHAT_APPS:
            del USER_CHAT_APPS[app_name]
            self.app_list.set_chat_status(app_name, False)
            # 保存到配置
            self._save_user_chat_apps()

    def _show_add_to_chat_dialog(self, app_name: str):
        """显示'添加到聊天'对话框，让用户选择 AI 服务商"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"添加到聊天 — {app_name}")
        dialog.setFixedSize(420, 320)
        dialog.setStyleSheet(f"""
            QDialog {{ background: {COLOR['bg_primary']}; }}
            QLabel {{ color: {COLOR['text_primary']}; font-size: 13px; }}
            QPushButton {{ border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: bold; }}
            QGroupBox {{ color: {COLOR['text_primary']}; border: 1px solid {COLOR['bg_tertiary']};
                border-radius: 8px; margin-top: 16px; padding-top: 20px; font-size: 13px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title = QLabel(f"💬 将「{app_name}」添加到聊天")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR['accent_blue']};")
        layout.addWidget(title)

        desc = QLabel("选择一个 AI 服务商来管理此应用。\n配置 API Key 后，即可通过对话管理该应用的进程。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR['text_secondary']}; font-size: 12px;")
        layout.addWidget(desc)

        # AI 服务商选择
        provider_group = QGroupBox("AI 服务商")
        provider_layout = QVBoxLayout(provider_group)

        provider_combo = QComboBox()
        provider_combo.setStyleSheet(f"""
            QComboBox {{ background: {COLOR['bg_secondary']}; color: {COLOR['text_primary']};
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 6px; padding: 8px 12px; font-size: 13px; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{ background: {COLOR['bg_secondary']}; color: {COLOR['text_primary']};
                selection-background-color: {COLOR['sidebar_hover']}; border: 1px solid {COLOR['bg_tertiary']}; }}
        """)

        # 列出可用的 AI 服务商
        available_providers = []
        for key, cfg in AI_PROVIDERS.items():
            if key != "custom":
                has_key = self.ai_manager.has_key(key)
                status = " ✓" if has_key else " (未配置)"
                provider_combo.addItem(f"{cfg.name}{status}", key)
                available_providers.append(key)

        provider_layout.addWidget(provider_combo)
        layout.addWidget(provider_group)

        # 墓碑模式选择
        mode_group = QGroupBox("墓碑模式")
        mode_layout = QVBoxLayout(mode_group)

        mode_combo = QComboBox()
        mode_combo.setStyleSheet(f"""
            QComboBox {{ background: {COLOR['bg_secondary']}; color: {COLOR['text_primary']};
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 6px; padding: 8px 12px; font-size: 13px; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{ background: {COLOR['bg_secondary']}; color: {COLOR['text_primary']};
                selection-background-color: {COLOR['sidebar_hover']}; border: 1px solid {COLOR['bg_tertiary']}; }}
        """)
        mode_combo.addItem("挂起（冻结线程，保留状态）", "suspend")
        mode_combo.addItem("Kill（关闭进程，彻底释放内存）", "kill")
        mode_layout.addWidget(mode_combo)

        # 根据应用类型默认选择墓碑模式
        app_info = TARGET_APPS.get(app_name, {})
        if app_info.get("tombstone_mode") == "kill":
            mode_combo.setCurrentIndex(1)

        layout.addWidget(mode_group)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['text_secondary']};
                border: 1px solid {COLOR['bg_tertiary']}; }}
            QPushButton:hover {{ background: {COLOR['bg_secondary']}; }}
        """)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        add_btn = QPushButton("添加到聊天")
        add_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_blue']}; color: {COLOR['bg_primary']}; border: none; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; }}
        """)

        def on_add():
            provider_key = provider_combo.currentData()
            tombstone_mode = mode_combo.currentData()
            if not provider_key:
                return

            # 检查是否已配置 API Key
            if not self.ai_manager.has_key(provider_key):
                reply = QMessageBox.question(
                    dialog, "未配置 API Key",
                    f"该 AI 服务商尚未配置 API Key。\n\n是否现在去配置？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    dialog.accept()
                    self._show_agent_settings(provider_key)
                    return
                else:
                    return

            # 保存到用户聊天应用列表
            USER_CHAT_APPS[app_name] = {
                "ai_provider": provider_key,
                "tombstone_mode": tombstone_mode,
            }
            # 同时更新 TARGET_APPS（如果已存在则更新 ai_provider）
            if app_name in TARGET_APPS:
                TARGET_APPS[app_name]["ai_provider"] = provider_key
                TARGET_APPS[app_name]["tombstone_mode"] = tombstone_mode

            self.app_list.set_chat_status(app_name, True)
            self._save_user_chat_apps()
            dialog.accept()

            # 自动切换到该 AI 聊天面板
            self._show_ai_chat(app_name, provider_key)

        add_btn.clicked.connect(on_add)
        btn_layout.addWidget(add_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    def _save_user_chat_apps(self):
        """持久化用户手动添加的聊天应用到配置文件"""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
            data["user_chat_apps"] = USER_CHAT_APPS
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_user_chat_apps(self):
        """从配置文件加载用户手动添加的聊天应用"""
        try:
            if CONFIG_FILE.exists():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                saved = data.get("user_chat_apps", {})
                USER_CHAT_APPS.clear()
                USER_CHAT_APPS.update(saved)
                # 同步到 TARGET_APPS
                for app_name, info in USER_CHAT_APPS.items():
                    if app_name in TARGET_APPS:
                        TARGET_APPS[app_name]["ai_provider"] = info.get("ai_provider")
                        TARGET_APPS[app_name]["tombstone_mode"] = info.get("tombstone_mode", "suspend")
        except Exception:
            pass

    def _show_notifications(self):
        self._current_view = "notifications"
        self.right_stack.setCurrentIndex(0)

    def _show_codebuddy_agent(self):
        """显示 CodeBuddy Agent 面板"""
        self._current_view = "codebuddy_agent"
        self.right_stack.setCurrentIndex(self._codebuddy_page_index)

    def _show_ai_chat(self, app_name: str, provider_key: str):
        """显示 AI 对话面板"""
        self._current_view = "ai_chat"

        if provider_key not in self.ai_panels:
            provider_name = AI_PROVIDERS.get(provider_key)
            provider_name = provider_name.name if provider_name else app_name
            panel = AIChatPanel(provider_key, provider_name)
            panel.message_sent.connect(self._on_ai_message)
            panel.settings_requested.connect(self._show_agent_settings)
            idx = self.right_stack.addWidget(panel)
            self.ai_panels[provider_key] = panel
            self._ai_panel_indices[provider_key] = idx

            # 自动从 ai_manager 同步 API Key 到 agent_manager
            existing_key = self.ai_manager.get_api_key(provider_key)
            if existing_key:
                self._sync_agent_config(provider_key, existing_key)

        idx = self._ai_panel_indices.get(provider_key, 2)
        self.right_stack.setCurrentIndex(idx)

    def _show_app_detail(self, app_name: str):
        """显示软件详情面板"""
        self._current_view = "app_detail"
        pids = self._find_pids_for_app(app_name)
        is_running = len(pids) > 0
        is_suspended = any(self.process_mgr.is_suspended(p) for p in pids)

        # 获取墓碑模式
        tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")

        info_lines = [f"软件: {app_name}"]
        if tombstone_mode == "kill":
            info_lines.append(f"墓碑模式: Kill（关闭进程彻底释放内存）")
        else:
            info_lines.append(f"墓碑模式: 挂起（冻结线程保留状态）")
        if is_running:
            info_lines.append(f"进程数: {len(pids)}")
            total_mem = 0.0
            for p in pids:
                try:
                    total_mem += psutil.Process(p).memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
            info_lines.append(f"内存占用: {total_mem:.1f} MB")
            status = "已墓碑 ❄️" if is_suspended else "运行中 ▶"
            info_lines.append(f"状态: {status}")
        else:
            info_lines.append("状态: 未启动")

        self.detail_panel.set_app(app_name, "\n".join(info_lines), is_running, is_suspended, tombstone_mode)

        # 切换到详情页（索引 2）
        # 先确保 detail_panel 在正确位置
        detail_idx = self.right_stack.indexOf(self.detail_panel)
        self.right_stack.setCurrentIndex(detail_idx)

    def _on_ai_message(self, provider_key: str, message: str):
        """处理 AI 消息发送（优先使用 Agent 模式）"""
        panel = self.ai_panels.get(provider_key)

        def do_chat():
            # 尝试使用 Agent（带 Function Calling）
            agent_reply = self.agent_manager.chat(provider_key, message)
            if agent_reply and not agent_reply.startswith("[智能体未配置"):
                # Agent 模式成功
                if panel:
                    QTimer.singleShot(0, lambda: panel.add_message("assistant", agent_reply))
                return

            # 降级到普通 AI 对话模式
            reply = self.ai_manager.chat(provider_key, message)
            if panel:
                QTimer.singleShot(0, lambda: panel.add_message("assistant", reply))

        t = threading.Thread(target=do_chat, daemon=True)
        t.start()

    def _wake_app(self, app_name: str):
        """唤醒软件"""
        tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")
        pids = self._find_pids_for_app(app_name)

        if tombstone_mode == "kill":
            # Kill 模式：如果进程不存在则重新启动
            if not pids:
                self._launch_app(app_name)
            else:
                # 进程还在，可能是被短暂唤醒后还没被杀
                self._bring_to_front(pids[0])
        else:
            # 挂起模式：恢复线程
            for pid in pids:
                if self.process_mgr.is_suspended(pid):
                    self.process_mgr.resume(pid)
            if pids:
                # 尝试将窗口带到前台
                self._bring_to_front(pids[0])
            else:
                # 没运行则启动
                self._launch_app(app_name)

    def _on_toast_wake_app(self, app_name: str):
        """点击弹幕 → 唤醒软件 + 带到前台"""
        tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")
        pids = self._find_pids_for_app(app_name)

        if tombstone_mode == "kill":
            # Kill 模式：重新启动软件
            if not pids:
                self._launch_app(app_name)
            else:
                self._bring_to_front(pids[0])
            return

        if pids:
            for pid in pids:
                if self.process_mgr.is_suspended(pid):
                    self.process_mgr.resume(pid)
                # 设置短暂唤醒 10 秒，防止立即又被墓碑
                self.process_mgr.set_transient_wake(pid, 10.0)
            self._bring_to_front(pids[0])
        else:
            # 软件没运行，尝试启动
            self._launch_app(app_name)

    def _suspend_app(self, app_name: str):
        """墓碑（冻结/kill）软件"""
        tombstone_mode = TARGET_APPS.get(app_name, {}).get("tombstone_mode", "suspend")
        pids = self._find_pids_for_app(app_name)

        if tombstone_mode == "kill":
            # Kill 模式：直接杀进程
            for pid in pids:
                self._kill_pid(pid)
                self.process_mgr.remove_managed_pid(pid)
        else:
            # 挂起模式：冻结线程
            for pid in pids:
                if not self.process_mgr.is_suspended(pid):
                    self.process_mgr.suspend(pid)

    def _kill_app(self, app_name: str):
        """结束软件进程"""
        pids = self._find_pids_for_app(app_name)
        for pid in pids:
            try:
                p = psutil.Process(pid)
                p.terminate()
            except Exception:
                pass

    def _bring_to_front(self, pid: int):
        """将进程的主窗口带到前台"""
        try:
            import win32gui, win32con

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
            def enum_proc(hwnd, lParam):
                pid_out = ctypes.c_int()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
                if pid_out.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    return False
                return True

            ctypes.windll.user32.EnumWindows(enum_proc, 0)
        except Exception:
            pass

    def _launch_app(self, app_name: str):
        """启动软件（如果未运行）"""
        if app_name not in TARGET_APPS:
            return
        exe_hint = TARGET_APPS[app_name].get("exe_hint", "")
        if not exe_hint:
            return
        try:
            import subprocess
            # 使用 CREATE_NO_WINDOW 避免弹出终端窗口
            subprocess.Popen(
                exe_hint,
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # 写入日志
            try:
                debug_log = CONFIG_DIR / "tombstone_debug.log"
                with open(debug_log, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().isoformat()}] 启动软件: {app_name} ({exe_hint})\n")
            except Exception:
                pass
        except Exception:
            pass

    # ============================================================
    # Agent 设置
    # ============================================================
    def _sync_agent_config(self, provider_key: str, api_key: str):
        """从 ai_manager 的 API Key 同步到 agent_manager"""
        from ai_chat import AI_PROVIDERS
        provider = AI_PROVIDERS.get(provider_key)
        if not provider or not api_key:
            return

        # 检查是否是自定义 API
        if provider_key == "custom":
            custom_url = self.ai_manager.get_api_key("custom_url") or ""
            custom_model = self.ai_manager.get_api_key("custom_model") or ""
            if custom_url:
                self.agent_manager.configure_agent(
                    agent_id=provider_key,
                    api_url=custom_url,
                    api_key=api_key,
                    model=custom_model or "gpt-3.5-turbo",
                )
        else:
            self.agent_manager.configure_agent(
                agent_id=provider_key,
                api_url=provider.api_url,
                api_key=api_key,
                model=provider.default_model,
                extra_headers=dict(provider.headers),
            )

    def _show_agent_settings(self, provider_key: str):
        """显示 Agent 设置对话框"""
        provider = AI_PROVIDERS.get(provider_key)
        if not provider:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"智能体设置 — {provider.name}")
        dialog.setFixedSize(480, 380)
        dialog.setStyleSheet(f"""
            QDialog {{ background: {COLOR['bg_primary']}; }}
            QLabel {{ color: {COLOR['text_primary']}; font-size: 13px; }}
            QLineEdit {{ background: {COLOR['bg_secondary']}; color: {COLOR['text_primary']};
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 6px; padding: 8px 12px; font-size: 13px; }}
            QLineEdit:focus {{ border: 1px solid {COLOR['accent_blue']}; }}
            QPushButton {{ border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: bold; }}
            QGroupBox {{ color: {COLOR['text_primary']}; border: 1px solid {COLOR['bg_tertiary']};
                border-radius: 8px; margin-top: 16px; padding-top: 20px; font-size: 13px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel(f"🤖 {provider.name} 智能体配置")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLOR['accent_blue']};")
        layout.addWidget(title)

        desc = QLabel("填入 API Key 后，智能体即可管理你的电脑。支持 Function Calling 的模型效果最佳。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR['text_secondary']}; font-size: 12px;")
        layout.addWidget(desc)

        # API Key
        key_group = QGroupBox("API Key")
        key_layout = QVBoxLayout(key_group)

        key_label = QLabel("API Key / Token")
        key_label.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 11px;")
        key_layout.addWidget(key_label)

        key_input = QLineEdit()
        key_input.setEchoMode(QLineEdit.Password)
        existing_key = self.ai_manager.get_api_key(provider_key)
        if existing_key:
            key_input.setText(existing_key)
            key_input.setPlaceholderText("已配置 (隐藏)")
        else:
            key_input.setPlaceholderText("请输入 API Key...")
        key_layout.addWidget(key_input)

        layout.addWidget(key_group)

        # 模型设置
        model_group = QGroupBox("模型设置")
        model_layout = QVBoxLayout(model_group)

        model_label = QLabel("模型名称")
        model_label.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 11px;")
        model_layout.addWidget(model_label)

        model_input = QLineEdit()
        model_input.setText(provider.default_model)
        model_input.setPlaceholderText("例如: gpt-4o, deepseek-chat, qwen-plus")
        # 加载已保存的自定义模型
        saved_model = self.ai_manager.get_api_key(f"{provider_key}_model")
        if saved_model:
            model_input.setText(saved_model)
        model_layout.addWidget(model_input)

        layout.addWidget(model_group)

        # 自定义 API URL（仅对 custom 显示）
        url_group = QGroupBox("API 端点")
        url_layout = QVBoxLayout(url_group)

        url_input = QLineEdit()
        url_input.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        if provider_key == "custom":
            custom_url = self.ai_manager.get_api_key("custom_url")
            if custom_url:
                url_input.setText(custom_url)
        else:
            url_input.setText(provider.api_url)
            url_input.setReadOnly(True)
        url_layout.addWidget(url_input)

        layout.addWidget(url_group)

        # 提示
        hint = QLabel("💡 支持所有 OpenAI 兼容 API（千问/豆包/DeepSeek/OpenAI 等）\n配置后可在对话中让 AI 帮你管理软件进程。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 11px;")
        layout.addWidget(hint)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['text_secondary']};
                border: 1px solid {COLOR['bg_tertiary']}; }}
            QPushButton:hover {{ background: {COLOR['bg_secondary']}; }}
        """)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("保存并启用")
        save_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_blue']}; color: {COLOR['bg_primary']};
                border: none; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; }}
        """)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

        def on_save():
            api_key = key_input.text().strip()
            model = model_input.text().strip()
            api_url = url_input.text().strip()

            if not api_key:
                QMessageBox.warning(dialog, "提示", "请输入 API Key")
                return

            # 保存到 ai_manager
            self.ai_manager.set_api_key(provider_key, api_key)
            self.ai_manager.set_api_key(f"{provider_key}_model", model)
            if provider_key == "custom" and api_url:
                self.ai_manager.set_api_key("custom_url", api_url)
                self.ai_manager.set_api_key("custom_model", model)

            # 同步到 agent_manager
            if provider_key == "custom":
                self.agent_manager.configure_agent(
                    agent_id=provider_key,
                    api_url=api_url,
                    api_key=api_key,
                    model=model,
                )
            else:
                self.agent_manager.configure_agent(
                    agent_id=provider_key,
                    api_url=provider.api_url,
                    api_key=api_key,
                    model=model,
                    extra_headers=dict(provider.headers),
                )

            QMessageBox.information(dialog, "成功", f"{provider.name} 智能体已就绪！\n\n你现在可以在对话中让它帮你管理软件了。")
            dialog.accept()

        save_btn.clicked.connect(on_save)

        dialog.exec()

    # ============================================================
    # 窗口关闭
    # ============================================================
    def closeEvent(self, event):
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide()
            self.tray.showMessage("itent", "itent 仍在后台运行，点击托盘图标可恢复窗口。",
                                   QSystemTrayIcon.Information, 2000)
            event.ignore()
        else:
            self._cleanup_and_exit()
            event.accept()

    def _cleanup_and_exit(self):
        try:
            # 停止 Node.js 后端
            self._stop_node_server()
            if hasattr(self, 'notification_hub') and self.notification_hub:
                self.notification_hub.stop()
            if hasattr(self, 'toast_mgr') and self.toast_mgr:
                self.toast_mgr.clear_all()
            if hasattr(self, 'monitor_thread') and self.monitor_thread:
                self.monitor_thread.stop()
            if hasattr(self, 'system_monitor') and self.system_monitor:
                self.system_monitor.stop()
            if hasattr(self, 'policy_timer') and self.policy_timer.isActive():
                self.policy_timer.stop()
            if hasattr(self, 'app_state_timer') and self.app_state_timer.isActive():
                self.app_state_timer.stop()
            if hasattr(self, 'process_mgr'):
                # 恢复所有已挂起的进程（仅挂起模式的）
                for pid in list(self.process_mgr._suspended.keys()):
                    try:
                        self.process_mgr.resume(pid)
                    except Exception:
                        pass
                # 额外安全：确保所有被管理的线程都恢复了
                for pid in list(self.process_mgr._suspended_threads.keys()):
                    try:
                        self.process_mgr.resume(pid)
                    except Exception:
                        pass
        except Exception:
            pass

    def real_exit(self):
        self._cleanup_and_exit()
        QApplication.quit()


# ============================================================
# [11] 图标生成
# ============================================================
def _generate_app_icon():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if ICON_PATH.exists():
        return
    try:
        from PySide6.QtGui import QImage, QPainter, QColor, QFont
        from PySide6.QtCore import Qt, QRect
        size = 256
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor("#000000"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI", 72)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        rect = QRect(0, 0, size, size)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "itent")
        painter.end()
        img.save(str(ICON_PATH), "PNG")
    except Exception as e:
        print(f"[itent] 图标生成失败: {e}")


# ============================================================
# [12] main()
# ============================================================
def _log(msg: str):
    """追加写入启动日志"""
    try:
        log_file = CONFIG_DIR / "itent_startup.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _log("itent 启动中...")
    print("[itent] 启动中...", flush=True)

    # 管理员权限
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False

    if not is_admin:
        # 使用 Windows 原生 MessageBox（不依赖 QApplication）
        ret = ctypes.windll.user32.MessageBoxW(
            0,
            "本程序需要管理员权限才能冻结进程。\n是否立即以管理员身份重启？",
            "itent - 需要管理员权限",
            0x00000004 | 0x00000030  # MB_YESNO | MB_ICONWARNING
        )
        if ret == 6:  # IDYES = 6
            # PyInstaller 打包后 sys.executable 是 itent.exe 自身
            exe_path = sys.executable
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, None, None, 1)
            sys.exit(0)
        else:
            sys.exit(0)  # 用户选 No 则退出

    _log("创建 QApplication...")
    print("[itent] 创建 QApplication...", flush=True)

    try:
        app = QApplication(sys.argv)
    except Exception as e:
        msg = f"QApplication 创建失败: {e}\n{traceback.format_exc()}"
        _log(msg)
        print(msg, flush=True)
        ctypes.windll.user32.MessageBoxW(0, msg[:500], "itent - 致命错误", 0x10)
        sys.exit(1)

    app.setStyle("Fusion")
    app.setApplicationName("itent")

    # 图标生成必须在 QApplication 之后（打包后 Qt 需要 QApplication 先初始化）
    try:
        _generate_app_icon()
    except Exception as e:
        _log(f"[ERROR] 图标生成失败: {e}")
        print(f"[itent] 图标生成失败: {e}", flush=True)

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLOR["bg_primary"]))
    palette.setColor(QPalette.WindowText, QColor(COLOR["text_primary"]))
    palette.setColor(QPalette.Base, QColor(COLOR["bg_secondary"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLOR["bg_tertiary"]))
    palette.setColor(QPalette.Text, QColor(COLOR["text_primary"]))
    palette.setColor(QPalette.Button, QColor(COLOR["bg_secondary"]))
    palette.setColor(QPalette.ButtonText, QColor(COLOR["text_primary"]))
    palette.setColor(QPalette.Highlight, QColor(COLOR["accent_blue"]))
    palette.setColor(QPalette.HighlightedText, QColor(COLOR["bg_tertiary"]))
    app.setPalette(palette)

    _log("创建 MainWindow...")
    print("[itent] 创建 MainWindow...", flush=True)

    try:
        window = MainWindow()
        window.show()
        print("[itent] 窗口已显示，进入事件循环", flush=True)
        sys.exit(app.exec())
    except Exception as e:
        err_detail = f"主窗口崩溃: {e}\n{traceback.format_exc()}"
        _log(err_detail)
        print(err_detail, flush=True)
        # 弹出错误框
        log_path = CONFIG_DIR / "itent_startup.log"
        ctypes.windll.user32.MessageBoxW(
            0,
            f"itent 启动失败:\n{str(e)}\n\n详情已写入:\n{log_path}",
            "itent - 错误",
            0x00000000 | 0x00000010  # MB_OK | MB_ICONERROR
        )
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 打印到控制台
        import traceback as _tb
        print(f"\n[itent] 严重崩溃: {e}", flush=True)
        _tb.print_exc()
        # 写入崩溃日志
        log_path = Path.home() / ".itent" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        crash_info = f"{datetime.now().isoformat()}\n崩溃: {e}\n{_tb.format_exc()}\n"
        try:
            log_path.write_text(crash_info, encoding="utf-8")
        except Exception:
            pass
        # 弹出错误框（如果 ctypes 可用）
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"itent 严重崩溃:\n{str(e)}\n\n详情已写入:\n{log_path}",
                "itent - 致命错误",
                0x00000000 | 0x00000010  # MB_OK | MB_ICONERROR
            )
        except Exception:
            pass
        sys.exit(1)
