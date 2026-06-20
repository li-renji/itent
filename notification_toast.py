#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# notification_toast.py - 顶部弹幕通知条
# ============================================================
# 功能：
#   当微信/QQ等来消息时，从屏幕顶部左侧滑入一条弹幕，
#   滑到最右边停住，点击可打开对应软件，几秒后自动消失。
# ============================================================

import ctypes
import ctypes.wintypes
import threading
import time
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QApplication,
)
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect,
    QParallelAnimationGroup, QSequentialAnimationGroup,
    QPauseAnimation, Signal, QObject, Slot,
)
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QLinearGradient, QIcon, QPixmap, QCursor,
)

# ============================================================
# 配色
# ============================================================
COLOR = {
    "bg_dark":    QColor(30, 30, 46, 235),      # 半透明深色背景
    "bg_lighter": QColor(49, 50, 68, 235),
    "text_primary":  QColor("#cdd6f4"),
    "accent_blue":   QColor("#89b4fa"),
    "accent_green":  QColor("#a6e3a1"),
    "accent_red":    QColor("#f38ba8"),
    "accent_yellow": QColor("#f9e2af"),
    "accent_teal":   QColor("#94e2d5"),
}

# 各软件对应的强调色
APP_ACCENT = {
    "微信": QColor("#a6e3a1"),
    "QQ": QColor("#89b4fa"),
    "钉钉": QColor("#94e2d5"),
    "飞书": QColor("#cba6f7"),
    "千问": QColor("#f9e2af"),
    "豆包": QColor("#a6e3a1"),
    "元宝": QColor("#89b4fa"),
    "腾讯会议": QColor("#f38ba8"),
}


class ToastBanner(QWidget):
    """单条弹幕通知条"""
    clicked = Signal(str)  # app_name

    def __init__(self, app_name: str, title: str, body: str,
                 icon: QIcon = None, parent=None):
        super().__init__(parent)
        self.app_name = app_name
        self._icon = icon
        self._closing = False

        # 窗口属性：无边框、置顶、半透明、不抢焦点
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # 固定高度，宽度自适应
        self.setFixedHeight(52)
        self._init_ui(title, body)

    def _init_ui(self, title: str, body: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        # 软件图标
        self.icon_label = QLabel()
        if self._icon and not self._icon.isNull():
            self.icon_label.setPixmap(self._icon.pixmap(28, 28))
        else:
            # 默认图标：首字母圆形
            pix = QPixmap(28, 28)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QBrush(APP_ACCENT.get(self.app_name, COLOR["accent_blue"])))
            p.setPen(Qt.NoPen)
            p.drawEllipse(0, 0, 28, 28)
            p.setPen(QColor("#1e1e2e"))
            p.setFont(QFont("Segoe UI", 14, QFont.Bold))
            p.drawText(QRect(0, 0, 28, 28), Qt.AlignCenter, self.app_name[0])
            p.end()
            self.icon_label.setPixmap(pix)
        self.icon_label.setFixedSize(28, 28)
        layout.addWidget(self.icon_label)

        # 文字区域
        text_layout = QHBoxLayout()
        text_layout.setSpacing(6)

        # 软件名
        name_label = QLabel(self.app_name)
        accent = APP_ACCENT.get(self.app_name, COLOR["accent_blue"])
        name_label.setStyleSheet(
            f"color: {accent.name()}; font-size: 12px; font-weight: bold;"
        )
        name_label.setFixedWidth(50)
        text_layout.addWidget(name_label)

        # 分隔
        sep = QLabel("|")
        sep.setStyleSheet(f"color: #45475a; font-size: 11px;")
        text_layout.addWidget(sep)

        # 通知内容
        content = body[:60] if body else title[:60]
        if not content:
            content = f"{self.app_name} 新消息"
        content_label = QLabel(content)
        content_label.setStyleSheet(
            f"color: {COLOR['text_primary'].name()}; font-size: 12px;"
        )
        content_label.setWordWrap(False)
        text_layout.addWidget(content_label)

        layout.addLayout(text_layout, 1)

        # 设置光标为手型
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        return self.layout().sizeHint()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        painter.setBrush(QBrush(COLOR["bg_dark"]))
        painter.setPen(QPen(QColor("#313244"), 1))
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 10, 10)

        # 左侧强调色条
        accent = APP_ACCENT.get(self.app_name, COLOR["accent_blue"])
        painter.setBrush(QBrush(accent))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(1, 6, 4, h - 12, 2, 2)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.app_name)
            self.close_animate()

    def close_animate(self):
        """淡出动画"""
        if self._closing:
            return
        self._closing = True
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(300)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self.close)
        self._anim.start()


