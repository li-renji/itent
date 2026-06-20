---
name: 修复itent.exe启动崩溃问题
overview: 修复打包后 itent.exe 无法启动的问题：1) 移除打包后无意义的 _auto_install_dependencies；2) 在 main.py 顶部添加早期异常捕获和日志；3) 修复 spec 使 EXE 能正确运行；4) 添加启动崩溃的 MessageBox 提示
todos:
  - id: fix-auto-install
    content: 条件化 _auto_install_dependencies() 调用，打包后跳过依赖安装
    status: completed
  - id: add-crash-protection
    content: 在 main() 入口和 __main__ 处添加全局异常捕获和崩溃日志
    status: completed
    dependencies:
      - fix-auto-install
  - id: fix-spec-console
    content: 修改 itent.spec 将 console 改为 True 以便查看错误信息
    status: completed
  - id: fix-target-names
    content: 修复 TARGET_APPS 进程名匹配问题，确保 SystemProcessMonitor 能正确发现目标进程
    status: completed
  - id: add-debug-log
    content: 在 _apply_tombstone_policy 中添加调试日志，记录墓碑决策过程
    status: completed
    dependencies:
      - fix-target-names
  - id: rebuild-and-test
    content: 重新打包 itent.exe 并以管理员身份运行测试
    status: completed
    dependencies:
      - fix-auto-install
      - add-crash-protection
      - fix-spec-console
      - fix-target-names
      - add-debug-log
---

## 用户需求

修复 itent.exe 打包后无法启动的问题，以及墓碑后台效果未达到预期的问题。

## 核心问题

1. **程序打不开**：打包后的 itent.exe 运行时完全无反应，日志文件不存在，说明程序在 main() 执行前就崩溃
2. **墓碑效果未达到**：目标软件（微信、QQ、钉钉等）没有被正确挂起/恢复

## 功能内容

修复后，itent.exe 应能正常启动并显示主窗口，同时能对 TARGET_APPS 中定义的软件正确执行墓碑策略（空闲时挂起、活跃时恢复）。

## 技术分析

### 问题1：程序打不开的根本原因

**原因A：`_auto_install_dependencies()` 在模块顶层执行（main.py 第41行）**

- 该函数定义在模块顶层，在函数体内部调用 `_auto_install_dependencies()`
- 打包后 `sys.executable` 指向 `itent.exe`，执行 `pip install` 会失败
- 更关键的是：`console=False` 时，子进程启动失败会导致静默崩溃

**原因B：`console=False` 导致看不到任何错误信息**

- itent.spec 第36行设置了 `console=False`
- 任何导入期或启动期错误都完全不可见

**修复方案：**

1. 移除或条件化 `_auto_install_dependencies()` 的调用——打包后用 `sys.frozen` 或 `getattr(sys, 'is_frozen', False)` 检测
2. 将 `itent.spec` 的 `console` 改为 `True`（调试阶段），或保留 `False` 但添加崩溃回调
3. 在 `main()` 最开始处（甚至在导入之前）写入启动日志

### 问题2：墓碑效果未达到的根本原因

**原因A：`policy_engine.py` 的规则 `process_names` 与实际进程名不匹配**

- `DEFAULT_APP_RULES` 中用的是 `"WeChat.exe"`、`"QQ.exe"` 等（首字母大写）
- `TARGET_APPS` 中用的是 `"wechat.exe"`、`"qq.exe"` 等（全小写）
- `_check_app_rules` 中的匹配逻辑：`any(pn.lower() == proc_name_lower)` 理论上没问题，但规则里的 `process_names` 字段值是 `"WeChat.exe"`，小写后是 `"wechat.exe"`，实际进程名也是 `"wechat.exe"`，所以匹配应该能成功

**重新检查**：实际上 `_check_app_rules` 的匹配逻辑是正确的（`pn.lower() == proc_name_lower`）。那问题可能在别处。

**原因B：`SystemProcessMonitor` 只监控 `target_proc_names` 中的进程**

