---
name: itent-全功能墓碑后台管理器
overview: 将 itent 改造为完整的系统级墓碑后台管理器：1) 用 PyInstaller 打包为独立 exe + NSIS 制作完整安装包；2) 接管系统所有非核心进程，实现智能墓碑策略（特定软件规则 + 通用规则）；3) 软件运行时在后台持续管理所有进程，GUI 用于配置和监控。
design:
  fontSystem:
    fontFamily: system-ui
    heading:
      size: 18px
      weight: 700
    subheading:
      size: 14px
      weight: 500
    body:
      size: 13px
      weight: 400
  colorSystem:
    primary:
      - "#89b4fa"
      - "#cba6f7"
    background:
      - "#000000"
      - "#1e1e2e"
      - "#181825"
    text:
      - "#FFFFFF"
      - "#cdd6f4"
      - "#a6adc8"
    functional:
      - "#a6e3a1"
      - "#f9e2af"
      - "#89b4fa"
      - "#f38ba8"
      - "#6c7086"
todos:
  - id: refactor-process-manager
    content: 重构 ProcessManager：新增核心进程保护列表、系统级进程扫描、新进程自动纳入管理
    status: completed
  - id: implement-policy-engine
    content: 实现 TombstonePolicyEngine 智能墓碑决策引擎（特定软件规则 + 通用规则优先级决策）
    status: completed
    dependencies:
      - refactor-process-manager
  - id: implement-detectors
    content: 实现 AudioDetector 和 NetworkDetector 通用规则检测类
    status: completed
    dependencies:
      - implement-policy-engine
  - id: create-app-rules-config
    content: 创建 config/app_rules.json 特定软件预设规则配置（微信/QQ/钉钉/腾讯会议/飞书）
    status: completed
    dependencies:
      - implement-policy-engine
  - id: refactor-gui-main
    content: 重构主窗口 GUI：系统进程列表表格、资源监控面板、搜索过滤功能
    status: completed
    dependencies:
      - implement-detectors
  - id: implement-settings-dialog
    content: 实现设置对话框：白名单管理、墓碑策略配置、关于页面
    status: completed
    dependencies:
      - create-app-rules-config
  - id: modify-main-entry
    content: 修改 main() 启动流程：移除启动对话框，直接启动系统级进程管理
    status: completed
    dependencies:
      - refactor-gui-main
  - id: convert-icon-and-package
    content: 转换 PNG 图标为 ICO 格式，创建 PyInstaller spec 并执行打包
    status: completed
    dependencies:
      - modify-main-entry
  - id: create-nsis-installer
    content: 编写 NSIS 安装包脚本（桌面快捷方式+开始菜单+卸载程序）并编译
    status: completed
    dependencies:
      - convert-icon-and-package
---

## 产品概述

itent 是一款 Windows 系统级后台进程管理器。软件运行后自动接管系统内所有非核心进程的后台管理，根据智能墓碑策略自动挂起/恢复进程，降低系统资源占用。提供图形界面用于监控、配置和管理。软件图标为黑底白字 "itent"。

## 核心功能

### 1. 系统级进程接管

- 软件启动后自动枚举系统内所有非核心进程，纳入 itent 管理
- 核心系统进程（csrss、wininit、services、lsass、svchost、dwm、explorer 等）自动排除，防止系统崩溃
- 支持新进程自动纳入管理、退出进程自动清理

### 2. 智能墓碑策略

**特定软件预设规则（微信、QQ、钉钉、腾讯会议、飞书）：**

- 聊天消息通知：短暂脱离墓碑（3-5秒），随后自动回到墓碑状态
- 语音/视频通话：全程保留后台，不进入墓碑
- 通过进程名 + 窗口标题/类名特征判断软件状态

**通用规则（满足任一条件则暂时不墓碑）：**

- 有音频输出（检测进程是否占用音频端点）
- 有网络活动（检测网络 IO 速率是否超过阈值）
- CPU 使用率高于阈值（默认 5%，可配置）

### 3. 图形界面（itent GUI）

- 主窗口：系统进程列表 + 资源监控 + 墓碑状态显示
- 配置页面：白名单管理、墓碑策略规则配置、阈值调整
- 状态栏：当前管理的进程数、已墓碑进程数、资源节省统计

### 4. 打包与部署

