---
name: 整理打包脚本
overview: 删除多余的打包脚本（一键打包.bat、quick_build.bat、pack.py），保留并完善 build.py 和 打包.bat，确保功能最全面（打包exe + 生成NSIS安装包）。
todos:
  - id: delete-files
    content: 删除多余的打包文件：一键打包.bat、quick_build.bat、pack.py
    status: completed
  - id: upgrade-pack-bat
    content: 升级打包.bat，在PyInstaller打包后自动调用build.py生成NSIS安装包
    status: completed
    dependencies:
      - delete-files
  - id: optimize-build-py
    content: 优化build.py，移除重复步骤，只保留NSIS安装包生成功能
    status: completed
    dependencies:
      - upgrade-pack-bat
  - id: test-packaging
    content: 测试新的打包流程，验证exe生成和安装包生成都正常工作
    status: completed
    dependencies:
      - optimize-build-py
  - id: cleanup-references
    content: 清理项目中对已删除文件的引用，确保没有残留的依赖或文档引用
    status: completed
    dependencies:
      - test-packaging
---

## 用户需求

整理项目中的打包脚本文件，只保留功能最全面、最完整的版本，删除多余和有问题文件。

## 具体要求

1. 需要生成安装包（.exe 安装程序，用户双击安装），不只是绿色版
2. 不需要 test.py 测试程序的打包功能
3. 希望保留「打包.bat」这个文件名
4. 删除多余、重复、有问题的打包脚本文件

## 当前打包文件分析

- `打包.bat`：简单实用，杀进程→清理→PyInstaller打包，但不生成安装包
- `一键打包.bat`：复杂有暂停，会先打包test.py（用户不需要），应删除
- `quick_build.bat`：功能被打包.bat完全覆盖，应删除
- `build.py`：功能最全，PyInstaller打包→生成NSIS安装包，应保留并优化
- `pack.py`：纯Python实现自解压安装包，但用户已有NSIS方案，应删除

## 技术方案

### 文件处理策略

1. **删除文件**：

- `一键打包.bat` - 复杂、有暂停、包含不需要的test.py打包
- `quick_build.bat` - 功能完全被打包.bat覆盖
- `pack.py` - 用户已有NSIS方案，此文件实现的自解压安装包不必要

2. **保留并升级文件**：

- `打包.bat` - 保留文件名，升级功能
- `build.py` - 保留作为安装包生成的核心脚本

### 升级方案

**打包.bat 升级内容**：

- 保留现有的杀进程、清理、PyInstaller打包功能
- 在打包成功后，自动调用 `python build.py` 生成 NSIS 安装包
- 这样用户只需双击 `打包.bat` 即可完成完整流程

**build.py 优化内容**：

- 移除重复的清理和打包步骤（避免和打包.bat重复执行）
- 只保留 NSIS 安装包生成的核心功能
- 或者保持原样，由打包.bat判断是否调用

### 实施步骤

1. 删除三个多余文件
2. 升级打包.bat，添加安装包生成步骤
3. 测试新的打包流程
4. 清理可能存在的引用

### 技术细节

- 打包.bat 使用 `call python build.py` 调用安装包生成脚本
- 检查 NSIS 是否安装，未安装时给出提示
- 保持向后兼容，即使没有NSIS也能完成exe打包

## Agent Extensions

无需要扩展工具，此任务为文件整理和脚本优化，不涉及复杂的代码分析或自动化工具调用。