#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# policy_engine.py - 智能墓碑策略决策引擎
# ============================================================
# 决策优先级（从高到低）：
#   1. 核心系统进程 → 永不墓碑
#   2. 白名单进程 → 永不墓碑
#   3. 特定规则 "never_suspend" 匹配 → 永不墓碑
#   4. 特定规则 "transient_awake" 匹配 → 暂时唤醒
#   5. 通用规则匹配（音频/网络/CPU）→ 暂时不墓碑
#   6. 其他 → 执行墓碑
# ============================================================

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import psutil
import ctypes
import ctypes.wintypes

from detectors import AudioDetector, NetworkDetector


# ============================================================
# 默认特定软件规则
# ============================================================
DEFAULT_APP_RULES = {
    "WeChat": {
        "process_names": ["WeChat.exe"],
        "tombstone_mode": "suspend",
        "never_suspend": {
            "description": "语音/视频通话时不墓碑",
            "detect_window_class": ["WeChatVoipWindow", "VoipWindow"],
            "detect_child_process": ["WeChatVoipHelper.exe"],
        },
        "transient_awake": {
            "description": "新消息通知时短暂唤醒",
            "wake_duration_sec": 4,
            "detect_window_title_contains": ["[消息]"],
        },
    },
    "QQ": {
        "process_names": ["QQ.exe", "QQGuild.exe"],
        "tombstone_mode": "suspend",
        "never_suspend": {
            "description": "语音/视频通话时不墓碑",
            "detect_window_class": ["QQVoipWindow"],
            "detect_child_process": ["QQVoipHelper.exe"],
        },
        "transient_awake": {
            "description": "新消息时短暂唤醒",
            "wake_duration_sec": 3,
            "detect_window_title_flash": True,
        },
    },
    "DingTalk": {
        "process_names": ["DingTalk.exe"],
        "tombstone_mode": "suspend",
        "never_suspend": {
            "description": "语音/视频通话时不墓碑",
            "detect_window_class": ["DingTalkVoip"],
            "detect_child_process": ["DingTalkHelper.exe"],
        },
        "transient_awake": {
            "description": "新消息通知时短暂唤醒",
            "wake_duration_sec": 4,
            "detect_window_title_contains": ["钉钉"],
        },
    },
    "TencentMeeting": {
        "process_names": ["wemeet.exe", "TencentMeeting.exe"],
        "tombstone_mode": "suspend",
        "never_suspend": {
            "description": "会议进行中全程不墓碑",
            "detect_always": True,
        },
        "transient_awake": None,
    },
    "Feishu": {
        "process_names": ["Feishu.exe"],
        "tombstone_mode": "suspend",
        "never_suspend": {
            "description": "语音/视频通话时不墓碑",
            "detect_window_class": ["FeishuVoip"],
            "detect_child_process": ["FeishuHelper.exe"],
        },
        "transient_awake": {
            "description": "新消息时短暂唤醒",
            "wake_duration_sec": 3,
            "detect_window_title_contains": ["飞书"],
        },
    },
    "Qianwen": {
        "process_names": ["qianwen.exe"],
        "tombstone_mode": "kill",
        "never_suspend": {
            "description": "千问AI助手：有可见窗口时不墓碑",
            "detect_visible_window": True,
        },
        "transient_awake": {
            "description": "收到通知时短暂唤醒",
            "wake_duration_sec": 5,
            "detect_window_title_contains": ["千问", "Qianwen", "通义"],
        },
    },
    "Doubao": {
        "process_names": ["doubao.exe"],
        "tombstone_mode": "kill",
        "never_suspend": {
            "description": "豆包AI助手：有可见窗口时不墓碑",
            "detect_visible_window": True,
        },
        "transient_awake": {
            "description": "收到通知时短暂唤醒",
            "wake_duration_sec": 5,
            "detect_window_title_contains": ["豆包", "Doubao"],
        },
    },
    "Yuanbao": {
        "process_names": ["yuanbao.exe"],
        "tombstone_mode": "kill",
        "never_suspend": {
            "description": "元宝AI助手：有可见窗口时不墓碑",
            "detect_visible_window": True,
        },
        "transient_awake": {
            "description": "收到通知时短暂唤醒",
            "wake_duration_sec": 5,
            "detect_window_title_contains": ["元宝", "Yuanbao"],
        },
    },
    "ChatGPT": {
        "process_names": ["chatgpt.exe"],
        "tombstone_mode": "kill",
        "never_suspend": {
            "description": "ChatGPT：有可见窗口时不墓碑",
            "detect_visible_window": True,
        },
        "transient_awake": {
            "description": "收到通知时短暂唤醒",
            "wake_duration_sec": 5,
            "detect_window_title_contains": ["ChatGPT"],
        },
    },
    "Copilot": {
        "process_names": ["microsoftcopilot.exe"],
        "tombstone_mode": "kill",
        "never_suspend": {
            "description": "Copilot：有可见窗口时不墓碑",
            "detect_visible_window": True,
        },
        "transient_awake": {
            "description": "收到通知时短暂唤醒",
            "wake_duration_sec": 5,
            "detect_window_title_contains": ["Copilot"],
        },
    },
}


