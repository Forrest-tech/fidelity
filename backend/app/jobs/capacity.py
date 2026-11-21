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


def available_memory_bytes() -> int | None:
    """Memory free right now (other programs included), or None when it cannot be told."""
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
            return int(ms.ullAvailPhys)
        if hasattr(os, "sysconf") and "SC_AVPHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        pass
    return None


FREE_PER_POINT = 1.2 * 1024 ** 3     # a reader with its OCR models needs about this much free memory


def auto_points(mem_bytes: int | None = None, cpus: int | None = None) -> int:
    mem = (mem_bytes if mem_bytes is not None else total_memory_bytes()) / 1024 ** 3
    cpu = cpus if cpus is not None else (os.cpu_count() or 2)
    return max(1, min(int(round(mem / 2)), max(1, cpu // 2) * 2))


def points(avail: int | None = -1) -> int:
    """The machine's capacity. Worked out from its size, and also from the memory free right now: on the 4 GB
    machine this runs on, other programs often leave under 1 GB, and two readers then swapped so hard that OCR went
    from about 15 s to over 70 s a page. With little memory free a run reads one file at a time instead."""
    v = os.environ.get("FIDELITY_CAPACITY_POINTS", "").strip()
    if v.isdigit() and int(v) > 0:
        return int(v)
    p = auto_points()
    free = available_memory_bytes() if avail == -1 else avail
    if free is not None:
        p = min(p, max(1, int(free // FREE_PER_POINT)))
    return p
