# -*- coding: utf-8 -*-
"""How much distillation can run at once on this machine, in "points".

A run of plain text PDFs takes 1 point; a run that needs OCR on scanned files takes 2, because OCR holds a lot
of memory. The machine's capacity is worked out from its memory and processor count, so a 4 GB virtual machine
gets 2 points (one OCR room, or two text rooms) and a 32 GB Mac mini gets many more. An administrator can
override it with FIDELITY_CAPACITY_POINTS.
"""
import os


def total_memory_bytes() -> int:
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return int(ms.ullTotalPhys)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return 4 * 1024 ** 3


def auto_points(mem_bytes: int | None = None, cpus: int | None = None) -> int:
    mem = (mem_bytes if mem_bytes is not None else total_memory_bytes()) / 1024 ** 3
    cpu = cpus if cpus is not None else (os.cpu_count() or 2)
    return max(1, min(int(round(mem / 2)), max(1, cpu // 2) * 2))


def points() -> int:
    v = os.environ.get("FIDELITY_CAPACITY_POINTS", "").strip()
    if v.isdigit() and int(v) > 0:
        return int(v)
    return auto_points()