# ============================================================
# TombstonePolicyEngine - 墓碑策略决策引擎
# ============================================================
class TombstonePolicyEngine:
    """
    智能墓碑策略决策引擎。
    根据特定软件规则和通用规则，决定是否应该挂起某个进程。
    """

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.rules_file = config_dir / "app_rules.json"
        self.rules: Dict[str, Any] = {}
        self.audio_detector = AudioDetector()
        self.network_detector = NetworkDetector()
        self.cpu_threshold = 5.0       # CPU 阈值（%）
        self.network_threshold = 10.0  # 网络活动阈值（KB/s）
        self._lock = threading.Lock()
        self._load_rules()

    def _load_rules(self):
        """加载规则配置，不存在则创建默认配置"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if self.rules_file.exists():
            try:
                self.rules = json.loads(self.rules_file.read_text(encoding="utf-8"))
            except Exception:
                self.rules = dict(DEFAULT_APP_RULES)
                self._save_rules()
        else:
            self.rules = dict(DEFAULT_APP_RULES)
            self._save_rules()

    def _save_rules(self):
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.rules_file.write_text(
                json.dumps(self.rules, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def reload_rules(self):
        """重新加载规则配置"""
        with self._lock:
            self._load_rules()

    def set_cpu_threshold(self, value: float):
        with self._lock:
            self.cpu_threshold = value

    def set_network_threshold(self, value: float):
        with self._lock:
            self.network_threshold = value

    def should_suspend(self, pid: int,
                        is_core: bool,
                        is_whitelisted: bool) -> Tuple[bool, str]:
        """
        决策是否应该挂起进程。
        返回 (should_suspend, reason)
        reason: 原因字符串，用于 UI 显示和日志
        """
        # 1. 核心系统进程 → 永不墓碑
        if is_core:
            return False, "core_process"

        # 2. 白名单进程 → 永不墓碑
        if is_whitelisted:
            return False, "whitelisted"

        # 获取进程名
        try:
            p = psutil.Process(pid)
            proc_name = p.name()
            proc_name_lower = proc_name.lower()
        except Exception:
            return True, "ok_to_suspend"  # 无法访问的进程可以挂起

        # 3. 前台窗口检测 → 用户正在使用的进程绝不挂起
        if self._is_foreground_process(pid):
            return False, "foreground_active"

        # 4. 特定规则匹配
        rule_result = self._check_app_rules(pid, proc_name_lower)
        if rule_result:
            return rule_result

        # 5. 通用规则匹配
        general_result = self._check_general_rules(pid)
        if general_result:
            return general_result

        # 6. 可以墓碑
        return True, "ok_to_suspend"

    def _check_app_rules(self, pid: int, proc_name_lower: str) -> Optional[Tuple[bool, str]]:
        """检查特定软件规则。返回 (should_suspend, reason) 或 None"""
        with self._lock:
            rules = self.rules

        for app_name, app_rule in rules.items():
            process_names = app_rule.get("process_names", [])
            if not any(pn.lower() == proc_name_lower for pn in process_names):
                continue

            # 检查 never_suspend 规则
            never_rule = app_rule.get("never_suspend")
            if never_rule:
                if self._match_never_suspend(pid, never_rule):
                    return False, f"never_suspend:{app_name.lower()}"

            # 检查 transient_awake 规则
            transient_rule = app_rule.get("transient_awake")
            if transient_rule:
                if self._match_transient_awake(pid, transient_rule):
                    return False, f"transient_awake:{app_name.lower()}"

        return None

    def _match_never_suspend(self, pid: int, rule: Dict) -> bool:
        """匹配 never_suspend 规则"""
        # detect_always：始终不墓碑
        if rule.get("detect_always"):
            return True

        # detect_visible_window：有可见窗口时不墓碑
        if rule.get("detect_visible_window"):
            hwnd = self._find_app_window(pid)
            if hwnd:
                return True

        # 检测窗口类名
        class_names = rule.get("detect_window_class", [])
        if class_names:
            hwnd = self._find_app_window(pid)
            if hwnd:
                for cn in class_names:
                    actual_cn = self._get_window_class(hwnd)
                    if cn.lower() in actual_cn.lower():
                        return True

        # 检测子进程
        child_procs = rule.get("detect_child_process", [])
        if child_procs:
            try:
                p = psutil.Process(pid)
                for child in p.children(recursive=True):
                    if child.name() in child_procs:
                        return True
            except Exception:
                pass

        return False

    def _match_transient_awake(self, pid: int, rule: Dict) -> bool:
        """匹配 transient_awake 规则"""
        # 检测窗口标题包含关键字
        title_keywords = rule.get("detect_window_title_contains", [])
        if title_keywords:
            hwnd = self._find_app_window(pid)
            if hwnd:
                title = self._get_window_title(hwnd)
                for kw in title_keywords:
                    if kw in title:
                        return True

        # 检测窗口标题闪烁（通过检测窗口文本变化，简化版）
        if rule.get("detect_window_title_flash"):
            # 简化实现：检测窗口标题是否包含通知标记
            hwnd = self._find_app_window(pid)
            if hwnd:
                title = self._get_window_title(hwnd)
                if "[" in title or "【" in title or "*" in title:
                    return True

        return False

    def _check_general_rules(self, pid: int) -> Optional[Tuple[bool, str]]:
        """检查通用规则。返回 (should_suspend, reason) 或 None"""
        # 音频输出检测
        if self.audio_detector.is_playing_audio(pid):
            return False, "active_audio"

        # 网络活动检测
        net_active = self.network_detector.is_network_active(pid, self.network_threshold)
        if net_active:
            return False, "active_network"

        # CPU 阈值检测
        try:
            p = psutil.Process(pid)
            cpu = p.cpu_percent(interval=0.05)
            if cpu > self.cpu_threshold:
                return False, "high_cpu"
        except Exception:
            pass

        return None

    # ============================================================
    # Win32 窗口检测辅助方法
    # ============================================================
    @staticmethod
    def _get_foreground_pid() -> Optional[int]:
        """获取当前前台窗口所属的进程 PID"""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                pid = ctypes.c_int()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                return pid.value if pid.value > 0 else None
        except Exception:
            pass
        return None

    @staticmethod
    def _is_foreground_process(pid: int) -> bool:
        """检查进程是否拥有当前前台窗口（用户正在使用）"""
        foreground_pid = TombstonePolicyEngine._get_foreground_pid()
        if foreground_pid is None:
            return False
        # 检查前台窗口是否属于该进程或其子进程
        if foreground_pid == pid:
            return True
        try:
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                if child.pid == foreground_pid:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _find_app_window(pid: int) -> Optional[int]:
        """查找进程的主窗口句柄"""
        result = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
        def enum_proc(hwnd, lParam):
            pid_out = ctypes.c_int()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
            if pid_out.value == pid:
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    result.append(hwnd)
            return True

        ctypes.windll.user32.EnumWindows(enum_proc, 0)
        return result[0] if result else None

    @staticmethod
    def _get_window_class(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value or ""

    @staticmethod
    def _get_window_title(hwnd: int) -> str:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