class ToastManager(QObject):
    """
    弹幕通知管理器。
    管理多个弹幕条的生命周期：入场动画 → 停留 → 出场动画。
    """

    # 动画参数（像素值）
    BANNER_WIDTH = 300       # 弹幕宽度
    BANNER_HEIGHT = 52       # 弹幕高度
    BANNER_MARGIN = 8        # 弹幕间距
    TOP_MARGIN = 8           # 距屏幕顶部距离
    SLIDE_DURATION = 800     # 滑入动画时长（ms）
    STAY_DURATION = 4000     # 停留时长（ms）
    FADE_DURATION = 300      # 淡出时长（ms）

    wake_app_signal = Signal(str)  # 点击弹幕时唤醒软件

    def __init__(self, icon_cache=None):
        super().__init__()
        self._banners: list = []           # 当前显示的弹幕列表
        self._banner_positions: dict = {}  # banner -> y 坐标
        self._icon_cache = icon_cache
        self._next_y = self.TOP_MARGIN
        self._screen_width = 0
        self._screen_height = 0
        self._update_screen_geometry()

    def _update_screen_geometry(self):
        """获取主屏幕尺寸"""
        try:
            smi = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(smi), 0)
            self._screen_width = smi.right - smi.left
            self._screen_height = smi.bottom - smi.top
        except Exception:
            self._screen_width = 1920
            self._screen_height = 1080

    def show_toast(self, app_name: str, title: str, body: str):
        """显示一条弹幕通知"""
        self._update_screen_geometry()

        # 获取图标
        icon = QIcon()
        if self._icon_cache:
            try:
                icon = self._icon_cache.get_icon(app_name, size=28)
            except Exception:
                pass

        banner = ToastBanner(app_name, title, body, icon)
        banner.clicked.connect(self._on_banner_clicked)
        banner.setFixedWidth(self.BANNER_WIDTH)

        # 计算 Y 位置
        y = self._next_y
        self._next_y += self.BANNER_HEIGHT + self.BANNER_MARGIN

        # 如果超出屏幕底部，回到顶部
        if y + self.BANNER_HEIGHT > self._screen_height - 40:
            y = self.TOP_MARGIN
            self._next_y = y + self.BANNER_HEIGHT + self.BANNER_MARGIN

        # 起始位置：屏幕左侧外
        start_x = -self.BANNER_WIDTH - 10
        # 终点位置：屏幕右侧停住
        end_x = self._screen_width - self.BANNER_WIDTH - 10

        banner.move(start_x, y)
        banner.setWindowOpacity(0.0)
        banner.show()

        self._banners.append(banner)
        self._banner_positions[banner] = y

        # 创建动画序列：淡入 → 滑入 → 停留 → 淡出
        # 阶段1: 淡入 (100ms)
        fade_in = QPropertyAnimation(banner, b"windowOpacity")
        fade_in.setDuration(100)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 阶段2: 从左滑到右 (SLIDE_DURATION ms)
        slide = QPropertyAnimation(banner, b"pos")
        slide.setDuration(self.SLIDE_DURATION)
        slide.setStartValue(QPoint(start_x, y))
        slide.setEndValue(QPoint(end_x, y))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 阶段3: 停留
        pause = QPauseAnimation(self.STAY_DURATION)

        # 阶段4: 淡出
        fade_out = QPropertyAnimation(banner, b"windowOpacity")
        fade_out.setDuration(self.FADE_DURATION)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 组合动画
        group = QSequentialAnimationGroup()
        group.addAnimation(fade_in)
        group.addAnimation(slide)
        group.addAnimation(pause)
        group.addAnimation(fade_out)

        # 动画结束后清理
        def on_finished():
            self._remove_banner(banner)

        group.finished.connect(on_finished)
        group.start()

        # 保存动画引用防止被 GC
        banner._anim_group = group

    def _on_banner_clicked(self, app_name: str):
        """点击弹幕 → 发送唤醒信号"""
        self.wake_app_signal.emit(app_name)

    def _remove_banner(self, banner: ToastBanner):
        """移除弹幕并回收 Y 空间"""
        try:
            if banner in self._banners:
                self._banners.remove(banner)
            y = self._banner_positions.pop(banner, None)
            banner.close()
            banner.deleteLater()

            # 重新计算下一个弹幕的 Y 位置
            self._recalc_positions()
        except Exception:
            pass

    def _recalc_positions(self):
        """重新计算弹幕位置（回收空间）"""
        if not self._banners:
            self._next_y = self.TOP_MARGIN
            return

        # 按 Y 坐标排序
        self._banners.sort(key=lambda b: self._banner_positions.get(b, 0))

        current_y = self.TOP_MARGIN
        for banner in self._banners:
            self._banner_positions[banner] = current_y
            current_y += self.BANNER_HEIGHT + self.BANNER_MARGIN

        self._next_y = current_y

    def clear_all(self):
        """清除所有弹幕"""
        for banner in list(self._banners):
            try:
                banner.close()
                banner.deleteLater()
            except Exception:
                pass
        self._banners.clear()
        self._banner_positions.clear()
        self._next_y = self.TOP_MARGIN