- PyInstaller 打包为独立 itent.exe（隐藏控制台窗口）
- NSIS 制作安装包：桌面快捷方式 + 开始菜单 + 卸载程序

## 技术栈

- 语言：Python 3.11+
- GUI：PySide6 >= 6.10
- 进程管理：psutil + ctypes (NtSuspendProcess/NtResumeProcess)
- 音频检测：pywin32 (WASAPI)
- 网络检测：psutil + Windows IP Helper API
- 打包：PyInstaller + NSIS

## 实施方案

### 1. 系统级进程接管

**核心系统进程保护列表（硬编码在 ProcessManager）：**

```
_CORE_PROCESSES = {
    "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "svchost.exe", "dwm.exe", "explorer.exe", "winlogon.exe",
    "System", "Idle", "itent.exe"
}
```

**ProcessManager 新增方法：**

- `scan_all_processes() -> List[int]`：使用 `psutil.process_iter(attrs=['pid', 'name'])` 枚举所有进程，过滤核心进程和白名单
- `start_system_monitor()`：启动后台线程（QThread），每 3 秒调用 `scan_all_processes()`，发现新进程自动纳入
- `_is_core_process(pid) -> bool`：检查 PID 对应的进程名是否在保护列表中

**性能优化：**

- 使用 `psutil.process_iter(attrs=[...])` 只获取必要属性，避免每个进程单独调用 `.name()`
- 维护 `_managed_pids: Set[int]` 缓存，避免重复处理
- 扫描间隔 3-5 秒，平衡实时性和性能

### 2. 智能墓碑策略引擎

#### 2.1 新增 `TombstonePolicyEngine` 类

**决策优先级（从高到低）：**

1. 核心系统进程 → 永不墓碑
2. 白名单进程 → 永不墓碑
3. 特定规则 "never_suspend" 匹配 → 永不墓碑
4. 特定规则 "transient_awake" 匹配 → 暂时唤醒（N秒后自动墓碑）
5. 通用规则匹配（音频/网络/CPU）→ 暂时不墓碑
6. 其他 → 执行墓碑

**`should_suspend(pid) -> (bool, str)` 方法：**

- 输入：进程 PID
- 输出：(是否应该挂起, 原因字符串)
- 原因字符串用于 UI 显示和日志：`"core_process"` | `"whitelisted"` | `"never_suspend:wechat_call"` | `"transient_awake:wechat_msg"` | `"active_audio"` | `"active_network"` | `"high_cpu"` | `"ok_to_suspend"`

#### 2.2 特定软件规则

**规则配置文件：`config/app_rules.json`**

程序首次运行时自动生成默认配置，用户可在 GUI 中编辑。

预设 5 款软件规则：

```
{
  "WeChat": {
    "process_names": ["WeChat.exe"],
    "never_suspend": {
      "description": "语音/视频通话时不墓碑",
      "detect_window_class": ["WeChatVoipWindow"],
      "detect_child_process": ["WeChatVoipHelper.exe"]
    },
    "transient_awake": {
      "description": "新消息通知时短暂唤醒",
      "wake_duration_sec": 4,
      "detect_window_title_contains": ["[消息]"]
    }
  },
  "QQ": {
    "process_names": ["QQ.exe", "QQGuild.exe"],
    "never_suspend": {
      "description": "语音/视频通话",
      "detect_window_class": ["QQVoipWindow"]
    },
    "transient_awake": {
      "description": "新消息",
      "wake_duration_sec": 3,
      "detect_window_title_flash": true
    }
  },
  "DingTalk": {...},
  "TencentMeeting": {
    "process_names": ["wemeet.exe"],
    "never_suspend": {
      "description": "会议进行中",
      "detect_always": true
    },
    "transient_awake": null
  },
  "Feishu": {...}
}
```

**规则匹配实现：**

- 进程名匹配：`psutil.Process(pid).name().lower()` 匹配 `process_names`
- 窗口特征匹配：调用 `EnumWindows` + `GetClassName` + `GetWindowText`（已有 `_find_window_by_pid` 可参考）
- 子进程匹配：`psutil.Process(pid).children(recursive=True)` 检查子进程名

#### 2.3 通用规则检测

**音频输出检测（`AudioDetector` 类）：**

简化 v1 实现：检测进程是否加载音频相关 DLL

