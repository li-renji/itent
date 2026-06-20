#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# detectors.py - 通用规则检测类（音频 + 网络）
# ============================================================

import psutil
import time
from typing import Dict, Optional


# ============================================================
# AudioDetector - 音频输出检测
# ============================================================
class AudioDetector:
    """
    检测进程是否有音频输出。
    v1 简化实现：通过检测进程加载的音频相关 DLL 来判断。
    后续可通过 WASAPI Audio Session API 实现更精确的检测。
    """

    AUDIO_DLL_KEYWORDS = {
        "wasapi", "mmdevapi", "audioses", "audioendpoint",
        "wdmaud", "ksuser", "avrt", "coreaudio",
    }

    def __init__(self):
        self._cache: Dict[int, tuple] = {}  # pid -> (timestamp, result)
        self._cache_ttl = 3.0  # 缓存有效期（秒）

    def is_playing_audio(self, pid: int) -> bool:
        """
        检测进程是否有音频输出。
        使用缓存避免频繁检查。
        """
        now = time.time()
        if pid in self._cache:
            ts, result = self._cache[pid]
            if now - ts < self._cache_ttl:
                return result

        result = self._detect_audio(pid)
        self._cache[pid] = (now, result)
        return result

    def _detect_audio(self, pid: int) -> bool:
        """实际检测逻辑"""
        try:
            p = psutil.Process(pid)
            # 方法1：检测内存映射中的音频 DLL
            for mmap in p.memory_maps():
                path = (mmap.path or "").lower()
                if any(kw in path for kw in self.AUDIO_DLL_KEYWORDS):
                    # 加载了音频 DLL，进一步检查是否有音频会话
                    # 简化版：如果进程有音频相关 DLL 且 CPU 不低，认为可能有音频
                    return True

            # 方法2：检测子进程（有些软件的音频在独立进程中）
            for child in p.children(recursive=True):
                for mmap in child.memory_maps():
                    path = (mmap.path or "").lower()
                    if any(kw in path for kw in self.AUDIO_DLL_KEYWORDS):
                        return True

            return False
        except Exception:
            return False

    def clear_cache(self):
        self._cache.clear()


# ============================================================
# NetworkDetector - 网络活动检测
# ============================================================
class NetworkDetector:
    """
    检测进程是否有活跃的网络连接。
    通过检测 ESTABLISHED 状态的连接来判断。
    """

    def __init__(self):
        self._cache: Dict[int, tuple] = {}  # pid -> (timestamp, result)
        self._cache_ttl = 2.0
        self._io_cache: Dict[int, tuple] = {}  # pid -> (timestamp, bytes_sent, bytes_recv)

    def is_network_active(self, pid: int, threshold_kbps: float = 10.0) -> bool:
        """
        检测进程是否有活跃网络连接。
        threshold_kbps: 网络活动阈值（KB/s）
        """
        now = time.time()
        if pid in self._cache:
            ts, result = self._cache[pid]
            if now - ts < self._cache_ttl:
                return result

        result = self._detect_network_io(pid, threshold_kbps)
        self._cache[pid] = (now, result)
        return result

    def _detect_network_io(self, pid: int, threshold_kbps: float) -> bool:
        """通过 IO 速率检测网络活动"""
        try:
            p = psutil.Process(pid)
            io_counters = p.io_counters()
            now = time.time()

            if pid in self._io_cache:
                prev_time, prev_sent, prev_recv = self._io_cache[pid]
                dt = now - prev_time
                if dt > 0.1:
                    sent_rate = (io_counters.bytes_sent - prev_sent) / 1024 / dt
                    recv_rate = (io_counters.bytes_recv - prev_recv) / 1024 / dt
                    total_rate = sent_rate + recv_rate
                    self._io_cache[pid] = (now, io_counters.bytes_sent, io_counters.bytes_recv)
                    return total_rate > threshold_kbps

            self._io_cache[pid] = (now, io_counters.bytes_sent, io_counters.bytes_recv)
            return False
        except Exception:
            return False

    def has_established_connections(self, pid: int) -> bool:
        """检测进程是否有已建立的网络连接"""
        try:
            p = psutil.Process(pid)
            connections = p.net_connections(kind='inet')
            established = [c for c in connections if c.status == 'ESTABLISHED']
            return len(established) > 0
        except Exception:
            return False

    def clear_cache(self):
        self._cache.clear()
        self._io_cache.clear()
