#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# agent.py - itent AI 智能体（Function Calling）
# ============================================================
# 功能：
#   1. 定义智能体可用的工具（Tool）列表
#   2. 调用 AI API 时注入工具定义
#   3. 解析 AI 返回的 function_call 并执行
#   4. 将执行结果返回给 AI 生成最终回复
# ============================================================

import json
import os
import sys
import time
import threading
import traceback
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import URLError

import psutil

# ============================================================
# 工具定义（OpenAI Function Calling 格式）
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_running_apps",
            "description": "列出 itent 正在管理的所有软件及其运行状态（运行中/已墓碑/未运行），包含内存和 CPU 占用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suspend_app",
            "description": "墓碑（冻结）指定的软件，释放其 CPU 和内存资源。软件被冻结后不再消耗 CPU，内存被压缩到最小。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "要墓碑的软件名称，如「微信」「QQ」「钉钉」等",
                    },
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_app",
            "description": "唤醒（恢复）被墓碑的软件，使其恢复正常运行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "要唤醒的软件名称，如「微信」「QQ」「钉钉」等",
                    },
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kill_app",
            "description": "彻底结束（终止）指定软件的所有进程。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "要结束的软件名称，如「微信」「QQ」「钉钉」等",
                    },
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": "启动指定软件（如果尚未运行）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "要启动的软件名称，如「微信」「QQ」「钉钉」等",
                    },
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "获取系统整体信息：CPU 使用率、内存使用率、磁盘使用率等。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_processes",
            "description": "列出系统中内存占用最高的前 N 个进程（非系统进程）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "显示前几个进程，默认 10",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_memory",
            "description": "一键优化内存：墓碑所有可管理的非活跃软件，释放系统内存。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ============================================================
# 系统提示词
# ============================================================

AGENT_SYSTEM_PROMPT = """你是 itent 智能后台管理器内置的 AI 智能体。你可以帮助用户管理电脑上的软件进程。

你的能力：
- 查看 itent 管理的所有软件及其运行状态
- 墓碑（冻结）软件以释放 CPU 和内存
- 唤醒被墓碑的软件
- 终止软件进程
- 启动软件
- 查看系统资源信息（CPU、内存、磁盘）
- 查看系统中占用资源最多的进程
- 一键优化内存

重要规则：
1. 始终使用提供的工具函数来执行操作，不要编造结果。
2. 当用户要求「优化」「清理」「释放内存」时，使用 optimize_memory 工具。
3. 当用户询问软件状态时，使用 list_running_apps 工具。
4. 回复要简洁、友好，用中文。
5. 如果工具返回了结果，基于结果给用户一个清晰的总结。
6. 不要执行用户没有明确要求的危险操作（如 kill_app），如果不确定可以先询问用户。
7. 如果用户说的软件名不在 itent 管理列表中，告诉用户 itent 目前管理哪些软件。"""


# ============================================================
# AgentSession - 带 Function Calling 的 AI 会话
# ============================================================

@dataclass
class ToolCall:
    """一次工具调用"""
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class AgentMessage:
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None


