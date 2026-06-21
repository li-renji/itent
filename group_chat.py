#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# group_chat.py - 飞书风格 AI 群聊面板
# ============================================================
# 功能：
#   - 多个 AI 在同一个聊天室中互相交流
#   - 用户发送消息，选中的 AI 依次回复
#   - AI 能看到之前的完整对话历史
#   - 支持 @ 提及特定 AI
# ============================================================

import json
import threading
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QLineEdit, QPushButton, QFrame, QCheckBox, QSizePolicy,
    QSpacerItem, QMenu,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QFont

from ai_chat import AI_PROVIDERS, AIChatManager, AIChatSession


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
    "accent_pink":   "#f5c2e7",
    "accent_peach":  "#fab387",
    "sidebar_bg":    "#1e1e2e",
    "sidebar_hover": "#313244",
    "sidebar_active":"#2a2a3e",
    "chat_bg":       "#1e1e2e",
    "chat_bubble_user": "#313244",
    "chat_bubble_ai":   "#252540",
}

# 每个 AI 的专属颜色
AI_COLORS = {
    "qianwen":  "#89b4fa",  # 蓝
    "doubao":   "#a6e3a1",  # 绿
    "yuanbao":  "#f9e2af",  # 黄
    "openai":   "#cba6f7",  # 紫
    "deepseek": "#94e2d5",  # 青
    "custom":   "#fab387",  # 橙
}

AI_EMOJI = {
    "qianwen":  "🌊",
    "doubao":   "🫘",
    "yuanbao":  "💰",
    "openai":   "🧠",
    "deepseek": "🔍",
    "custom":   "🔧",
}


class GroupChatBubble(QFrame):
    """群聊消息气泡"""
    def __init__(self, sender_name: str, content: str, is_user: bool = False, 
                 provider_key: str = "", parent=None):
        super().__init__(parent)
        self.sender_name = sender_name
        self.provider_key = provider_key
        self._is_user = is_user
        
        accent = AI_COLORS.get(provider_key, COLOR["accent_purple"])
        emoji = AI_EMOJI.get(provider_key, "🤖")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        
        # 发送者标签
        sender_label = QLabel(f"{emoji} {sender_name}")
        if is_user:
            sender_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {COLOR['accent_teal']};")
        else:
            sender_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {accent};")
        layout.addWidget(sender_label)
        
        # 消息内容
        msg = QLabel(content)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {COLOR['text_primary']}; font-size: 13px; padding: 2px 0;")
        msg.setTextFormat(Qt.PlainText)
        layout.addWidget(msg)
        
        # 时间戳
        ts = QLabel(datetime.now().strftime("%H:%M"))
        ts.setStyleSheet(f"font-size: 10px; color: {COLOR['text_muted']};")
        ts.setAlignment(Qt.AlignRight)
        layout.addWidget(ts)
        
        # 气泡样式
        if is_user:
            bg = COLOR["chat_bubble_user"]
            border_color = COLOR["accent_teal"]
        else:
            bg = COLOR["chat_bubble_ai"]
            border_color = accent
        
        self.setStyleSheet(f"""
            GroupChatBubble {{ 
                background: {bg}; 
                border: 1px solid {border_color}40;
                border-radius: 10px; 
                margin: 4px 8px; 
            }}
        """)
        
        # 用户消息右对齐
        if is_user:
            self.setFixedWidth(380)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        else:
            self.setFixedWidth(420)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)