```python
def is_process_playing_audio(self, pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        # 检查内存映射中是否有音频相关 DLL
        for mmap in p.memory_maps():
            path = mmap.path.lower()
            if any(kw in path for kw in ['audio', 'wasapi', 'mmdevapi', 'audioses']):
                return True
        return False
    except Exception:
        return False
```

> 完整 WASAPI 音频 session 检测需要复杂的 COM 调用，v1 使用简化方案，后续迭代完善。

**网络活动检测（`NetworkDetector` 类）：**

```python
def get_network_active(self, pid: int) -> bool:
    """检测进程是否有活跃网络连接"""
    try:
        p = psutil.Process(pid)
        connections = p.net_connections(kind='inet')
        # 有已建立的连接则认为有网络活动
        established = [c for c in connections if c.status == 'ESTABLISHED']
        return len(established) > 0
    except Exception:
        return False
```

**CPU 阈值检测：**

- 已有 `psutil.Process(pid).cpu_percent(interval=0.1)`
- 阈值从配置读取（默认 5%，GUI 可配置 1%-20%）

### 3. GUI 重构

#### 3.1 主窗口改造

**现有 `AppWindow` 改造：**

去掉原有的"选择要启动的软件"对话框（`StartupDialog`），改为直接启动系统级管理。

**新增 UI 组件：**

- `ProcessTableWidget`：进程列表表格（QTableWidget），列：状态图标、进程名、PID、CPU%、内存(MB)、墓碑策略匹配
- `ResourceMonitorPanel`：系统资源监控面板，显示总 CPU%、总内存%、已墓碑进程数
- 搜索框：`QLineEdit`，实时过滤进程列表

#### 3.2 设置对话框（新增 `SettingsDialog`）

**三个 Tab 页面：**

1. **白名单 Tab**：列表 + 添加/删除按钮
2. **墓碑策略 Tab**：特定软件规则开关 + 通用规则阈值配置
3. **关于 Tab**：版本信息 + 图标预览

### 4. 打包方案

#### 4.1 PyInstaller 打包

**安装：** `pip install pyinstaller`

**执行命令：**

```
pyinstaller --onedir --windowed --icon=app_icon.ico --name=itent ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtGui ^
  --hidden-import PySide6.QtWidgets ^
  --hidden-import psutil ^
  --hidden-import win32gui ^
  --hidden-import win32process ^
  --hidden-import win32api ^
  --hidden-import win32con ^
  --collect-all PySide6 ^
  --add-data "app_icon.png;." ^
  --add-data "config;config" ^
  main.py
```

**关键参数说明：**

- `--onedir`：文件夹模式（推荐，Qt 插件需要）
- `--windowed`：不显示控制台窗口
- `--icon`：应用图标（需要 ICO 格式）
- `--collect-all PySide6`：确保 Qt 插件被打包
- `--add-data`：打包配置文件和资源

**图标格式转换：**
将现有的 256x256 PNG 图标转换为多尺寸 ICO（16x16 ~ 256x256），使用 Pillow：

```python
from PIL import Image
img = Image.open('app_icon.png')
img.save('app_icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
```

#### 4.2 NSIS 安装包

**`itent_installer.nsi` 脚本关键内容：**

```
Name "itent 墓碑后台管理器"
OutFile "itent_setup.exe"
InstallDir "$PROGRAMFILES64\itent"
RequestExecutionLevel admin

; 页面流程
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

Section "主程序" SecMain
    SetOutPath "$INSTDIR"
    File /r "dist\itent\*.*"
    
    ; 桌面快捷方式
    CreateShortcut "$DESKTOP\itent.lnk" "$INSTDIR\itent.exe"
    ; 开始菜单
    CreateDirectory "$SMPROGRAMS\itent"
    CreateShortcut "$SMPROGRAMS\itent\itent.lnk" "$INSTDIR\itent.exe"
    CreateShortcut "$SMPROGRAMS\itent\卸载 itent.lnk" "$INSTDIR\uninstall.exe"
    
    ; 注册卸载信息
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\itent" \
        "DisplayName" "itent 墓碑后台管理器"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\itent" \
        "UninstallString" '"$INSTDIR\uninstall.exe"'
    
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd
```

**编译：** `"C:\Program Files (x86)\NSIS\makensis.exe" itent_installer.nsi`

### 5. 代码文件结构

