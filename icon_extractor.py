#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# icon_extractor.py - 从 .exe 提取图标
# ============================================================
# 从 exe 文件中提取图标，缓存到本地目录供 GUI 使用
# ============================================================

import os
import ctypes
import ctypes.wintypes
from pathlib import Path
from typing import Dict, Optional
from PySide6.QtGui import QIcon, QPixmap


def extract_icon_from_exe(exe_path: str, size: int = 32) -> Optional[QIcon]:
    """
    从 exe 文件提取图标。
    
    Args:
        exe_path: exe 文件路径
        size: 图标尺寸
    
    Returns:
        QIcon 对象，失败返回 None
    """
    try:
        # 方法1：用 Qt 直接提取
        from PySide6.QtWinExtras import QtWin
        import PySide6

        # 检查是否可用
        hicon = extract_hicon(exe_path, 0)
        if hicon:
            pixmap = QtWin.fromHICON(hicon)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(size, size, 
                    PySide6.QtCore.Qt.KeepAspectRatio, 
                    PySide6.QtCore.Qt.SmoothTransformation)
                icon = QIcon(pixmap)
                return icon
    except ImportError:
        pass
    except Exception:
        pass

    # 方法2：用 Win32 API
    try:
        from PySide6.QtGui import QImage, QPixmap
        import PySide6.QtCore as QtCore

        large_icon = ctypes.c_int()
        small_icon = ctypes.c_int()
        num_icons = ctypes.windll.shell32.ExtractIconExW(
            exe_path, 0,
            ctypes.byref(large_icon), ctypes.byref(small_icon), 1
        )
        if num_icons > 0 and large_icon.value:
            pixmap = QPixmap.fromWinHICON(large_icon.value)
            ctypes.windll.user32.DestroyIcon(large_icon.value)
            if small_icon.value:
                ctypes.windll.user32.DestroyIcon(small_icon.value)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(size, size, 
                    QtCore.Qt.KeepAspectRatio, 
                    QtCore.Qt.SmoothTransformation)
                return QIcon(pixmap)
    except Exception:
        pass

    return None


def extract_hicon(exe_path: str, index: int = 0) -> Optional[int]:
    """提取 HICON 句柄"""
    try:
        hicon = ctypes.windll.shell32.ExtractIconW(0, exe_path, index)
        if hicon and hicon <= 65536:
            return None
        return hicon
    except Exception:
        return None


class IconCache:
    """图标缓存管理器"""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir) / "icons"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, QIcon] = {}

    def get_icon(self, app_name: str, exe_path: str = None, size: int = 32) -> QIcon:
        """
        获取应用图标（优先从缓存）。
        
        Args:
            app_name: 应用名称（用于缓存 key）
            exe_path: exe 文件路径
            size: 图标尺寸
        
        Returns:
            QIcon
        """
        # 内存缓存
        cache_key = f"{app_name}_{size}"
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        # 磁盘缓存
        cache_file = self.cache_dir / f"{app_name}_{size}.png"
        if cache_file.exists():
            icon = QIcon(str(cache_file))
            self._memory_cache[cache_key] = icon
            return icon

        # 从 exe 提取
        if exe_path and os.path.exists(exe_path):
            icon = extract_icon_from_exe(exe_path, size)
            if icon:
                # 保存到磁盘缓存
                pixmap = icon.pixmap(size, size)
                pixmap.save(str(cache_file), "PNG")
                self._memory_cache[cache_key] = icon
                return icon

        # 默认图标
        return self._get_default_icon(size)

    def _get_default_icon(self, size: int) -> QIcon:
        """生成默认图标（灰底白字首字母）"""
        from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPixmap
        from PySide6.QtCore import Qt

        if size <= 0:
            size = 32
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor("#555555"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI", size // 2)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "?")
        painter.end()
        return QIcon(QPixmap.fromImage(img))

    def preload_icons(self, apps: Dict[str, str]):
        """预加载应用图标
        Args:
            apps: {app_name: exe_path}
        """
        for name, path in apps.items():
            self.get_icon(name, path, 32)

    def clear_cache(self):
        self._memory_cache.clear()