class AIThinkingBubble(QFrame):
    """AI 思考中的动画气泡"""
    def __init__(self, provider_name: str, provider_key: str, parent=None):
        super().__init__(parent)
        self.provider_name = provider_name
        self.provider_key = provider_key
        self._dot_count = 0
        
        accent = AI_COLORS.get(provider_key, COLOR["accent_purple"])
        emoji = AI_EMOJI.get(provider_key, "🤖")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        
        self.label = QLabel(f"{emoji} {provider_name} 正在思考...")
        self.label.setStyleSheet(f"font-size: 12px; color: {accent}; font-style: italic;")
        layout.addWidget(self.label)
        
        self.setStyleSheet(f"""
            AIThinkingBubble {{ 
                background: {COLOR['chat_bubble_ai']}; 
                border: 1px dashed {accent}60;
                border-radius: 10px; 
                margin: 4px 8px; 
            }}
        """)
        
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(500)
    
    def _animate(self):
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        emoji = AI_EMOJI.get(self.provider_key, "🤖")
        self.label.setText(f"{emoji} {self.provider_name} 正在思考{dots}")
    
    def stop(self):
        self._timer.stop()
        self.setParent(None)
        self.deleteLater()


class AIGroupChatPanel(QWidget):
    """飞书风格 AI 群聊面板
    
    布局：
    ┌──────────────────────────────────────┐
    │  标题栏：📢 {群名}    [清空]         │
    ├──────────┬───────────────────────────┤
    │ 成员列表 │  消息区（滚动）            │
    │ ☑ 千问   │  [用户]: 大家好           │
    │ ☑ 豆包   │  [千问]: 你好！           │
    │ ☑ 元宝   │  [豆包]: 今天聊什么？     │
    │ ☑ OpenAI │                           │
    │ ☑ DeepS  │                           │
    │          │                           │
    ├──────────┴───────────────────────────┤
    │  [输入框]              [发送] [全体回复] │
    └──────────────────────────────────────┘
    """
    
    settings_requested = Signal(str)  # provider_key - 请求打开设置
    
    def __init__(self, group_name: str, ai_manager: AIChatManager):
        super().__init__()
        self.group_name = group_name
        self.ai_manager = ai_manager
        self._ai_members: Dict[str, bool] = {}  # provider_key -> enabled
        self._ai_sessions: Dict[str, AIChatSession] = {}  # provider_key -> session
        self._chat_history: List[Tuple[str, str, str]] = []  # [(sender_name, provider_key, content)]
        self._thinking_bubbles: List[AIThinkingBubble] = []
        self._is_talking = False  # 是否正在 AI 对话中
        self._init_ui()
        self._init_ai_members()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ---- 顶部标题栏 ----
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-bottom: 1px solid {COLOR['bg_tertiary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        
        title = QLabel(f"📢 {self.group_name} · AI 群聊")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {COLOR['accent_blue']};")
        h_layout.addWidget(title)
        h_layout.addStretch()
        
        # 管理成员按钮
        self.member_btn = QPushButton("👥 成员")
        self.member_btn.setFixedHeight(26)
        self.member_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['accent_teal']}; 
                border: 1px solid {COLOR['accent_teal']}; border-radius: 4px; font-size: 11px; padding: 2px 8px; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}30; }}
        """)
        self.member_btn.clicked.connect(self._toggle_member_panel)
        h_layout.addWidget(self.member_btn)
        
        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(50, 26)
        clear_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['text_muted']}; 
                border: 1px solid {COLOR['text_muted']}; border-radius: 4px; font-size: 11px; }}
            QPushButton:hover {{ color: {COLOR['accent_red']}; border-color: {COLOR['accent_red']}; }}
        """)
        clear_btn.clicked.connect(self.clear_chat)
        h_layout.addWidget(clear_btn)
        
        layout.addWidget(header)
        
        # ---- 主体：成员面板 + 聊天区 ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        
        # 成员侧边栏（可折叠）
        self.member_panel = QWidget()
        self.member_panel.setFixedWidth(200)
        self.member_panel.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-right: 1px solid {COLOR['bg_tertiary']};")
        self._member_layout = QVBoxLayout(self.member_panel)
        self._member_layout.setContentsMargins(8, 8, 8, 8)
        self._member_layout.setSpacing(4)
        
        member_title = QLabel("👥 AI 成员")
        member_title.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {COLOR['text_primary']}; padding: 4px 0;")
        self._member_layout.addWidget(member_title)
        
        # AI 成员复选框
        self._member_checkboxes: Dict[str, QCheckBox] = {}
        for key, cfg in AI_PROVIDERS.items():
            if key == "custom":
                continue
            cb = QCheckBox(cfg.name)
            emoji = AI_EMOJI.get(key, "🤖")
            cb.setText(f"{emoji} {cfg.name}")
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {COLOR['text_secondary']}; font-size: 12px; padding: 4px 2px; spacing: 6px; }}
                QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 3px; 
                    border: 1px solid {COLOR['bg_tertiary']}; background: {COLOR['bg_primary']}; }}
                QCheckBox::indicator:checked {{ background: {COLOR['accent_blue']}; border-color: {COLOR['accent_blue']}; }}
                QCheckBox::indicator:hover {{ border-color: {COLOR['accent_blue']}; }}
            """)
            cb.setChecked(self.ai_manager.has_key(key))
            cb.toggled.connect(lambda checked, k=key: self._on_member_toggled(k, checked))
            self._member_checkboxes[key] = cb
            self._ai_members[key] = self.ai_manager.has_key(key)
            self._member_layout.addWidget(cb)
            
            # 未配置 key 的显示提示
            if not self.ai_manager.has_key(key):
                hint = QLabel("   ⚠ 未配置 API Key")
                hint.setStyleSheet(f"color: {COLOR['text_muted']}; font-size: 10px; padding: 0 0 0 20px;")
                hint.setObjectName(f"hint_{key}")
                self._member_layout.addWidget(hint)
        
        # 设置按钮
        self._member_layout.addSpacing(8)
        settings_btn = QPushButton("⚙ 配置 API Keys")
        settings_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR['accent_teal']}; 
                border: 1px solid {COLOR['accent_teal']}; border-radius: 6px; 
                font-size: 11px; padding: 6px 12px; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}20; }}
        """)
        settings_btn.clicked.connect(lambda: self.settings_requested.emit("qianwen"))
        self._member_layout.addWidget(settings_btn)
        
        self._member_layout.addStretch()
        body.addWidget(self.member_panel)
        
        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {COLOR['bg_tertiary']};")
        body.addWidget(sep)
        
        # 聊天区域
        chat_container = QWidget()
        chat_container.setStyleSheet(f"background: {COLOR['chat_bg']};")
        c_layout = QVBoxLayout(chat_container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {COLOR['chat_bg']}; }}")
        
        self.chat_widget = QWidget()
        self.chat_widget.setStyleSheet(f"background: {COLOR['chat_bg']};")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(8, 12, 8, 12)
        self.chat_layout.setSpacing(2)
        self.chat_layout.addStretch()
        
        scroll.setWidget(self.chat_widget)
        c_layout.addWidget(scroll, 1)
        
        # 底部输入栏
        input_bar = QWidget()
        input_bar.setFixedHeight(56)
        input_bar.setStyleSheet(f"background: {COLOR['bg_secondary']}; border-top: 1px solid {COLOR['bg_tertiary']};")
        i_layout = QHBoxLayout(input_bar)
        i_layout.setContentsMargins(12, 8, 12, 8)
        i_layout.setSpacing(8)
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息，按 Enter 发送，Shift+Enter 换行...")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{ background: {COLOR['bg_primary']}; color: {COLOR['text_primary']}; 
                border: 1px solid {COLOR['bg_tertiary']}; border-radius: 8px; padding: 8px 12px; font-size: 13px; }}
            QLineEdit:focus {{ border-color: {COLOR['accent_blue']}; }}
        """)
        self.input_field.returnPressed.connect(self._send_message)
        i_layout.addWidget(self.input_field, 1)
        
        send_btn = QPushButton("发送")
        send_btn.setFixedSize(60, 32)
        send_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR['accent_blue']}; color: {COLOR['bg_primary']}; 
                border: none; border-radius: 6px; font-size: 12px; font-weight: bold; }}
            QPushButton:hover {{ background: {COLOR['accent_teal']}; }}
            QPushButton:disabled {{ background: {COLOR['text_muted']}; }}
        """)
        send_btn.clicked.connect(self._send_message)
        i_layout.addWidget(send_btn)
        
        c_layout.addWidget(input_bar)
        body.addWidget(chat_container, 1)
        layout.addLayout(body, 1)
        
        self._scroll_area = scroll
        self._send_btn = send_btn
    
    def _init_ai_members(self):
        """初始化 AI 成员（已配置 API Key 的自动加入）"""
        for key, cfg in AI_PROVIDERS.items():
            if key == "custom":
                continue
            if self.ai_manager.has_key(key):
                self._ai_members[key] = True
                self._create_session(key)
    
    def _on_member_toggled(self, provider_key: str, checked: bool):
        """成员复选框切换"""
        if checked and not self.ai_manager.has_key(provider_key):
            # 未配置 key，提示
            self._member_checkboxes[provider_key].setChecked(False)
            self.settings_requested.emit(provider_key)
            return
        self._ai_members[provider_key] = checked
        if checked:
            self._create_session(provider_key)
    
    def _create_session(self, provider_key: str):
        """为 AI 创建对话会话"""
        if provider_key in self._ai_sessions:
            return
        api_key = self.ai_manager.get_api_key(provider_key)
        if api_key:
            try:
                session = AIChatSession(provider_key, api_key)
                self._ai_sessions[provider_key] = session
            except Exception:
                pass
    
    def refresh_members(self):
        """刷新成员列表（API Key 变更后调用）"""
        for key, cb in self._member_checkboxes.items():
            has_key = self.ai_manager.has_key(key)
            cb.setEnabled(True)
            if has_key and not cb.isChecked():
                cb.setChecked(True)
                self._ai_members[key] = True
                self._create_session(key)
            # 更新提示
            hint = self.member_panel.findChild(QLabel, f"hint_{key}")
            if hint:
                hint.setVisible(not has_key)
    
    def _toggle_member_panel(self):
        """切换成员面板显示"""
        visible = self.member_panel.isVisible()
        self.member_panel.setVisible(not visible)
    
    def _send_message(self):
        """发送消息"""
        text = self.input_field.text().strip()
        if not text:
            return
        if self._is_talking:
            return
        
        self.input_field.clear()
        
        # 显示用户消息
        self._add_bubble("你", text, is_user=True, provider_key="")
        self._chat_history.append(("你", "", text))
        
        # 检查有哪些 AI 可用
        active_members = [k for k, v in self._ai_members.items() if v and k in self._ai_sessions]
        if not active_members:
            self._add_bubble("系统", "没有可用的 AI 成员。请先在左侧成员面板中配置 API Key 并勾选 AI 成员。", 
                           is_user=False, provider_key="")
            return
        
        # 启动 AI 接力对话
        self._is_talking = True
        self._send_btn.setEnabled(False)
        self._send_btn.setText("...")
        
        threading.Thread(target=self._run_ai_roundtable, args=(text, active_members), daemon=True).start()
    
    def _run_ai_roundtable(self, user_message: str, active_members: List[str]):
        """AI 圆桌会议：AI 轮流回复"""
        
        # 构建系统提示：告诉 AI 这是一个群聊
        system_prompt = f"""你正在一个名为「{self.group_name}」的 AI 群聊中参与对话。

群聊规则：
1. 你是群聊中的一名 AI 成员，请用自然、友好的语气参与讨论
2. 你可以回复用户的问题，也可以回应其他 AI 的发言
3. 回复要简洁（50-200 字），像真实群聊一样
4. 你可以用 @其他AI名称 的方式点名回应特定 AI
5. 保持对话流畅，不要重复前面的内容
6. 这是第 {len(self._chat_history)} 条消息之后的发言

当前对话上下文：
"""
        # 构建对话历史
        context_lines = []
        for i, (sender, pk, content) in enumerate(self._chat_history[-10:]):  # 最近10条
            if sender == "你":
                context_lines.append(f"[用户]: {content}")
            else:
                context_lines.append(f"[{sender}]: {content}")
        
        context = "\n".join(context_lines) if context_lines else f"[用户]: {user_message}"
        
        full_system = system_prompt + context + "\n\n请用中文回复，不要输出任何前缀标记。"
        
        # AI 轮流发言
        for i, member_key in enumerate(active_members):
            if member_key not in self._ai_sessions:
                continue
            
            cfg = AI_PROVIDERS.get(member_key)
            if not cfg:
                continue
            member_name = cfg.name
            
            # 显示"思考中"气泡
            QTimer.singleShot(0, lambda mk=member_key, mn=member_name: self._show_thinking(mn, mk))
            
            try:
                session = self._ai_sessions[member_key]
                # 每个 AI 独立会话，但共享对话历史
                reply = session.chat(f"[新消息] {user_message}", system_prompt=full_system)
                
                # 清理回复
                if reply and not reply.startswith("["):
                    reply = reply.strip()
                    if reply:
                        QTimer.singleShot(0, lambda mn=member_name, mk=member_key, r=reply: self._on_ai_reply(mn, mk, r))
                        self._chat_history.append((member_name, member_key, reply))
            except Exception as e:
                QTimer.singleShot(0, lambda mn=member_name, mk=member_key: self._on_ai_error(mn, mk, str(e)))
            
            # 移除思考气泡
            QTimer.singleShot(0, self._remove_all_thinking)
            
            # AI 之间短暂间隔（模拟真人打字）
            time.sleep(0.5)
        
        # 对话结束
        QTimer.singleShot(0, self._on_roundtable_done)
    
    def _show_thinking(self, provider_name: str, provider_key: str):
        """显示思考中气泡"""
        bubble = AIThinkingBubble(provider_name, provider_key)
        # 插入到 stretch 之前
        idx = self.chat_layout.count() - 1
        self.chat_layout.insertWidget(idx, bubble, alignment=Qt.AlignLeft)
        self._thinking_bubbles.append(bubble)
        self._scroll_bottom()
    
    def _remove_all_thinking(self):
        """移除所有思考中气泡"""
        for b in self._thinking_bubbles:
            b.stop()
        self._thinking_bubbles.clear()
    
    def _on_ai_reply(self, sender_name: str, provider_key: str, content: str):
        """AI 回复回调（主线程）"""
        self._add_bubble(sender_name, content, is_user=False, provider_key=provider_key)
    
    def _on_ai_error(self, sender_name: str, provider_key: str, error: str):
        """AI 错误回调"""
        self._add_bubble(sender_name, f"⚠️ 回复失败: {error}", is_user=False, provider_key=provider_key)
    
    def _on_roundtable_done(self):
        """圆桌会议结束"""
        self._is_talking = False
        self._send_btn.setEnabled(True)
        self._send_btn.setText("发送")
        self._remove_all_thinking()
    
    def _add_bubble(self, sender_name: str, content: str, is_user: bool = False, provider_key: str = ""):
        """添加消息气泡"""
        bubble = GroupChatBubble(sender_name, content, is_user, provider_key)
        
        # 用户消息右对齐，AI 消息左对齐
        if is_user:
            align = Qt.AlignRight
        else:
            align = Qt.AlignLeft
        
        idx = self.chat_layout.count() - 1
        self.chat_layout.insertWidget(idx, bubble, alignment=align)
        self._scroll_bottom()
    
    def _scroll_bottom(self):
        """滚动到底部"""
        QTimer.singleShot(100, lambda: self._scroll_area.verticalScrollBar().setValue(
            self._scroll_area.verticalScrollBar().maximum()
        ))
    
    def clear_chat(self):
        """清空聊天记录"""
        for i in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, (GroupChatBubble, AIThinkingBubble)):
                    w.setParent(None)
                    w.deleteLater()
        self._chat_history.clear()
        # 清除 AI 会话历史
        for s in self._ai_sessions.values():
            s.clear_history()
    
    def get_enabled_members(self) -> List[str]:
        """获取已启用的 AI 成员列表"""
        return [k for k, v in self._ai_members.items() if v]