```
c:/Users/人机/Desktop/ten/
├── main.py                      # [MODIFY] 主入口，重构启动流程
├── policy_engine.py             # [NEW] 墓碑策略引擎（TombstonePolicyEngine）
├── audio_detector.py            # [NEW] 音频检测（AudioDetector）
├── network_detector.py         # [NEW] 网络活动检测（NetworkDetector）
├── config/
│   └── app_rules.json          # [NEW] 特定软件规则配置（自动生成）
├── itent.spec                  # [NEW] PyInstaller spec 文件
├── app_icon.ico               # [NEW] ICO 格式图标
├── itent_installer.nsi        # [NEW] NSIS 安装包脚本
└── dist/                       # [GENERATED] PyInstaller 输出
    └── itent/
        └── itent.exe
```

### 6. main.py 具体修改点

**移除/修改的部分：**

- 移除 `StartupDialog` 类（不再需要用户手动选择软件）
- 修改 `main()` 函数：不再显示选择对话框，直接启动系统级管理
- 修改 `AppWindow.__init__`：初始化 `TombstonePolicyEngine`，启动系统监控

**新增的部分：**

- 在 `main.py` 或新文件中实现 `TombstonePolicyEngine`
- 在 `AppWindow` 中新增系统进程扫描线程
- 新增设置对话框入口

**保持的部分：**

- `ProcessManager` 核心方法（`suspend`/`resume`/`suspend_all_except`）
- `WhitelistManager` 白名单管理
- `AdminChecker` 管理员权限检测
- 图标生成逻辑（`_generate_app_icon`）
- Catppuccin Mocha 配色方案

## 实施步骤概览

1. **重构 ProcessManager**：新增系统级进程扫描和保护列表
2. **实现 TombstonePolicyEngine**：智能墓碑决策引擎
3. **实现 AudioDetector + NetworkDetector**：通用规则检测
4. **生成默认 app_rules.json**：特定软件预设规则
5. **重构 GUI**：主窗口改为系统进程列表，新增设置页面
6. **修改 main() 启动流程**：去掉启动对话框，直接启动系统管理
7. **转换图标为 ICO 格式**
8. **创建 PyInstaller spec 并执行打包**
9. **编写 NSIS 安装包脚本并编译**

## 设计风格

采用深色科技风格（Dark Tech），以纯黑（#000000）为底色，白色（#FFFFFF）为主文字色，
配合蓝紫色渐变作为强调色，营造专业、高端的墓碑管理器视觉体验。
整体风格融合终端/系统管理工具的质感。

## 页面规划（共 2 个核心页面）

### 页面 1：主控制台（Process Dashboard）

- **顶部工具栏**：左侧显示 itent 文字 logo（白字 on 黑底），中间显示系统资源总览（CPU/内存进度条），右侧为设置按钮和开始/暂停按钮
- **左侧进程列表区域（占比 70%）**：表格形式展示所有被管理进程，列包括：状态圆点（绿/灰/蓝/红）、进程名、PID、CPU%、内存(MB)、匹配规则。支持顶部搜索框实时过滤，点击列头排序
- **右侧资源面板（占比 30%）**：显示已管理进程数、已墓碑进程数、估算节省内存、系统总 CPU/内存进度条。使用圆点指示器和大数字显示关键指标
- **底部状态栏**：显示 itent 状态和简版版权信息

### 页面 2：设置对话框（Settings Dialog）

- **白名单管理 Tab**：顶部搜索/添加栏，下方列表显示当前白名单进程名，右侧有删除按钮。支持从运行进程中选取添加
- **墓碑策略 Tab**：上半部分"特定软件规则"（5 个软件各一行，显示软件图标、名称、never_suspend 开关、transient_awake 开关、wake_duration 输入框）；下半部分"通用规则"（音频检测开关、网络活动阈值输入框、CPU 阈值滑块）
- **关于 Tab**：显示 itent 文字 logo（大号黑底白字）、版本号、作者信息、开源协议

## 交互设计

- 进程状态用圆点指示：绿色（活跃）、灰色（墓碑）、蓝色（短暂唤醒）、红色（保护/核心进程）
- 列表支持实时过滤：输入框即时过滤进程名，无结果时显示"无匹配进程"
- 设置对话框使用 QTabWidget 切换三个 Tab
- 阈值滑块使用 QSlider + 数字标签联动
- 开关使用 QCheckBox 或自定义开关组件
- 所有按钮添加 hover 效果（颜色变亮）

# Agent Extensions

<!-- 无可用扩展，省略此标签 -->