class AgentSession:
    """
    带 Function Calling 能力的 AI 会话。

    工作流程：
    1. 用户发送消息 → 调用 AI API（带 tools 定义）
    2. 如果 AI 返回 function_call → 执行工具 → 将结果发回 AI
    3. AI 基于工具结果生成最终回复 → 返回给用户
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str,
        extra_headers: Dict[str, str] = None,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers or {}
        self.history: List[AgentMessage] = []
        self._tool_executor: Optional[Callable] = None

    def set_tool_executor(self, executor: Callable[[str, Dict], str]):
        """设置工具执行回调。executor(tool_name, arguments) -> result_string"""
        self._tool_executor = executor

    def add_message(self, role: str, content: str,
                    tool_calls: List[ToolCall] = None,
                    tool_call_id: str = None):
        self.history.append(AgentMessage(
            role=role, content=content,
            tool_calls=tool_calls, tool_call_id=tool_call_id,
        ))

    def _build_messages(self) -> List[Dict]:
        """构建发送给 API 的消息列表"""
        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        for m in self.history:
            msg = {"role": m.role}
            if m.content:
                msg["content"] = m.content
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            messages.append(msg)
        return messages

    def _call_api(self, messages: List[Dict], with_tools: bool = True) -> Dict:
        """调用 AI API"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000,
        }
        if with_tools:
            payload["tools"] = TOOLS
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        headers.update(self.extra_headers)

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(self.api_url, data=data, headers=headers, method="POST")

        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, message: str) -> str:
        """
        发送消息并获取回复（同步，支持多轮 Function Calling）。

        返回 AI 的最终文本回复。
        """
        self.add_message("user", message)

        # 第一轮：调用 AI
        messages = self._build_messages()
        try:
            result = self._call_api(messages, with_tools=True)
        except URLError as e:
            return f"[网络错误: {e}]"
        except Exception as e:
            return f"[请求失败: {e}]"

        choice = result.get("choices", [{}])[0]
        msg = choice.get("message", {})

        # 检查是否有 tool_calls
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            # 纯文本回复
            content = msg.get("content", "")
            self.add_message("assistant", content)
            return content or "[AI 未返回内容]"

        # ---- 有 Function Call ----
        # 记录 AI 的 tool_calls 请求
        parsed_calls = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            parsed_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
            ))

        self.add_message("assistant", "", tool_calls=parsed_calls)

        # 执行工具
        if not self._tool_executor:
            return "[错误: 工具执行器未设置]"

        for tc in parsed_calls:
            try:
                tool_result = self._tool_executor(tc.name, tc.arguments)
            except Exception as e:
                tool_result = f"工具执行失败: {e}"
            self.add_message("tool", tool_result, tool_call_id=tc.id)

        # 第二轮：将工具结果发回 AI
        messages = self._build_messages()
        try:
            result2 = self._call_api(messages, with_tools=False)
        except Exception as e:
            return f"[第二轮请求失败: {e}]"

        choice2 = result2.get("choices", [{}])[0]
        content2 = choice2.get("message", {}).get("content", "")
        self.add_message("assistant", content2)
        return content2 or "[AI 未生成回复]"

    def clear_history(self):
        self.history.clear()


# ============================================================
# ToolExecutor - 工具执行器（桥接 itent 内部功能）
# ============================================================

