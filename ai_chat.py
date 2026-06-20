#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# ai_chat.py - 内置 AI 对话调用
# ============================================================
# 支持：千问 (DashScope)、豆包 (ByteDance)、元宝 (Tencent)
# 使用 HTTP API 调用，无需额外 SDK
# ============================================================

import json
import threading
import time
import re
from typing import Dict, List, Optional, Callable, Generator
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import URLError
import urllib.parse


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ChatMessage:
    role: str          # "user" | "assistant" | "system"
    content: str
    timestamp: float = 0.0

@dataclass
class AIConfig:
    name: str              # 显示名
    key: str               # 内部 key
    api_url: str           # API 端点
    api_key_required: bool = True
    default_model: str = ""
    headers: Dict = field(default_factory=dict)


# ============================================================
# AI 服务商配置
# ============================================================

AI_PROVIDERS: Dict[str, AIConfig] = {
    "qianwen": AIConfig(
        name="千问 (通义)",
        key="qianwen",
        api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        api_key_required=True,
        default_model="qwen-plus",
        headers={"Content-Type": "application/json"},
    ),
    "doubao": AIConfig(
        name="豆包",
        key="doubao",
        api_url="https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        api_key_required=True,
        default_model="ep-20240601142238-abcde",
        headers={"Content-Type": "application/json"},
    ),
    "yuanbao": AIConfig(
        name="元宝",
        key="yuanbao",
        api_url="https://yuanbao.tencent.com/api/chat/completions",
        api_key_required=True,
        default_model="hunyuan-turbo",
        headers={"Content-Type": "application/json"},
    ),
    "openai": AIConfig(
        name="OpenAI",
        key="openai",
        api_url="https://api.openai.com/v1/chat/completions",
        api_key_required=True,
        default_model="gpt-4o",
        headers={"Content-Type": "application/json"},
    ),
    "deepseek": AIConfig(
        name="DeepSeek",
        key="deepseek",
        api_url="https://api.deepseek.com/v1/chat/completions",
        api_key_required=True,
        default_model="deepseek-chat",
        headers={"Content-Type": "application/json"},
    ),
    "custom": AIConfig(
        name="自定义 API",
        key="custom",
        api_url="",
        api_key_required=True,
        default_model="",
        headers={"Content-Type": "application/json"},
    ),
}


# ============================================================
# AIChatSession - 单次 AI 对话会话
# ============================================================
class AIChatSession:
    """管理一次 AI 对话"""

    def __init__(self, provider_key: str, api_key: str, model: str = None):
        self.provider = AI_PROVIDERS.get(provider_key)
        if not self.provider:
            raise ValueError(f"未知 AI 服务商: {provider_key}")
        self.api_key = api_key
        self.model = model or self.provider.default_model
        self.history: List[ChatMessage] = []

    def add_message(self, role: str, content: str):
        self.history.append(ChatMessage(role=role, content=content, timestamp=time.time()))

    def chat(self, message: str, system_prompt: str = "") -> str:
        """
        发送消息并获取回复（同步阻塞）。
        
        Args:
            message: 用户消息
            system_prompt: 系统提示词
        
        Returns:
            AI 回复文本
        """
        self.add_message("user", message)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in self.history:
            messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        headers = dict(self.provider.headers)
        if self.provider.api_key_required and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(self.provider.api_url, data=data, headers=headers, method="POST")

        try:
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                reply = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if reply:
                    self.add_message("assistant", reply)
                return reply or "[未获取到回复]"
        except URLError as e:
            return f"[网络错误: {e}]"
        except Exception as e:
            return f"[请求失败: {e}]"

    def chat_stream(self, message: str, system_prompt: str = "") -> Generator[str, None, None]:
        """
        流式对话（简化版，暂不支持真正的 SSE 流）。
        直接返回完整回复。
        """
        reply = self.chat(message, system_prompt)
        yield reply

    def clear_history(self):
        self.history.clear()

    def get_history(self) -> List[ChatMessage]:
        return list(self.history)


# ============================================================
# AIChatManager - AI 对话管理器
# ============================================================
class AIChatManager:
    """管理多个 AI 会话和 API Key"""

    CONFIG_FILE_NAME = "ai_keys.json"

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._sessions: Dict[str, AIChatSession] = {}
        self._api_keys: Dict[str, str] = {}
        self._load_keys()

    def _config_path(self) -> str:
        import os
        return os.path.join(self.config_dir, self.CONFIG_FILE_NAME)

    def _load_keys(self):
        try:
            import os
            path = self._config_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._api_keys = json.load(f)
        except Exception:
            self._api_keys = {}

    def _save_keys(self):
        try:
            import os
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump(self._api_keys, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def set_api_key(self, provider_key: str, api_key: str):
        """设置 API Key"""
        self._api_keys[provider_key] = api_key
        self._save_keys()

    def get_api_key(self, provider_key: str) -> str:
        return self._api_keys.get(provider_key, "")

    def has_key(self, provider_key: str) -> bool:
        return bool(self._api_keys.get(provider_key))

    def get_session(self, provider_key: str) -> Optional[AIChatSession]:
        """获取或创建会话"""
        api_key = self._api_keys.get(provider_key, "")
        if not api_key:
            return None
        if provider_key not in self._sessions:
            self._sessions[provider_key] = AIChatSession(provider_key, api_key)
        return self._sessions[provider_key]

    def chat(self, provider_key: str, message: str, system_prompt: str = "") -> str:
        """发送消息到指定 AI"""
        session = self.get_session(provider_key)
        if not session:
            return f"[未配置 {AI_PROVIDERS.get(provider_key, AIConfig(name=provider_key, key=provider_key, api_url='')).name} 的 API Key，请在设置中配置]"
        return session.chat(message, system_prompt)

    def clear_history(self, provider_key: str):
        if provider_key in self._sessions:
            self._sessions[provider_key].clear_history()

    def get_available_providers(self) -> List[Dict]:
        """获取可用的 AI 服务商列表"""
        result = []
        for key, cfg in AI_PROVIDERS.items():
            result.append({
                "key": key,
                "name": cfg.name,
                "has_key": self.has_key(key),
                "default_model": cfg.default_model,
            })
        return result