- 上轮修改后，`SystemProcessMonitor` 只扫描 `TARGET_APPS` 里定义的进程名
- 如果目标软件没运行，`managed_pids` 为空，`_apply_tombstone_policy` 不会对任何进程操作
- 这是正确行为

**原因C：`_apply_tombstone_policy` 的逻辑问题**

- 第1069行：`self.process_mgr.check_transient_wake_expiry()` 在每次循环都调用，但这个方法是清理所有过期的短暂唤醒标记，每次循环都调用是合理的
- 但问题是：`for pid in managed_pids` 中的 `managed_pids` 是调用时刻的快照，而 `check_transient_wake_expiry()` 会修改 `_transient_wake` 字典，不过这两个没有直接冲突

**最可能的原因**：`TARGET_APPS` 里定义的进程名和实际运行的进程名不一致。比如微信的进程名可能是 `WeChat.exe`（大写W），而 `TARGET_APPS` 里是 `wechat.exe`（小写）。虽然 `SystemProcessMonitor` 里用了 `.lower()`，但 `psutil.process_iter` 返回的 `name` 可能保留原始大小写。

实际上，`psutil.Process.name()` 在 Windows 上返回的是进程名的原始大小写（如 `WeChat.exe`）。而 `TARGET_APPS` 里的 `procs` 是全小写的 `wechat.exe`。在 `_start_system_monitor` 中：

```python
target_names.add(p.name().lower())
```

这里用了 `.lower()`，所以应该能匹配。

**真正的问题可能是**：用户电脑上没有运行这些目标软件，所以 `managed_pids` 一直为空，墓碑策略无从执行。或者 `add_managed_pid` 没有正确工作。

## 实施方案

### 修复1：移除打包后的依赖自动安装（关键）

**文件：main.py**

在 `_auto_install_dependencies()` 调用前检测是否在打包环境：

```python
if not getattr(sys, 'frozen', False):
    _auto_install_dependencies()
```

### 修复2：添加启动崩溃保护（关键）

**文件：main.py**

在 `if __name__ == "__main__":` 处添加全局异常捕获，并将 `console` 改为 `True` 以便调试：

```python
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 写入崩溃日志
        log_path = Path.home() / ".itent" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"{datetime.now().isoformat()}\n崩溃: {e}\n{traceback.format_exc()}\n", encoding="utf-8")
        # 弹出错误框
        ctypes.windll.user32.MessageBoxW(0, f"itent 启动失败:\n{e}", "错误", 0x10)
```

### 修复3：修改 itent.spec 配置（关键）

**文件：itent.spec**

1. 将 `console` 改为 `True`（调试阶段，确认能启动后再改回 False）
2. 考虑使用 `onefile` 模式而非 `COLLECT` 文件夹模式，简化分发

### 修复4：确保 TARGET_APPS 进程名能正确匹配

**文件：main.py**

在 `_start_system_monitor` 中，确保 `target_names` 的收集是正确的。同时，在 `_apply_tombstone_policy` 中添加调试日志。

对于 `process_manager.py` 的 `SystemProcessMonitor`，当前只监控 `target_proc_names` 中的进程。需要确保 `target_proc_names` 在初始化后不会被清空。

### 修复5：墓碑策略调试

**文件：main.py**

在 `_apply_tombstone_policy` 中添加日志输出（写入文件），记录每次决策的结果，方便排查。

## 实施细节

### 文件修改清单

1. **main.py**

- 第41行：条件化 `_auto_install_dependencies()` 的调用
- 第1391-1392行：添加全局异常捕获
- `_start_system_monitor`：确保 target_names 正确传递
- `_apply_tombstone_policy`：添加调试日志

2. **itent.spec**

- 第36行：`console=True`（临时，用于调试）
- 考虑改为 onefile 模式

3. **process_manager.py**（检查）

- 确认 `SystemProcessMonitor` 的 `target_proc_names` 正确设置

4. **policy_engine.py**（检查）

- 确认 `DEFAULT_APP_RULES` 的 `process_names` 与 `TARGET_APPS` 的 `procs` 能正确匹配