class ToolExecutor:
    """
    工具执行器，将 AI 的 function_call 映射到 itent 的实际操作。
    通过回调函数与 MainWindow 交互。
    """

    def __init__(self):
        # 回调注册
        self._callbacks: Dict[str, Callable] = {}

    def register(self, name: str, callback: Callable):
        """注册工具回调"""
        self._callbacks[name] = callback

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行工具并返回结果字符串"""
        if tool_name in self._callbacks:
            try:
                return self._callbacks[tool_name](arguments)
            except Exception as e:
                return f"执行 {tool_name} 时出错: {e}\n{traceback.format_exc()}"
        else:
            return f"未知工具: {tool_name}"


# ============================================================
# 内置工具实现（不依赖 MainWindow 的纯函数）
# ============================================================

def tool_get_system_info(args: Dict) -> str:
    """获取系统信息"""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:"))

        lines = [
            f"CPU 使用率: {cpu:.1f}%",
            f"内存: {mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB ({mem.percent:.1f}%)",
            f"磁盘: {disk.used / (1024**3):.1f} GB / {disk.total / (1024**3):.1f} GB ({disk.percent:.1f}%)",
            f"开机时间: {_format_uptime()}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"获取系统信息失败: {e}"

def tool_list_all_processes(args: Dict) -> str:
    """列出内存占用最高的进程"""
    top_n = args.get("top_n", 10)
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                info = p.info
                mem_mb = info['memory_info'].rss / (1024 * 1024)
                procs.append((info['name'], info['pid'], mem_mb))
            except Exception:
                pass

        # 排序取 top N
        procs.sort(key=lambda x: x[2], reverse=True)
        procs = procs[:top_n]

        lines = [f"内存占用 TOP {top_n} 进程："]
        for i, (name, pid, mem_mb) in enumerate(procs, 1):
            lines.append(f"  {i}. {name} (PID {pid}) - {mem_mb:.1f} MB")
        return "\n".join(lines)
    except Exception as e:
        return f"获取进程列表失败: {e}"

def _format_uptime() -> str:
    """格式化开机时间"""
    try:
        boot_time = psutil.boot_time()
        uptime = time.time() - boot_time
        h = int(uptime // 3600)
        m = int((uptime % 3600) // 60)
        return f"{h} 小时 {m} 分钟"
    except Exception:
        return "未知"


# ============================================================
# AgentManager - 智能体管理器
# ============================================================

class AgentManager:
    """
    管理 AI Agent 的生命周期。
    一个 API Key 可以创建一个专属智能体。
    """

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._sessions: Dict[str, AgentSession] = {}
        self._tool_executor = ToolExecutor()
        self._api_keys: Dict[str, str] = {}
        self._provider_configs: Dict[str, Dict] = {}
        self._load_config()

    def _config_path(self) -> str:
        return os.path.join(self.config_dir, "agent_config.json")

    def _load_config(self):
        try:
            path = self._config_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._api_keys = data.get("api_keys", {})
                self._provider_configs = data.get("providers", {})
        except Exception:
            self._api_keys = {}
            self._provider_configs = {}

    def _save_config(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump({
                    "api_keys": self._api_keys,
                    "providers": self._provider_configs,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def register_tool(self, name: str, callback: Callable):
        """注册一个工具回调"""
        self._tool_executor.register(name, callback)

    def configure_agent(
        self,
        agent_id: str,
        api_url: str,
        api_key: str,
        model: str,
        extra_headers: Dict[str, str] = None,
    ):
        """配置一个智能体（设置 API Key + 端点）"""
        self._api_keys[agent_id] = api_key
        self._provider_configs[agent_id] = {
            "api_url": api_url,
            "model": model,
            "extra_headers": extra_headers or {},
        }
        self._save_config()

    def has_agent(self, agent_id: str) -> bool:
        return bool(self._api_keys.get(agent_id)) and agent_id in self._provider_configs

    def get_session(self, agent_id: str) -> Optional[AgentSession]:
        """获取或创建 Agent 会话"""
        if not self.has_agent(agent_id):
            return None

        if agent_id not in self._sessions:
            cfg = self._provider_configs[agent_id]
            session = AgentSession(
                api_url=cfg["api_url"],
                api_key=self._api_keys[agent_id],
                model=cfg["model"],
                extra_headers=cfg.get("extra_headers", {}),
            )
            session.set_tool_executor(self._tool_executor.execute)
            self._sessions[agent_id] = session

        return self._sessions[agent_id]

    def chat(self, agent_id: str, message: str) -> str:
        """向智能体发送消息"""
        session = self.get_session(agent_id)
        if not session:
            return "[智能体未配置，请先在设置中填入 API Key]"
        return session.chat(message)

    def clear_history(self, agent_id: str):
        if agent_id in self._sessions:
            self._sessions[agent_id].clear_history()

    def get_config(self, agent_id: str) -> Optional[Dict]:
        return self._provider_configs.get(agent_id)

    def list_agents(self) -> List[str]:
        return list(self._provider_configs.keys())


# ============================================================
# 便捷函数：从 ai_chat.py 的 AI_PROVIDERS 创建 Agent
# ============================================================

def create_agent_from_provider(
    agent_mgr: AgentManager,
    provider_key: str,
    api_key: str,
    model: str = None,
):
    """
    从 ai_chat.py 的 AI_PROVIDERS 配置快速创建智能体。

    Args:
        agent_mgr: AgentManager 实例
        provider_key: AI 服务商 key（qianwen/doubao/yuanbao）
        api_key: API Key
        model: 模型名称（可选，默认使用服务商的 default_model）
    """
    from ai_chat import AI_PROVIDERS, AIConfig
    provider = AI_PROVIDERS.get(provider_key)
    if not provider:
        raise ValueError(f"未知 AI 服务商: {provider_key}")

    agent_mgr.configure_agent(
        agent_id=provider_key,
        api_url=provider.api_url,
        api_key=api_key,
        model=model or provider.default_model,
        extra_headers=dict(provider.headers),
    )
