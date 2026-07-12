"""OS 의존 동작을 한곳에 모은 크로스플랫폼 유틸 (Windows / macOS / Linux).

UI·코어의 다른 모듈은 이 모듈만 호출하고 OS 분기를 직접 두지 않는다.
Mac 이식 시 손볼 곳을 이 파일 하나로 좁히는 것이 목적이다.
"""
from __future__ import annotations

import os
import sys
import subprocess


def available_ram_mb() -> float:
    """현재 가용 물리 RAM(MB).

    우선순위: psutil(크로스플랫폼) → Windows API(폴백) → 보수적 기본값 1GB.
    동적 워커 수 계산에 쓰이며, 못 구하면 1워커로 안전하게 강등되도록 작은 값을 준다.
    """
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import ctypes

            class _MemStatEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength",                ctypes.c_ulong),
                    ("dwMemoryLoad",            ctypes.c_ulong),
                    ("ullTotalPhys",            ctypes.c_ulonglong),
                    ("ullAvailPhys",            ctypes.c_ulonglong),
                    ("ullTotalPageFile",        ctypes.c_ulonglong),
                    ("ullAvailPageFile",        ctypes.c_ulonglong),
                    ("ullTotalVirtual",         ctypes.c_ulonglong),
                    ("ullAvailVirtual",         ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemStatEx()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys / (1024 * 1024)
        except Exception:
            pass

    return 1024.0   # 측정 실패 시 1 GB 보수적 가정


def open_in_file_manager(path: str) -> None:
    """파일 탐색기 / Finder 에서 폴더(또는 파일 위치)를 연다. 실패는 조용히 무시."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                       # Windows 전용 API (런타임에만 호출)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def apply_dark_titlebar(widget) -> None:
    """Windows 제목 표시줄(캡션)을 다크로 강제. macOS/Linux 는 no-op(시스템 테마 따름).

    PC가 라이트 모드여도 흰색 제목줄이 다크 본문과 충돌하지 않게 한다.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(widget.winId()))
        val = ctypes.c_int(1)   # 1 = 다크 모드 사용
        # DWMWA_USE_IMMERSIVE_DARK_MODE: Win10 2004+ = 20, 구버전(1809~1909) = 19
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, ctypes.c_int(attr),
                    ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def platform_label() -> str:
    """About 다이얼로그에 표시할 플랫폼 문자열."""
    if sys.platform.startswith("win"):
        return "Windows 10/11 64-bit"
    if sys.platform == "darwin":
        return "macOS"
    return "Linux"
