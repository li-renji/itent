---
name: itent-托盘最小化与自启动
overview: 实现 itent 点 X 最小化到托盘、开机自启动（注册表）、以及 NSIS 安装时创建计划任务实现静默管理员启动
todos:
  - id: tray-restore
    content: 修改 main.py _init_tray() 添加托盘图标双击/单击恢复窗口功能，添加 _on_tray_activated 方法
    status: completed
  - id: autostart-registry
    content: 在 main.py MainWindow 类中添加 _set_autostart() 和 _is_autostart_enabled() 方法，使用 winreg 操作注册表
    status: completed
    dependencies:
      - tray-restore
  - id: autostart-ui
    content: 在 main.py AppListPanel 底部添加自启动 QCheckBox，绑定状态变更到 _set_autostart()，初始化时读取 _is_autostart_enabled() 设置选中状态
    status: completed
    dependencies:
      - autostart-registry
  - id: nsis-task-scheduler
    content: 修改 itent_installer.nsi，在安装 Section 中添加 PowerShell 命令创建计划任务，在卸载 Section 中添加删除计划任务命令
    status: completed
  - id: test-verify
    content: 测试验证：关闭窗口确认最小化到托盘、托盘双击恢复窗口、自启动开关写入注册表生效、NSIS 安装包正确创建计划任务
    status: completed
    dependencies:
      - tray-restore
      - autostart-ui
      - nsis-task-scheduler
---

## 用户需求

### 1. 关闭窗口最小化到托盘

点击 itent 窗口右上角 X 按钮时，不退出程序，而是隐藏窗口并最小化到系统托盘，后台继续运行。

### 2. 开机自启动

在软件中添加自启动开关，勾选后写入注册表实现开机自启；取消勾选则删除注册表项。

### 3. 静默获取管理员权限（不弹 UAC）

通过 NSIS 安装包创建 Windows 计划任务（Task Scheduler），实现开机时以管理员身份静默启动 itent，不再每次弹 UAC 确认框。

## 现状分析

- `main.py` 的 `closeEvent`（第 1317 行）已实现 `self.hide() + event.ignore()`，功能基本正确，但托盘图标缺少双击恢复窗口的行为。
- 托盘菜单（第 952 行）已有"显示主窗口"和"退出"选项。
- 自启动功能尚未实现。
- 当前管理员权限检测使用 `ShellExecuteW "runas"` 会触发 UAC 弹窗。
- NSIS 安装脚本 `itent_installer.nsi` 尚未包含计划任务创建逻辑。

## 技术方案

### 1. 关闭最小化到托盘（完善）

**现状**：`closeEvent` 已实现隐藏逻辑，功能正确。

**修改点**：在 `_init_tray()` 方法中添加托盘图标的 `activated` 信号连接：

- 双击托盘图标（`QSystemTrayIcon.Trigger` 或 `DoubleClick`）：调用 `self.show()` + `self.raise_()` + `self.activateWindow()` 恢复窗口。

修改文件：`c:/Users/人机/Desktop/ten/main.py`，`_init_tray()` 方法（约第 942 行）。

### 2. 开机自启动（注册表方式）

**实现方式**：写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（当前用户，不需要管理员权限）。

在 `MainWindow` 类中添加两个方法：

- `_set_autostart(enable: bool)`：写入/删除注册表值 `itent`
- `_is_autostart_enabled() -> bool`：读取注册表检查是否存在 itent 值

**UI 位置**：在 `AppListPanel` 底部统计栏上方添加自启动 `QCheckBox`，与现有 UI 风格保持一致（Catppuccin Mocha 配色）。

修改文件：

- `c:/Users/人机/Desktop/ten/main.py`：`AppListPanel._init_ui()` 方法（约第 347 行），以及 `MainWindow` 类添加自启动方法。

### 3. 静默管理员启动（NSIS + 计划任务）

**原理**：安装程序（NSIS）本身以管理员权限运行（`RequestExecutionLevel admin`），可在安装过程中通过 PowerShell 创建计划任务。

**计划任务配置**：

- 触发器：用户登录时（`-AtLogOn`）
- 操作：启动 itent.exe（完整安装路径）
- 权限：以最高权限运行（`-RunLevel Highest`）
- 创建方式：通过 PowerShell `Register-ScheduledTask` COM API 创建，安装时已有管理员权限，可一次性创建好任务；用户登录时任务计划程序服务以 SYSTEM 身份运行任务，不触发 UAC 弹窗。

**NSIS 脚本修改**：

- 安装 Section 末尾：调用 PowerShell 创建计划任务
- 卸载 Section 末尾：删除计划任务（`schtasks /delete /tn "itent" /f`）

修改文件：`c:/Users/人机/Desktop/ten/itent_installer.nsi`

### 目录结构

```
c:/Users/人机/Desktop/ten/
├── main.py                          [MODIFY] 添加托盘双击恢复、自启动注册表读写、自启动 UI 开关
├── itent_installer.nsi              [MODIFY] 添加计划任务创建/删除逻辑
```

### 关键代码结构设计

```python
# main.py 中添加到 MainWindow 类的方法

import winreg

def _set_autostart(self, enable: bool):
    """写入/删除开机自启动注册表"""
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
```

```python
# _init_tray() 中添加（在 self.tray.show() 之前）
self.tray.activated.connect(self._on_tray_activated)

def _on_tray_activated(self, reason: int):
    """托盘图标被激活（单击/双击）时恢复窗口"""
    from PySide6.QtCore import Qt
    if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
        self.show()
        self.raise_()
        self.activateWindow()
```

## Agent Extensions

### code-explorer（SubAgent）

- **用途**：在生成计划时进行更深层次的代码库探索，确认修改点的精确位置和现有代码模式
- **预期结果**：精确定位所有需要修改的函数和行号，确保修改不引入回归问题