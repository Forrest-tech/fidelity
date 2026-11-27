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
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        lim, _ = _cgroup_memory()
        return min(total, lim) if lim else total
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
        avail = _meminfo("MemAvailable")
        if avail is None and hasattr(os, "sysconf") and "SC_AVPHYS_PAGES" in os.sysconf_names:
            avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
        lim, used = _cgroup_memory()
        if lim is not None:
            room = max(0, lim - (used or 0))
            avail = room if avail is None else min(avail, room)
        return avail
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _meminfo(key: str, path: str = "/proc/meminfo") -> int | None:
    """A /proc/meminfo value in bytes. MemAvailable, not the "free" figure: on Linux (and in Docker) free memory is
    nearly always low because the kernel keeps file caches in it, which it hands back at once when a program needs
    memory. Reading "free" (SC_AVPHYS_PAGES) gave a container on a 16 GB Mac 1 point: one file read at a time."""
    try:
        with open(path, encoding="ascii") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _cgroup_memory(root: str = "/sys/fs/cgroup") -> tuple:
    """(limit, in use) of this container's memory in bytes, or (None, None) outside a limited container."""
    for lim_f, use_f in (("memory.max", "memory.current"), ("memory/memory.limit_in_bytes", "memory/memory.usage_in_bytes")):
        try:
            with open(os.path.join(root, lim_f)) as f:
                raw = f.read().strip()
            if raw == "max" or not raw.isdigit() or int(raw) >= 1 << 60:
                return None, None
            used = None
            try:
                with open(os.path.join(root, use_f)) as f:
                    used = int(f.read().strip())
            except (OSError, ValueError):
                pass
            return int(raw), used
        except OSError:
            continue
    return None, None


def cpu_count() -> int:
    """Processors this process may use: the container's CPU limit when there is one, else the machine's."""
    n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 2)
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()[:2]
        if quota != "max":
            n = min(n, max(1, int(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, n)


FREE_PER_POINT = 1.2 * 1024 ** 3     # a reader with its OCR models needs about this much free memory


def auto_points(mem_bytes: int | None = None, cpus: int | None = None) -> int:
    mem = (mem_bytes if mem_bytes is not None else total_memory_bytes()) / 1024 ** 3
    cpu = cpus if cpus is not None else cpu_count()
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


def emulated() -> bool:
    """True when this program runs as x86 code translated on an ARM machine (Docker on an Apple-silicon Mac with an
    image built for linux/amd64): everything, OCR above all, is several times slower. The kernel is still ARM, so
    /proc/cpuinfo describes ARM processors ("CPU implementer") while Python reports x86_64."""
    import platform
    if platform.machine().lower() not in ("x86_64", "amd64") or not os.path.isfile("/proc/cpuinfo"):
        return False
    try:
        with open("/proc/cpuinfo", encoding="ascii", errors="replace") as f:
            info = f.read(20000)
    except OSError:
        return False
    return "CPU implementer" in info or "VirtualApple" in info


def machine() -> dict:
    """What the reading capacity is worked out from, for the page (so a slow or small setup can be seen)."""
    import platform
    return {"cpus": cpu_count(), "memory_gb": round(total_memory_bytes() / 1024 ** 3, 1),
            "free_gb": round((available_memory_bytes() or 0) / 1024 ** 3, 1), "arch": platform.machine(),
            "emulated": emulated(), "points": points()}
